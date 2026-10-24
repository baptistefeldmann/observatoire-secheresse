# ruff: noqa
"""Outils communs des mesures Sentinel-2 de V2.0 (jetables, hors dépôt)."""

import warnings

warnings.filterwarnings("ignore")
import os, numpy as np, xarray as xr, dask, geopandas as gpd
import odc.stac, planetary_computer
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import geometry_mask

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
V = os.environ.get("V20_SORTIE", "rasters/v2_0")
CL = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
FENETRES = {
    "pin": (300000, 6645000),
    "mixte": (405000, 6600000),
}  # fenêtres de 15 x 15 km (EPSG:2154)


def geobox(nom, taille=15000):
    x, y = FENETRES[nom]
    return GeoBox.from_bbox((x, y, x + taille, y + taille), crs="EPSG:2154", resolution=10)


def bbox4326(gb):
    return (
        tuple(gpd.GeoSeries([gb.boundingbox.polygon.geom], crs=2154).to_crs(4326).total_bounds)
        if False
        else tuple(
            gpd.GeoSeries.from_xy(
                [gb.boundingbox.left, gb.boundingbox.right],
                [gb.boundingbox.bottom, gb.boundingbox.top],
                crs=2154,
            )
            .to_crs(4326)
            .total_bounds
        )
    )


def recherche(gb, periode, nuage_max=80):
    return list(
        CL.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox4326(gb),
            datetime=periode,
            query={"eo:cloud_cover": {"lt": nuage_max}},
        ).items()
    )


def baseline(it):
    b = it.properties.get("s2:processing_baseline")
    if b is not None:
        return float(b)
    return None


def offset(it):
    b = baseline(it)
    if b is None:
        return None  # baseline inconnue : scène écartée (jamais déduite de la date)
    return -1000.0 if b >= 4.0 else 0.0


def cube(items, gb, bandes=("B04", "B08", "B11", "SCL")):
    items = [i for i in items if offset(i) is not None]
    ds = odc.stac.load(
        items,
        bands=list(bandes),
        geobox=gb,
        chunks={"x": 1024, "y": 1024},
        groupby="solar_day",
        resampling={"*": "nearest"},
        patch_url=planetary_computer.sign,
        dtype="uint16",
        nodata=0,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        ds = ds.compute()
    par_jour = {}
    for i in items:
        par_jour.setdefault(np.datetime64(i.datetime.date()), []).append(i)
    meta = []
    for t in ds.time.values:
        c = par_jour[min(par_jour, key=lambda d: abs(d - t.astype("datetime64[D]")))]
        meta.append(
            dict(
                date=str(t)[:10],
                plateforme=c[0].properties.get("platform"),
                baseline=baseline(c[0]),
                offset=offset(c[0]),
                nuage=float(np.mean([i.properties.get("eo:cloud_cover", np.nan) for i in c])),
            )
        )
    return ds, meta


def reflectances(ds, meta, corriger=True):
    off = xr.DataArray(
        np.array([m["offset"] if corriger else 0.0 for m in meta], "float32"),
        dims=("time",),
        coords={"time": ds.time},
    )
    return {
        b: ((ds[b].astype("float32") + off) / 10000.0).clip(min=0)
        for b in ("B04", "B08", "B11")
        if b in ds
    }


def indices(refl):
    return (refl["B08"] - refl["B04"]) / (refl["B08"] + refl["B04"]), (
        refl["B08"] - refl["B11"]
    ) / (refl["B08"] + refl["B11"])


def valide(ds):
    return ds.SCL.isin([4, 5, 6, 7]) & (ds.B04 > 0) & (ds.B08 > 0) & (ds.B11 > 0)


def masque(gdf, gb, ero=-10):
    g = gdf.geometry.buffer(ero).union_all()
    return (
        ~geometry_mask([g], out_shape=gb.shape, transform=gb.affine)
        if not g.is_empty
        else np.zeros(gb.shape, bool)
    )
