# ruff: noqa
"""V2.0 B4 : détection de crue par changement (VV d'hiver contre la médiane sèche d'été du même pixel et de la même orbite).
Validation interne : les 6 orbites observent le même événement à quelques jours d'écart, leurs surfaces doivent concorder."""

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
rpg = gpd.read_parquet(f"{V}/rpg.parquet")
bf = gpd.read_parquet(f"{V}/bdforet.parquet")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
ETE, HIVER = "2024-07-01/2024-09-30", "2024-01-01/2024-02-29"
DELTA, ABS = [-2, -3, -4], [-12, -14, -16]
rows = []
t0 = time.time()
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)

    def masque(gdf):
        g = gdf[gdf.intersects(geom)].geometry.buffer(-10).union_all().intersection(geom)
        return (
            ~geometry_mask([g], out_shape=gb.shape, transform=gb.affine)
            if not g.is_empty
            else np.zeros(gb.shape, bool)
        )

    cls = {
        "prairie_pp": masque(rpg[rpg.code_group.astype(int) == 18]),
        "cultures": masque(rpg[rpg.code_group.astype(int).isin([1, 2, 3, 4, 5, 6])]),
        "foret": masque(bf),
    }
    bb4326 = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)

    def charger(its):
        ds = odc.stac.load(
            its,
            bands=["vv"],
            geobox=gb,
            groupby="solar_day",
            chunks={"x": 2048, "y": 2048},
            patch_url=planetary_computer.sign,
            dtype="float32",
            nodata=-32768,
        )
        with dask.config.set(scheduler="threads", num_workers=8):
            v = ds.vv.compute().values
        db = np.where(
            np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan
        ).astype("float32")
        return db, [str(t)[:10] for t in ds.time.values]

    its_e = list(cl.search(collections=["sentinel-1-rtc"], bbox=bb4326, datetime=ETE).items())
    its_h = list(cl.search(collections=["sentinel-1-rtc"], bbox=bb4326, datetime=HIVER).items())
    orbs = sorted({i.properties["sat:relative_orbit"] for i in its_h})
    for orb in orbs:
        e = [i for i in its_e if i.properties["sat:relative_orbit"] == orb]
        h = [i for i in its_h if i.properties["sat:relative_orbit"] == orb]
        dbe, de = charger(e)
        ref = np.nanmedian(dbe, axis=0)  # référence sèche : médiane d'été par pixel
        dbh, dh = charger(h)
        for nom, (db, dates, saison) in {
            "hiver": (dbh, dh, "hiver"),
            "ete": (dbe, de, "ete"),
        }.items():
            for k, date in enumerate(dates):
                x = db[k]
                ok = np.isfinite(x) & np.isfinite(ref)
                diff = x - ref
                for dl in DELTA:
                    for ab in ABS:
                        crue = (
                            (diff < dl) & (x < ab) & (ref >= -16) & ok
                        )  # hors eau permanente (réf. sèche déjà sombre)
                        row = dict(
                            marais=marais,
                            orbite=orb,
                            saison=saison,
                            date=date,
                            delta=dl,
                            absolu=ab,
                            ha_domaine=float((crue & dans).sum() * 0.01),
                        )
                        for c, m in cls.items():
                            row[f"pct_{c}"] = (
                                float(crue[m & ok].mean() * 100) if (m & ok).any() else np.nan
                            )
                        rows.append(row)
        print(
            marais,
            "orbite",
            orb,
            "été",
            len(de),
            "passages ; hiver",
            dh,
            f"t={time.time() - t0:.0f}s",
            flush=True,
        )
pd.DataFrame(rows).to_csv(f"{V}/changement.csv", index=False)
print("terminé")
