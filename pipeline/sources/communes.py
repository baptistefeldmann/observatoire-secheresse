"""Communes et contour du territoire, depuis geo.api.gouv.fr (SPEC §4.5)."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import MultiPolygon

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import COLONNES_COMMUNE, en_multipolygone, normaliser


def ingerer_communes(config: Config, client: ClientHttp) -> gpd.GeoDataFrame:
    dep = config.projet.territoire.code_departement
    geojson = client.json(
        f"{config.sources.geo_api}departements/{dep}/communes",
        {"format": "geojson", "geometry": "contour", "fields": "code,nom"},
    )
    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs=4326)
    if gdf.empty:
        raise RuntimeError(f"aucune commune renvoyée pour le département {dep}")
    gdf = gdf.rename(columns={"code": "code_insee"})
    gdf["geometry"] = gdf.geometry.map(en_multipolygone)
    return normaliser(gdf, COLONNES_COMMUNE, "code_insee", config.projet.crs)


def contour(communes: gpd.GeoDataFrame) -> MultiPolygon:
    """Contour du territoire : fusion des communes."""
    return en_multipolygone(communes.union_all())
