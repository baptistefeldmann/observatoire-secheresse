# ruff: noqa
"""V2.0 B2 : calibrage du seuil d'eau sur l'eau connue (BD TOPO surface_hydrographique) : VV de l'eau de référence contre le reste du domaine."""

import warnings

warnings.filterwarnings("ignore")
import os, io, time, collections, requests, numpy as np, pandas as pd, geopandas as gpd, dask
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
com = gpd.read_parquet("data/referentiels/communes.parquet")
bb = com.to_crs(4326).total_bounds
bbox = f"{bb[1]},{bb[0]},{bb[3]},{bb[2]},urn:ogc:def:crs:EPSG::4326"
dom = gpd.read_parquet(f"{V}/domaine.parquet").set_index("marais")


def pages(layer):
    out, d = [], 0
    while True:
        p = dict(
            SERVICE="WFS",
            VERSION="2.0.0",
            REQUEST="GetFeature",
            TYPENAMES=layer,
            OUTPUTFORMAT="application/json",
            SRSNAME="EPSG:2154",
            BBOX=bbox,
            COUNT=5000,
            STARTINDEX=d,
            SORTBY="cleabs",
        )
        r = requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=600)
        r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content))
        g = g.set_crs(2154) if g.crs is None else g.to_crs(2154)
        out.append(g)
        d += len(g)
        if len(g) < 5000:
            break
    return pd.concat(out, ignore_index=True)


sh = pages("BDTOPO_V3:surface_hydrographique")
print(
    "surface_hydrographique:",
    len(sh),
    "; colonnes",
    [c for c in sh.columns if c != "geometry"][:10],
)
for c in ("nature", "persistance"):
    if c in sh.columns:
        print(c, sh[c].value_counts(dropna=False).head(8).to_dict())
sh = sh[[c for c in ("cleabs", "nature", "persistance", "geometry") if c in sh.columns]]
sh.to_parquet(f"{V}/surface_hydro.parquet")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
PER = {"hiver": "2024-01-01/2024-01-31", "ete": "2024-08-01/2024-08-31"}
rows = []
t0 = time.time()
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    eau_geo = (
        sh[sh.intersects(geom)].geometry.buffer(-10).union_all().intersection(geom)
    )  # eau connue, pixels purs
    eau = (
        ~geometry_mask([eau_geo], out_shape=gb.shape, transform=gb.affine)
        if not eau_geo.is_empty
        else np.zeros(gb.shape, bool)
    )
    eau &= dans
    reste = dans & ~eau
    print(
        marais,
        "px domaine",
        int(dans.sum()),
        "| px eau connue",
        int(eau.sum()),
        f"({eau.sum() * 0.01:.0f} ha)",
        flush=True,
    )
    bb4326 = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    for saison, per in PER.items():
        items = list(cl.search(collections=["sentinel-1-rtc"], bbox=bb4326, datetime=per).items())
        par = collections.defaultdict(lambda: collections.defaultdict(list))
        for it in items:
            par[it.properties["sat:relative_orbit"]][it.datetime.date()].append(it)
        for orb, jours in sorted(par.items()):
            ch = sorted(jours)[:: max(1, len(jours) // 2)][:2]
            ds = odc.stac.load(
                [i for j in ch for i in jours[j]],
                bands=["vv"],
                geobox=gb,
                groupby="solar_day",
                chunks={"x": 2048, "y": 2048},
                patch_url=planetary_computer.sign,
                dtype="float32",
                nodata=-32768,
            )
            with dask.config.set(scheduler="threads", num_workers=8):
                vv = ds.vv.compute().values
            for k in range(vv.shape[0]):
                db = np.full(vv[k].shape, np.nan, "float32")
                ok = np.isfinite(vv[k]) & (vv[k] > 0)
                db[ok] = 10 * np.log10(vv[k][ok])
                a, b = db[eau & ok], db[reste & ok]
                rows.append(
                    dict(
                        marais=marais,
                        saison=saison,
                        orbite=orb,
                        date=str(ds.time.values[k])[:10],
                        n_eau=len(a),
                        n_reste=len(b),
                        **{f"eau_p{q}": np.percentile(a, q) for q in (5, 25, 50, 75, 95)},
                        **{f"reste_p{q}": np.percentile(b, q) for q in (1, 5, 25, 50, 75, 95)},
                        **{f"reste_lt{t}": float((b < t).mean()) for t in (-14, -16, -18, -20)},
                        **{f"eau_lt{t}": float((a < t).mean()) for t in (-14, -16, -18, -20)},
                    )
                )
    print(" ", marais, "fait", round(time.time() - t0), "s", flush=True)
pd.DataFrame(rows).to_csv(f"{V}/calibrage_vv.csv", index=False)
print("terminé")
