"""Météo-France SIM quotidienne, data.gouv.fr (SPEC §4.4, spike n°1).

Grille SAFRAN de 8 km : les fichiers CSV donnent le centre des mailles (LAMBX, LAMBY) en
Lambert II étendu et en hectomètres ; l'identifiant `num_maille` vient du shapefile
`SHP_SIM_FRANCE` du même jeu de données.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import COLONNES_MAILLE, normaliser

FICHIERS_GRILLE = ("SHP_SIM_FRANCE.shp", "SHP_SIM_FRANCE.shx", "SHP_SIM_FRANCE.dbf")


def ressources(config: Config, client: ClientHttp) -> dict[str, str]:
    """Titre de ressource du jeu SIM -> URL de téléchargement."""
    sim = config.sources.sim
    jeu = client.json(f"{sim.api_datagouv}datasets/{sim.jeu_datagouv}/")
    return {r["title"]: r["url"] for r in jeu["resources"]}


def grille(config: Config, client: ClientHttp) -> gpd.GeoDataFrame:
    """Toutes les mailles SIM : `maille_id`, `lambx`, `lamby`, carré de la maille (CRS projet)."""
    sim = config.sources.sim
    urls = ressources(config, client)
    manquants = [f for f in FICHIERS_GRILLE if f not in urls]
    if manquants:
        raise RuntimeError(f"ressources absentes du jeu SIM : {manquants}")
    with tempfile.TemporaryDirectory() as dossier:
        for nom in FICHIERS_GRILLE:
            (Path(dossier) / nom).write_bytes(client.contenu(urls[nom]))
        points = gpd.read_file(Path(dossier) / FICHIERS_GRILLE[0])
    u, demi = sim.unite_coordonnees_m, sim.pas_grille_m / 2
    carres = [
        box(x * u - demi, y * u - demi, x * u + demi, y * u + demi)
        for x, y in zip(points["lambx"], points["lamby"], strict=True)
    ]
    gdf = gpd.GeoDataFrame(
        {
            "maille_id": points["num_maille"].astype("int64"),
            "lambx": points["lambx"].astype("int64"),
            "lamby": points["lamby"].astype("int64"),
        },
        geometry=carres,
        crs=sim.crs_grille,
    )
    return gdf.to_crs(config.projet.crs)


def ingerer_mailles(
    config: Config, client: ClientHttp, territoire: BaseGeometry
) -> gpd.GeoDataFrame:
    """Mailles qui intersectent le territoire (déjà élargi du tampon d'emprise)."""
    toutes = grille(config, client)
    retenues = toutes[toutes.intersects(territoire)]
    if retenues.empty:
        raise RuntimeError("aucune maille SIM n'intersecte le territoire")
    return normaliser(retenues, COLONNES_MAILLE, "maille_id", config.projet.crs)
