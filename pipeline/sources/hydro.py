"""Hub'Eau Hydrométrie (SPEC §4.2)."""

from __future__ import annotations

import geopandas as gpd

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import COLONNES_STATION, identifiant_station, metadonnees, normaliser
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
