"""Normales de l'IPS par piézomètre et par mois (SPEC §6.2, méthodologie D7).

Niveau moyen mensuel, un mois comptant s'il a au moins `jours_min_mois` jours de mesures.
La normale d'un mois est l'ensemble des moyennes de ce mois sur les années retenues : l'IPS
en est déduit par une approche non paramétrique (voir `pipeline.indices`)."""

from __future__ import annotations

import pandas as pd

from pipeline.config import Config
from pipeline.reference.commun import choisir_annees, lire_brut, ruptures


def moyennes_mensuelles(obs: pd.DataFrame, jours_min: int) -> pd.DataFrame:
    """station_id, annee, mois, niveau_moyen, n_jours ; mois incomplets écartés."""
    table = obs[["station_id", "date", "niveau_ngf"]].copy()
    dates = pd.to_datetime(table["date"])
    table["annee"], table["mois"] = dates.dt.year, dates.dt.month
    mensuel = table.groupby(["station_id", "annee", "mois"], as_index=False).agg(
        niveau_moyen=("niveau_ngf", "mean"), n_jours=("niveau_ngf", "size")
    )
    return mensuel[mensuel["n_jours"] >= jours_min].reset_index(drop=True)


COLONNES = [
    "station_id",
    "mois",
    "valeurs_ref",
    "n_annees",
    "periode_ref",
    "hors_reference",
    "rupture",
]


def normales(config: Config, obs: pd.DataFrame | None = None) -> pd.DataFrame:
    ref = config.projet.periode_reference.hydro_meteo
    annees_rupture = ruptures(config)
    obs = obs if obs is not None else lire_brut(config, "piezo", "chroniques")
    mensuel = moyennes_mensuelles(obs, config.projet.indices.ips.jours_min_mois)
    lignes = []
    for (station_id, mois), groupe in mensuel.groupby(["station_id", "mois"]):
        choix = choisir_annees(set(groupe["annee"]), ref, annees_rupture.get(str(station_id)))
        if not choix.annees:
            continue
        valeurs = groupe.loc[groupe["annee"].isin(choix.annees), "niveau_moyen"]
        lignes.append(
            {
                "station_id": station_id,
                "mois": mois,
                "valeurs_ref": sorted(float(v) for v in valeurs),
                "n_annees": len(choix.annees),
                "periode_ref": choix.periode_ref,
                "hors_reference": choix.hors_reference,
                "rupture": annees_rupture.get(str(station_id)),
            }
        )
    return (
        pd.DataFrame(lignes, columns=COLONNES)
        .astype({"rupture": "Int64"})
        .sort_values(["station_id", "mois"], ignore_index=True)
    )
