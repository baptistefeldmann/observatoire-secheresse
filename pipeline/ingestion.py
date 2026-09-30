"""Ingestion des observations dans `data/raw/` (SPEC §5.2, §7.1) : un fichier par source et
par année. Idempotent (voir `stockage.fusionner_par_annee`) ; une source en échec ne bloque
pas les autres et figure dans le rapport (SPEC §7.2)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline import referentiels, stockage
from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.sources import hydro, meteo, onde, piezo, retenues

log = logging.getLogger(__name__)

Lecture = tuple[pd.DataFrame, list[str]]  # observations, erreurs par station


@dataclass(frozen=True)
class Stockage:
    prefixe: str
    cles: list[str]
    valeurs: list[str]
    colonne_date: str = "date"


STOCKAGE = {
    "piezo": Stockage(
        "chroniques", ["station_id", "date"], ["niveau_ngf", "profondeur", "qualification"]
    ),
    "hydro": Stockage("qmj", ["station_id", "date"], ["qmj_ls", "qualification"]),
    "onde": Stockage(
        "observations",
        ["station_id", "date_campagne"],
        ["modalite", "type_campagne"],
        "date_campagne",
    ),
    "meteo": Stockage("sim", ["maille_id", "date"], ["precip_mm", "etp_mm", "swi"]),
    "retenues": Stockage(
        "retenues", ["station_id", "date"], ["volume_m3", "capacite_m3", "source_donnee"]
    ),
}


@dataclass
class Rapport:
    fichiers: dict[str, set[Path]] = field(default_factory=dict)
    lignes: dict[str, int] = field(default_factory=dict)
    erreurs: list[str] = field(default_factory=list)


def dossier_brut(config: Config, source: str) -> Path:
    return config.projet.chemins.data / "raw" / source


def _stocker(config: Config, rapport: Rapport, source: str, obs: pd.DataFrame) -> None:
    s = STOCKAGE[source]
    rapport.lignes[source] = rapport.lignes.get(source, 0) + len(obs)
    if obs.empty:
        return
    chemins = stockage.fusionner_par_annee(
        obs, dossier_brut(config, source), s.prefixe, s.cles, s.valeurs, s.colonne_date
    )
    rapport.fichiers.setdefault(source, set()).update(chemins)


def ingerer(
    config: Config, client: ClientHttp, aujourd_hui: date, depuis: date | None = None
) -> Rapport:
    """Ingère toutes les sources depuis `depuis` (tout l'historique si None)."""
    dossier_ref = referentiels.dossier(config)
    stations = gpd.read_parquet(dossier_ref / "stations.parquet")
    mailles = gpd.read_parquet(dossier_ref / "mailles_safran.parquet")
    emprise = referentiels.emprise(config)
    rapport = Rapport()

    def lire_piezo() -> Lecture:
        return piezo.ingerer_observations(config, client, stations, depuis, aujourd_hui)

    def lire_hydro() -> Lecture:
        return hydro.ingerer_observations(config, client, stations, depuis, aujourd_hui)

    def lire_onde() -> Lecture:
        return onde.ingerer_observations(config, client, stations, depuis, aujourd_hui)

    def lire_retenues() -> Lecture:
        return retenues.ingerer_observations(config, client, emprise, aujourd_hui), []

    lecteurs: dict[str, Callable[[], Lecture]] = {
        "piezo": lire_piezo,
        "hydro": lire_hydro,
        "onde": lire_onde,
        "retenues": lire_retenues,
    }
    # Une source en échec ne bloque pas les autres : toute exception est consignée.
    for source, lire in lecteurs.items():
        try:
            obs, erreurs = lire()
            _stocker(config, rapport, source, obs)
            rapport.erreurs += erreurs
        except Exception as exc:
            log.exception("source %s en échec", source)
            rapport.erreurs.append(f"{source} : {exc}")

    debut = depuis.year if depuis else config.projet.periode_reference.hydro_meteo.debut - 1
    try:
        annees = list(range(debut, aujourd_hui.year + 1))
        for titre, obs in meteo.ingerer_observations(config, client, mailles, annees, aujourd_hui):
            _stocker(config, rapport, "meteo", obs)
            log.info("meteo %s : %d valeurs", titre, len(obs))
    except Exception as exc:
        log.exception("source meteo en échec")
        rapport.erreurs.append(f"meteo : {exc}")

    for source, n in rapport.lignes.items():
        log.info("%s : %d valeurs, %d fichier(s)", source, n, len(rapport.fichiers.get(source, ())))
    return rapport
