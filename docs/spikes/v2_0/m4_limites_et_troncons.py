# ruff: noqa
"""V2.0 marée, distance des limites de salure et transversales de la mer aux tronçons. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import sys, geopandas as gpd, pandas as pd, numpy as np

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
t = gpd.read_parquet(f"{S}/maree/troncons.parquet").reset_index(drop=True)
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
D = dom.geometry.union_all()
lm = gpd.read_parquet(f"{S}/limite_terre_mer.parquet")
lim = lm[
    lm.type_de_limite.isin(["Limite de salure des eaux", "Limite transversale de la mer"])
].copy()
sal = t[(t.salinite == "True") & (t.fictif != "True")]
est = t[t.nature == "Estuaire"]
nonfic = t[t.fictif != "True"]
lim["d_dom"] = lim.geometry.distance(D)
lim["d_sal"] = lim.geometry.apply(lambda g: sal.geometry.distance(g).min())
lim["d_est"] = lim.geometry.apply(lambda g: est.geometry.distance(g).min())
lim["d_troncon"] = lim.geometry.apply(lambda g: nonfic.geometry.distance(g).min())
lim["long"] = lim.length
lim["nom"] = lim.get("toponyme", None)
c = lim.sort_values("d_dom")[
    ["type_de_limite", "d_dom", "d_sal", "d_est", "d_troncon", "long"]
].round(0)
c["type_de_limite"] = c.type_de_limite.str.replace("Limite ", "")
print(c.head(30).to_string(index=False))
print(
    "\nlimites à moins de 2 km du domaine :",
    int((lim.d_dom < 2000).sum()),
    "; dont à moins de 100 m d'un tronçon non fictif :",
    int(((lim.d_dom < 2000) & (lim.d_troncon < 100)).sum()),
)
print("colonnes de la couche :", [x for x in lm.columns if x != "geometry"])
