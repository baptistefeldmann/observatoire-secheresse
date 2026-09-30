"""Construction des référentiels (`data/referentiels/`, SPEC §5.2) : communes, zones, mailles
SIM, stations des trois réseaux Hub'Eau. Idempotent : relancer réécrit les mêmes fichiers."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline import zonage
from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.sources import communes, hydro, meteo, onde, piezo, sandre

log = logging.getLogger(__name__)


def dossier(config: Config) -> Path:
    return config.projet.chemins.data / "referentiels"


def ecrire_geoparquet(gdf: gpd.GeoDataFrame, chemin: Path) -> None:
    """Écriture atomique : un fichier interrompu ne remplace jamais le précédent."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".tmp")
    gdf.to_parquet(temporaire, index=False)
    temporaire.replace(chemin)


def construire(config: Config, client: ClientHttp, aujourd_hui: date) -> dict[str, Path]:
    sortie = dossier(config)
    tables: dict[str, gpd.GeoDataFrame] = {}

    tampon = config.projet.emprise.tampon_m
    tables["communes"] = communes.ingerer_communes(config, client)
    territoire = communes.contour(tables["communes"])
    emprise = territoire.buffer(tampon)

    masses = sandre.masses_eau(config, client, emprise)
    if any(z.zones_alerte for z in config.zonage.zones):
        alertes = sandre.zones_alerte(config, client, emprise)
    else:
        alertes = gpd.GeoDataFrame({"code": []}, geometry=gpd.GeoSeries([], crs=config.projet.crs))
    tables["zones"] = zonage.construire_zones(config, masses, alertes, territoire)
    tables["mailles_safran"] = meteo.ingerer_mailles(config, client, emprise)
    stations = [
        piezo.ingerer_stations(config, client, aujourd_hui),
        hydro.ingerer_stations(config, client),
        onde.ingerer_stations(config, client),
    ]
    tables["stations"] = zonage.rattacher_stations(
        gpd.GeoDataFrame(
            pd.concat(stations, ignore_index=True), geometry="geometry", crs=config.projet.crs
        ).sort_values("station_id", ignore_index=True),
        tables["zones"],
        tampon,
    )

    chemins = {}
    for nom, gdf in tables.items():
        chemins[nom] = sortie / f"{nom}.parquet"
        ecrire_geoparquet(gdf, chemins[nom])
        log.info("%s : %d lignes -> %s", nom, len(gdf), chemins[nom])
    return chemins
