"""IPS de la semaine par piézomètre (SPEC §6.2, méthodologie D1, D7, D9).

Mois retenu pour le dimanche de la semaine : le mois en cours s'il compte au moins
`jours_min_mois` jours de mesures jusqu'au dimanche, sinon le dernier mois qui les atteint.
Sa moyenne est classée parmi les moyennes de référence du même mois. La date de la dernière
mesure retenue est conservée : la station n'entre dans le composite que si elle a moins de
`fraicheur_max_jours` jours (D1), et aucun indice n'est produit au-delà de
`ingestion.piezo_inactif_apres_jours` jours (station hors service)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.indices.commun import dans_regime, libelle_semaine, z_rang
from pipeline.reference.ips import moyennes_mensuelles

COLONNES = [
    "station_id", "semaine", "indice", "valeur", "periode_ref", "hors_reference",
    "date_mesure", "dans_composite",
]  # fmt: skip


def _mois_en_cours(journalier: pd.DataFrame, cibles: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque (station, dimanche) : moyenne et nombre de jours du mois du dimanche,
    mesures jusqu'au dimanche inclus."""
    journalier = journalier.sort_values("date")
    groupes = journalier.groupby(["station_id", "debut_mois"])
    journalier = journalier.assign(
        n_jours=groupes.cumcount() + 1,
        moyenne=groupes["niveau_ngf"].cumsum() / (groupes.cumcount() + 1),
    )
    derniere = pd.merge_asof(
        cibles.sort_values("dimanche"),
        journalier[["station_id", "date", "debut_mois", "n_jours", "moyenne"]],
        left_on="dimanche", right_on="date", by="station_id", direction="backward",
    )  # fmt: skip
    en_cours = derniere["debut_mois"] == derniere["debut_dimanche"]
    return derniere[en_cours][["station_id", "dimanche", "date", "n_jours", "moyenne"]]


def _mois_precedent(mensuel: pd.DataFrame, cibles: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque (station, dimanche) : dernier mois valide antérieur au mois du dimanche."""
    mensuel = mensuel.sort_values("fin_mois")
    precedent = pd.merge_asof(
        cibles.assign(veille=cibles["debut_dimanche"] - pd.Timedelta(days=1)).sort_values("veille"),
        mensuel[["station_id", "fin_mois", "date", "moyenne"]],
        left_on="veille", right_on="fin_mois", by="station_id", direction="backward",
    )  # fmt: skip
    return precedent.dropna(subset=["moyenne"])[["station_id", "dimanche", "date", "moyenne"]]


def calculer(
    config: Config, obs: pd.DataFrame, normales: pd.DataFrame, dimanches: pd.DatetimeIndex
) -> pd.DataFrame:
    parametres = config.projet.indices.ips
    stations = normales["station_id"].unique()
    journalier = obs.loc[obs["station_id"].isin(stations), ["station_id", "date", "niveau_ngf"]]
    # Types homogènes pour les jointures ordonnées (identifiants en texte, dates en ns)
    journalier = journalier.dropna(subset=["niveau_ngf"]).assign(
        station_id=lambda t: t["station_id"].astype(str),
        date=lambda t: pd.to_datetime(t["date"]).astype("datetime64[ns]"),
    )
    if journalier.empty or len(dimanches) == 0:
        return pd.DataFrame(columns=COLONNES)
    journalier["debut_mois"] = journalier["date"].dt.to_period("M").dt.start_time
    cibles = pd.MultiIndex.from_product(
        [stations.astype(str), dimanches.astype("datetime64[ns]")],
        names=["station_id", "dimanche"],
    ).to_frame(index=False)
    cibles["debut_dimanche"] = cibles["dimanche"].dt.to_period("M").dt.start_time

    en_cours = _mois_en_cours(journalier, cibles)
    en_cours = en_cours[en_cours["n_jours"] >= parametres.jours_min_mois]
    en_cours = en_cours.assign(mois=en_cours["dimanche"].dt.month)

    mensuel = moyennes_mensuelles(journalier, parametres.jours_min_mois)
    debut = pd.to_datetime(dict(year=mensuel["annee"], month=mensuel["mois"], day=1))
    dernieres = journalier.groupby(["station_id", "debut_mois"])["date"].max()
    mensuel = mensuel.assign(
        fin_mois=debut + pd.offsets.MonthEnd(0),
        moyenne=mensuel["niveau_moyen"],
        date=dernieres.reindex(pd.MultiIndex.from_arrays([mensuel["station_id"], debut])).values,
    )
    precedent = _mois_precedent(mensuel, cibles)
    precedent = precedent.assign(mois=precedent["date"].dt.month)

    cle = ["station_id", "dimanche"]
    retenu = pd.concat(
        [en_cours, precedent[~precedent.set_index(cle).index.isin(en_cours.set_index(cle).index)]]
    )
    age = (retenu["dimanche"] - retenu["date"]).dt.days
    retenu = retenu[age <= config.projet.ingestion.piezo_inactif_apres_jours]
    retenu = retenu.merge(normales, on=["station_id", "mois"])
    retenu = retenu[dans_regime(retenu["date"], retenu["rupture"])]
    if retenu.empty:
        return pd.DataFrame(columns=COLONNES)
    return pd.DataFrame(
        {
            "station_id": retenu["station_id"],
            "semaine": [libelle_semaine(d.date()) for d in retenu["dimanche"]],
            "indice": "ips",
            "valeur": [
                z_rang(v, np.asarray(r))
                for v, r in zip(retenu["moyenne"], retenu["valeurs_ref"], strict=True)
            ],
            "periode_ref": retenu["periode_ref"],
            "hors_reference": retenu["hors_reference"].astype(bool),
            "date_mesure": retenu["date"].dt.date,
            "dans_composite": (retenu["dimanche"] - retenu["date"]).dt.days
            < parametres.fraicheur_max_jours,
        }
    )[COLONNES]
