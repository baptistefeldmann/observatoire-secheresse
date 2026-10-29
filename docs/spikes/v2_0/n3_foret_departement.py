# ruff: noqa
"""V2.0 BD Forêt V2 (2006) à l'échelle du département : le suivi NDVI et NDMI de la végétation se fait sur toute la Vendée, pas sur les seuls marais. Cœur des polygones de la BD Forêt (30 m des bords) : NDVI médian d'été et d'hiver 2025 (Sentinel-2), part dans le RPG 2025, part encore vue comme arbre par Impact Observatory 2023 ; marais et reste du département séparés. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 1.3)."""

import warnings

warnings.filterwarnings("ignore")
import os, sys, numpy as np, pandas as pd, geopandas as gpd, dask
import odc.stac, planetary_computer
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import rasterize
from shapely.geometry import box

os.environ.update(
    {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "GDAL_HTTP_MAX_RETRY": "8",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "GDAL_HTTP_TIMEOUT": "60",
        "VSI_CACHE": "TRUE",
    }
)
S = os.environ.get("V20_SORTIE", "rasters/v2_0")
RES, HA, BLOC = 30, 0.09, 40000
communes = gpd.read_parquet("data/referentiels/communes.parquet").to_crs(2154)
territoire = communes.geometry.union_all()
marais = gpd.read_parquet(f"{S}/domaine.parquet").geometry.union_all()
bf = gpd.read_parquet(f"{S}/bdforet.parquet")
rpg = gpd.read_parquet(f"{S}/rpg.parquet")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
bf = bf[~bf.tfv_g11.isin(["Lande", "Formation herbacée"])]
GROUPES = {
    "conifères": lambda s: s.str.contains("conifères"),
    "feuillus": lambda s: s.str.contains("feuillus"),
    "mixte": lambda s: s.str.contains("mixte"),
    "peupleraie": lambda s: s == "Peupleraie",
}


def s2_ndvi(gb, bb, periode):
    its = list(
        cl.search(
            collections=["sentinel-2-l2a"],
            bbox=bb,
            datetime=periode,
            query={"eo:cloud_cover": {"lt": 30}},
        ).items()
    )
    its = [i for i in its if i.properties.get("s2:processing_baseline") is not None]
    if not its:
        return np.full(gb.shape, np.nan, "float32")
    ds = odc.stac.load(
        its,
        bands=["B04", "B08", "SCL"],
        geobox=gb,
        chunks={"x": 1024, "y": 1024},
        groupby="solar_day",
        resampling="nearest",
        patch_url=planetary_computer.sign,
        dtype="uint16",
        nodata=0,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        ds = ds.compute()
    base = {
        np.datetime64(i.datetime.date()): float(i.properties["s2:processing_baseline"]) for i in its
    }
    off = np.array(
        [
            -1000.0
            if base[min(base, key=lambda d: abs(d - t.astype("datetime64[D]")))] >= 4.0
            else 0.0
            for t in ds.time.values
        ],
        "float32",
    )[:, None, None]
    red = np.clip(ds.B04.values.astype("float32") + off, 0, None) / 1e4
    nir = np.clip(ds.B08.values.astype("float32") + off, 0, None) / 1e4
    ok = np.isin(ds.SCL.values, [4, 5, 6, 7]) & (ds.B04.values > 0) & (ds.B08.values > 0)
    return np.nanmedian(np.where(ok, (nir - red) / (nir + red + 1e-9), np.nan), axis=0)


def io_arbres(gb, bb):
    its = [
        i
        for i in cl.search(collections=["io-lulc-annual-v02"], bbox=bb).items()
        if str(i.properties.get("start_datetime", i.datetime))[:4] == "2023"
    ]
    if not its:
        return np.zeros(gb.shape, bool)
    ds = odc.stac.load(
        its,
        bands=["data"],
        geobox=gb,
        groupby="solar_day",
        resampling="mode",
        patch_url=planetary_computer.sign,
        chunks={"x": 1024, "y": 1024},
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        a = ds["data"].compute().values
    return (a.max(axis=0) if a.ndim == 3 else a) == 2


x0, y0, x1, y1 = territoire.bounds
rows = []
for bx in np.arange(x0, x1, BLOC):
    for by in np.arange(y0, y1, BLOC):
        fen = box(bx, by, min(bx + BLOC, x1), min(by + BLOC, y1))
        if not fen.intersects(territoire):
            continue
        b = bf[bf.intersects(fen)]
        if b.empty:
            continue
        gb = GeoBox.from_bbox(fen.bounds, crs="EPSG:2154", resolution=RES)
        bb = tuple(gpd.GeoSeries([fen], crs=2154).to_crs(4326).total_bounds)
        shp, tr = gb.shape, gb.affine
        ras = lambda gg: rasterize(
            [(x, 1) for x in gg if not x.is_empty], out_shape=shp, transform=tr, fill=0
        ).astype(bool)
        dans = ras([territoire.intersection(fen)])
        dm = ras([marais.intersection(fen)]) if marais.intersects(fen) else np.zeros(shp, bool)
        ete, hiv, arb = (
            s2_ndvi(gb, bb, "2025-07-01/2025-08-31"),
            s2_ndvi(gb, bb, "2025-01-01/2025-02-28"),
            io_arbres(gb, bb),
        )
        m_rpg = ras(rpg[rpg.intersects(fen)].geometry)
        for nom, f in GROUPES.items():
            g = b[f(b.tfv_g11)]
            if g.empty:
                continue
            core = (
                ras(g.geometry.buffer(-RES).intersection(territoire))
                & dans
                & np.isfinite(ete)
                & np.isfinite(hiv)
            )
            for lieu, m in (("marais", core & dm), ("reste du département", core & ~dm)):
                if m.sum():
                    rows.append(
                        pd.DataFrame(
                            dict(
                                classe=nom,
                                lieu=lieu,
                                ete=ete[m],
                                hiv=hiv[m],
                                rpg=m_rpg[m],
                                arbre=arb[m],
                            )
                        )
                    )
        print(f"bloc {bx:.0f},{by:.0f} fait", flush=True)
d = pd.concat(rows)
d["ecart"] = d.ete - d.hiv
res = (
    d.groupby(["classe", "lieu"])
    .agg(
        ha_coeur=("ete", lambda s: round(len(s) * HA)),
        ndvi_ete=("ete", "median"),
        ndvi_hiver=("hiv", "median"),
        ecart_ete_hiver=("ecart", "median"),
        part_sous_0_4=("ete", lambda s: (s < 0.4).mean() * 100),
        part_rpg=("rpg", lambda s: s.mean() * 100),
        part_encore_arbre_io2023=("arbre", lambda s: s.mean() * 100),
    )
    .round(2)
)
res.to_csv(f"{S}/foret_departement.csv")
d.groupby("classe").agg(
    ha_coeur=("ete", lambda s: round(len(s) * HA)),
    ndvi_ete=("ete", "median"),
    ecart=("ecart", "median"),
    part_sous_0_4=("ete", lambda s: (s < 0.4).mean() * 100),
    part_rpg=("rpg", lambda s: s.mean() * 100),
    part_arbre=("arbre", lambda s: s.mean() * 100),
).round(2).to_csv(f"{S}/foret_departement_total.csv")
print(res.to_string())
print(pd.read_csv(f"{S}/foret_departement_total.csv").to_string())
