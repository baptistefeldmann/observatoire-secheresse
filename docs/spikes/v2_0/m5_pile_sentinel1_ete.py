# ruff: noqa
"""V2.0 marée, pile Sentinel-1 RTC (VV en dB, 30 m) des étés 2022-2025 pour une orbite, avec la hauteur de marée à l'heure de chaque passage. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os, sys, time, numpy as np, pandas as pd, geopandas as gpd, dask, odc.stac, planetary_computer
from odc.geo.geobox import GeoBox
from pystac_client import Client

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
MARAIS = sys.argv[1]
ORB = int(sys.argv[2])
STATION = {"poitevin": 34, "breton": 62}[MARAIS]
PERIODES = [f"{a}-06-01/{a}-10-31" for a in (2022, 2023, 2024, 2025)]
CL = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")


def retry(f, n=12):
    for t in range(n):
        try:
            return f()
        except Exception as e:
            print("reprise", t, str(e)[:100], flush=True)
            time.sleep(min(90, 8 * (t + 1)))
    raise RuntimeError


dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
gb = GeoBox.from_bbox(dom.loc[MARAIS].geometry.bounds, crs="EPSG:2154", resolution=30)
bb = tuple(
    gpd.GeoSeries.from_xy(
        [gb.boundingbox.left, gb.boundingbox.right],
        [gb.boundingbox.bottom, gb.boundingbox.top],
        crs=2154,
    )
    .to_crs(4326)
    .total_bounds
)
items = []
for p in PERIODES:
    items += retry(
        lambda: [
            i
            for i in CL.search(collections=["sentinel-1-rtc"], bbox=bb, datetime=p).items()
            if i.properties["sat:relative_orbit"] == ORB
        ]
    )
print(MARAIS, "orbite", ORB, "scènes", len(items), "grille", gb.shape, flush=True)
# marée : nettoyage des pointes (médiane glissante) puis interpolation à l'heure de la scène
m = (
    pd.read_csv(f"{S}/maree/maree_{STATION}_s2.csv", parse_dates=["t"])
    .set_index("t")
    .value.sort_index()
)
med = m.rolling(7, center=True, min_periods=3).median()
m = m.where((m - med).abs() < 0.4)
m = m.interpolate(limit=3)
m = m.dropna()
ti = (m.index - pd.Timestamp("2000-01-01", tz="UTC")).total_seconds().values


def hauteur(t):
    t = pd.Timestamp(t)
    x = (t - pd.Timestamp("2000-01-01", tz="UTC")).total_seconds()
    i = np.searchsorted(ti, x)
    if i == 0 or i >= len(ti) or ti[i] - ti[i - 1] > 1800:
        return np.nan
    return float(np.interp(x, ti[i - 1 : i + 1], m.values[i - 1 : i + 1]))


ds = retry(
    lambda: odc.stac.load(
        items,
        bands=["vv"],
        geobox=gb,
        groupby="solar_day",
        chunks={"x": 1024, "y": 1024},
        resampling={"*": "average"},
        patch_url=planetary_computer.sign,
        dtype="float32",
        nodata=-32768,
    )
)
t0 = time.time()
with dask.config.set(scheduler="threads", num_workers=8):
    ds = retry(lambda: ds.compute())
print("chargé", ds.vv.shape, round(time.time() - t0), "s", flush=True)
v = ds.vv.values
v = np.where(v > 0, v, np.nan)
db = (10 * np.log10(v)).astype("float16")
temps = pd.to_datetime(ds.time.values, utc=True)
# heure exacte du passage : celle de la scène retenue pour le jour solaire
dt_item = {}
for i in items:
    dt_item.setdefault(pd.Timestamp(i.datetime).tz_convert("UTC").date(), []).append(
        pd.Timestamp(i.datetime)
    )
heures = []
for t in temps:
    c = (
        dt_item.get(t.date())
        or dt_item.get((t - pd.Timedelta(days=1)).date())
        or dt_item.get((t + pd.Timedelta(days=1)).date())
    )
    heures.append(c[0] if c else t)
h = np.array([hauteur(x) for x in heures])
np.savez_compressed(
    f"{S}/maree/pile_{MARAIS}_{ORB}.npz",
    db=db,
    h=h,
    t=np.array([x.value for x in heures]),
    transform=np.array(gb.affine)[:6],
    shape=np.array(gb.shape),
)
print(
    "passages",
    len(h),
    "hauteur min/max",
    np.nanmin(h).round(2),
    np.nanmax(h).round(2),
    "sauvé",
    flush=True,
)
