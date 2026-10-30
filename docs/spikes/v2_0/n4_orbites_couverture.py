# ruff: noqa
"""V2.0 Q18, orbites : couverture de chaque orbite sur le domaine de chaque marais, et surface de crue détectée par passage (Δ ≤ −3 dB, VV ≤ −16 dB, filtre spatial) sur l'emprise commune à toutes les orbites du marais, hivers 2023-2024 et 2024-2025 (référence : été précédent). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 3.8)."""

import warnings

warnings.filterwarnings("ignore")
import os, time, numpy as np, pandas as pd, geopandas as gpd, dask
import odc.stac, planetary_computer
from scipy import ndimage as ndi
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
S = os.environ.get("V20_SORTIE", "rasters/v2_0")
HIVERS = [
    ("2023-12-01/2024-03-31", "2023-07-01/2023-09-30"),
    ("2024-12-01/2025-03-31", "2024-07-01/2024-09-30"),
]
ORBITES = {"poitevin": [8, 30, 81], "breton": [30, 81, 103, 154]}
DELTA, HA = -3, 0.01
ABS_GRILLE = [
    -18,
    -17,
    -16,
    -15,
    -14,
]  # seuil absolu testé : l'écart entre orbites vient du niveau de VV de chaque orbite
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
rows = []
t0 = time.time()
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)

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
        return np.where(
            np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan
        ).astype("float32"), [str(t)[:10] for t in ds.time.values]

    for hiver, ete in HIVERS:
        its_e = list(cl.search(collections=["sentinel-1-rtc"], bbox=bb, datetime=ete).items())
        its_h = list(cl.search(collections=["sentinel-1-rtc"], bbox=bb, datetime=hiver).items())
        refs, hivs = {}, {}
        for orb in ORBITES[marais]:
            e = [i for i in its_e if i.properties["sat:relative_orbit"] == orb]
            h = [i for i in its_h if i.properties["sat:relative_orbit"] == orb]
            if not e or not h:
                continue
            dbe, _ = charger(e)
            refs[orb] = np.nanmedian(dbe, axis=0)
            hivs[orb] = charger(h)
            print(
                marais,
                hiver,
                "orbite",
                orb,
                len(e),
                "été",
                len(h),
                "hiver",
                f"t={time.time() - t0:.0f}s",
                flush=True,
            )
        commun = dans.copy()
        for r in refs.values():
            commun &= np.isfinite(r)
        for orb, (db, dates) in hivs.items():
            ref = refs[orb]
            rf = ndi.median_filter(np.where(np.isfinite(ref), ref, np.nanmedian(ref)), size=3)
            for k, date in enumerate(dates):
                x = db[k]
                ok = np.isfinite(x) & np.isfinite(ref)
                xf = ndi.median_filter(np.where(ok, x, np.nanmedian(x)), size=3)
                for ab in ABS_GRILLE:
                    c0 = ((xf - rf) < DELTA) & (xf < ab) & (rf >= -16) & ok
                    lab, _ = ndi.label(c0)
                    tai = np.bincount(lab.ravel())
                    crue = np.isin(lab, np.where(tai >= 10)[0]) & (lab > 0)
                    rows.append(
                        dict(
                            marais=marais,
                            hiver=hiver[:7],
                            orbite=orb,
                            date=date,
                            absolu=ab,
                            couvert_ha=float((dans & ok).sum() * HA),
                            domaine_ha=float(dans.sum() * HA),
                            crue_ha=float((crue & dans).sum() * HA),
                            commun_ha=float(commun.sum() * HA),
                            crue_commun_ha=float((crue & commun).sum() * HA),
                            vv_median_commun=float(np.nanmedian(x[commun]))
                            if commun.any()
                            else np.nan,
                            ref_vv_commun=float(np.nanmedian(ref[commun]))
                            if commun.any()
                            else np.nan,
                        )
                    )
pd.DataFrame(rows).to_csv(f"{S}/orbites_couverture.csv", index=False)
print("terminé")
