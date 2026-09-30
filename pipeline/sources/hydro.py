"""Hub'Eau Hydrométrie (SPEC §4.2)."""

from __future__ import annotations

from datetime import date
from typing import Any

import geopandas as gpd
import pandas as pd

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import (
    COLONNES_STATION,
    OBS_DEBIT,
    identifiant_station,
    metadonnees,
    normaliser,
    normaliser_observations,
)
from pipeline.sources import hubeau

SOURCE = "hydro"


def ingerer_stations(config: Config, client: ClientHttp) -> gpd.GeoDataFrame:
    brut = hubeau.stations(
        client,
        config.sources.hubeau.hydrometrie + "referentiel/stations",
        config.projet.territoire.code_departement,
    )
    lignes = [
        {
            "station_id": identifiant_station(SOURCE, s["code_station"]),
            "source": SOURCE,
            "code": s["code_station"],
            "libelle": hubeau.valeur(s, "libelle_station"),
            "en_service": bool(hubeau.valeur(s, "en_service")),
            "masse_eau": None,
            "zone_id": None,
            "metadonnees": metadonnees(
                {
                    "code_site": hubeau.valeur(s, "code_site"),
                    "cours_eau": hubeau.valeur(s, "libelle_cours_eau"),
                    "code_cours_eau": hubeau.valeur(s, "code_cours_eau"),
                    "type_station": hubeau.valeur(s, "type_station"),
                    "date_ouverture": hubeau.valeur(s, "date_ouverture_station"),
                    "date_fermeture": hubeau.valeur(s, "date_fermeture_station"),
                    "code_commune": hubeau.valeur(s, "code_commune_station"),
                }
            ),
            "geometry": s.geometry,
        }
        for _, s in brut.iterrows()
    ]
    gdf = gpd.GeoDataFrame(lignes, geometry="geometry", crs=brut.crs)
    return normaliser(gdf, COLONNES_STATION, "station_id", config.projet.crs)


def _qmnj(client: ClientHttp, url: str, code: str, depuis: date | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "code_entite": code,
        "grandeur_hydro_elab": "QmnJ",
        "size": 20000,
        "format": "json",
        "fields": "date_obs_elab,resultat_obs_elab,libelle_statut",
    }
    if depuis is not None:
        params["date_debut_obs_elab"] = depuis.isoformat()
    return list(client.pages_hubeau(url, params))  # curseur : pas de limite de profondeur


def ingerer_observations(
    config: Config,
    client: ClientHttp,
    stations: gpd.GeoDataFrame,
    depuis: date | None,
    aujourd_hui: date,
) -> tuple[pd.DataFrame, list[str]]:
    """`obs.debit_jour` : débits moyens journaliers (QmnJ, l/s) des stations du référentiel.
    Les stations successives d'un même site restent distinctes ici ; leur raccordement (D4)
    se fait au calcul des indices."""
    codes = list(stations.loc[stations["source"] == SOURCE, "code"])
    url = config.sources.hubeau.hydrometrie + "obs_elab"
    brut, erreurs = hubeau.par_station(codes, lambda code: _qmnj(client, url, code, depuis), SOURCE)
    table = pd.DataFrame(
        brut, columns=["code", "date_obs_elab", "resultat_obs_elab", "libelle_statut"]
    ).dropna(subset=["resultat_obs_elab"])
    obs = pd.DataFrame(
        {
            "station_id": [identifiant_station(SOURCE, c) for c in table["code"]],
            "date": table["date_obs_elab"],
            "qmj_ls": table["resultat_obs_elab"],
            "qualification": table["libelle_statut"],
            "ingere_le": aujourd_hui,
        }
    )
    return normaliser_observations(obs, OBS_DEBIT, ["station_id", "date"]), erreurs
