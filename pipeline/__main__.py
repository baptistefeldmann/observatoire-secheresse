"""Point d'entrée du pipeline : `python -m pipeline <commande>` (appelé par le Makefile)."""

from __future__ import annotations

import argparse
import sys

from pipeline.config import Config, charger_config


def _afficher_config(config: Config) -> None:
    t = config.projet.territoire
    print(f"Territoire : {t.nom} ({t.code_departement}), slug « {t.slug} »")
    print(f"CRS        : {config.projet.crs}")
    ref = config.projet.periode_reference.hydro_meteo
    print(f"Référence  : {ref.debut}-{ref.fin} (minimum {ref.annees_min} ans)")
    fraicheur = config.projet.indices.ips.fraicheur_max_jours
    print(f"IPS        : station exclue du composite au-delà de {fraicheur} j sans mesure")
    print("Zones      :")
    for zone in config.zones:
        poids = ", ".join(f"{k}={v:.2f}" for k, v in zone.ponderations.items())
        print(f"  - {zone.zone_id:<16} {zone.libelle} [{poids}]")
    print("Raccordements hydro :")
    for r in config.stations.raccordements_hydro:
        print(f"  - {r.site:<16} {r.libelle} [{' > '.join(r.stations)}]")


COMMANDES_A_VENIR = {
    "ingest": "ingestion complète de l'historique",
    "reference": "calcul des normales",
    "hebdo": "job hebdomadaire",
    "db-rebuild": "reconstruction de PostGIS depuis data/",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="Observatoire de la sécheresse")
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("config", help="valide et affiche la configuration")
    for nom, aide in COMMANDES_A_VENIR.items():
        sous.add_parser(nom, help=aide)
    args = parser.parse_args(argv)

    config = charger_config()
    if args.commande == "config":
        _afficher_config(config)
        return 0

    print(f"« {args.commande} » n'est pas encore implémenté.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
