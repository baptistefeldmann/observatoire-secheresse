"""Ingestion des observations dans `data/raw/` (SPEC §5.2, §7.1) : un fichier par source et
par année. Idempotent (voir `stockage.fusionner_par_annee`)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from pipeline import referentiels, stockage
from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.sources import retenues

log = logging.getLogger(__name__)


def dossier_brut(config: Config, source: str) -> Path:
    return config.projet.chemins.data / "raw" / source


def ingerer(config: Config, client: ClientHttp, aujourd_hui: date) -> dict[str, list[Path]]:
    emprise = referentiels.emprise(config)
    obs = retenues.ingerer_observations(config, client, emprise, aujourd_hui)
    chemins = {
        "retenues": stockage.fusionner_par_annee(
            obs,
            dossier_brut(config, "retenues"),
            "retenues",
            cles=["station_id", "date"],
            valeurs=["volume_m3", "capacite_m3", "source_donnee"],
        )
    }
    log.info("retenues : %d relevés, %d fichier(s)", len(obs), len(chemins["retenues"]))
    return chemins
