"""[V2] Surface de crue : médiane mensuelle des passages et tendance des crues d'hiver.

Entrée : `data/satellite/crue_passages.parquet` (`pipeline.raster.crue`). Sorties :
`crue_mois.parquet` (une ligne par marais, variante de référence et mois civil) et
`crue_tendance.parquet` (pente de Theil-Sen et test de Kendall sur les hivers, comme D12).
Valeur brute en hectares : jamais un taux, jamais un indice standardisé à ce stade (rang en V2.3).
"""

from __future__ import annotations

import pandas as pd
from scipy import stats

from pipeline.config import Config
from pipeline.raster.crue import dossier_satellite, fichier_passages

MOIS_HIVER = (12, 1, 2, 3)


def _colonnes_ha(passages: pd.DataFrame) -> list[str]:
    return ["surface_ha", *[c for c in passages.columns if c.startswith("ha_")]]


def _preparer(passages: pd.DataFrame, pct_valides_min: float) -> pd.DataFrame:
    """Passages observables avec une surface ; mois civil et hiver (décembre N à mars N+1)."""
    p = passages[
        passages["surface_ha"].notna() & (passages["pct_valides"] >= pct_valides_min)
    ].copy()
    dates = pd.to_datetime(p["date"])
    p["mois"] = dates.dt.strftime("%Y-%m")
    p["hiver"] = (dates.dt.year - (dates.dt.month <= 3)).where(dates.dt.month.isin(MOIS_HIVER))
    return p


def agreger_mois(passages: pd.DataFrame, pct_valides_min: float = 0.0) -> pd.DataFrame:
    """Médiane mensuelle de la surface de crue et nombre de passages retenus."""
    p = _preparer(passages, pct_valides_min)
    colonnes = _colonnes_ha(p)
    groupes = p.groupby(["marais", "variante", "mois"], sort=True)
    resultat = groupes[colonnes].median()
    resultat["n_passages"] = groupes.size()
    resultat["pct_valides"] = groupes["pct_valides"].median()
    return resultat.reset_index()


def tendance_hiver(
    passages: pd.DataFrame, pct_valides_min: float = 0.0, hivers_min: int = 5, passages_min: int = 3
) -> pd.DataFrame:
    """Surface d'hiver (médiane des passages de décembre N à mars N+1), puis pente de Theil-Sen
    (hectares par an) et test de Kendall, par marais et variante de référence."""
    p = _preparer(passages, pct_valides_min)
    p = p[p["hiver"].notna()]
    p["mois_civil"] = pd.to_datetime(p["date"]).dt.month
    par_hiver = (
        p.groupby(["marais", "variante", "hiver"])
        .agg(
            surface_ha=("surface_ha", "median"),
            n_passages=("surface_ha", "size"),
            n_mois=("mois_civil", "nunique"),
        )
        .reset_index()
    )
    # D16 : un hiver n'est comparé aux autres que s'il a au moins un passage chaque mois de
    # décembre à mars (l'hiver 2014-2015 commence le 3 janvier : incomplet)
    par_hiver = par_hiver[
        (par_hiver["n_passages"] >= passages_min) & (par_hiver["n_mois"] == len(MOIS_HIVER))
    ]
    lignes: list[dict[str, object]] = []
    for (marais, variante), serie in par_hiver.groupby(["marais", "variante"]):
        n = len(serie)
        ligne: dict[str, object] = {
            "marais": marais,
            "variante": variante,
            "n_hivers": n,
            "premier_hiver": int(serie["hiver"].min()),
            "dernier_hiver": int(serie["hiver"].max()),
            "mediane_ha": float(serie["surface_ha"].median()),
        }
        if n >= hivers_min:
            pente, _, bas, haut = stats.theilslopes(serie["surface_ha"], serie["hiver"])
            tau, p_valeur = stats.kendalltau(serie["hiver"], serie["surface_ha"])
            ligne |= {
                "pente_ha_par_an": float(pente),
                "pente_ic95_bas": float(bas),
                "pente_ic95_haut": float(haut),
                "tau_kendall": float(tau),
                "p_kendall": float(p_valeur),
            }
        lignes.append(ligne)
    return pd.DataFrame(lignes)


def calculer(config: Config, pct_valides_min: float = 0.0) -> dict[str, pd.DataFrame]:
    # Seule la référence retenue (D16) est publiée ; les contrôles restent dans les passages
    retenue = config.projet.satellite.crue.reference.variante
    passages = pd.read_parquet(fichier_passages(config))
    passages = passages[passages["variante"] == retenue]
    sortie = dossier_satellite(config)
    tables = {
        "crue_mois": agreger_mois(passages, pct_valides_min),
        "crue_tendance": tendance_hiver(passages, pct_valides_min),
    }
    for nom, table in tables.items():
        table.to_parquet(sortie / f"{nom}.parquet", index=False)
    return tables
