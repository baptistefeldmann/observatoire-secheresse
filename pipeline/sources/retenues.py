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
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, cast

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


def _cle_semaine(jour: date) -> int:
    annee, semaine, _ = jour.isocalendar()
    return annee * 100 + semaine


def _semaines_decalees(brut: pd.DataFrame) -> pd.DataFrame:
    """Corrige les relevés dont la date tombe une semaine trop tard (D14).

    La semaine ISO se déduit de la date. Un relevé daté hors dimanche peut tomber dans la semaine
    suivante (ex. « Semaine 08 (au mardi 25/02/2025) » : semaine ISO 09). Il n'est déplacé que
    dans ce cas précis : sa semaine ISO contient déjà un autre relevé de la même retenue et la
    semaine précédente n'en a aucun. Il prend alors la date du dimanche de la semaine vide. Tout
    autre relevé hors dimanche est laissé tel quel ; une semaine qui garde plusieurs relevés est
    signalée dans le journal."""
    brut = brut.reset_index(drop=True)
    for code, groupe in brut.groupby("code"):
        compte = Counter(groupe["date"].map(_cle_semaine))
        for indice in groupe.index[groupe["date"].map(lambda jour: jour.weekday() != 6)]:
            jour = cast(date, brut.at[indice, "date"])
            dimanche_precedent = jour - timedelta(days=jour.weekday() + 1)
            if compte[_cle_semaine(jour)] > 1 and compte[_cle_semaine(dimanche_precedent)] == 0:
                log.info(
                    "%s : relevé du %s ramené au %s (semaine vide)", code, jour, dimanche_precedent
                )
                compte[_cle_semaine(jour)] -= 1
                compte[_cle_semaine(dimanche_precedent)] += 1
                brut.at[indice, "date"] = dimanche_precedent
    par_semaine = brut.assign(semaine_iso=brut["date"].map(_cle_semaine))
    tailles = par_semaine.groupby(["code", "semaine_iso"], as_index=False).size()
    for ligne in tailles[tailles["size"] > 1].itertuples():
        log.warning(
            "%s : %d relevés dans la semaine ISO %d, à examiner",
            ligne.code,
            ligne.size,
            ligne.semaine_iso,
        )
    return brut


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
    brut = _semaines_decalees(brut.dropna(subset=["date", "volume_m3"]))
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
