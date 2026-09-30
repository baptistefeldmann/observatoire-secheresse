"""Point d'entrée du pipeline : `python -m pipeline <commande>` (appelé par le Makefile)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from pipeline import ingestion, referentiels
from pipeline.config import Config, charger_config
from pipeline.http import ClientHttp


def _afficher_config(config: Config) -> None:
    t = config.projet.territoire
    print(f"Territoire : {t.nom} ({t.code_departement}), slug « {t.slug} »")
    print(f"CRS        : {config.projet.crs}")
    ref = config.projet.periode_reference.hydro_meteo
    print(f"Référence  : {ref.debut}-{ref.fin} (minimum {ref.annees_min} ans)")
    fraicheur = config.projet.indices.ips.fraicheur_max_jours
    print(f"IPS        : station exclue du composite au-delà de {fraicheur} j sans mesure")
    print("Zones      :")
    for zone in config.zonage.zones:
        poids = ", ".join(f"{k}={v:.2f}" for k, v in zone.ponderations.items())
        print(f"  - {zone.zone_id:<24} {zone.libelle} [{poids}]")
    print("Raccordements hydro :")
    for r in config.stations.raccordements_hydro:
        print(f"  - {r.site:<16} {r.libelle} [{' > '.join(r.stations)}]")


def _referentiels(config: Config) -> None:
    client = ClientHttp(config.sources.http)
    for nom, chemin in referentiels.construire(config, client, date.today()).items():
        print(f"{nom:<16} -> {chemin}")


COMMANDES_A_VENIR = {
    "reference": "calcul des normales",
    "hebdo": "job hebdomadaire",
    "db-rebuild": "reconstruction de PostGIS depuis data/",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="Observatoire de la sécheresse")
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("config", help="valide et affiche la configuration")
    sous.add_parser("referentiels", help="communes, mailles SIM et stations (data/referentiels/)")
    sous.add_parser("ingest", help="ingestion complète : référentiels puis sources")
    for nom, aide in COMMANDES_A_VENIR.items():
        sous.add_parser(nom, help=aide)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s"
    )
    config = charger_config()
    if args.commande == "config":
        _afficher_config(config)
        return 0
    if args.commande == "referentiels":
        _referentiels(config)
        return 0
    if args.commande == "ingest":
        _referentiels(config)
        client = ClientHttp(config.sources.http)
        for source, chemins in ingestion.ingerer(config, client, date.today()).items():
            print(f"{source:<16} -> {len(chemins)} fichier(s) dans {chemins[0].parent}")
        print("Autres sources (piézo, débits, ONDE, SIM) : étape 2 en cours.", file=sys.stderr)
        return 0

    print(f"« {args.commande} » n'est pas encore implémenté.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
