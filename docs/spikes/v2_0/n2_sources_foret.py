# ruff: noqa
"""V2.0 sources de forêt plus récentes que la BD Forêt V2 (2006) : ESA WorldCover 2021, Impact Observatory 2023 (Planetary Computer), Copernicus HRL Dominant Leaf Type 2018 (serveur public de l'AEE), hauteur de canopée de Meta (n2b). Comparées entre elles, à la BD Forêt de 2006 et à Sentinel-2 (NDVI d'été 2025 et d'hiver 2025). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 1.2)."""

import warnings

warnings.filterwarnings("ignore")
import os, io, sys, numpy as np, pandas as pd, geopandas as gpd, dask, requests
import odc.stac, planetary_computer, rasterio
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import rasterize

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
RES, HA = 30, 0.09
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
bf = gpd.read_parquet(f"{S}/bdforet.parquet")
rpg = gpd.read_parquet(f"{S}/rpg.parquet")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
EEA = "https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/HRL_DominantLeafType2018/ImageServer/exportImage"


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
    return np.nanmedian(np.where(ok, (nir - red) / (nir + red + 1e-9), np.nan), axis=0), len(its)


def pc_classes(collection, annee, bb, gb, asset):
    its = [
        i
        for i in cl.search(collections=[collection], bbox=bb).items()
        if (i.datetime and i.datetime.year == annee)
        or str(i.properties.get("start_datetime", ""))[:4] == str(annee)
    ]
    ds = odc.stac.load(
        its,
        bands=[asset],
        geobox=gb,
        groupby="solar_day",
        resampling="mode",
        patch_url=planetary_computer.sign,
        chunks={"x": 1024, "y": 1024},
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        return (
            ds[asset].compute().values.max(axis=0)
            if ds[asset].ndim == 3
            else ds[asset].compute().values
        )


def eea_dlt(gb):
    x0, y0, x1, y1 = (
        gb.boundingbox.left,
        gb.boundingbox.bottom,
        gb.boundingbox.right,
        gb.boundingbox.top,
    )
    h, w = gb.shape
    r = requests.get(
        EEA,
        params=dict(
            bbox=f"{x0},{y0},{x1},{y1}",
            bboxSR=2154,
            imageSR=2154,
            size=f"{w},{h}",
            format="tiff",
            pixelType="U8",
            interpolation="RSP_NearestNeighbor",
            f="image",
        ),
        timeout=300,
    )
    r.raise_for_status()
    with rasterio.MemoryFile(r.content) as m, m.open() as d:
        return d.read(1)


rows, tfv_rows = [], []
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=RES)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    shp, tr = gb.shape, gb.affine
    ras = lambda gg: rasterize(
        [(x, 1) for x in gg if not x.is_empty], out_shape=shp, transform=tr, fill=0
    ).astype(bool)
    dans = ras([geom])
    ete, n1 = s2_ndvi(gb, bb, "2025-07-01/2025-08-31")
    hiv, n2 = s2_ndvi(gb, bb, "2025-01-01/2025-02-28")
    print(marais, "S2 scènes été", n1, "hiver", n2, flush=True)
    b = bf[bf.intersects(geom)].copy()
    forets = b[~b.tfv_g11.isin(["Lande", "Formation herbacée"])]
    m_bf = ras(forets.geometry)
    coeur = lambda g: ras(g.geometry.buffer(-RES).intersection(geom))
    c_conif = coeur(forets[forets.tfv_g11.str.contains("conifères")])
    c_feuil = coeur(forets[forets.tfv_g11.str.contains("feuillus")])
    c_mixte = coeur(forets[forets.tfv_g11.str.contains("mixte")])
    c_peup = coeur(forets[forets.tfv_g11 == "Peupleraie"])
    c_tout = c_conif | c_feuil | c_mixte | c_peup
    m_rpg = ras(rpg.geometry)
    sources = {}
    sources["WorldCover 2021"] = pc_classes("esa-worldcover", 2021, bb, gb, "map") == 10
    sources["Impact Observatory 2023"] = pc_classes("io-lulc-annual-v02", 2023, bb, gb, "data") == 2
    dlt = eea_dlt(gb)
    sources["HRL Dominant Leaf Type 2018"] = np.isin(dlt, [1, 2])
    p = f"{S}/chm_meta_{marais}.npy"
    if os.path.exists(p):
        sources["Meta hauteur de canopée (moyenne 30 m ≥ 5 m)"] = (
            np.nan_to_num(np.load(p), nan=0) >= 5
        )
    sources["BD Forêt 2006 (référence)"] = m_bf
    ref = dans & c_tout & np.isfinite(ete)
    for nom, m in sources.items():
        t = m & dans
        hors = t & ~m_bf & np.isfinite(ete)
        rows.append(
            dict(
                marais=marais,
                source=nom,
                ha_arbres=round(t.sum() * HA),
                rappel_coeur_bdforet_pct=round(float(m[ref].mean()) * 100, 1),
                ha_hors_bdforet=round(hors.sum() * HA),
                hors_ndvi_ete_median=round(float(np.median(ete[hors])), 2)
                if hors.sum()
                else np.nan,
                hors_part_ndvi_ete_sup_0_65_pct=round(float((ete[hors] > 0.65).mean()) * 100, 1)
                if hors.sum()
                else np.nan,
                hors_part_rpg_pct=round(float(m_rpg[hors].mean()) * 100, 1)
                if hors.sum()
                else np.nan,
                ha_dans_bdforet_coeur_non_arbre=round((c_tout & dans & ~m).sum() * HA),
            )
        )
    # type de feuillage : HRL contre le cœur de la BD Forêt, et NDVI d'hiver (feuillage persistant : conifères)
    for nom_bd, c in (
        ("conifères BD Forêt", c_conif),
        ("feuillus BD Forêt", c_feuil),
        ("mixte BD Forêt", c_mixte),
        ("peupleraie BD Forêt", c_peup),
    ):
        k = c & dans & np.isfinite(hiv) & np.isfinite(ete)
        if k.sum() < 20:
            continue
        tfv_rows.append(
            dict(
                marais=marais,
                classe_2006=nom_bd,
                ha_coeur=round(k.sum() * HA),
                hrl_feuillus_pct=round(float((dlt[k] == 1).mean()) * 100, 1),
                hrl_coniferes_pct=round(float((dlt[k] == 2).mean()) * 100, 1),
                hrl_non_arbre_pct=round(float((dlt[k] == 0).mean()) * 100, 1),
                ndvi_hiver_median=round(float(np.median(hiv[k])), 2),
                ndvi_ete_median=round(float(np.median(ete[k])), 2),
                ecart_ete_hiver=round(float(np.median(ete[k] - hiv[k])), 2),
            )
        )
    print(marais, "terminé", flush=True)
pd.DataFrame(rows).to_csv(f"{S}/sources_foret.csv", index=False)
pd.DataFrame(tfv_rows).to_csv(f"{S}/sources_foret_feuillage.csv", index=False)
print(pd.DataFrame(rows).to_string())
print(pd.DataFrame(tfv_rows).to_string())
