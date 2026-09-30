"""Découpage du territoire en zones et rattachement des stations (docs/methodologie.md, D5).

Une zone est l'union de masses d'eau affleurantes, éventuellement croisée avec l'union de
zones d'alerte. Les limites des deux référentiels ne coïncident pas : leur croisement laisse
des fragments et des lacunes. Les morceaux de moins de `fragment_max_km2` sont rattachés à
la zone voisine de plus longue frontière commune ; au-delà, c'est une erreur de configuration.
"""

from __future__ import annotations

import json
import logging

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from pipeline.config import Config, Zone
from pipeline.schema import COLONNES_ZONE, en_multipolygone, normaliser

log = logging.getLogger(__name__)

TOLERANCE_M = 1.0  # contact entre morceaux voisins (bruit numérique des référentiels)
COUVERTURE_MIN = 0.9999


def _polygones(geom: BaseGeometry) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for part in getattr(geom, "geoms", []) for g in _polygones(part)]


def geometrie_brute(
    zone: Zone, masses: gpd.GeoDataFrame, alertes: gpd.GeoDataFrame
) -> BaseGeometry:
    inconnues = sorted(set(zone.masses_eau) - set(masses["code"]))
    if inconnues:
        raise ValueError(f"{zone.zone_id} : masse(s) d'eau absente(s) de l'emprise : {inconnues}")
    geom = unary_union(masses.loc[masses["code"].isin(zone.masses_eau), "geometry"])
    if zone.zones_alerte:
        inconnues_za = sorted(set(zone.zones_alerte) - set(alertes["code"]))
        if inconnues_za:
            raise ValueError(f"{zone.zone_id} : zone(s) d'alerte inconnue(s) : {inconnues_za}")
        geom = geom.intersection(
            unary_union(alertes.loc[alertes["code"].isin(zone.zones_alerte), "geometry"])
        )
    return geom


def _rattacher(petits: list[Polygon], grands: pd.DataFrame) -> list[str]:
    """Zone de chaque petit morceau : plus longue frontière commune, sinon la plus proche."""
    tampons = [g.buffer(TOLERANCE_M) for g in grands["geometry"]]
    choix = []
    for morceau in petits:
        contour = morceau.boundary
        communs = [contour.intersection(t).length for t in tampons]
        if max(communs) > 0:
            idx = communs.index(max(communs))
        else:
            idx = min(
                range(len(tampons)), key=lambda i: morceau.distance(grands["geometry"].iloc[i])
            )
        choix.append(grands["zone_id"].iloc[idx])
    return choix


def construire_zones(
    config: Config,
    masses: gpd.GeoDataFrame,
    alertes: gpd.GeoDataFrame,
    territoire: BaseGeometry,
) -> gpd.GeoDataFrame:
    seuil_m2 = config.zonage.fragment_max_km2 * 1e6
    zones = config.zonage.zones

    # 1. géométries brutes découpées au territoire, rendues disjointes dans l'ordre du fichier
    deja: BaseGeometry = Polygon()
    morceaux = []
    for zone in zones:
        brute = geometrie_brute(zone, masses, alertes).intersection(territoire)
        chevauchement = brute.intersection(deja).area
        if chevauchement > seuil_m2:
            raise ValueError(
                f"{zone.zone_id} chevauche une zone précédente sur {chevauchement / 1e6:.1f} km²"
            )
        propre = brute.difference(deja)
        deja = deja.union(propre)
        morceaux += [{"zone_id": zone.zone_id, "geometry": p} for p in _polygones(propre)]

    # 2. lacunes : territoire non couvert par les zones configurées
    lacunes = _polygones(territoire.difference(deja))
    grandes_lacunes = [p for p in lacunes if p.area >= seuil_m2]
    if grandes_lacunes:
        details = ", ".join(
            f"{p.area / 1e6:.1f} km² vers ({p.centroid.x:.0f}, {p.centroid.y:.0f})"
            for p in grandes_lacunes
        )
        raise ValueError(f"territoire non couvert par les zones : {details}")

    # 3. rattachement des fragments et des lacunes
    table = pd.DataFrame(morceaux)
    table["surface"] = table["geometry"].map(lambda g: g.area)
    grands = table[table["surface"] >= seuil_m2].reset_index(drop=True)
    petits = table[table["surface"] < seuil_m2]
    orphelins = list(petits["geometry"]) + lacunes
    if orphelins:
        attribues = _rattacher(orphelins, grands)
        table = pd.concat(
            [grands, pd.DataFrame({"zone_id": attribues, "geometry": orphelins})],
            ignore_index=True,
        )
        log.info(
            "%d fragments et lacunes rattachés (%.1f km²)",
            len(orphelins),
            sum(p.area for p in orphelins) / 1e6,
        )

    # 4. une géométrie par zone, contrôles
    geometries = table.groupby("zone_id")["geometry"].agg(unary_union)
    absentes = [z.zone_id for z in zones if z.zone_id not in geometries.index]
    if absentes:
        raise ValueError(f"zone(s) sans surface sur le territoire : {absentes}")
    couverture = unary_union(list(geometries)).intersection(territoire).area / territoire.area
    if couverture < COUVERTURE_MIN:
        raise ValueError(f"couverture du territoire insuffisante : {couverture:.4%}")

    gdf = gpd.GeoDataFrame(
        {
            "zone_id": [z.zone_id for z in zones],
            "libelle": [z.libelle for z in zones],
            "type_zone": [z.type_zone for z in zones],
            "ponderations": [json.dumps(z.ponderations, sort_keys=True) for z in zones],
        },
        geometry=[en_multipolygone(geometries[z.zone_id]) for z in zones],
        crs=config.projet.crs,
    )
    return normaliser(gdf, COLONNES_ZONE, "zone_id", config.projet.crs)


def rattacher_stations(
    stations: gpd.GeoDataFrame, zones: gpd.GeoDataFrame, distance_max_m: float
) -> gpd.GeoDataFrame:
    """`zone_id` de chaque station : zone qui la contient, sinon la plus proche à moins de
    `distance_max_m` (stations du littoral hors du contour communal), sinon vide."""
    resultat = stations.copy()
    jointure = gpd.sjoin_nearest(
        stations[["station_id", "geometry"]],
        zones[["zone_id", "geometry"]],
        how="left",
        max_distance=distance_max_m,
    ).drop_duplicates("station_id")
    resultat["zone_id"] = (
        jointure.set_index("station_id")["zone_id"]
        .reindex(resultat["station_id"])
        .astype("string")
        .values
    )
    sans_zone = resultat["zone_id"].isna().sum()
    if sans_zone:
        log.warning("%d station(s) sans zone à moins de %.0f m", sans_zone, distance_max_m)
    return resultat
