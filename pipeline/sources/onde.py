"""Hub'Eau Écoulement des cours d'eau, réseau ONDE (SPEC §4.3)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import geopandas as gpd
import httpx
import pandas as pd

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import (
    COLONNES_STATION,
    OBS_ONDE,
    identifiant_station,
    metadonnees,
    normaliser,
    normaliser_observations,
)
from pipeline.sources import hubeau

SOURCE = "onde"
ETAT_ACTIF = "Active"

log = logging.getLogger(__name__)


def ingerer_stations(config: Config, client: ClientHttp) -> gpd.GeoDataFrame:
    brut = hubeau.stations(
        client,
        config.sources.hubeau.ecoulement + "stations",
        config.projet.territoire.code_departement,
    )
    lignes = [
        {
            "station_id": identifiant_station(SOURCE, s["code_station"]),
            "source": SOURCE,
            "code": s["code_station"],
            "libelle": hubeau.valeur(s, "libelle_station"),
            "en_service": hubeau.valeur(s, "etat_station") == ETAT_ACTIF,
            "masse_eau": None,
            "zone_id": None,
            "metadonnees": metadonnees(
                {
                    "cours_eau": hubeau.valeur(s, "libelle_cours_eau"),
                    "code_cours_eau": hubeau.valeur(s, "code_cours_eau"),
                    "etat_station": hubeau.valeur(s, "etat_station"),
                    "code_commune": hubeau.valeur(s, "code_commune"),
                }
            ),
            "geometry": s.geometry,
        }
        for _, s in brut.iterrows()
    ]
    gdf = gpd.GeoDataFrame(lignes, geometry="geometry", crs=brut.crs)
    return normaliser(gdf, COLONNES_STATION, "station_id", config.projet.crs)


# Modalités ONDE (code_ecoulement) : 1 écoulement visible, 1a acceptable, 1f faible,
# 2 écoulement non visible, 3 assec. Le code est stocké tel quel dans `modalite`.
TAILLE_PAGE = 5000


def ingerer_observations(
    config: Config,
    client: ClientHttp,
    stations: gpd.GeoDataFrame,
    depuis: date | None,
    aujourd_hui: date,
) -> tuple[pd.DataFrame, list[str]]:
    """`obs.onde` du département : une modalité par station et par campagne. Le type de
    campagne (usuelle, complémentaire) vient de l'endpoint `campagnes`. Seules les stations du
    référentiel sont gardées (clé étrangère de `obs.onde`)."""
    dep = config.projet.territoire.code_departement
    base = config.sources.hubeau.ecoulement
    filtre: dict[str, Any] = {"code_departement": dep, "size": TAILLE_PAGE, "format": "json"}
    if depuis is not None:
        filtre["date_observation_min"] = depuis.isoformat()
    try:
        observations = list(client.pages_hubeau(base + "observations", filtre))
        # code_campagne : entier dans `campagnes`, texte dans `observations`
        campagnes = {
            str(c["code_campagne"]): c.get("libelle_type_campagne")
            for c in client.pages_hubeau(
                base + "campagnes", {"code_departement": dep, "size": TAILLE_PAGE, "format": "json"}
            )
        }
    except (httpx.HTTPError, RuntimeError) as exc:
        return pd.DataFrame(columns=list(OBS_ONDE)), [f"{SOURCE} : {exc}"]
    obs = pd.DataFrame(
        {
            "station_id": [identifiant_station(SOURCE, o["code_station"]) for o in observations],
            "date_campagne": [o["date_observation"] for o in observations],
            "modalite": [o.get("code_ecoulement") for o in observations],
            "type_campagne": [campagnes.get(str(o.get("code_campagne"))) for o in observations],
            "ingere_le": aujourd_hui,
        }
    )
    obs = obs.dropna(subset=["modalite"])
    connues = obs["station_id"].isin(stations.loc[stations["source"] == SOURCE, "station_id"])
    if not connues.all():
        inconnues = sorted(obs.loc[~connues, "station_id"].unique())
        log.warning("ONDE : %d observation(s) de stations hors référentiel écartées : %s",
                    int((~connues).sum()), inconnues[:5])  # fmt: skip
        obs = obs[connues]
    return normaliser_observations(obs, OBS_ONDE, ["station_id", "date_campagne"]), []
