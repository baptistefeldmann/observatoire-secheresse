"""Semaines ISO « AAAA-Www » : fonctions de dates, sans dépendance externe.

Module volontairement léger : l'API (image Docker) l'importe sans charger pandas, scipy ni
geopandas, qui n'appartiennent qu'au pipeline de calcul.
"""

from __future__ import annotations

from datetime import date, timedelta


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
