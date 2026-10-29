# ruff: noqa
"""V2.0 marée, tronçons salés de la BD TOPO sur le domaine, distances à la côte. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import sys, geopandas as gpd, pandas as pd, numpy as np

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
t = gpd.read_parquet(f"{S}/maree/troncons.parquet")
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
lm = gpd.read_parquet(f"{S}/limite_terre_mer.parquet")
D = dom.geometry.union_all()
t["sal"] = t.salinite == "True"
t["fic"] = t.fictif == "True"
t["L"] = t.length
t["dans"] = t.intersects(D)
print(
    "tronçons",
    len(t),
    "dont dans le domaine",
    int(t.dans.sum()),
    "; km total",
    round(t.L.sum() / 1e3),
    "; km dans le domaine",
    round(t[t.dans].L.sum() / 1e3),
)
print(
    "salinité vraie : n",
    int(t.sal.sum()),
    "; dans le domaine",
    int((t.sal & t.dans).sum()),
    "; km",
    round(t[t.sal & t.dans].L.sum() / 1e3),
)
print(t[t.sal].groupby("nature").size().to_dict())
print(
    "dans le domaine, salé par nature (km):",
    (t[t.sal & t.dans].groupby("nature").L.sum() / 1e3).round(1).to_dict(),
)
for marais, g in dom.geometry.items():
    m = t[t.intersects(g)]
    print(
        marais,
        "tronçons",
        len(m),
        "salés",
        int(m.sal.sum()),
        "km salés",
        round(m[m.sal].L.sum() / 1e3, 1),
        "km totaux",
        round(m.L.sum() / 1e3),
    )
# surface couverte par buffer des tronçons salés
sal = t[t.sal & ~t.fic]
for d in (25, 50, 100, 250):
    b = sal.geometry.buffer(d).union_all()
    print(
        f"domaine dans {d} m d'un tronçon salé :",
        {k: round(g.intersection(b).area / 1e4) for k, g in dom.geometry.items()},
        "ha",
    )
# limites spéciales
lim = lm[lm.type_de_limite.isin(["Limite de salure des eaux", "Limite transversale de la mer"])]
print(
    "limites : ",
    len(lim),
    "; à moins de 20 m d'un tronçon salé :",
    int(lim.geometry.apply(lambda g: (sal.geometry.distance(g) < 20).any()).sum()),
)
# où se situent les tronçons salés les plus à l'intérieur : distance à la limite terre-mer
coast = lm[lm.type_de_limite.isna() & (lm.niveau == "Plus hautes eaux")].geometry.union_all()
sd = sal[sal.intersects(D)].copy()
sd["dist_cote"] = sd.geometry.centroid.distance(coast)
print(
    "tronçons salés dans le domaine, distance à la côte (m):",
    sd.dist_cote.describe().round(0).to_dict(),
)
print(
    "km salés dans le domaine par classe de distance :",
    (sd.groupby(pd.cut(sd.dist_cote, [0, 500, 1000, 2000, 5000, 10000, 50000])).L.sum() / 1e3)
    .round(1)
    .to_dict(),
)
