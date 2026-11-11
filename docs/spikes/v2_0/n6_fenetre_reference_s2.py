# ruff: noqa
"""V2.0 fenêtre de référence de Sentinel-2 : scènes L2A par tuile, par année et par mois sur le département, avec baseline connue (catalogue STAC seulement, aucun pixel lu). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 4.4)."""

import warnings

warnings.filterwarnings("ignore")
import os, collections, numpy as np, pandas as pd, geopandas as gpd
from pystac_client import Client

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
communes = gpd.read_parquet("data/referentiels/communes.parquet").to_crs(4326)
bb = tuple(communes.total_bounds)
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
rows = []
for an in range(2015, 2027):
    for mois in range(1, 13):
        if an == 2026 and mois > 10:
            continue
        deb = f"{an}-{mois:02d}-01"
        fin = f"{an + (mois == 12)}-{(mois % 12) + 1:02d}-01"
        for it in cl.search(
            collections=["sentinel-2-l2a"], bbox=bb, datetime=f"{deb}/{fin}", max_items=2000
        ).items():
            if it.datetime.strftime("%Y-%m") != f"{an}-{mois:02d}":
                continue
            rows.append(
                dict(
                    annee=an,
                    mois=mois,
                    tuile=it.properties.get("s2:mgrs_tile", it.id.split("_")[1]),
                    date=it.datetime.date(),
                    nuage=it.properties.get("eo:cloud_cover", np.nan),
                    baseline=it.properties.get("s2:processing_baseline"),
                    plateforme=it.properties.get("platform"),
                )
            )
    print(an, len(rows), flush=True)
d = pd.DataFrame(rows)
d.to_csv(f"{S}/scenes_s2_departement.csv", index=False)
print("terminé", len(d))
