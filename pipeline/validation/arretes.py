"""Niveau de restriction en vigueur chaque semaine, par zone du projet.

Une semaine ISO prend le niveau en vigueur le dimanche qui la termine (comme les indices, D9).
Si plusieurs arrêtés couvrent la même zone d'alerte ce jour-là, le plus récent l'emporte (date
de début, puis de signature). Une zone du projet prend le niveau le plus sévère de ses zones
d'alerte (`zones_alerte_arretes` dans `zones.yaml`) ; sans arrêté en vigueur, le niveau est 0.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from pipeline.config import Config
from pipeline.indices.commun import dimanches, libelle_semaine
from pipeline.sources.vigieau import NIVEAUX

COLONNES = ["zone_id", "semaine", "niveau", "zones_alerte"]


def cle_nom(nom: str) -> str:
    """Nom de zone d'alerte comparable : sans accents ni casse, ponctuation réduite à un espace."""
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_.casefold()).strip()


def rattacher(config: Config, arretes: pd.DataFrame) -> pd.DataFrame:
    """Lignes d'arrêtés avec la colonne `zone_id` (vide si la zone d'alerte n'est pas rattachée)."""
    index: dict[tuple[str, str], str] = {
        (type_, cle_nom(nom)): zone.zone_id
        for zone in config.zonage.zones
        for type_, noms in zone.zones_alerte_arretes.items()
        for nom in noms
    }
    cles = zip(arretes["type_zone_alerte"], arretes["nom_zone_alerte"], strict=True)
    zone_id = [
        index.get((t, cle_nom(n))) if isinstance(t, str) and isinstance(n, str) else None
        for t, n in cles
    ]
    return arretes.assign(zone_id=pd.array(zone_id, dtype="string"))


def non_rattachees(arretes: pd.DataFrame) -> list[tuple[str, str]]:
    """Zones d'alerte citées par les arrêtés et rattachées à aucune zone du projet."""
    orphelines = arretes[arretes["zone_id"].isna() & arretes["nom_zone_alerte"].notna()]
    paires = zip(orphelines["type_zone_alerte"], orphelines["nom_zone_alerte"], strict=True)
    return sorted({(str(t), str(n)) for t, n in paires})


def premiere_annee(arretes: pd.DataFrame) -> int | None:
    """Première année dont les arrêtés listent leurs zones d'alerte : avant, le niveau par zone
    est inconnu (et non nul)."""
    detailles = arretes.dropna(subset=["nom_zone_alerte"])
    return None if detailles.empty else min(d.year for d in detailles["date_debut"])


def niveaux_hebdo(config: Config, arretes: pd.DataFrame, fin: str) -> pd.DataFrame:
    """Niveau (0 à 4) de chaque zone du projet ayant des zones d'alerte, de la semaine 1 de la
    première année détaillée à la semaine `fin` ; `zones_alerte` liste les zones d'alerte à ce
    niveau."""
    zones = [z.zone_id for z in config.zonage.zones if z.zones_alerte_arretes]
    annee = premiere_annee(arretes)
    if annee is None or not zones:
        return pd.DataFrame(columns=COLONNES)
    jours = dimanches(f"{annee}-W01", fin)
    lignes = rattacher(config, arretes).dropna(subset=["zone_id", "niveau_gravite"])
    lignes = lignes.assign(
        niveau=lignes["niveau_gravite"].map(NIVEAUX).astype("int64"),
        debut=pd.to_datetime(lignes["date_debut"]),
        fin=pd.to_datetime(lignes["date_fin"]).fillna(pd.Timestamp.max),
        signature=pd.to_datetime(lignes["date_signature"]).fillna(pd.Timestamp.min),
        zone_alerte=lignes["type_zone_alerte"] + " " + lignes["nom_zone_alerte"],
        cle=lignes["type_zone_alerte"] + ":" + lignes["nom_zone_alerte"].map(cle_nom),
    )
    croise = lignes.merge(pd.DataFrame({"dimanche": jours}), how="cross")
    croise = croise[(croise["debut"] <= croise["dimanche"]) & (croise["dimanche"] <= croise["fin"])]
    # arrêté le plus récent par zone d'alerte et par dimanche
    croise = croise.sort_values(["debut", "signature", "arrete_id"])
    en_vigueur = croise.groupby(["zone_id", "cle", "dimanche"]).tail(1)
    maxi = en_vigueur.groupby(["zone_id", "dimanche"])["niveau"].transform("max")
    au_max = en_vigueur[en_vigueur["niveau"] == maxi]
    par_zone = au_max.groupby(["zone_id", "dimanche"]).agg(
        niveau=("niveau", "first"),
        zones_alerte=("zone_alerte", lambda s: ", ".join(sorted(set(s)))),
    )
    grille = pd.MultiIndex.from_product([zones, jours], names=["zone_id", "dimanche"])
    table = par_zone.reindex(grille).reset_index()
    table["niveau"] = table["niveau"].fillna(0).astype("int64")
    table["semaine"] = [libelle_semaine(d.date()) for d in table["dimanche"]]
    table["zone_id"] = table["zone_id"].astype("string")
    table["zones_alerte"] = table["zones_alerte"].astype("string")
    return table[COLONNES].sort_values(["zone_id", "semaine"], ignore_index=True)
