# ruff: noqa
"""V2.0 E et F : (E) médiane contre moyenne sur juillet 2025 ; (F) NDMI contre NDVI, juillet 2022 (sec) contre juillet 2023, par classe
(cultures par année avec le RPG de l'année, prairies permanentes, forêts BD Forêt). Fenêtre mixte de 15 x 15 km."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import io, requests, pandas as pd, time

gb = geobox("mixte")
b = (
    gpd.GeoSeries.from_xy(
        [gb.boundingbox.left, gb.boundingbox.right],
        [gb.boundingbox.bottom, gb.boundingbox.top],
        crs=2154,
    )
    .to_crs(4326)
    .total_bounds
)
bbox = f"{b[1]},{b[0]},{b[3]},{b[2]},urn:ogc:def:crs:EPSG::4326"


def wfs(layer):
    p = dict(
        SERVICE="WFS",
        VERSION="2.0.0",
        REQUEST="GetFeature",
        TYPENAMES=layer,
        OUTPUTFORMAT="application/json",
        SRSNAME="EPSG:2154",
        BBOX=bbox,
        COUNT=5000,
    )
    g = gpd.read_file(
        io.BytesIO(requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=600).content)
    )
    return g.set_crs(2154) if g.crs is None else g.to_crs(2154)


bf = gpd.read_parquet(f"{V}/bdforet.parquet")
rpg25 = gpd.read_parquet(f"{V}/rpg.parquet")


def classes(annee):
    r = rpg25.copy() if annee == 2025 else wfs(f"RPG.{annee}:parcelles_graphiques")
    r["g"] = r["code_group"].astype(int)
    return {
        "maïs": r[r.g == 2],
        "blé tendre": r[r.g == 1],
        "tournesol": r[r.g == 6],
        "prairies permanentes": rpg25[rpg25.code_group.astype(int) == 18],
        "feuillus (BD Forêt)": bf[bf.tfv_g11 == "Forêt fermée feuillus"],
        "chênes purs (BD Forêt)": bf[bf.code_tfv == "FF1G01-01"],
    }


res, t0 = [], time.time()


def composite(annee, mois):
    its = recherche(gb, f"{annee}-{mois}-01/{annee}-{mois}-31", 80)
    ds, meta = cube(its, gb)
    v = valide(ds)
    ndvi, ndmi = indices(reflectances(ds, meta, True))
    ndvi, ndmi = ndvi.where(v), ndmi.where(v)
    return ds, meta, v, ndvi.values, ndmi.values


# ---- F : 2022 contre 2023
for annee in (2022, 2023) if not os.path.exists(f"{V}/ndmi_vs_ndvi.csv") else ():
    ds, meta, v, ndvi, ndmi = composite(annee, "07")
    cl = classes(annee)
    med_ndvi, med_ndmi = np.nanmedian(ndvi, axis=0), np.nanmedian(ndmi, axis=0)
    print(
        "juillet",
        annee,
        len(meta),
        "dates ; baselines",
        sorted({m["baseline"] for m in meta}),
        f"t={time.time() - t0:.0f}s",
        flush=True,
    )
    for nom, g in cl.items():
        m = masque(g, gb)
        a, c = med_ndvi[m & np.isfinite(med_ndvi)], med_ndmi[m & np.isfinite(med_ndmi)]
        if len(a) < 500:
            continue
        res.append(
            dict(
                annee=annee,
                classe=nom,
                n_px=len(a),
                ndvi_med=np.median(a),
                ndvi_sig=1.4826 * np.median(abs(a - np.median(a))),
                ndmi_med=np.median(c),
                ndmi_sig=1.4826 * np.median(abs(c - np.median(c))),
            )
        )
if res:
    pd.DataFrame(res).to_csv(f"{V}/ndmi_vs_ndvi.csv", index=False)
# ---- E : médiane contre moyenne, juillet 2025
ds, meta, v, ndvi, ndmi = composite(2025, "07")
med, moy = np.nanmedian(ndvi, axis=0), np.nanmean(ndvi, axis=0)
nobs = np.isfinite(ndvi).sum(0)
mn = np.nanmin(ndvi, axis=0)
ok = np.isfinite(med) & np.isfinite(moy)
d = (moy - med)[ok]
out = dict(
    dates=len(meta),
    px=int(ok.sum()),
    nobs_med=float(np.median(nobs[ok])),
    **{f"nobs_{k}": float((nobs[ok] == k).mean()) for k in (1, 2, 3, 4, 5)},
    nobs_ge6=float((nobs[ok] >= 6).mean()),
    moy_moins_med_p50=float(np.median(d)),
    moy_moins_med_p5=float(np.percentile(d, 5)),
    moy_moins_med_p95=float(np.percentile(d, 95)),
    **{f"abs_gt_{t}": float((abs(d) > t).mean()) for t in (0.02, 0.05, 0.1)},
    ombre_possible=float(((mn - med)[ok] < -0.3).mean()),
)
cl = classes(2025)
cls = []
for nom, g in cl.items():
    m = masque(g, gb) & ok
    if m.sum() < 500:
        continue
    cls.append(
        dict(
            classe=nom,
            n_px=int(m.sum()),
            mediane=float(np.median(med[m])),
            moyenne=float(np.mean(moy[m])),
            sig_med=float(1.4826 * np.median(abs(med[m] - np.median(med[m])))),
            sig_moy=float(np.std(moy[m])),
            diff_pixels_abs_p95=float(np.percentile(abs((moy - med)[m]), 95)),
        )
    )
pd.DataFrame([out]).to_csv(f"{V}/mediane_moyenne.csv", index=False)
pd.DataFrame(cls).to_csv(f"{V}/mediane_moyenne_classes.csv", index=False)
print("terminé", f"t={time.time() - t0:.0f}s")
