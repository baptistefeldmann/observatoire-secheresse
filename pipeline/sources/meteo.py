"""Météo-France SIM quotidienne, data.gouv.fr (SPEC §4.4, spike n°1).

Grille SAFRAN de 8 km : les fichiers CSV donnent le centre des mailles (LAMBX, LAMBY) en
Lambert II étendu et en hectomètres ; l'identifiant `num_maille` vient du shapefile
`SHP_SIM_FRANCE` du même jeu de données.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.schema import COLONNES_MAILLE, OBS_METEO, normaliser, normaliser_observations

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


COLONNES_CSV = ["LAMBX", "LAMBY", "DATE", "PRELIQ", "PRENEI", "ETP", "SWI"]
TITRE_RECENT = "QUOT_SIM2_latest"  # 60 jours glissants, mis à jour chaque jour
LIGNES_PAR_MORCEAU = 1_000_000


def titre_annee(annee: int) -> str:
    return f"QUOT_SIM2_{annee}"


def coordonnees_grille(config: Config, mailles: gpd.GeoDataFrame) -> pd.DataFrame:
    """`maille_id` -> (LAMBX, LAMBY) des CSV, retrouvés depuis le centre des mailles."""
    sim = config.sources.sim
    centres = mailles.geometry.centroid.to_crs(sim.crs_grille)
    return pd.DataFrame(
        {
            "maille_id": mailles["maille_id"].to_numpy(),
            "LAMBX": (centres.x / sim.unite_coordonnees_m).round().astype("int64").to_numpy(),
            "LAMBY": (centres.y / sim.unite_coordonnees_m).round().astype("int64").to_numpy(),
        }
    )


def _lire_csv(chemin: Path, grille: pd.DataFrame) -> pd.DataFrame:
    morceaux = [
        morceau.merge(grille, on=["LAMBX", "LAMBY"], how="inner")
        for morceau in pd.read_csv(
            chemin, sep=";", usecols=COLONNES_CSV, chunksize=LIGNES_PAR_MORCEAU
        )
    ]
    return pd.concat(morceaux, ignore_index=True)


def ingerer_observations(
    config: Config,
    client: ClientHttp,
    mailles: gpd.GeoDataFrame,
    annees: list[int],
    aujourd_hui: date,
) -> Iterator[tuple[str, pd.DataFrame]]:
    """`obs.meteo_jour` des mailles du territoire : un lot par fichier SIM (années demandées,
    puis fichier des 60 derniers jours). Précipitations = liquides + solides ; SWI en fraction
    (la notice indique des %, à tort : spike n°1)."""
    urls = ressources(config, client)
    grille = coordonnees_grille(config, mailles)
    for titre in [*(titre_annee(a) for a in annees), TITRE_RECENT]:
        if titre not in urls:
            raise RuntimeError(f"ressource SIM absente du jeu de données : {titre}")
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / f"{titre}.csv.gz"
            client.telecharger(urls[titre], chemin)
            brut = _lire_csv(chemin, grille)
        obs = pd.DataFrame(
            {
                "maille_id": brut["maille_id"],
                "date": pd.to_datetime(brut["DATE"].astype(str), format="%Y%m%d"),
                "precip_mm": brut["PRELIQ"] + brut["PRENEI"],
                "etp_mm": brut["ETP"],
                "swi": brut["SWI"],
                "ingere_le": aujourd_hui,
            }
        )
        yield titre, normaliser_observations(obs, OBS_METEO, ["maille_id", "date"])
