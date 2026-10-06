"""Calcul ponctuel des normales de référence (SPEC §6.1) : `make reference`.

Écrit `data/normales/` (versionné par DVC) ; le job hebdomadaire ne fait que les lire."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline import stockage
from pipeline.config import Config
from pipeline.reference import commun, debit, enveloppe, ips, ruptures, spi

log = logging.getLogger(__name__)


def calculer(config: Config) -> dict[str, Path]:
    sortie = commun.dossier(config)
    chemins = {}
    tables: dict[str, pd.DataFrame] = {}
    for nom, calcul in (("spi_zone", spi.normales), ("ips_station", ips.normales),
                        ("debit_station", debit.normales),
                        ("ruptures", ruptures.detecter),
                        ("enveloppe_station", lambda _: enveloppe.enveloppes(
                            tables["ips_station"], tables["debit_station"]))):  # fmt: skip
        tables[nom] = table = calcul(config)
        chemins[nom] = sortie / f"{nom}.parquet"
        stockage.ecrire_parquet(table, chemins[nom])
        log.info("%s : %d lignes -> %s", nom, len(table), chemins[nom])
    return chemins
