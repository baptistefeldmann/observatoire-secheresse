"""Restandardisation des indices de zone et du composite (méthodologie D10).

Une moyenne d'indices varie moins que chacun d'eux : sans correction, l'IPS et le débit de
zone (moyennes de stations) et le composite (moyenne pondérée des composantes) atteignent
rarement les classes extrêmes. Chacun est donc reclassé parmi ses propres valeurs des semaines
de référence de la zone, par le rang de Gringorten comme les indices de station (D9) :
10 % des semaines de référence en classe 1, valeurs bornées.

La référence d'une zone suit la règle des stations (`choisir_annees`) : les années 1991-2020
si elles sont assez nombreuses, sinon une référence figée hors période. Une année compte si la
zone a une valeur au moins `semaines_min_annee` semaines. Les échantillons sont calculés une
fois par `make reference` (`rang_zone.parquet`) et ne bougent plus : l'échelle reste fixe dans
le temps, et la fréquence des classes sèches peut dépasser 10 % si les sécheresses se
multiplient.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.indices.commun import detail_json, z_rang
from pipeline.reference.commun import choisir_annees

INDICES_STATIONS = ("ips", "debit")  # indices de zone moyennés sur les stations
COMPOSITE = "composite"
COLONNES = ["zone_id", "indice", "valeurs_ref", "n_semaines", "periode_ref", "hors_reference"]


def references(config: Config, valeurs: pd.DataFrame) -> pd.DataFrame:
    """Échantillon de référence trié par zone et par indice, à partir des valeurs brutes
    hebdomadaires (`zone_id`, `semaine`, `indice`, `valeur`)."""
    ref = config.projet.periode_reference.hydro_meteo
    minimum = config.projet.indices.rang_zone.semaines_min_annee
    lignes = []
    for (zone_id, indice), groupe in valeurs.dropna(subset=["valeur"]).groupby(
        ["zone_id", "indice"], sort=True
    ):
        annees = groupe["semaine"].str[:4].astype(int)
        effectifs = annees.value_counts()
        choix = choisir_annees(set(effectifs[effectifs >= minimum].index), ref)
        if not choix.annees:
            continue
        echantillon = np.sort(groupe.loc[annees.isin(choix.annees), "valeur"].to_numpy())
        lignes.append(
            {
                "zone_id": zone_id,
                "indice": indice,
                "valeurs_ref": echantillon.tolist(),
                "n_semaines": len(echantillon),
                "periode_ref": choix.periode_ref,
                "hors_reference": choix.hors_reference,
            }
        )
    return pd.DataFrame(lignes, columns=COLONNES)


def restandardiser(table: pd.DataFrame, refs: pd.DataFrame) -> pd.DataFrame:
    """Remplace `valeur` par son rang dans la référence de la zone ; la valeur brute et la
    période de référence passent dans `detail`. Sans référence, la ligne est retirée."""
    if table.empty:
        return table
    jointe = table.merge(
        refs[["zone_id", "indice", "valeurs_ref", "periode_ref", "hors_reference"]],
        on=["zone_id", "indice"],
        how="inner",
    )
    valeurs = [
        z_rang(float(v), np.asarray(r, dtype=float))
        for v, r in zip(jointe["valeur"], jointe["valeurs_ref"], strict=True)
    ]
    details = [
        detail_json(
            json.loads(d)
            | {"valeur_brute": round(float(v), 4), "reference": p, "hors_reference": bool(h)}
        )
        for d, v, p, h in zip(
            jointe["detail"], jointe["valeur"], jointe["periode_ref"], jointe["hors_reference"],
            strict=True,
        )
    ]  # fmt: skip
    return jointe.assign(valeur=valeurs, detail=details)[list(table.columns)]
