# ruff: noqa
"""V2.0 scènes Sentinel-2 en double (même tuile, même jour, deux baselines) : NDVI et NDMI des mêmes pixels de forêt dans les deux versions, avec et sans la correction de l'offset BOA. Teste directement l'homogénéité entre baselines. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 4.4)."""

import warnings

warnings.filterwarnings("ignore")
import os, collections, numpy as np, pandas as pd, geopandas as gpd, dask
import odc.stac, planetary_computer
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import rasterize

os.environ.update(
    {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MAX_RETRY": "8",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "VSI_CACHE": "TRUE",
    }
)
S = os.environ.get("V20_SORTIE", "rasters/v2_0")
FEN = (300000, 6645000, 315000, 6660000)  # fenêtre « pin » de 15 km (conifères, cibles stables)
bf = gpd.read_parquet(f"{S}/bdforet.parquet")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
gb = GeoBox.from_bbox(FEN, crs="EPSG:2154", resolution=20)
from shapely.geometry import box

b = bf[bf.intersects(box(*FEN))]
b = b[b.tfv_g11.str.contains("conifères|feuillus|mixte")]
coeur = rasterize(
    [(g, 1) for g in b.geometry.buffer(-20).intersection(box(*FEN)) if not g.is_empty],
    out_shape=gb.shape,
    transform=gb.affine,
    fill=0,
).astype(bool)
print("pixels de cœur de forêt (20 m) :", int(coeur.sum()), flush=True)
bb = tuple(gpd.GeoSeries([box(*FEN)], crs=2154).to_crs(4326).total_bounds)


def ndvi(it, offset):
    ds = odc.stac.load(
        [it],
        bands=["B04", "B08", "B11", "SCL"],
        geobox=gb,
        resampling="nearest",
        patch_url=planetary_computer.sign,
        dtype="uint16",
        nodata=0,
        chunks={"x": 512, "y": 512},
    ).compute()
    red = np.clip(ds.B04.values[0].astype("float32") + offset, 0, None) / 1e4
    nir = np.clip(ds.B08.values[0].astype("float32") + offset, 0, None) / 1e4
    swir = np.clip(ds.B11.values[0].astype("float32") + offset, 0, None) / 1e4
    ok = (
        np.isin(ds.SCL.values[0], [4, 5])
        & (ds.B04.values[0] > 0)
        & (ds.B08.values[0] > 0)
        & (ds.B11.values[0] > 0)
    )
    return np.where(ok, (nir - red) / (nir + red + 1e-9), np.nan), np.where(
        ok, (nir - swir) / (nir + swir + 1e-9), np.nan
    )


rows = []
for an in range(2019, 2026):
    its = list(
        cl.search(
            collections=["sentinel-2-l2a"],
            bbox=bb,
            datetime=f"{an}-03-01/{an}-10-31",
            query={"eo:cloud_cover": {"lt": 25}},
        ).items()
    )
    par = collections.defaultdict(list)
    for i in its:
        if i.properties.get("s2:processing_baseline"):
            par[(i.properties["s2:mgrs_tile"], i.datetime.date())].append(i)
    for (t, d), l in par.items():
        if len({i.properties["s2:processing_baseline"] for i in l}) < 2:
            continue
        l = sorted(l, key=lambda i: float(i.properties["s2:processing_baseline"]))
        a, c = l[0], l[-1]
        ba, bc = (
            float(a.properties["s2:processing_baseline"]),
            float(c.properties["s2:processing_baseline"]),
        )
        oa, oc = (-1000.0 if ba >= 4 else 0.0), (-1000.0 if bc >= 4 else 0.0)
        (na, ma), (nc, mc) = ndvi(a, oa), ndvi(c, oc)
        (na0, ma0), (nc0, mc0) = ndvi(a, 0.0), ndvi(c, 0.0)
        k = coeur & np.isfinite(na) & np.isfinite(nc)
        if k.sum() < 200:
            continue
        rows.append(
            dict(
                annee=an,
                tuile=t,
                date=str(d),
                anc=a.properties["s2:processing_baseline"],
                rec=c.properties["s2:processing_baseline"],
                pixels=int(k.sum()),
                ndvi_anc=float(np.median(na[k])),
                ndvi_rec=float(np.median(nc[k])),
                diff_corrigee=float(np.median(nc[k] - na[k])),
                diff_sans_offset=float(np.median((nc0 - na0)[k])),
                ecart_type_diff=float(np.std((nc - na)[k])),
                ndmi_diff_corrigee=float(np.median((mc - ma)[k])),
                ndmi_diff_sans_offset=float(np.median((mc0 - ma0)[k])),
                ndmi_ecart_type=float(np.std((mc - ma)[k])),
            )
        )
        print(rows[-1], flush=True)
r = pd.DataFrame(rows)
r.to_csv(f"{S}/doublons_baseline_ndmi.csv", index=False)
r["paire"] = r.anc + " -> " + r.rec
print(
    r.groupby("paire")
    .agg(
        dates=("date", "count"),
        ndvi_corrigee=("diff_corrigee", "median"),
        ndvi_sans_offset=("diff_sans_offset", "median"),
        ndmi_corrigee=("ndmi_diff_corrigee", "median"),
        ndmi_sans_offset=("ndmi_diff_sans_offset", "median"),
        ndmi_ecart_type=("ndmi_ecart_type", "median"),
    )
    .round(4)
    .to_string()
)
print("terminé")
