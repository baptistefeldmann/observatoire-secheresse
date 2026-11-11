# ruff: noqa
"""V2.0 masque d'eau permanente de Sentinel-1 (orbite 81, juillet à septembre 2015-2025) : pixels sombres (VV filtré ≤ −16 dB) dans plus de la moitié des passages ; stabilité d'une année à l'autre, comparaison à la BD TOPO, effet sur la surface de crue des hivers 2023-2024 et 2024-2025. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 3.9)."""

import warnings

warnings.filterwarnings("ignore")
import os, time, numpy as np, pandas as pd, geopandas as gpd, dask
import odc.stac, planetary_computer
from scipy import ndimage as ndi
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import geometry_mask, rasterize

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
ORBITE, ANNEES, SEUIL_VV, PART = 81, range(2015, 2026), -16, 0.5
HIVERS = [("2023-12-01/2024-03-31", 2023), ("2024-12-01/2025-03-31", 2024)]
HA = 0.01
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
hydro = gpd.read_parquet(f"{S}/surface_hydro.parquet")
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
t0 = time.time()


def charger(its, gb):
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
    return np.where(np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan).astype(
        "float32"
    )


def lisse(x):
    return ndi.median_filter(np.where(np.isfinite(x), x, np.nanmedian(x)), size=3)


rows = []
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    sombre, valide, par_an, refs = (
        np.zeros(gb.shape, "uint16"),
        np.zeros(gb.shape, "uint16"),
        {},
        {},
    )
    for an in ANNEES:
        its = [
            i
            for i in cl.search(
                collections=["sentinel-1-rtc"], bbox=bb, datetime=f"{an}-07-01/{an}-09-30"
            ).items()
            if i.properties["sat:relative_orbit"] == ORBITE
        ]
        if not its:
            print(marais, an, "aucun passage", flush=True)
            continue
        db = charger(its, gb)
        s_an, v_an = np.zeros(gb.shape, "uint16"), np.zeros(gb.shape, "uint16")
        for k in range(db.shape[0]):
            ok = np.isfinite(db[k])
            s_an += ((lisse(db[k]) <= SEUIL_VV) & ok).astype("uint16")
            v_an += ok.astype("uint16")
        sombre += s_an
        valide += v_an
        par_an[an] = (s_an / np.maximum(v_an, 1)) > PART
        if an in (2023, 2024):
            refs[an] = np.nanmedian(db, axis=0)
        print(marais, an, db.shape[0], "passages", f"t={time.time() - t0:.0f}s", flush=True)
    frac = sombre / np.maximum(valide, 1)
    masque = (frac > PART) & (valide > 0)
    ha = lambda m: float((m & dans).sum() * HA)
    print(
        f"\\n=== {marais} : masque fixe (part de passages sombres > {PART}) : {ha(masque):.0f} ha sur {ha(np.ones_like(dans)):.0f} ; passages cumulés par pixel : médiane {int(np.median(valide[dans]))}"
    )
    for seuil in (0.3, 0.4, 0.5, 0.6, 0.7):
        print(f"   part > {seuil} : {ha(frac > seuil):.0f} ha")
    for an, m in par_an.items():
        j = (m & masque & dans).sum() / max((m | masque).__and__(dans).sum(), 1)
        rows.append(
            dict(
                marais=marais,
                annee=an,
                ha_annee=ha(m),
                ha_fixe=ha(masque),
                jaccard=round(float(j), 2),
                ha_annee_hors_fixe=ha(m & ~masque),
                ha_fixe_hors_annee=ha(masque & ~m),
            )
        )
    # BD TOPO : surfaces d'eau
    h = hydro[hydro.intersects(geom)]
    m_h = rasterize(
        [(g, 1) for g in h.geometry if not g.is_empty],
        out_shape=gb.shape,
        transform=gb.affine,
        fill=0,
    ).astype(bool)
    print(
        f"   BD TOPO surface d'eau : {ha(m_h):.0f} ha ; dans le masque : {ha(m_h & masque):.0f} ha ; masque hors BD TOPO : {ha(masque & ~m_h):.0f} ha"
    )
    np.savez_compressed(
        f"{S}/masque_eau_permanente_{marais}.npz",
        masque=masque,
        frac=(frac * 100).astype("uint8"),
        valide=valide,
    )
    # effet sur la surface de crue des deux hivers (orbite 81)
    for hiver, an_ref in HIVERS:
        its = [
            i
            for i in cl.search(collections=["sentinel-1-rtc"], bbox=bb, datetime=hiver).items()
            if i.properties["sat:relative_orbit"] == ORBITE
        ]
        db = charger(its, gb)
        ref = refs[an_ref]
        rf = lisse(ref)
        sans, avec = [], []
        for k in range(db.shape[0]):
            x = db[k]
            ok = np.isfinite(x) & np.isfinite(ref)
            xf = lisse(np.where(ok, x, np.nan))
            c0 = ((xf - rf) < -3) & (xf < SEUIL_VV) & (rf >= -16) & ok
            lab, _ = ndi.label(c0)
            tai = np.bincount(lab.ravel())
            crue = np.isin(lab, np.where(tai >= 10)[0]) & (lab > 0)
            sans.append(ha(crue))
            avec.append(ha(crue & ~masque))
        print(
            f"   hiver {hiver[:7]} : {len(sans)} passages ; surface de crue médiane sans masque {np.median(sans):.0f} ha, avec masque {np.median(avec):.0f} ha (écart {np.median(np.array(sans) - np.array(avec)):.0f} ha)",
            flush=True,
        )
pd.DataFrame(rows).to_csv(f"{S}/masque_eau_permanente_annees.csv", index=False)
print(pd.DataFrame(rows).to_string())
print("terminé")
