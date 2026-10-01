"""Normales de l'indice de débit par station et par semaine (SPEC §6.2, méthodologie D4, D7).

Débit moyen sur 7 jours (Q7), calculé si au moins `jours_min_q7` jours sont renseignés. La
normale d'une semaine réunit les Q7 des dates situées à ±`demi_fenetre_jours` du dimanche de
cette semaine, sur chaque année retenue (une année compte si au moins `part_min_fenetre` de sa
fenêtre est renseignée). Les stations raccordées (D4) forment une seule série, rattachée à la
première station de la liste."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.reference.commun import SEMAINE_MAX, choisir_annees, lire_brut, ruptures


def series(config: Config, obs: pd.DataFrame | None = None) -> pd.DataFrame:
    """station_id, date, qmj_ls, raccordements appliqués (priorité à la première station)."""
    obs = obs if obs is not None else lire_brut(config, "hydro", "qmj")
    table = obs[["station_id", "date", "qmj_ls"]].copy()
    for raccordement in config.stations.raccordements_hydro:
        ids = [f"hydro:{code}" for code in raccordement.stations]
        partie = table[table["station_id"].isin(ids)].copy()
        partie["priorite"] = partie["station_id"].map({s: i for i, s in enumerate(ids)})
        fusion = partie.sort_values("priorite").drop_duplicates("date", keep="first")
        fusion["station_id"] = ids[0]
        table = pd.concat([table[~table["station_id"].isin(ids)], fusion.drop(columns="priorite")])
    return table.sort_values(["station_id", "date"], ignore_index=True)


def q7(series_debit: pd.DataFrame, jours_min: int) -> pd.DataFrame:
    """Débit moyen glissant sur 7 jours terminés à chaque date : station_id, date, q7."""
    morceaux = []
    for station_id, groupe in series_debit.groupby("station_id"):
        journalier = groupe.set_index(pd.to_datetime(groupe["date"]))["qmj_ls"].asfreq("D")
        glissant = journalier.rolling(7, min_periods=jours_min).mean().dropna()
        morceaux.append(
            pd.DataFrame(
                {"station_id": station_id, "date": glissant.index, "q7": glissant.to_numpy()}
            )
        )
    if not morceaux:
        return pd.DataFrame(columns=["station_id", "date", "q7"])
    return pd.concat(morceaux, ignore_index=True)


def fenetres(annees: range, demi: int) -> pd.DataFrame:
    """Pour chaque année ISO et semaine 1-52 : les dates à ±demi jours du dimanche."""
    decalages = np.arange(-demi, demi + 1)
    lignes = []
    for annee in annees:
        for semaine in range(1, SEMAINE_MAX + 1):
            dimanche = pd.Timestamp(date.fromisocalendar(annee, semaine, 7))
            for d in decalages:
                lignes.append((annee, semaine, dimanche + pd.Timedelta(days=int(d))))
    return pd.DataFrame(lignes, columns=["annee", "semaine", "date"])


COLONNES = [
    "station_id",
    "semaine",
    "valeurs_ref",
    "n_annees",
    "periode_ref",
    "hors_reference",
    "rupture",
]


def normales(config: Config, obs: pd.DataFrame | None = None) -> pd.DataFrame:
    ref = config.projet.periode_reference.hydro_meteo
    annees_rupture = ruptures(config)
    parametres = config.projet.indices.debit
    debits = q7(series(config, obs), parametres.jours_min_q7)
    if debits.empty:
        return pd.DataFrame(columns=COLONNES)
    annees = range(debits["date"].dt.year.min(), debits["date"].dt.year.max() + 1)
    cibles = fenetres(annees, parametres.demi_fenetre_jours)
    minimum = math.ceil((2 * parametres.demi_fenetre_jours + 1) * parametres.part_min_fenetre)
    lignes = []
    for station_id, groupe in debits.groupby("station_id"):
        valeurs = cibles.merge(groupe[["date", "q7"]], on="date")
        couverture = valeurs.groupby(["semaine", "annee"])["q7"].count().reset_index(name="n")
        for semaine, par_annee in couverture.groupby("semaine"):
            valides = {int(a) for a in par_annee.loc[par_annee["n"] >= minimum, "annee"]}
            choix = choisir_annees(valides, ref, annees_rupture.get(str(station_id)))
            if not choix.annees:
                continue
            retenues = valeurs[
                (valeurs["semaine"] == semaine) & valeurs["annee"].isin(choix.annees)
            ]
            lignes.append(
                {
                    "station_id": station_id,
                    "semaine": semaine,
                    "valeurs_ref": sorted(float(v) for v in retenues["q7"]),
                    "n_annees": len(choix.annees),
                    "periode_ref": choix.periode_ref,
                    "hors_reference": choix.hors_reference,
                    "rupture": annees_rupture.get(str(station_id)),
                }
            )
    return (
        pd.DataFrame(lignes, columns=COLONNES)
        .astype({"rupture": "Int64"})
        .sort_values(["station_id", "semaine"], ignore_index=True)
    )
