# ruff: noqa
"""V2.0 B3 : calibrage affiné. Eau de référence = grandes surfaces permanentes (BD TOPO), terre sèche = cultures annuelles (RPG),
prairies permanentes = témoin de crue (RPG PP)."""

import warnings

warnings.filterwarnings("ignore")
import os, time, collections, numpy as np, pandas as pd, geopandas as gpd, dask
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
dom = gpd.read_parquet(f"{V}/domaine.parquet").set_index("marais")
sh = gpd.read_parquet(f"{V}/surface_hydro.parquet")
sh["ha"] = sh.geometry.area / 1e4
sh = sh[
    sh.nature.isin(["Retenue", "Canal", "Ecoulement naturel", "Mare", "Réservoir-bassin"])
    & (sh.persistance == "Permanent")
    & (sh.ha >= 1.0)
]
rpg = gpd.read_parquet(f"{V}/rpg.parquet")
cult = rpg[rpg.code_group.astype(int).isin([1, 2, 3, 4, 5, 6])]
prai = rpg[rpg.code_group.astype(int) == 18]
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
PER = {"hiver": "2024-01-01/2024-01-31", "ete": "2024-08-01/2024-08-31"}
T = [-14, -15, -16, -17, -18, -19, -20]
rows = []
t0 = time.time()
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)

    def masque(gdf, ero=-10):
        g = gdf[gdf.intersects(geom)].geometry.buffer(ero).union_all().intersection(geom)
        return (
            ~geometry_mask([g], out_shape=gb.shape, transform=gb.affine)
            if not g.is_empty
            else np.zeros(gb.shape, bool)
        )

    M = {"eau": masque(sh), "terre": masque(cult), "prairie": masque(prai)}
    print(marais, {k: f"{v.sum() * 0.01:.0f} ha" for k, v in M.items()}, flush=True)
    bb4326 = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    for saison, per in PER.items():
        items = list(cl.search(collections=["sentinel-1-rtc"], bbox=bb4326, datetime=per).items())
        par = collections.defaultdict(lambda: collections.defaultdict(list))
        for it in items:
            par[it.properties["sat:relative_orbit"]][it.datetime.date()].append(it)
        for orb, jours in sorted(par.items()):
            ch = sorted(jours)[:: max(1, len(jours) // 2)][:2]
            its = [i for j in ch for i in jours[j]]
            ori = {i.properties["sat:orbit_state"] for i in its}
            ds = odc.stac.load(
                its,
                bands=["vv", "vh"],
                geobox=gb,
                groupby="solar_day",
                chunks={"x": 2048, "y": 2048},
                patch_url=planetary_computer.sign,
                dtype="float32",
                nodata=-32768,
            )
            with dask.config.set(scheduler="threads", num_workers=8):
                vv, vh = ds.vv.compute().values, ds.vh.compute().values
            for k in range(vv.shape[0]):
                ok = np.isfinite(vv[k]) & (vv[k] > 0)
                db = np.full(vv[k].shape, np.nan, "float32")
                db[ok] = 10 * np.log10(vv[k][ok])
                row = dict(
                    marais=marais,
                    saison=saison,
                    orbite=orb,
                    sens=",".join(sorted(ori)),
                    date=str(ds.time.values[k])[:10],
                )
                for nom, m in M.items():
                    a = db[m & ok]
                    row[f"{nom}_n"] = len(a)
                    row[f"{nom}_p50"] = float(np.percentile(a, 50))
                    row[f"{nom}_p10"] = float(np.percentile(a, 10))
                    row[f"{nom}_p90"] = float(np.percentile(a, 90))
                    for t in T:
                        row[f"{nom}_lt{t}"] = float((a < t).mean())
                rows.append(row)
    print("  fait", round(time.time() - t0), "s", flush=True)
pd.DataFrame(rows).to_csv(f"{V}/calibrage_vv2.csv", index=False)
print("terminé")
