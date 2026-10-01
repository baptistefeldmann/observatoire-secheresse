"""Détection des ruptures de fonctionnement des stations (méthodologie D8).

Test de Pettitt sur les moyennes annuelles des années complètes : niveau moyen pour la
piézométrie, logarithme du débit moyen pour l'hydrométrie. Le test ne décide rien : il
alimente le rapport de `make reference`. Seules les ruptures listées dans `stations.yaml`
modifient les normales."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.reference import debit
from pipeline.reference.commun import lire_brut, ruptures
from pipeline.reference.ips import moyennes_mensuelles

log = logging.getLogger(__name__)

ANNEES_MIN_TEST = 15
COLONNES = [
    "station_id", "source", "premiere_annee", "derniere_annee", "n_annees", "annee_rupture",
    "p_valeur", "ecart", "significative", "traitee",
]  # fmt: skip


def pettitt(valeurs: np.ndarray) -> tuple[int, float]:
    """(indice du premier élément après la rupture, p-valeur approchée) du test de Pettitt."""
    n = len(valeurs)
    stats_u = np.array(
        [np.sign(valeurs[t + 1 :, None] - valeurs[None, : t + 1]).sum() for t in range(n - 1)]
    )
    t = int(np.argmax(np.abs(stats_u)))
    k = float(abs(stats_u[t]))
    return t + 1, min(1.0, 2 * float(np.exp(-6 * k**2 / (n**3 + n**2))))


def _tester(
    source: str, annuel: pd.Series, config: Config, traitees: set[str]
) -> list[dict[str, object]]:
    seuil = config.projet.indices.ruptures.seuil_p
    lignes: list[dict[str, object]] = []
    for station_id, serie in annuel.groupby(level="station_id"):
        serie = serie.droplevel("station_id").sort_index()
        if len(serie) < ANNEES_MIN_TEST:
            continue
        i, p = pettitt(serie.to_numpy())
        avant, apres = serie.iloc[:i].mean(), serie.iloc[i:].mean()
        ecart = float(apres - avant) if source == "piezo" else float(np.exp(apres - avant))
        lignes.append(
            {
                "station_id": station_id, "source": source,
                "premiere_annee": int(serie.index[0]), "derniere_annee": int(serie.index[-1]),
                "n_annees": len(serie), "annee_rupture": int(serie.index[i]), "p_valeur": p,
                "ecart": round(ecart, 3), "significative": p < seuil,
                "traitee": station_id in traitees,
            }
        )  # fmt: skip
    return lignes


def detecter(config: Config) -> pd.DataFrame:
    parametres = config.projet.indices.ruptures
    traitees = set(ruptures(config))
    mensuel = moyennes_mensuelles(
        lire_brut(config, "piezo", "chroniques"), config.projet.indices.ips.jours_min_mois
    )
    completes = mensuel.groupby(["station_id", "annee"])["niveau_moyen"].agg(["mean", "size"])
    piezo = completes.loc[completes["size"] >= parametres.mois_min_annee, "mean"]

    debits = debit.series(config)
    debits["annee"] = pd.to_datetime(debits["date"]).dt.year
    annuels = debits.groupby(["station_id", "annee"])["qmj_ls"].agg(["mean", "size"])
    annuels = annuels[annuels["size"] >= parametres.jours_min_annee]
    hydro = np.log(annuels["mean"].clip(lower=1))  # débits nuls : plancher à 1 l/s

    table = pd.DataFrame(
        _tester("piezo", piezo, config, traitees) + _tester("hydro", hydro, config, traitees),
        columns=COLONNES,
    )
    for _, r in table[table["significative"] & ~table["traitee"]].iterrows():
        log.warning(
            "rupture possible non traitée : %s en %d (p = %.4f) — à examiner (stations.yaml)",
            r["station_id"], r["annee_rupture"], r["p_valeur"],
        )  # fmt: skip
    return table.sort_values(["source", "p_valeur"], ignore_index=True)
