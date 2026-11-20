# ruff: noqa
"""V2.2d : chiffrage des seuils laissés ouverts par D15, sur les composites mensuels réels
(`rasters/mensuel/`, 2018-2025) et les classes de 2025 (`rasters/classes/`). Jetable, hors dépôt de
production (résultats : docs/spikes/07_v2_chiffrage.md, section 4.5).

1. Règle 2 : NDVI d'été (moyenne de juillet et août) sous un seuil, par classe de forêt et par année.
2. Règle 3 : écart de NDVI été - hiver (janvier et février) par classe, pixel par pixel, médiane des
   années ; seuils séparant feuillage persistant et caduc.
3. Observations : nombre de dates valides par pixel et par mois (part des pixels sous 3, 2, 1 date),
   par type de classe et par zone.
"""

import os, sys, warnings

warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, rasterio, geopandas as gpd
from pathlib import Path
from rasterio.features import rasterize

sys.path.insert(0, os.getcwd())
from pipeline.config import charger_config

config = charger_config(Path("config"))
M = Path(config.projet.chemins.rasters) / "mensuel"
OUT = M / "_analyse"
OUT.mkdir(exist_ok=True)
ANNEES = list(range(2018, 2026))
slug = config.projet.territoire.slug
cl = rasterio.open(f"rasters/classes/ocs_2025_{slug}.tif").read(1)
nomen = config.nomenclature_ocs
foret = {c.code: c for c in nomen.foret.classes}
cultures = {c.code: c for c in nomen.cultures.classes}
dans_foret = np.isin(cl, list(foret))
idx = np.flatnonzero(dans_foret.ravel())
classe_f = cl.ravel()[idx]


def lire(annee, mois, nom="ndvi"):
    f = M / f"{annee}-{mois:02d}" / f"{nom}.tif"
    if not f.is_file():
        return None
    with rasterio.open(f) as s:
        a = s.read(1).ravel()
    return a


def indice(annee, mois, nom="ndvi"):
    a = lire(annee, mois, nom)
    if a is None:
        return None
    v = a[idx].astype("float32") / 10000
    v[a[idx] == -32768] = np.nan
    return v


def moyenne(*valeurs):
    v = [x for x in valeurs if x is not None]
    return np.nanmean(np.stack(v), axis=0) if v else None


# ---- 1 et 2 : NDVI d'été et d'hiver sur les pixels de forêt de 2025
ete, hiver = {}, {}
for a in ANNEES:
    ete[a] = moyenne(indice(a, 7), indice(a, 8))
    hiver[a] = moyenne(indice(a, 1), indice(a, 2))
    print(
        a,
        "été",
        None if ete[a] is None else "ok",
        "hiver",
        None if hiver[a] is None else "ok",
        flush=True,
    )

SEUILS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
lignes = []
for code, c in foret.items():
    m = classe_f == code
    for a in ANNEES:
        v = ete[a]
        if v is None:
            continue
        x = v[m]
        x = x[np.isfinite(x)]
        lignes.append(
            dict(
                classe=c.id,
                annee=a,
                n=len(x),
                p01=np.percentile(x, 1),
                p05=np.percentile(x, 5),
                p10=np.percentile(x, 10),
                mediane=np.median(x),
                **{f"sous_{s:.2f}": 100 * (x < s).mean() for s in SEUILS},
            )
        )
t1 = pd.DataFrame(lignes)
t1.to_csv(OUT / "regle2_ndvi_ete.csv", index=False)
pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)
print("\n== Règle 2 : part des pixels de forêt sous un seuil de NDVI d'été (juillet-août), %")
print(
    t1.groupby("classe")[[f"sous_{s:.2f}" for s in SEUILS]]
    .agg(["median", "max"])
    .round(1)
    .to_string()
)
print("\nannée la plus sèche (2022) et la plus récente (2025) :")
print(
    t1[t1.annee.isin([2022, 2025])]
    .set_index(["classe", "annee"])[["mediane", "p05"] + [f"sous_{s:.2f}" for s in SEUILS]]
    .round(2)
    .to_string()
)

# ---- 2 : écart été - hiver
ecarts = np.stack(
    [ete[a] - hiver[a] for a in ANNEES if ete[a] is not None and hiver[a] is not None]
)
ecart_med = np.nanmedian(ecarts, axis=0)
lignes = []
for code, c in foret.items():
    x = ecart_med[classe_f == code]
    x = x[np.isfinite(x)]
    lignes.append(
        dict(
            classe=c.id,
            feuillage=c.feuillage,
            n=len(x),
            **{f"p{p:02d}": np.percentile(x, p) for p in (5, 25, 50, 75, 95)},
        )
    )
