"""Outils communs au calcul des normales (SPEC §6.1, méthodologie D7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pipeline.config import Config, Periode

SEMAINE_MAX = 52  # la semaine ISO 53, rare, utilise la normale de la semaine 52


def dossier(config: Config) -> Path:
    return config.projet.chemins.data / "normales"


def lire_brut(config: Config, source: str, prefixe: str) -> pd.DataFrame:
    fichiers = sorted((config.projet.chemins.data / "raw" / source).glob(f"{prefixe}_*.parquet"))
    if not fichiers:
        raise FileNotFoundError(f"aucune donnée {source} : lancer d'abord `make ingest`")
    return pd.concat([pd.read_parquet(f) for f in fichiers], ignore_index=True)


def semaine_ref(dates: pd.Series) -> pd.Series:
    """Numéro de semaine ISO servant de clé aux normales (53 ramenée à 52)."""
    return pd.to_datetime(dates).dt.isocalendar().week.clip(upper=SEMAINE_MAX).astype("int64")


@dataclass(frozen=True)
class Choix:
    annees: list[int]  # années retenues ; vide = pas de normale possible
    periode_ref: str  # « 1991-2020 », ou période effective si hors référence
    hors_reference: bool  # avertissement stocké avec l'indice (SPEC §6.1)


def _figees(annees: list[int], minimum: int, gel: int | None) -> list[int]:
    """Référence hors période figée (D10) : années jusqu'à `gel` si elles suffisent, sinon les
    `minimum` premières dès qu'elles existent ; vide en deçà."""
    avant_gel = [a for a in annees if gel is None or a <= gel]
    retenues = avant_gel if len(avant_gel) >= minimum else annees[:minimum]
    return retenues if len(retenues) >= minimum else []


def choisir_annees(valides: set[int], ref: Periode, rupture: int | None = None) -> Choix:
    """Années de la période de référence si elles sont assez nombreuses ; à défaut, une
    référence figée hors période (D10), avec avertissement ; sinon aucune.

    Hors période, les années suivant `annee_gel` n'entrent pas, sauf pour atteindre le minimum :
    la référence ne s'allonge plus avec le temps (D10). Station à rupture confirmée (D8) :
    seules les années à partir de la rupture comptent, admises dès `annees_min_apres_rupture`,
    toujours avec avertissement."""
    minimum = ref.annees_min or 1
    if rupture is not None:
        apres = sorted(a for a in valides if a >= rupture)
        retenues = _figees(apres, ref.annees_min_apres_rupture or minimum, ref.annee_gel)
    else:
        dans_ref = sorted(a for a in valides if ref.debut <= a <= ref.fin)
        if len(dans_ref) >= minimum:
            return Choix(dans_ref, f"{ref.debut}-{ref.fin}", False)
        retenues = _figees(sorted(valides), minimum, ref.annee_gel)
    if not retenues:
        return Choix([], "", True)
    return Choix(retenues, f"{retenues[0]}-{retenues[-1]}", True)


def ruptures(config: Config) -> dict[str, int]:
    """station_id -> première année du nouveau régime (stations.yaml, D8)."""
    return {r.station: r.annee for r in config.stations.ruptures}
