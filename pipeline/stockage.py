"""Écriture des GeoParquet / Parquet de `data/` (source de vérité, SPEC §5.2)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd


def ecrire_parquet(table: pd.DataFrame, chemin: Path) -> None:
    """Écriture atomique : un fichier interrompu ne remplace jamais le précédent."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".tmp")
    table.to_parquet(temporaire, index=False)
    temporaire.replace(chemin)


def _identiques(a: pd.DataFrame, b: pd.DataFrame) -> pd.Series:
    """Lignes aux valeurs identiques, deux valeurs manquantes étant égales. Avec les types
    nullables (`string`), `<NA> == "x"` vaut `<NA>` et non False : on le force à False, sinon
    une valeur manquante complétée à la source ne serait jamais mise à jour."""
    egales = (a == b).fillna(False).astype(bool)
    return (egales | (a.isna() & b.isna())).all(axis=1)


def fusionner_par_annee(
    nouveau: pd.DataFrame,
    dossier: Path,
    prefixe: str,
    cles: Sequence[str],
    valeurs: Sequence[str],
    colonne_date: str = "date",
) -> list[Path]:
    """Fusionne des observations dans `<dossier>/<prefixe>_<annee>.parquet` (année de la date).

    Une observation déjà stockée et inchangée garde sa ligne d'origine (dont `ingere_le`) ;
    une observation corrigée à la source remplace l'ancienne. Idempotent : relancer avec les
    mêmes données réécrit des fichiers identiques.
    """
    chemins = []
    annees = pd.to_datetime(nouveau[colonne_date]).dt.year
    for annee, bloc in nouveau.groupby(annees):
        chemin = dossier / f"{prefixe}_{annee}.parquet"
        bloc = bloc.set_index(list(cles))
        if chemin.exists():
            ancien = pd.read_parquet(chemin).set_index(list(cles))
            communs = ancien.index.intersection(bloc.index)
            inchanges = communs[
                _identiques(ancien.loc[communs, list(valeurs)], bloc.loc[communs, list(valeurs)])
            ]
            a_ecrire = bloc.drop(inchanges)
            fusion = pd.concat([ancien.drop(a_ecrire.index.intersection(ancien.index)), a_ecrire])
        else:
            fusion = bloc
        ecrire_parquet(fusion.reset_index().sort_values(list(cles), ignore_index=True), chemin)
        chemins.append(chemin)
    return chemins
