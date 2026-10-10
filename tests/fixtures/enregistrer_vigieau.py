"""Fixture des arrêtés VigiEau (tests/fixtures/vigieau/) : extrait synthétique au format réel.

Colonnes et encodage du CSV « Arrêtés » du jeu data.gouv.fr 662a5e2cd71b24df5e9a0827 (zones
d'alerte en listes JSON parallèles, valeurs manquantes écrites `null`). Cas couverts : arrêté
sans zone (2011), autre département, anciens noms, chevauchement de deux arrêtés, arrêté en
vigueur sans date de fin, accents et casse, zone d'alerte non rattachée.

    uv run python tests/fixtures/enregistrer_vigieau.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

DOSSIER = Path(__file__).parent / "vigieau"
ENTETE = [
    "id", "numero", "date_debut", "date_signature", "date_fin", "statut", "departement",
    "chemin_fichier", "niveau_gravite_specifique_aep", "ressource_aep_communique", "regle_gestion",
    "arrete_cadre.id", "arrete_cadre.numero", "arrete_cadre.date_debut", "arrete_cadre.date_fin",
    "arrete_cadre.chemin_fichier", "zones_alerte.id", "zones_alerte.type", "zones_alerte.code",
    "zones_alerte.nom", "zones_alerte.niveau_gravite", "zones_alerte.id_sandre",
    "zones_alerte.communes",
]  # fmt: skip


def arrete(id_: int, debut: str, signature: str, fin: str, statut: str, dep: str,
           zones: list[tuple[str, str, str, str]]) -> dict[str, str]:  # fmt: skip
    ligne = dict.fromkeys(ENTETE, "")
    ligne |= {
        "id": str(id_), "numero": f"A-{id_}", "date_debut": debut, "date_signature": signature,
        "date_fin": fin, "statut": statut, "departement": dep,
        "niveau_gravite_specifique_aep": "null", "ressource_aep_communique": "null",
        "regle_gestion": "undefined",
    }  # fmt: skip
    if zones:
        types, codes, noms, niveaux = (list(c) for c in zip(*zones, strict=True))
        ligne |= {
            "zones_alerte.id": json.dumps(list(range(len(zones)))),
            "zones_alerte.type": json.dumps(types),
            "zones_alerte.code": json.dumps(codes),
            "zones_alerte.nom": json.dumps(noms, ensure_ascii=False),
            "zones_alerte.niveau_gravite": json.dumps(niveaux),
        }
    return ligne


ARRETES = [
    arrete(1, "2011-07-08", "2011-07-07", "2011-08-04", "abroge", "85", []),
    arrete(2, "2012-07-07", "2012-07-06", "2012-08-31", "abroge", "01",
           [("SUP", "01_1", "LAY", "crise")]),
    # chevauché à partir du 2012-08-20 par l'arrêté 4, plus récent
    arrete(3, "2012-08-04", "2012-08-03", "2012-08-31", "abroge", "85",
           [("SUP", "52_85_08", "LAY", "crise"), ("SUP", "52_85_07", "VENDEE", "alerte"),
            ("SOU", "52_85_4", "NAPPE PLAINE-BOCAGE", "vigilance")]),
    arrete(4, "2012-08-20", "2012-08-17", "2012-09-30", "abroge", "85",
           [("SUP", "52_85_08", "LAY", "alerte")]),
    arrete(5, "2026-09-14", "2026-09-11", "null", "publie", "85",
           [("SUP", "52_85_000010", "Vendée superficiel", "vigilance"),
            ("SUP", "52_85_000012", "Autize superficiel", "crise"),
            ("SUP", "52_85_000006", "COTIERS VENDEENS", "alerte_renforcee")]),
]  # fmt: skip


def main() -> None:
    DOSSIER.mkdir(exist_ok=True)
    with (DOSSIER / "arretes.csv").open("w", encoding="utf-8", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=ENTETE)
        ecrivain.writeheader()
        ecrivain.writerows(ARRETES)
    jeu = {"resources": [
        {"title": "Arrêtés 2024", "url": "https://vigieau.test/arretes-2024.csv"},
        {"title": "Arrêtés", "url": "https://vigieau.test/arretes.csv"},
    ]}  # fmt: skip
    (DOSSIER / "jeu_datagouv.json").write_text(
        json.dumps(jeu, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
