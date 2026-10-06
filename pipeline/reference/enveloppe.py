"""Enveloppe de la normale par station : minimum, médiane et maximum de l'échantillon de
référence (SPEC §8.2), pour comparer une chronique brute à sa normale (API, dashboard, QGIS).

Nappes : moyennes mensuelles de niveau (m NGF), par mois. Débits : Q7 (l/s), par semaine ISO.
Dérivée des normales de l'IPS et de l'indice de débit, sur les mêmes années (D7, D8)."""

from __future__ import annotations

import numpy as np
import pandas as pd

COLONNES = [
    "station_id", "indice", "pas", "periode", "minimum", "mediane", "maximum", "n_annees",
    "periode_ref", "hors_reference",
]  # fmt: skip


def _enveloppe(normales: pd.DataFrame, indice: str, pas: str, colonne: str) -> pd.DataFrame:
    valeurs = normales["valeurs_ref"].map(np.asarray)
    return pd.DataFrame(
        {
            "station_id": normales["station_id"],
            "indice": indice,
            "pas": pas,
            "periode": normales[colonne].astype("int64"),
            "minimum": valeurs.map(np.min),
            "mediane": valeurs.map(np.median),
            "maximum": valeurs.map(np.max),
            "n_annees": normales["n_annees"].astype("int64"),
            "periode_ref": normales["periode_ref"],
            "hors_reference": normales["hors_reference"].astype(bool),
        }
    )


def enveloppes(ips: pd.DataFrame, debit: pd.DataFrame) -> pd.DataFrame:
    """`ips` : normales par station et mois ; `debit` : par station et semaine."""
    morceaux = [
        _enveloppe(t, indice, pas, colonne)
        for t, indice, pas, colonne in ((ips, "ips", "mois", "mois"),
                                        (debit, "debit", "semaine", "semaine"))
        if not t.empty
    ]  # fmt: skip
    if not morceaux:
        return pd.DataFrame(columns=COLONNES)
    table = pd.concat(morceaux, ignore_index=True)[COLONNES]
    return table.sort_values(["station_id", "indice", "periode"], ignore_index=True)
