"""Point d'entrée du pipeline : `python -m pipeline <commande>` (appelé par le Makefile)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from pipeline import indices, ingestion, reference, referentiels, run_hebdo
from pipeline.config import Config, charger_config
from pipeline.db import chargement
from pipeline.db.connexion import moteur
from pipeline.http import ClientHttp
from pipeline.indices.commun import derniere_semaine_complete


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description="Observatoire de la sécheresse")
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("config", help="valide et affiche la configuration")
    sous.add_parser("referentiels", help="communes, mailles SIM et stations (data/referentiels/)")
    sous.add_parser("ingest", help="ingestion complète : référentiels puis sources")
    sous.add_parser("db-rebuild", help="reconstruction de PostGIS depuis data/")
    sous.add_parser("projet-qgis", help="charge le projet QGIS de qgis/ dans PostGIS")
    sous.add_parser("reference", help="calcul des normales -> data/normales/")
    calcul = sous.add_parser("indices", help="indices hebdomadaires -> data/indices/")
    calcul.add_argument("--debut", help="première semaine AAAA-Www (défaut : historique_debut)")
    calcul.add_argument("--fin", help="dernière semaine AAAA-Www (défaut : dernière complète)")
    hebdo = sous.add_parser("hebdo", help="job hebdomadaire (dernière semaine complète)")
    hebdo.add_argument(
        "--sans-publication", action="store_true", help="ni DVC, ni commit, ni étiquette"
    )
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
        rapport = ingestion.ingerer(config, ClientHttp(config.sources.http), date.today())
        for source, n in rapport.lignes.items():
            print(
                f"{source:<16} {n:>9} valeurs, {len(rapport.fichiers.get(source, ()))} fichier(s)"
            )
        for erreur in rapport.erreurs:
            print(f"ERREUR {erreur}", file=sys.stderr)
        return 1 if rapport.erreurs else 0
    if args.commande == "reference":
        for nom, chemin in reference.calculer(config).items():
            print(f"{nom:<16} -> {chemin}")
        return 0
    if args.commande == "indices":
        debut = args.debut or f"{config.projet.indices.historique_debut}-W01"
        fin = args.fin or derniere_semaine_complete(date.today())
        for nom, calcule in indices.calculer(config, debut, fin).items():
            print(f"{nom:<16} {len(calcule):>9} lignes ({debut} à {fin})")
        return 0
    if args.commande == "projet-qgis":
        if not chargement.charger_projet_qgis(config, moteur()):
            print(f"{chargement.projet_qgis(config)} absent : lancer make qgis", file=sys.stderr)
            return 1
        print(f"{chargement.projet_qgis(config)} -> {chargement.PROJETS_QGIS}")
        return 0
    if args.commande == "db-rebuild":
        for table, n in chargement.reconstruire(config, moteur()).items():
            print(f"{table:<22} {n:>9} lignes")
        return 0

    if args.commande == "hebdo":
        job = run_hebdo.executer(
            config, ClientHttp(config.sources.http), date.today(), Path.cwd(), moteur,
            publier=not args.sans_publication,
        )  # fmt: skip
        chemin = run_hebdo.ecrire_rapport(config, job)
        print(f"Semaine {job.semaine} : {job.statut}. Rapport : {chemin}")
        for echec in job.echecs:
            print(f"ÉCHEC {echec}", file=sys.stderr)
        return 1 if job.echecs else 0

    print(f"« {args.commande} » inconnue.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
