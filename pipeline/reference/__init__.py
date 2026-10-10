"""Calcul ponctuel des normales de référence (SPEC §6.1) : `make reference`.

Écrit `data/normales/` (versionné par DVC) ; le job hebdomadaire ne fait que les lire.
`rang_zone` : références de la restandardisation des indices de zone et du composite (D10)."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline import stockage
from pipeline.config import Config
from pipeline.reference import commun, debit, enveloppe, ips, ruptures, spi

log = logging.getLogger(__name__)


def _normales_zone(config: Config) -> pd.DataFrame:
    from pipeline.indices import normales_zone  # import tardif : pipeline.indices lit ce paquet

    return normales_zone(config)


def calculer(config: Config) -> dict[str, Path]:
    sortie = commun.dossier(config)
    chemins = {}
    tables: dict[str, pd.DataFrame] = {}
    for nom, calcul in (("spi_zone", spi.normales), ("ips_station", ips.normales),
                        ("debit_station", debit.normales),
                        ("ruptures", ruptures.detecter),
                        ("enveloppe_station", lambda _: enveloppe.enveloppes(
                            tables["ips_station"], tables["debit_station"])),
                        # en dernier : lit les normales de station écrites ci-dessus (D10)
                        ("rang_zone", _normales_zone)):  # fmt: skip
        tables[nom] = table = calcul(config)
        chemins[nom] = sortie / f"{nom}.parquet"
        stockage.ecrire_parquet(table, chemins[nom])
        log.info("%s : %d lignes -> %s", nom, len(table), chemins[nom])
    return chemins
