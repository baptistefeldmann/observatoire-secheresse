"""Arrêtés sécheresse, jeu data.gouv.fr « Donnée Sécheresse - VigiEau » (validation des indices).

Le CSV de l'historique complet porte une ligne par arrêté de restriction ; ses zones d'alerte
(type, code, nom, niveau de gravité) sont des listes JSON parallèles. Les arrêtés du département
sont dépliés en une ligne par arrêté et par zone d'alerte. Les plus anciens (2011 en Vendée) ne
listent aucune zone : ils sont gardés, avec des colonnes de zone vides.

Source de validation seulement : n'entre ni dans les indices ni dans PostGIS.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.config import Config
from pipeline.http import ClientHttp

COLONNES = [
    "arrete_id", "numero", "date_signature", "date_debut", "date_fin", "statut",
    "type_zone_alerte", "code_zone_alerte", "nom_zone_alerte", "niveau_gravite",
]  # fmt: skip

# Niveaux de gravité des arrêtés, du moins au plus sévère (0 : pas de restriction)
NIVEAUX = {"vigilance": 1, "alerte": 2, "alerte_renforcee": 3, "crise": 4}

CHAMPS_ZONE = {
    "type_zone_alerte": "zones_alerte.type",
    "code_zone_alerte": "zones_alerte.code",
    "nom_zone_alerte": "zones_alerte.nom",
    "niveau_gravite": "zones_alerte.niveau_gravite",
}


VIDES = {"", "null", "undefined"}  # valeurs manquantes écrites en texte dans le CSV


def _texte(valeur: str) -> str | None:
    return None if valeur in VIDES else valeur


def _liste(texte: Any) -> list[Any]:
    """Liste JSON d'une cellule ; vide si la cellule est vide, `null` ou illisible."""
    try:
        valeur = json.loads(texte) if isinstance(texte, str) and texte else None
    except json.JSONDecodeError:
        return []
    return valeur if isinstance(valeur, list) else []


def url_arretes(config: Config, client: ClientHttp) -> str:
    vigieau = config.sources.vigieau
    jeu = client.json(f"{vigieau.api_datagouv}datasets/{vigieau.jeu_datagouv}/")
    urls = {r["title"]: r["url"] for r in jeu["resources"]}
    if vigieau.ressource not in urls:
        raise RuntimeError(f"ressource « {vigieau.ressource} » absente du jeu VigiEau")
    return str(urls[vigieau.ressource])


def lire_arretes(chemin: Path, code_departement: str) -> pd.DataFrame:
    """Arrêtés du département, une ligne par arrêté et par zone d'alerte (`COLONNES`)."""
    brut = pd.read_csv(chemin, dtype=str, keep_default_na=False)
    brut = brut[brut["departement"] == code_departement]
    lignes: list[dict[str, Any]] = []
    for _, a in brut.iterrows():
        commun = {
            "arrete_id": int(a["id"]),
            "numero": a["numero"],
            "date_signature": _texte(a["date_signature"]),
            "date_debut": a["date_debut"],
            "date_fin": _texte(a["date_fin"]),
            "statut": a["statut"],
        }
        zones = {col: _liste(a[champ]) for col, champ in CHAMPS_ZONE.items()}
        n = len(zones["nom_zone_alerte"])
        if any(len(v) != n for v in zones.values()):
            raise ValueError(
                f"arrêté {a['id']} : listes de zones d'alerte de longueurs différentes"
            )
        if n == 0:
            lignes.append(commun | dict.fromkeys(CHAMPS_ZONE))
        for i in range(n):
            lignes.append(commun | {col: v[i] for col, v in zones.items()})
    table = pd.DataFrame(lignes, columns=COLONNES)
    for col in ("date_signature", "date_debut", "date_fin"):
        table[col] = pd.to_datetime(table[col], format="%Y-%m-%d").dt.date
    table["arrete_id"] = table["arrete_id"].astype("int64")
    texte = [
        c for c in COLONNES if c not in ("arrete_id", "date_signature", "date_debut", "date_fin")
    ]
    table[texte] = table[texte].astype("string")
    table["nom_zone_alerte"] = table["nom_zone_alerte"].str.strip()
    return table.sort_values(["date_debut", "arrete_id", "type_zone_alerte", "nom_zone_alerte"],
                             ignore_index=True)  # fmt: skip


def ingerer_arretes(config: Config, client: ClientHttp) -> pd.DataFrame:
    """Télécharge l'historique national (environ 12 Mo) et garde les arrêtés du département."""
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier) / "arretes.csv"
        client.telecharger(url_arretes(config, client), chemin)
        return lire_arretes(chemin, config.projet.territoire.code_departement)
