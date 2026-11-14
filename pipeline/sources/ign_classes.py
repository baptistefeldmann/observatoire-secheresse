"""[V2] BD Forêt V2 et RPG de la Géoplateforme de l'IGN (WFS), pour les classes du satellite.

Les deux couches sont lues par pages triées (un tri stable est nécessaire à la pagination WFS) sur
l'emprise demandée, en EPSG:2154. Aucune écriture ici : `pipeline.raster.classes` met en cache.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import geopandas as gpd
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline.config import Config
from pipeline.http import ClientHttp

log = logging.getLogger(__name__)

Emprise = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax, en EPSG:2154


# Le WFS renvoie parfois une réponse 200 au corps vide ou tronqué : la page est relue
_relire = retry(
    retry=retry_if_exception_type(json.JSONDecodeError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=1, max=30),
    reraise=True,
)


def _page(client: ClientHttp, url: str, parametres: dict[str, Any]) -> Any:
    return _relire(client.json)(url, parametres)


def _pages(
    config: Config, client: ClientHttp, couche: str, emprise: Emprise, tri: str
) -> gpd.GeoDataFrame:
    source = config.sources.occupation_sol
    xmin, ymin, xmax, ymax = emprise
    morceaux: list[gpd.GeoDataFrame] = []
    debut = 0
    while True:
        page = _page(
            client,
            source.wfs,
            {
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": couche,
                "OUTPUTFORMAT": "application/json",
                "SRSNAME": config.projet.crs,
                "BBOX": f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::2154",
                "COUNT": source.page,
                "STARTINDEX": debut,
                "SORTBY": tri,
            },
        )
        objets = page.get("features", [])
        if not objets:
            break
        for objet in objets:  # l'identifiant GeoJSON de l'objet sert à écarter les doublons de page
            objet["properties"].setdefault("id", objet.get("id"))
        morceaux.append(gpd.GeoDataFrame.from_features(objets, crs=config.projet.crs))
        debut += len(objets)
        log.info("%s : %d objets lus", couche, debut)
        if len(objets) < source.page:
            break
    if not morceaux:
        raise RuntimeError(f"{couche} : aucun objet dans l'emprise {emprise}")
    gdf = pd.concat(morceaux, ignore_index=True)
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs=config.projet.crs)


def ingerer_bdforet(config: Config, client: ClientHttp, emprise: Emprise) -> gpd.GeoDataFrame:
    """Polygones de la BD Forêt V2 : `code_tfv` (poste de formation végétale) et géométrie."""
    brut = _pages(config, client, config.sources.occupation_sol.bdforet, emprise, "id")
    if "code_tfv" not in brut.columns:
        raise RuntimeError("BD Forêt : champ code_tfv absent de la couche")
    brut = brut.drop_duplicates("id")  # un objet à cheval sur deux pages revient deux fois
    return gpd.GeoDataFrame(
        {"code_tfv": brut["code_tfv"].astype(str)}, geometry=brut.geometry, crs=brut.crs
    ).reset_index(drop=True)


def ingerer_rpg(
    config: Config, client: ClientHttp, annee: int, emprise: Emprise
) -> gpd.GeoDataFrame:
    """Parcelles du RPG de l'année : `code_cultu`, `code_group` (entier) et géométrie."""
    couches = config.sources.occupation_sol.rpg
    if annee not in couches:
        raise ValueError(
            f"RPG {annee} : aucune couche dans config/sources.yaml (occupation_sol.rpg)"
        )
    couche = couches[annee]
    # Les couches 2018-2024 et la couche 2025 n'ont pas le même identifiant de parcelle
    brut = _pages(config, client, couche, emprise, "num_parcel" if annee >= 2025 else "id_parcel")
    for champ in ("code_cultu", "code_group"):
        if champ not in brut.columns:
            raise RuntimeError(f"RPG {annee} : champ {champ} absent de {couche}")
    brut = brut.drop_duplicates("id")
    groupe = pd.to_numeric(brut["code_group"], errors="coerce")
    sans_groupe = int(groupe.isna().sum())
    if sans_groupe:
        log.warning(
            "RPG %d : %d parcelles sans code_group, comptées hors classes", annee, sans_groupe
        )
    return gpd.GeoDataFrame(
        {
            "code_cultu": brut["code_cultu"].astype(str),
            "code_group": groupe.fillna(-1).astype(int),
        },
        geometry=brut.geometry,
        crs=brut.crs,
    ).reset_index(drop=True)
