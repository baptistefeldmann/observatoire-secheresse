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


def vide(colonnes: dict[str, str], crs: str) -> gpd.GeoDataFrame:
    """Table sans ligne au schéma donné (ex. aucune retenue sur le territoire)."""
    donnees = pd.DataFrame({c: pd.Series(dtype=t) for c, t in colonnes.items()})
    return gpd.GeoDataFrame(donnees, geometry=gpd.GeoSeries([], crs=crs), crs=crs)


# Tables d'observation (`obs.*`, SPEC §5.3) : colonne -> type ; "date" = date sans heure.
OBS_PIEZO = {
    "station_id": "string", "date": "date", "niveau_ngf": "float64", "profondeur": "float64",
    "qualification": "string", "ingere_le": "date",
}  # fmt: skip
OBS_DEBIT = {
    "station_id": "string", "date": "date", "qmj_ls": "float64", "qualification": "string",
    "ingere_le": "date",
}  # fmt: skip
OBS_ONDE = {
    "station_id": "string", "date_campagne": "date", "modalite": "string",
    "type_campagne": "string", "ingere_le": "date",
}  # fmt: skip
OBS_METEO = {
    "maille_id": "int64", "date": "date", "precip_mm": "float64", "etp_mm": "float64",
    "swi": "float64", "ingere_le": "date",
}  # fmt: skip
OBS_RETENUE = {
    "station_id": "string", "date": "date", "volume_m3": "float64", "capacite_m3": "float64",
    "source_donnee": "string", "ingere_le": "date",
}  # fmt: skip


def normaliser_observations(
    table: pd.DataFrame, colonnes: dict[str, str], cles: list[str]
) -> pd.DataFrame:
    """Colonnes et types du schéma, doublons de clé retirés (le dernier gagne), tri par clé."""
    manquantes = set(colonnes) - set(table.columns)
    if manquantes:
        raise ValueError(f"colonnes manquantes : {sorted(manquantes)}")
    resultat = pd.DataFrame(index=table.index)
    for colonne, type_ in colonnes.items():
        if type_ == "date":
            resultat[colonne] = pd.to_datetime(table[colonne]).dt.date
        else:
            resultat[colonne] = table[colonne].astype(type_)  # type: ignore[call-overload]
    resultat = resultat.drop_duplicates(cles, keep="last")
    return resultat.sort_values(cles, ignore_index=True)


# Tables d'indices hebdomadaires (`idx.*`, SPEC §5.3, migration 0002) ; « detail » en JSON.
IDX_STATION = {
    "station_id": "string", "semaine": "string", "indice": "string", "valeur": "float64",
    "classe": "Int64", "periode_ref": "string", "hors_reference": "bool", "date_mesure": "date",
    "dans_composite": "bool", "version_methodo": "string",
}  # fmt: skip
IDX_ZONE = {
    "zone_id": "string", "semaine": "string", "indice": "string", "valeur": "float64",
    "classe": "Int64", "n_stations": "Int64", "detail": "string", "version_methodo": "string",
}  # fmt: skip
IDX_COMPOSITE = {
    "zone_id": "string", "semaine": "string", "valeur": "float64", "classe": "Int64",
    "detail": "string", "version_methodo": "string",
}  # fmt: skip
