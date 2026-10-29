# ruff: noqa
"""V2.0 marée, réseau maritime : parcours du graphe depuis la mer jusqu'aux limites, cinq variantes (la variante D est retenue). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import sys, geopandas as gpd, pandas as pd, numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
t = gpd.read_parquet(f"{S}/maree/troncons.parquet").reset_index(drop=True)
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
D = dom.geometry.union_all()
lm = gpd.read_parquet(f"{S}/limite_terre_mer.parquet")
print(
    t[["lien_vers_noeud_hydrographique_ini", "lien_vers_noeud_hydrographique_fin"]]
    .head(3)
    .to_string()
)
ini, fin = t.lien_vers_noeud_hydrographique_ini, t.lien_vers_noeud_hydrographique_fin
print("nœuds renseignés :", int(ini.ne("None").sum()), int(fin.ne("None").sum()), "/", len(t))


# nœuds absents : repli sur les coordonnées des extrémités (arrondies au décimètre)
def bout(g, i):
    ls = list(g.geoms)[0] if g.geom_type == "MultiLineString" else g
    c = ls.coords[0] if i == 0 else ls.coords[-1]
    return f"{round(c[0], 1)}_{round(c[1], 1)}"


a = np.where(ini.eq("None") | ini.eq("nan"), t.geometry.apply(lambda g: bout(g, 0)), ini)
b = np.where(fin.eq("None") | fin.eq("nan"), t.geometry.apply(lambda g: bout(g, 1)), fin)
tout = np.concatenate([a, b]).astype(str)
ids, uniq = pd.factorize(pd.Series(tout), use_na_sentinel=False)
n = len(uniq)
print("nœuds distincts", n, "; indices négatifs", int((ids < 0).sum()))
ia, ib = ids[: len(t)], ids[len(t) :]
lim = lm[
    lm.type_de_limite.isin(["Limite de salure des eaux", "Limite transversale de la mer"])
].geometry.union_all()
coast = lm[lm.type_de_limite.isna() & (lm.niveau == "Plus hautes eaux")].geometry.union_all()
bloque = t.geometry.distance(lim) < 15
depart = (t.geometry.distance(coast) < 30) | (t.nature == "Estuaire")
print("tronçons bloqués par une limite :", int(bloque.sum()), "; départs :", int(depart.sum()))
print("réseau_principal_coulant:", t.reseau_principal_coulant.value_counts().to_dict())
large = t.classe_de_largeur.isin(["Entre 5 et 15 m", "Entre 15 et 50 m", "Plus de 50 m"])
sal = t.salinite == "True"
fic = t.fictif == "True"
variantes = {
    "A tous": ~bloque,
    "B sans fictifs": ~bloque & ~fic,
    "C salé ou estuaire ou large (>5 m), sans fictifs": ~bloque
    & ~fic
    & (sal | (t.nature == "Estuaire") | large),
    "D salé ou estuaire, sans fictifs": ~bloque & ~fic & (sal | (t.nature == "Estuaire")),
    "E large (>5 m) ou estuaire, sans fictifs": ~bloque & ~fic & ((t.nature == "Estuaire") | large),
}
for nom, ok in variantes.items():
    ok = ok.values
    m = coo_matrix((np.ones(int(ok.sum())), (ia[ok], ib[ok])), shape=(n, n))
    nc, lab = connected_components(m, directed=False)
    labs_dep = set(lab[ia[depart.values & ok]])
    atteint = ok & pd.Series(lab[ia]).isin(labs_dep).values
    r = t[atteint]
    rd = r[r.intersects(D)]
    print(
        f"[{nom}] atteints {len(r)}, {r.length.sum() / 1e3:.0f} km ; dans le domaine {len(rd)} tronçons, {rd.length.sum() / 1e3:.0f} km ; ",
        {k: round(r[r.intersects(g)].length.sum() / 1e3) for k, g in dom.geometry.items()},
        "km",
    )
    r.to_parquet(f"{S}/maree/atteint_{nom[0]}.parquet")
