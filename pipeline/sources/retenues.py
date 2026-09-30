"""Remplissage des retenues d'eau (docs/methodologie.md, D6 ; spike n°6).

Deux sources, même format de relevé (une ligne par retenue et par date) :

- table ArcGIS propre au territoire (`stations.yaml`, bloc `retenues`) : historique complet ;
- couche nationale de la DREAL Bretagne (`sources.yaml`) : dernière semaine seulement, utilisée
  en repli si la table du territoire est indisponible, ou comme source principale sans elle.

La semaine ISO se déduit de la date du relevé : les numéros de semaine des sources n'en sont pas.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any

import geopandas as gpd
import httpx
import pandas as pd
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from pipeline.config import Config, SourceRetenues
from pipeline.http import ClientHttp
from pipeline.schema import (
    COLONNES_STATION,
    OBS_RETENUE,
    identifiant_station,
    metadonnees,
    normaliser,
    normaliser_observations,
    vide,
)

log = logging.getLogger(__name__)

SOURCE = "retenue"
TAILLE_PAGE_ARCGIS = 1000
MOTIF_DATE = re.compile(r"(\d{2}/\d{2}/\d{4})")
COLONNES_RELEVE = ["code", "libelle", "date", "volume_m3", "capacite_m3", "longitude", "latitude"]


def code_retenue(nom: str, alias: dict[str, str] | None = None) -> str:
    """Code stable d'une retenue : majuscules sans accents, suffixe « -RETENUE » retiré."""
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().upper()
    code = re.sub(r"[^A-Z0-9]+", "_", re.sub(r"-RETENUE$", "", ascii_.strip())).strip("_")
    return (alias or {}).get(code, code)


def _date(texte: Any) -> date | None:
    trouve = MOTIF_DATE.search(str(texte or ""))
    return datetime.strptime(trouve.group(1), "%d/%m/%Y").date() if trouve else None


def _releves_arcgis(client: ClientHttp, source: SourceRetenues) -> pd.DataFrame:
    champs = source.champs
    lignes: list[dict[str, Any]] = []
    decalage = 0
    while True:
        page = client.json(
            f"{source.table_arcgis}/query",
            {
                "where": "1=1",
                "outFields": "*",
                "orderByFields": "ObjectId",
                "resultOffset": decalage,
                "resultRecordCount": TAILLE_PAGE_ARCGIS,
                "f": "json",
            },
        )
        if "error" in page:
            raise RuntimeError(f"ArcGIS : {page['error']}")
        for entite in page["features"]:
            a = entite["attributes"]
            lignes.append(
                {
                    "code": code_retenue(a[champs.retenue]),
                    "libelle": a[champs.retenue],
                    "date": _date(a[champs.date]),
                    "volume_m3": a[champs.volume_m3],
                    "capacite_m3": a[champs.capacite_m3],
                    "longitude": a[champs.longitude],
                    "latitude": a[champs.latitude],
                }
            )
        if not page.get("exceededTransferLimit"):
            break
        decalage += len(page["features"])
    return pd.DataFrame(lignes, columns=COLONNES_RELEVE)


def _releves_national(config: Config, client: ClientHttp, alias: dict[str, str]) -> pd.DataFrame:
    source = config.sources.retenues_national
    geojson = client.json(
        source.wfs,
        {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": source.couche,
            "SRSNAME": "EPSG:4326",
            "OUTPUTFORMAT": "application/json",
        },
    )
    lignes = []
    for entite in geojson["features"]:
        p, geom = entite["properties"], entite.get("geometry")
        # sans relevé récent, la couche renvoie des chaînes vides plutôt que des valeurs nulles
        if not geom or p.get("stock_millions_m3") in (None, "") or not p.get("date_mesure"):
            continue
        point = shape(geom).centroid  # Point ou MultiPoint selon les entités
        lon, lat = point.x, point.y
        lignes.append(
            {
                "code": code_retenue(p["nom1"], alias),
                "libelle": p["nom1"],
                "date": _date(p["date_mesure"]),
                # millions de m³ -> m³ entiers (évite 4,1e6 = 4 099 999,999…)
                "volume_m3": round(float(p["stock_millions_m3"]) * 1e6),
                "capacite_m3": round(float(p["capacite_millions_m3"]) * 1e6),
                "longitude": lon,
                "latitude": lat,
            }
        )
    return pd.DataFrame(lignes, columns=COLONNES_RELEVE)


def releves(
    config: Config, client: ClientHttp, emprise: BaseGeometry
) -> tuple[gpd.GeoDataFrame, str]:
    """Relevés des retenues situées dans l'emprise, et nom de la source utilisée."""
    local = config.stations.retenues
    if local is not None:
        try:
            brut, origine = _releves_arcgis(client, local), "territoire"
        except (httpx.HTTPError, RuntimeError, KeyError) as exc:
            log.warning("table des retenues du territoire indisponible (%s) : repli national", exc)
            brut, origine = _releves_national(config, client, local.alias_repli), "national"
    else:
        brut, origine = _releves_national(config, client, {}), "national"
    brut = brut.dropna(subset=["date", "volume_m3"])
    gdf = gpd.GeoDataFrame(
        brut, geometry=gpd.points_from_xy(brut["longitude"], brut["latitude"]), crs=4326
    ).to_crs(config.projet.crs)
    return gdf[gdf.within(emprise)].reset_index(drop=True), origine


def ingerer_stations(config: Config, client: ClientHttp, emprise: BaseGeometry) -> gpd.GeoDataFrame:
    """Une station par retenue, d'après son relevé le plus récent (libellé, capacité, position)."""
    gdf, origine = releves(config, client, emprise)
    if gdf.empty:
        log.info("aucune retenue sur le territoire")
        return vide(COLONNES_STATION, config.projet.crs)
    dernier = gdf.sort_values("date").groupby("code").tail(1)
    lignes = [
        {
            "station_id": identifiant_station(SOURCE, r["code"]),
            "source": SOURCE,
            "code": r["code"],
            "libelle": r["libelle"],
            "en_service": True,
            "masse_eau": None,
            "zone_id": None,
            "metadonnees": metadonnees({"capacite_m3": r["capacite_m3"], "source": origine}),
            "geometry": r.geometry,
        }
        for _, r in dernier.iterrows()
    ]
    stations = gpd.GeoDataFrame(lignes, geometry="geometry", crs=config.projet.crs)
    return normaliser(stations, COLONNES_STATION, "station_id", config.projet.crs)


def ingerer_observations(
    config: Config, client: ClientHttp, emprise: BaseGeometry, aujourd_hui: date
) -> pd.DataFrame:
    """Observations `obs.retenue_semaine` : station, date, volume, capacité, source, ingestion."""
    gdf, origine = releves(config, client, emprise)
    obs = pd.DataFrame(
        {
            "station_id": [identifiant_station(SOURCE, c) for c in gdf["code"]],
            "date": gdf["date"],
            "volume_m3": gdf["volume_m3"],
            "capacite_m3": gdf["capacite_m3"],
            "source_donnee": origine,
            "ingere_le": aujourd_hui,
        }
    )
    doublons = obs.duplicated(["station_id", "date"])
    if doublons.any():
        log.warning("%d relevé(s) en double (même retenue, même date) écartés", int(doublons.sum()))
    return normaliser_observations(obs, OBS_RETENUE, ["station_id", "date"])
