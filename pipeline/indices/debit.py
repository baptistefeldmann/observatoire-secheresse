"""Indice de débit de la semaine par station (SPEC §6.2, méthodologie D4, D7, D9).

Débit moyen sur les 7 jours terminés le dimanche (au moins `jours_min_q7` jours renseignés),
classé parmi les Q7 de référence de la même semaine. Les stations raccordées (D4) forment une
seule série. Sans Q7 du dimanche, pas d'indice : la station manque au composite de la semaine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.indices.commun import dans_regime, libelle_semaine, z_rang
from pipeline.reference.commun import semaine_ref
from pipeline.reference.debit import q7, series

COLONNES = [
    "station_id", "semaine", "indice", "valeur", "periode_ref", "hors_reference",
    "date_mesure", "dans_composite",
]  # fmt: skip


def calculer(
    config: Config, obs: pd.DataFrame, normales: pd.DataFrame, dimanches: pd.DatetimeIndex
) -> pd.DataFrame:
    debits = series(config, obs).dropna(subset=["qmj_ls"])
    debits = debits[debits["station_id"].isin(normales["station_id"].unique())]
    semaine = q7(debits, config.projet.indices.debit.jours_min_q7)
    semaine = semaine[semaine["date"].isin(dimanches)]
    if semaine.empty:
        return pd.DataFrame(columns=COLONNES)
    semaine = semaine.assign(semaine_ref=semaine_ref(semaine["date"]))
    semaine = semaine.merge(
        normales, left_on=["station_id", "semaine_ref"], right_on=["station_id", "semaine"]
    )
    semaine = semaine[dans_regime(semaine["date"], semaine["rupture"])]
    semaine = semaine.assign(
        station_id=semaine["station_id"].astype(str),
        date=semaine["date"].astype("datetime64[ns]"),
    )
    mesures = debits.assign(
        station_id=debits["station_id"].astype(str),
        date_mesure=pd.to_datetime(debits["date"]).astype("datetime64[ns]"),
    )
    semaine = pd.merge_asof(
        semaine.sort_values("date"),
        mesures[["station_id", "date_mesure"]].sort_values("date_mesure"),
        left_on="date", right_on="date_mesure", by="station_id", direction="backward",
    )  # fmt: skip
    return pd.DataFrame(
        {
            "station_id": semaine["station_id"],
            "semaine": [libelle_semaine(d.date()) for d in semaine["date"]],
            "indice": "debit",
            "valeur": [
                z_rang(v, np.asarray(r))
                for v, r in zip(semaine["q7"], semaine["valeurs_ref"], strict=True)
            ],
            "periode_ref": semaine["periode_ref"],
            "hors_reference": semaine["hors_reference"].astype(bool),
            "date_mesure": semaine["date_mesure"].dt.date,
            "dans_composite": True,
        }
    )[COLONNES]
