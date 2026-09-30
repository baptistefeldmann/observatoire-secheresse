"""Référentiels SANDRE par WFS (GeoJSON) : masses d'eau souterraine et zones d'alerte sécheresse.

Servent au découpage du territoire en zones (docs/methodologie.md, D5).
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from pipeline.config import Config
from pipeline.http import ClientHttp


def _urn(crs: str) -> str:
    autorite, code = crs.split(":")
    return f"urn:ogc:def:crs:{autorite}::{code}"


def _entites(
    config: Config, client: ClientHttp, wfs: str, couche: str, emprise: BaseGeometry
) -> list[dict[str, Any]]:
    """Entités GeoJSON de la couche intersectant l'emprise, coordonnées dans le CRS du projet."""
    urn = _urn(config.projet.crs)
    xmin, ymin, xmax, ymax = emprise.bounds
    geojson = client.json(
        wfs,
        {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": couche,
            "SRSNAME": urn,
            "BBOX": f"{xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f},{urn}",
            "OUTPUTFORMAT": "geojson",
        },
    )
    entites: list[dict[str, Any]] = geojson.get("features") or []
    return entites


def masses_eau(config: Config, client: ClientHttp, emprise: BaseGeometry) -> gpd.GeoDataFrame:
    """Masses d'eau de l'horizon configuré (affleurantes) : `code`, `nom`, géométrie."""
    source = config.sources.sandre.masses_eau
    polygones = _entites(config, client, source.wfs, source.couche, emprise)
    noms = {
        e["properties"]["CdEuMasseDEau"]: e["properties"]["NomMasseDEau"]
        for e in _entites(config, client, source.wfs, source.couche_noms, emprise)
    }
    retenus = [e for e in polygones if e["properties"].get("Horizon") == source.horizon]
    if not retenus:
        raise RuntimeError(f"aucune masse d'eau d'horizon {source.horizon} sur l'emprise")
    gdf = gpd.GeoDataFrame.from_features(retenus, crs=config.projet.crs)
    gdf = gdf.rename(columns={"CdEuMasseDEau": "code"}).dissolve("code", as_index=False)
    gdf["nom"] = gdf["code"].map(noms)
    return gdf[["code", "nom", "geometry"]]


def zones_alerte(config: Config, client: ClientHttp, emprise: BaseGeometry) -> gpd.GeoDataFrame:
    """Zones d'alerte au statut configuré (« Validé ») : `code` (CdZAS), `libelle`, `type`."""
    source = config.sources.sandre.zones_alerte
    entites = [
        e
        for e in _entites(config, client, source.wfs, source.couche, emprise)
        if e["properties"].get("StZAS") == source.statut
    ]
    if not entites:
        return gpd.GeoDataFrame(
            {"code": [], "libelle": [], "type": []},
            geometry=gpd.GeoSeries([], crs=config.projet.crs),
        )
    gdf = gpd.GeoDataFrame.from_features(entites, crs=config.projet.crs)
    gdf = gdf.rename(columns={"CdZAS": "code", "LbZAS": "libelle", "TypeZAS": "type"})
    gdf["code"] = gdf["code"].astype("int64")
    return gdf[["code", "libelle", "type", "geometry"]]
