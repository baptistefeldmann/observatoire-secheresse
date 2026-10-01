"""Outils communs au calcul des indices hebdomadaires (SPEC §6, méthodologie D7 et D9)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.config import Classes

# Bornes de la valeur standardisée : un cumul nul sans précédent dans la référence (q0 = 0)
# donnerait −∞ (D9).
Z_MAX = 3.0


def libelle_semaine(dimanche: date) -> str:
    annee, semaine, _ = dimanche.isocalendar()
    return f"{annee}-W{semaine:02d}"


def dimanche(semaine: str) -> date:
    """Dimanche (fin) de la semaine ISO « AAAA-Www »."""
    annee, numero = semaine.split("-W")
    return date.fromisocalendar(int(annee), int(numero), 7)


def derniere_semaine_complete(aujourd_hui: date) -> str:
    """Semaine ISO dont le dimanche est passé (le dimanche même, la journée n'est pas finie)."""
    return libelle_semaine(aujourd_hui - timedelta(days=aujourd_hui.isoweekday()))


def dimanches(debut: str, fin: str) -> pd.DatetimeIndex:
    """Dimanches des semaines ISO de `debut` à `fin` incluses."""
    return pd.date_range(dimanche(debut), dimanche(fin), freq="7D")


def z_rang(valeur: float, reference: np.ndarray) -> float:
    """Valeur centrée réduite d'après le rang de `valeur` dans l'échantillon trié `reference`
    (approche non paramétrique, D9) : la valeur est ajoutée à l'échantillon et sa probabilité
    au non-dépassement est donnée par la formule de Gringorten, (i − 0,44) / (n + 0,12), les
    ex aequo prenant le rang moyen."""
    n = len(reference)
    inferieurs = np.searchsorted(reference, valeur, side="left")
    egaux = np.searchsorted(reference, valeur, side="right") - inferieurs
    rang = inferieurs + 1 + egaux / 2
    return float(stats.norm.ppf((rang - 0.44) / (n + 1 + 0.12)))


def z_probabilite(probabilite: np.ndarray) -> np.ndarray:
    """Φ⁻¹, borné à ±`Z_MAX`."""
    z: np.ndarray = np.clip(stats.norm.ppf(probabilite), -Z_MAX, Z_MAX)
    return z


def dans_regime(dates: pd.Series, rupture: pd.Series) -> pd.Series:
    """Vrai si la mesure relève du régime décrit par la normale : une station à rupture
    confirmée (D8) n'a de normale que pour le nouveau régime, les mesures antérieures à
    l'année de rupture n'ont donc pas d'indice."""
    return rupture.isna() | (pd.to_datetime(dates).dt.year >= rupture.fillna(0))


def classer(valeurs: pd.Series, classes: Classes) -> pd.Series:
    """Classe 1-7 (classes.yaml) : classe k si seuils[k-2] < v <= seuils[k-1] ; vide si v l'est."""
    rangs = np.searchsorted(np.asarray(classes.seuils), valeurs.to_numpy(dtype=float), "left")
    return pd.Series(rangs + 1, index=valeurs.index, dtype="Int64").mask(valeurs.isna())


def detail_json(valeurs: dict[str, Any]) -> str:
    """JSON trié (jsonb en base), stable d'une exécution à l'autre."""
    return json.dumps(valeurs, ensure_ascii=False, sort_keys=True)


def arrondi(valeurs: Iterable[float], chiffres: int = 4) -> list[float]:
    return [round(float(v), chiffres) for v in valeurs]
