"""Indices par zone et indice composite (SPEC §6.4, méthodologie D1, D3, D9 ; D10 pour la
restandardisation, dans `rang.py`).

Indice de zone d'une variable mesurée en station : moyenne des indices des stations de la
zone qui entrent au composite de la semaine. Composite : moyenne pondérée des composantes
disponibles (`zones.yaml`), poids renormalisés quand une composante manque ; le détail des
composantes est conservé."""

from __future__ import annotations

import pandas as pd

from pipeline.config import Config
from pipeline.indices.commun import detail_json

COLONNES_ZONE = ["zone_id", "semaine", "indice", "valeur", "n_stations", "detail"]
COLONNES_COMPOSITE = ["zone_id", "semaine", "valeur", "detail"]


def par_zone(indices_station: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    # Tri par station : l'ordre de sommation, donc la moyenne au bit près, ne dépend pas de
    # la plage de semaines calculée (idempotence, SPEC §12 n°10)
    retenus = (
        indices_station[indices_station["dans_composite"].astype(bool)]
        .merge(stations[["station_id", "zone_id"]].dropna(), on="station_id")
        .sort_values(["zone_id", "semaine", "indice", "station_id"])
    )
    if retenus.empty:
        return pd.DataFrame(columns=COLONNES_ZONE)
    zones = retenus.groupby(["zone_id", "semaine", "indice"], as_index=False).agg(
        valeur=("valeur", "mean"),
        n_stations=("station_id", "size"),
        stations=("station_id", lambda s: sorted(s)),
    )
    zones["detail"] = [detail_json({"stations": s}) for s in zones["stations"]]
    return zones[COLONNES_ZONE]


def composite(config: Config, indices_zone: pd.DataFrame) -> pd.DataFrame:
    valeurs = indices_zone.set_index(["zone_id", "semaine", "indice"])["valeur"]
    lignes = []
    for zone in config.zonage.zones:
        poids = {c: p for c, p in zone.ponderations.items() if p > 0}
        sous = indices_zone[
            (indices_zone["zone_id"] == zone.zone_id) & indices_zone["indice"].isin(poids)
        ]
        for semaine in sorted(sous["semaine"].unique()):
            presentes = {
                c: float(valeurs[(zone.zone_id, semaine, c)])
                for c in poids
                if (zone.zone_id, semaine, c) in valeurs.index
            }
            total = sum(poids[c] for c in presentes)
            composantes = {
                c: {"valeur": round(v, 4), "poids": poids[c],
                    "poids_applique": round(poids[c] / total, 4)}
                for c, v in presentes.items()
            }  # fmt: skip
            manquantes = sorted(set(poids) - set(presentes))
            lignes.append(
                {
                    "zone_id": zone.zone_id,
                    "semaine": semaine,
                    "valeur": sum(poids[c] * v for c, v in presentes.items()) / total,
                    "detail": detail_json(
                        {
                            "composantes": composantes,
                            "manquantes": manquantes,
                            "n_composantes": len(presentes),
                            "partiel": bool(manquantes),
                        }
                    ),
                }
            )
    return pd.DataFrame(lignes, columns=COLONNES_COMPOSITE)
