"""Outils communs aux API Hub'Eau (piézométrie, hydrométrie, écoulement)."""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from pipeline.http import ClientHttp

log = logging.getLogger(__name__)

TAILLE_PAGE = 5000


def stations(client: ClientHttp, url: str, code_departement: str) -> gpd.GeoDataFrame:
    """Stations d'un département, géométrie GeoJSON (WGS84) ; stations sans position écartées."""
    enregistrements = list(
        client.pages_hubeau(
            url, {"code_departement": code_departement, "size": TAILLE_PAGE, "format": "json"}
        )
    )
    geometries = [shape(e["geometry"]) if e.get("geometry") else None for e in enregistrements]
    df = pd.DataFrame([{k: v for k, v in e.items() if k != "geometry"} for e in enregistrements])
    gdf = gpd.GeoDataFrame(df, geometry=geometries, crs=4326)
    sans_position = gdf.geometry.isna()
    if sans_position.any():
        log.warning("%s : %d station(s) sans position écartée(s)", url, int(sans_position.sum()))
    return gdf[~sans_position]


def valeur(ligne: Any, champ: str) -> Any:
    """Valeur d'un champ, None si absent ou NaN (colonnes absentes de certaines réponses)."""
    v = ligne.get(champ)
    if isinstance(v, float) and pd.isna(v):
        return None
    return v
