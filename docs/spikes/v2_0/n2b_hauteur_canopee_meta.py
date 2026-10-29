# ruff: noqa
"""V2.0 sources de forêt plus récentes que la BD Forêt : hauteur de canopée de Meta (1 m, images de 2009 à 2020 selon la documentation de Meta), moyenne sur la grille de 30 m du domaine de chaque marais. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 1.2)."""

import warnings

warnings.filterwarnings("ignore")
import os, time, numpy as np, geopandas as gpd, rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds
from rasterio.transform import Affine
from odc.geo.geobox import GeoBox
from shapely.geometry import box

os.environ.update(
    {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MAX_RETRY": "8",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "VSI_CACHE": "TRUE",
    }
)
S = os.environ.get("V20_SORTIE", "rasters/v2_0")
BASE = "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float"
FACTEUR = 25  # pixels de 1,19 m regroupés par 25 : cellules de 30 m dans la projection de la source
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
tuiles = gpd.read_file(f"{S}/tiles_meta.geojson")
for marais, ligne in dom.iterrows():
    gb = GeoBox.from_bbox(ligne.geometry.bounds, crs="EPSG:2154", resolution=30)
    dst = np.full(gb.shape, np.nan, "float32")
    bb4326 = tuple(gpd.GeoSeries([box(*ligne.geometry.bounds)], crs=2154).to_crs(4326).total_bounds)
    for t in tuiles[tuiles.intersects(box(*bb4326))].tile:
        t0 = time.time()
        with rasterio.open(f"/vsicurl/{BASE}/chm/{t}.tif") as d:
            b3857 = transform_bounds("EPSG:2154", d.crs, *ligne.geometry.bounds)
            b3857 = (
                max(b3857[0], d.bounds.left),
                max(b3857[1], d.bounds.bottom),
                min(b3857[2], d.bounds.right),
                min(b3857[3], d.bounds.top),
            )
            if b3857[0] >= b3857[2] or b3857[1] >= b3857[3]:
                continue
            w = from_bounds(*b3857, d.transform).round_offsets().round_lengths()
            h, l = int(w.height // FACTEUR), int(w.width // FACTEUR)
            if h < 1 or l < 1:
                continue
            a = d.read(1, window=w, out_shape=(h, l), resampling=Resampling.average).astype(
                "float32"
            )
            tr = rasterio.windows.transform(w, d.transform) * Affine.scale(
                w.width / l, w.height / h
            )
            crs = d.crs
        tmp = np.full(gb.shape, np.nan, "float32")
        reproject(
            a,
            tmp,
            src_transform=tr,
            src_crs=crs,
            dst_transform=gb.affine,
            dst_crs="EPSG:2154",
            resampling=Resampling.average,
            src_nodata=None,
            dst_nodata=np.nan,
        )
        dst = np.where(np.isnan(dst), tmp, dst)
        print(marais, t, f"{time.time() - t0:.0f}s", flush=True)
    np.save(f"{S}/chm_meta_{marais}.npy", dst)
    print(
        marais,
        "hauteur moyenne médiane du domaine",
        float(np.nanmedian(dst)),
        "cellules renseignées",
        float(np.isfinite(dst).mean()),
        flush=True,
    )
