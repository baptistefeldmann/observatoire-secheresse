"""Colonnes des GeoParquet de référentiels, alignées sur le schéma `ref` (SPEC §5.3)."""

from __future__ import annotations

import json
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

# Colonne -> type pandas (hors géométrie). Types explicites : une colonne entièrement vide
# (zone_id avant le découpage des zones) garde ainsi un type exploitable par PostGIS.
COLONNES_STATION = {
    "station_id": "string", "source": "string", "code": "string", "libelle": "string",
    "en_service": "bool", "masse_eau": "string", "zone_id": "string", "metadonnees": "string",
}  # fmt: skip
COLONNES_COMMUNE = {"code_insee": "string", "nom": "string"}
COLONNES_MAILLE = {"maille_id": "int64"}
COLONNES_ZONE = {
    "zone_id": "string", "libelle": "string", "type_zone": "string", "ponderations": "string",
}  # fmt: skip


def identifiant_station(source: str, code: str) -> str:
    return f"{source}:{code}"


def metadonnees(valeurs: dict[str, Any]) -> str:
    """JSON trié, valeurs vides retirées : stable d'une exécution à l'autre (jsonb en base)."""
    return json.dumps(
        {k: v for k, v in valeurs.items() if v not in (None, "", [])},
        ensure_ascii=False,
        sort_keys=True,
    )


def en_multipolygone(geom: BaseGeometry) -> MultiPolygon:
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    raise ValueError(f"géométrie surfacique attendue, reçu {geom.geom_type}")


def normaliser(
    gdf: gpd.GeoDataFrame, colonnes: dict[str, str], cle: str, crs: str
) -> gpd.GeoDataFrame:
    """Colonnes et types du schéma, CRS de stockage, tri par clé, clé unique."""
    manquantes = set(colonnes) - set(gdf.columns)
    if manquantes:
        raise ValueError(f"colonnes manquantes : {sorted(manquantes)}")
    if gdf[cle].duplicated().any():
        doublons = sorted(gdf.loc[gdf[cle].duplicated(), cle].unique())
        raise ValueError(f"{cle} en double : {doublons[:5]}")
    donnees = pd.DataFrame(gdf[list(colonnes)]).astype(colonnes)
    resultat = gpd.GeoDataFrame(donnees, geometry=gdf.geometry.to_crs(crs).values, crs=crs)
    return resultat.sort_values(cle).reset_index(drop=True)
