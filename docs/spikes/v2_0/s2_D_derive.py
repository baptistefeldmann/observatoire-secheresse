# ruff: noqa
"""V2.0 D : contrôle de dérive radiométrique. NDVI/NDMI des cibles stables (pin maritime ; chênes décidus), juillet-août 2018-2025, par scène."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import pandas as pd, time

bf = gpd.read_parquet(f"{V}/bdforet.parquet")
CIBLES = {
    ("pin", "pin maritime pur"): bf[bf.code_tfv == "FF2-51-51"],
    ("mixte", "chênes décidus purs"): bf[bf.code_tfv == "FF1G01-01"],
}
rows = []
t0 = time.time()
for (fen, nom), g in CIBLES.items():
    gb = geobox(fen)
    m = masque(g, gb)
    print(nom, "pixels purs dans la fenêtre", int(m.sum()), flush=True)
    for annee in range(2018, 2026):
        its = recherche(gb, f"{annee}-07-01/{annee}-08-31", nuage_max=40)
        if not its:
            continue
        ds, meta = cube(its, gb)
        v = valide(ds)
        ndvi, ndmi = indices(reflectances(ds, meta, True))
        ndvi_brut, _ = indices(reflectances(ds, meta, False))
        for k, mt in enumerate(meta):
            ok = v.isel(time=k).values & m
            if ok.sum() < 200:
                continue
            rows.append(
                dict(
                    cible=nom,
                    annee=annee,
                    **mt,
                    n_px=int(ok.sum()),
                    ndvi=float(np.median(ndvi.isel(time=k).values[ok])),
                    ndmi=float(np.median(ndmi.isel(time=k).values[ok])),
                    ndvi_brut=float(np.median(ndvi_brut.isel(time=k).values[ok])),
                )
            )
        print(" ", nom, annee, len(meta), "dates", f"t={time.time() - t0:.0f}s", flush=True)
pd.DataFrame(rows).to_csv(f"{V}/derive.csv", index=False)
print("terminé")
