"""Validation des indices par les arrêtés sécheresse : `make validation`.

1. Télécharge les arrêtés VigiEau du département -> `data/validation/arretes.parquet`
   (`--hors-ligne` : réutilise le fichier existant).
2. Niveau de restriction par zone et par semaine, jusqu'à la dernière semaine des indices
   -> `data/validation/restrictions_zone.parquet`.
3. Mesures d'accord avec le composite et ses composantes -> rapport Markdown
   (`chemins.rapport_validation`).

Les arrêtés ne servent qu'à cette comparaison : ni indice, ni PostGIS. Idempotent : mêmes
données, mêmes fichiers.
"""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pipeline import stockage
from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.indices import dossier as dossier_indices
from pipeline.sources import vigieau
from pipeline.validation import arretes as niveaux
from pipeline.validation import rapport

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resultat:
    arretes: Path
    restrictions: Path
    rapport: Path
    non_rattachees: list[tuple[str, str]]


def dossier(config: Config) -> Path:
    return config.projet.chemins.data / "validation"


def _lire_indices(config: Config, table: str) -> pd.DataFrame:
    fichiers = sorted(glob.glob(str(dossier_indices(config) / f"{table}_*.parquet")))
    if not fichiers:
        raise FileNotFoundError(f"aucun fichier {table}_*.parquet : lancer d'abord `make indices`")
    return pd.concat([pd.read_parquet(f) for f in fichiers], ignore_index=True)


def executer(config: Config, client: ClientHttp | None) -> Resultat:
    """`client` à None : arrêtés relus depuis `data/validation/` (pas de réseau)."""
    chemin_arretes = dossier(config) / "arretes.parquet"
    if client is not None:
        stockage.ecrire_parquet(vigieau.ingerer_arretes(config, client), chemin_arretes)
    elif not chemin_arretes.is_file():
        raise FileNotFoundError(f"{chemin_arretes} manquant : lancer sans --hors-ligne")
    arretes = pd.read_parquet(chemin_arretes)

    composite = _lire_indices(config, "composite_zone")
    fin = str(composite["semaine"].max())
    restrictions = niveaux.niveaux_hebdo(config, arretes, fin)
    chemin_restrictions = dossier(config) / "restrictions_zone.parquet"
    stockage.ecrire_parquet(restrictions, chemin_restrictions)

    orphelines = niveaux.non_rattachees(niveaux.rattacher(config, arretes))
    for type_, nom in orphelines:
        log.warning("zone d'alerte non rattachée à une zone du projet : %s %s", type_, nom)
    table = rapport.assembler(config, restrictions, composite, _lire_indices(config, "indice_zone"))
    chemin_rapport = config.projet.chemins.rapport_validation
    chemin_rapport.parent.mkdir(parents=True, exist_ok=True)
    chemin_rapport.write_text(
        rapport.rediger(config, table, arretes, orphelines, fin), encoding="utf-8"
    )
    return Resultat(chemin_arretes, chemin_restrictions, chemin_rapport, orphelines)
