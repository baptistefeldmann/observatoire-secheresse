"""Hub'Eau Piézométrie (SPEC §4.1)."""

from __future__ import annotations

from datetime import date, timedelta

import geopandas as gpd

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import COLONNES_STATION, identifiant_station, metadonnees, normaliser
from pipeline.sources import hubeau

SOURCE = "piezo"


def ingerer_stations(config: Config, client: ClientHttp, aujourd_hui: date) -> gpd.GeoDataFrame:
    """Stations du territoire. L'API ne donne pas de statut : une station est en service si
    sa dernière mesure a moins de `ingestion.piezo_inactif_apres_jours` jours."""
    brut = hubeau.stations(
        client,
        config.sources.hubeau.piezometrie + "stations",
        config.projet.territoire.code_departement,
    )
    limite = aujourd_hui - timedelta(days=config.projet.ingestion.piezo_inactif_apres_jours)
    lignes = []
    for _, s in brut.iterrows():
        fin = hubeau.valeur(s, "date_fin_mesure")
        codes_me = hubeau.valeur(s, "codes_masse_eau_edl") or []
        lignes.append(
            {
                "station_id": identifiant_station(SOURCE, s["code_bss"]),
                "source": SOURCE,
                "code": s["code_bss"],
                "libelle": hubeau.valeur(s, "libelle_pe"),
                "en_service": fin is not None and date.fromisoformat(fin) >= limite,
                "masse_eau": ", ".join(codes_me) or None,
                "zone_id": None,
                "metadonnees": metadonnees(
                    {
                        "bss_id": hubeau.valeur(s, "bss_id"),
                        "date_debut_mesure": hubeau.valeur(s, "date_debut_mesure"),
                        "date_fin_mesure": fin,
                        "nb_mesures_piezo": hubeau.valeur(s, "nb_mesures_piezo"),
                        "altitude_station": hubeau.valeur(s, "altitude_station"),
                        "profondeur_investigation": hubeau.valeur(s, "profondeur_investigation"),
                        "codes_bdlisa": list(hubeau.valeur(s, "codes_bdlisa") or []),
                        "noms_masse_eau": list(hubeau.valeur(s, "noms_masse_eau_edl") or []),
                        "code_commune": hubeau.valeur(s, "code_commune_insee"),
                    }
                ),
                "geometry": s.geometry,
            }
        )
    gdf = gpd.GeoDataFrame(lignes, geometry="geometry", crs=brut.crs)
    return normaliser(gdf, COLONNES_STATION, "station_id", config.projet.crs)
