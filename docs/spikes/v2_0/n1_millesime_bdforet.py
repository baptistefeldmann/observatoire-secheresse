# ruff: noqa
"""V2.0 BD Forêt V2 : la carte de la Vendée date de 2006 ; ce que Sentinel-2 d'été 2025 en reste sur le domaine de chaque marais (NDVI médian de juillet-août 2025 par classe de la BD Forêt, parcelles du RPG 2025 sur la forêt). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 1.1)."""

import warnings

warnings.filterwarnings("ignore")
import os, sys, numpy as np, pandas as pd, geopandas as gpd, dask
import odc.stac, planetary_computer
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
PERIODE = sys.argv[1] if len(sys.argv) > 1 else "2025-07-01/2025-08-31"
RES = 30
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
bf = gpd.read_parquet(f"{S}/bdforet.parquet")
rpg = gpd.read_parquet(f"{S}/rpg.parquet")  # RPG 2025 complet
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
rows = []
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=RES)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    its = list(
        cl.search(
            collections=["sentinel-2-l2a"],
            bbox=bb,
            datetime=PERIODE,
            query={"eo:cloud_cover": {"lt": 20}},
        ).items()
    )
    its = [i for i in its if i.properties.get("s2:processing_baseline") is not None]
    print(marais, len(its), "scènes", flush=True)
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
    ndvi = np.where(ok, (nir - red) / (nir + red + 1e-9), np.nan)
    med = np.nanmedian(ndvi, axis=0)
    print(marais, "dates utilisables par pixel (médiane)", float(np.median(ok.sum(0))), flush=True)
    shp, tr = gb.shape, gb.affine
    dans = rasterize([(geom, 1)], out_shape=shp, transform=tr, fill=0).astype(bool)
    b = bf[bf.intersects(geom)].copy()
    b["geometry"] = b.geometry.buffer(-RES).intersection(
        geom
    )  # cœur du polygone : écarte les bords, mélangés à l'extérieur
    b = b[~b.geometry.is_empty]
    r_rpg = rasterize(
        [(g, 1) for g in rpg.geometry if not g.is_empty], out_shape=shp, transform=tr, fill=0
    ).astype(bool)
    for tfv, g in b.groupby("tfv_g11"):
        m = (
            rasterize(
                [(x, 1) for x in g.geometry if not x.is_empty], out_shape=shp, transform=tr, fill=0
            ).astype(bool)
            & dans
            & np.isfinite(med)
        )
        if m.sum() < 20:
            continue
        v = med[m]
        rows.append(
            dict(
                marais=marais,
                classe=tfv,
                ha_coeur=round(m.sum() * RES * RES / 1e4, 1),
                ndvi_p10=round(float(np.percentile(v, 10)), 2),
                ndvi_median=round(float(np.median(v)), 2),
                part_ndvi_sous_0_4=round(float((v < 0.4).mean()) * 100, 1),
                part_rpg=round(float(r_rpg[m].mean()) * 100, 1),
            )
        )
res = pd.DataFrame(rows)
res.to_csv(f"{S}/millesime_bdforet.csv", index=False)
print(res.to_string())
