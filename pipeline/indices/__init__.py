"""Indices hebdomadaires (SPEC §6, méthodologie D1 à D9) : `make indices`.

Lit les observations (`data/raw/`) et les normales (`data/normales/`), calcule pour chaque
semaine ISO demandée les indices par station, par zone et le composite, et les écrit dans
`data/indices/<table>_<annee>.parquet` (année ISO de la semaine). Les semaines recalculées
remplacent les précédentes ; les autres sont conservées. Idempotent."""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline import schema, stockage
from pipeline.config import Config
from pipeline.indices import commun, composite, debit, ips, onde, spi
from pipeline.reference import commun as reference
from pipeline.reference.spi import pluie_zones

log = logging.getLogger(__name__)

TABLES = {  # fichier -> (colonnes, clés)
    "indice_station": (schema.IDX_STATION, ["station_id", "semaine", "indice"]),
    "indice_zone": (schema.IDX_ZONE, ["zone_id", "semaine", "indice"]),
    "composite_zone": (schema.IDX_COMPOSITE, ["zone_id", "semaine"]),
}


def dossier(config: Config) -> Path:
    return config.projet.chemins.data / "indices"


def _normales(config: Config, nom: str) -> pd.DataFrame:
    chemin = reference.dossier(config) / f"{nom}.parquet"
    if not chemin.is_file():
        raise FileNotFoundError(f"{chemin} manquant : lancer d'abord `make reference`")
    return pd.read_parquet(chemin)


def _finaliser(table: pd.DataFrame, config: Config, classer: bool = True) -> pd.DataFrame:
    table = table.reset_index(drop=True)
    table["classe"] = commun.classer(table["valeur"], config.classes) if classer else pd.NA
    table["version_methodo"] = config.projet.indices.version_methodo
    return table


def calculer_semaines(config: Config, debut: str, fin: str) -> dict[str, pd.DataFrame]:
    """Indices des semaines `debut` à `fin` (« AAAA-Www »), sans écriture."""
    dimanches = commun.dimanches(debut, fin)
    semaines = {commun.libelle_semaine(d.date()) for d in dimanches}
    stations = gpd.read_parquet(config.projet.chemins.data / "referentiels" / "stations.parquet")
    stations = pd.DataFrame(stations.drop(columns="geometry"))

    par_station = pd.concat(
        [
            ips.calculer(config, reference.lire_brut(config, "piezo", "chroniques"),
                         _normales(config, "ips_station"), dimanches),
            debit.calculer(config, reference.lire_brut(config, "hydro", "qmj"),
                           _normales(config, "debit_station"), dimanches),
        ],
        ignore_index=True,
    )  # fmt: skip
    par_station = _finaliser(par_station, config)

    pluie = pluie_zones(config, reference.lire_brut(config, "meteo", "sim"))
    zones = pd.concat(
        [
            spi.calculer(config, pluie, _normales(config, "spi_zone"), dimanches),
            composite.par_zone(par_station, stations),
        ],
        ignore_index=True,
    )
    zones = _finaliser(zones, config)
    ecoulement = onde.calculer(reference.lire_brut(config, "onde", "observations"), stations,
                               semaines)  # fmt: skip
    zones = pd.concat([zones, _finaliser(ecoulement, config, classer=False)], ignore_index=True)

    composites = _finaliser(composite.composite(config, zones), config)
    return {"indice_station": par_station, "indice_zone": zones, "composite_zone": composites}


def ecrire(config: Config, tables: dict[str, pd.DataFrame], semaines: set[str]) -> list[Path]:
    """Remplace les `semaines` dans les fichiers annuels ; les autres semaines sont conservées."""
    chemins = []
    annees = sorted({s[:4] for s in semaines})
    for nom, (colonnes, cles) in TABLES.items():
        nouveau = tables[nom]
        for annee in annees:
            chemin = dossier(config) / f"{nom}_{annee}.parquet"
            bloc = nouveau[nouveau["semaine"].str[:4] == annee]
            if chemin.is_file():
                ancien = pd.read_parquet(chemin)
                bloc = pd.concat([ancien[~ancien["semaine"].isin(semaines)], bloc])
            elif bloc.empty:
                continue
            stockage.ecrire_parquet(schema.normaliser_observations(bloc, colonnes, cles), chemin)
            chemins.append(chemin)
    return chemins


def calculer(config: Config, debut: str, fin: str) -> dict[str, int]:
    """Calcule et écrit les semaines `debut` à `fin` ; renvoie le nombre de lignes par table."""
    tables = calculer_semaines(config, debut, fin)
    semaines = {commun.libelle_semaine(d.date()) for d in commun.dimanches(debut, fin)}
    ecrire(config, tables, semaines)
    for nom, table in tables.items():
        log.info("%s : %d lignes (%s à %s)", nom, len(table), debut, fin)
    return {nom: len(table) for nom, table in tables.items()}