t2 = pd.DataFrame(lignes)
t2.to_csv(OUT / "regle3_ecart_ete_hiver.csv", index=False)
print("\n== Règle 3 : écart de NDVI été - hiver, médiane des années (pixels de forêt de 2025)")
print(t2.round(3).to_string())

persistant = np.isin(classe_f, [c.code for c in foret.values() if c.feuillage == "persistant"])
caduc = np.isin(
    classe_f, [c.code for c in foret.values() if c.feuillage == "caduc" and c.controle_foret]
)
mixte = np.isin(classe_f, [c.code for c in foret.values() if c.feuillage == "mixte"])
ok = np.isfinite(ecart_med)
print("\nSeuil unique tau : un pixel est « caduc » si écart ≥ tau (classes de feuillage connu)")
lignes = []
for tau in np.arange(0.05, 0.46, 0.025):
    e_pers = 100 * (ecart_med[persistant & ok] >= tau).mean()  # persistant pris pour caduc
    e_cad = 100 * (ecart_med[caduc & ok] < tau).mean()  # caduc pris pour persistant
    part_mixte = 100 * (ecart_med[mixte & ok] >= tau).mean()
    lignes.append(
        dict(
            tau=round(tau, 3),
            persistant_pris_caduc=e_pers,
            caduc_pris_persistant=e_cad,
            erreur_moyenne=(e_pers + e_cad) / 2,
            mixte_vu_caduc=part_mixte,
        )
    )
t3 = pd.DataFrame(lignes)
t3.to_csv(OUT / "regle3_seuil.csv", index=False)
print(t3.round(1).to_string(index=False))
best = t3.loc[t3.erreur_moyenne.idxmin()]
print("\nMeilleur seuil unique (erreur moyenne minimale) :", best.round(3).to_dict())

# ---- 3 : nombre de dates valides par pixel et par mois
print("\n== Nombre d'observations valides par pixel et par mois (n_obs), 2018-2025")
zones = gpd.read_parquet("data/referentiels/zones.parquet")
transform = rasterio.open(f"rasters/classes/ocs_2025_{slug}.tif").transform
zr = rasterize(
    [(g, i + 1) for i, g in enumerate(zones.geometry)],
    out_shape=cl.shape,
    transform=transform,
    fill=0,
    dtype="uint8",
)
z_id = zones.zone_id.tolist()
types = {"forêt": dans_foret, "cultures et prairies": np.isin(cl, list(cultures))}
lignes = []
for a in ANNEES:
    for mois in range(1, 13):
        f = M / f"{a}-{mois:02d}" / "n_obs.tif"
        if not f.is_file():
            continue
        n = rasterio.open(f).read(1)
        for nom, m in types.items():
            x = n[m]
            lignes.append(
                dict(
                    annee=a,
                    mois=mois,
                    type=nom,
                    **{f"sous_{k}": 100 * (x < k).mean() for k in (1, 2, 3)},
                    mediane=float(np.median(x)),
                )
            )
        for zi, zid in enumerate(z_id, 1):
            m = (zr == zi) & (types["forêt"] | types["cultures et prairies"])
            if m.any():
                x = n[m]
                lignes.append(
                    dict(
                        annee=a,
                        mois=mois,
                        type=f"zone {zid}",
                        **{f"sous_{k}": 100 * (x < k).mean() for k in (1, 2, 3)},
                        mediane=float(np.median(x)),
                    )
                )
t4 = pd.DataFrame(lignes)
t4.to_csv(OUT / "observations.csv", index=False)
g = t4[t4.type.isin(types)]
print("part des pixels sous k observations, par mois civil (moyenne 2018-2025), %")
print(
    g.groupby(["type", "mois"])[["sous_1", "sous_2", "sous_3", "mediane"]]
    .mean()
    .round(1)
    .unstack(0)
    .to_string()
)
print("\nmois × zone les plus pauvres (part de pixels sous 3 observations) :")
print(
    t4[t4.type.str.startswith("zone")]
    .sort_values("sous_3", ascending=False)
    .head(12)
    .round(1)
    .to_string(index=False)
)
print("terminé")
