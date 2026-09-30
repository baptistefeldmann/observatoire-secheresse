"""Outils communs aux API Hub'Eau (piézométrie, hydrométrie, écoulement)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import geopandas as gpd
import httpx
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


def par_station(
    codes: list[str], lire: Callable[[str], list[dict[str, Any]]], source: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Applique `lire` à chaque station ; une station en échec est signalée sans bloquer les
    autres (SPEC §7.2). Renvoie les enregistrements et la liste des erreurs."""
    enregistrements: list[dict[str, Any]] = []
    erreurs: list[str] = []
    for i, code in enumerate(codes, 1):
        try:
            lus = lire(code)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            erreurs.append(f"{source}:{code} : {exc}")
            log.warning("%s:%s en échec : %s", source, code, exc)
            continue
        enregistrements += [{**e, "code": code} for e in lus]
        log.info("%s %d/%d %s : %d valeurs", source, i, len(codes), code, len(lus))
    return enregistrements, erreurs
