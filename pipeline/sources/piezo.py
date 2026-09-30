"""Hub'Eau Piézométrie (SPEC §4.1)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import geopandas as gpd
import pandas as pd

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import (
    COLONNES_STATION,
    OBS_PIEZO,
    identifiant_station,
    metadonnees,
    normaliser,
    normaliser_observations,
)
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


PROFONDEUR_MAX = 20000  # Hub'Eau : page * size <= 20 000 (spike n°2)
ALTITUDE_INCONNUE = -999


def _chronique(
    client: ClientHttp, url: str, code: str, debut: date | None, fin: date
) -> list[dict[str, Any]]:
    """Chronique d'une station ; au-delà de 20 000 mesures, la période est coupée en deux."""
    params: dict[str, Any] = {
        "code_bss": code,
        "size": PROFONDEUR_MAX,
        "format": "json",
        "fields": "date_mesure,niveau_nappe_eau,statut",
        "date_fin_mesure": fin.isoformat(),
    }
    if debut is not None:
        params["date_debut_mesure"] = debut.isoformat()
    page = client.json(url, params)
    if page["count"] <= PROFONDEUR_MAX:
        return list(page["data"])
    origine = debut or date.fromisoformat(page["data"][0]["date_mesure"])
    milieu = origine + (fin - origine) / 2
    return _chronique(client, url, code, origine, milieu) + _chronique(
        client, url, code, milieu + timedelta(days=1), fin
    )


def _altitude(metadonnees_json: str) -> float | None:
    valeur = json.loads(metadonnees_json).get("altitude_station")
    try:
        altitude = float(valeur)
    except (TypeError, ValueError):
        return None
    return None if altitude == ALTITUDE_INCONNUE else altitude


def ingerer_observations(
    config: Config,
    client: ClientHttp,
    stations: gpd.GeoDataFrame,
    depuis: date | None,
    aujourd_hui: date,
) -> tuple[pd.DataFrame, list[str]]:
    """`obs.piezo_jour` des stations piézométriques du référentiel, depuis `depuis` (ou tout
    l'historique). Seul `niveau_nappe_eau` (cote NGF) est lu : `profondeur_nappe` en est une
    copie dans Hub'Eau ; la profondeur vaut altitude du repère - niveau (méthodologie)."""
    piezos = stations[stations["source"] == SOURCE]
    url = config.sources.hubeau.piezometrie + "chroniques"
    brut, erreurs = hubeau.par_station(
        list(piezos["code"]),
        lambda code: _chronique(client, url, code, depuis, aujourd_hui),
        SOURCE,
    )
    table = pd.DataFrame(brut, columns=["code", "date_mesure", "niveau_nappe_eau", "statut"])
    table = table.dropna(subset=["niveau_nappe_eau"])
    altitudes = {
        code: _altitude(meta)
        for code, meta in zip(piezos["code"], piezos["metadonnees"], strict=True)
    }
    obs = pd.DataFrame(
        {
            "station_id": [identifiant_station(SOURCE, c) for c in table["code"]],
            "date": table["date_mesure"],
            "niveau_ngf": table["niveau_nappe_eau"].astype("float64"),
            "profondeur": [
                (altitudes[c] - n) if altitudes.get(c) is not None else None
                for c, n in zip(table["code"], table["niveau_nappe_eau"], strict=True)
            ],
            "qualification": table["statut"],
            "ingere_le": aujourd_hui,
        }
    )
    return normaliser_observations(obs, OBS_PIEZO, ["station_id", "date"]), erreurs
