"""Hub'Eau Écoulement des cours d'eau, réseau ONDE (SPEC §4.3)."""

from __future__ import annotations

import geopandas as gpd

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import COLONNES_STATION, identifiant_station, metadonnees, normaliser
from pipeline.sources import hubeau

SOURCE = "onde"
ETAT_ACTIF = "Active"


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
