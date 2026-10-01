"""Part de stations ONDE sans écoulement, par zone et par campagne (SPEC §6.2, méthodologie D3).

Valeur non standardisée (entre 0 et 1), sans classe, hors composite en V1. Une campagne est
rattachée à la semaine ISO de sa date ; hors campagne, aucune ligne (« hors période de
suivi », jamais zéro). Deux campagnes la même semaine : la plus récente l'emporte."""

from __future__ import annotations

import pandas as pd

from pipeline.indices.commun import detail_json, libelle_semaine

# Modalités ONDE (code_ecoulement) : 2 écoulement non visible (rupture), 3 assec
MODALITES = {"2": "n_rupture", "3": "n_assec"}
COLONNES = ["zone_id", "semaine", "indice", "valeur", "n_stations", "detail"]


def calculer(obs: pd.DataFrame, stations: pd.DataFrame, semaines: set[str]) -> pd.DataFrame:
    table = obs[["station_id", "date_campagne", "modalite", "type_campagne"]].merge(
        stations[["station_id", "zone_id"]].dropna(), on="station_id"
    )
    table = table.dropna(subset=["modalite"])
    table["semaine"] = [libelle_semaine(d) for d in pd.to_datetime(table["date_campagne"]).dt.date]
    table = table[table["semaine"].isin(semaines)]
    if table.empty:
        return pd.DataFrame(columns=COLONNES)
    for modalite, colonne in MODALITES.items():
        table[colonne] = table["modalite"].astype(str) == modalite
    campagnes = table.groupby(["zone_id", "semaine", "date_campagne"], as_index=False).agg(
        n_stations=("station_id", "nunique"),
        n_rupture=("n_rupture", "sum"),
        n_assec=("n_assec", "sum"),
        type_campagne=("type_campagne", lambda t: ", ".join(sorted(set(map(str, t))))),
    )
    campagnes = campagnes.sort_values("date_campagne").drop_duplicates(
        ["zone_id", "semaine"], keep="last"
    )
    campagnes["valeur"] = (campagnes["n_rupture"] + campagnes["n_assec"]) / campagnes["n_stations"]
    campagnes["indice"] = "onde"
    campagnes["detail"] = [
        detail_json(
            {
                "date_campagne": str(d),
                "type_campagne": t,
                "n_assec": int(a),
                "n_rupture": int(r),
            }
        )
        for d, t, a, r in zip(
            campagnes["date_campagne"],
            campagnes["type_campagne"],
            campagnes["n_assec"],
            campagnes["n_rupture"],
            strict=True,
        )
    ]
    return campagnes[COLONNES]
