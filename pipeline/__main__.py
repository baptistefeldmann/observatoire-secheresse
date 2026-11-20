"""Point d'entrée du pipeline : `python -m pipeline <commande>` (appelé par le Makefile)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from pipeline import indices, ingestion, reference, referentiels, run_hebdo, validation
from pipeline.config import Config, charger_config
from pipeline.db import chargement
from pipeline.db.connexion import moteur
from pipeline.http import ClientHttp
from pipeline.indices.commun import derniere_semaine_complete


def _nb_classes(config: Config) -> int:
    ocs = config.nomenclature_ocs
    return len(ocs.foret.classes) + len(ocs.cultures.classes)


def _afficher_config(config: Config) -> None:
    t = config.projet.territoire
    print(f"Territoire : {t.nom} ({t.code_departement}), slug « {t.slug} »")
    print(f"CRS        : {config.projet.crs}")
    ref = config.projet.periode_reference.hydro_meteo
    print(f"Référence  : {ref.debut}-{ref.fin} (minimum {ref.annees_min} ans)")
    fraicheur = config.projet.indices.ips.fraicheur_max_jours
    print(f"IPS        : station exclue du composite au-delà de {fraicheur} j sans mesure")
    sat = config.projet.satellite
    s2 = config.projet.periode_reference.sentinel2
    s1 = config.projet.periode_reference.sentinel1
    print(
        f"Satellite  : {sat.version_methodo}, référence NDVI {s2.debut}-{s2.fin}, "
        f"crue {s1.debut}-{s1.fin} (orbite {sat.crue.orbite_publiee}, "
        f"{len(sat.crue.marais)} marais), {_nb_classes(config)} classes"
    )
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


def _classes(config: Config, annees: list[int] | None, actualiser: bool) -> None:
    from pipeline.raster import classes  # extra `raster` : importé seulement ici

    surface_pixel_ha = config.sources.sentinel2.resolution_m**2 / 1e4
    ocs = config.nomenclature_ocs
    noms = {c.code: c.nom for c in ocs.foret.classes}
    noms |= {c.code: c.nom for c in ocs.cultures.classes}
    noms[ocs.codes_speciaux.hors_classes] = "hors classes"
    noms[ocs.codes_speciaux.nodata] = "hors emprise"
    for annee, bilan in classes.construire(
        config, ClientHttp(config.sources.http), annees, actualiser
    ).items():
        print(f"{classes.chemin_classes(config, annee)} (carte d'arbres : {bilan.carte_arbres})")
        for code, nombre in sorted(bilan.pixels.items()):
            print(f"  {code:>3} {noms.get(code, '-'):<34} {nombre * surface_pixel_ha:>10.0f} ha")


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
    classes = sous.add_parser("classes", help="[V2] classes mises à la grille -> rasters/classes/")
    classes.add_argument(
        "--annee", type=int, action="append", help="année du RPG (défaut : toutes)"
    )
    classes.add_argument(
        "--actualiser", action="store_true", help="relit BD Forêt, RPG et carte d'arbres"
    )
    crue = sous.add_parser(
        "crue", help="[V2] surface de crue Sentinel-1 par passage -> data/satellite/"
    )
    crue.add_argument("--marais", action="append", help="identifiant d'un marais (défaut : tous)")
    crue.add_argument(
        "--annee", type=int, action="append", help="année à calculer (défaut : toutes)"
    )
    mois = sous.add_parser("crue-mois", help="[V2] crue par mois et tendance d'hiver (sans réseau)")
    mois.add_argument("--pct-valides-min", type=float, default=0.0, help="part observable minimale")
    comp = sous.add_parser(
        "composites", help="[V2] NDVI et NDMI mensuels de Sentinel-2 -> rasters/mensuel/"
    )
    comp.add_argument("--annee", type=int, action="append", help="année (défaut : toutes)")
    comp.add_argument("--mois", type=int, action="append", help="mois 1 à 12 (défaut : tous)")
    comp.add_argument("--actualiser", action="store_true", help="recalcule les mois déjà écrits")
    sous.add_parser(
        "composites-controle",
        help="[V2] rapports de qualité et contrôle de dérive des composites -> data/satellite/",
    )
    valider = sous.add_parser("validation", help="indices confrontés aux arrêtés sécheresse")
    valider.add_argument(
        "--hors-ligne", action="store_true", help="réutilise les arrêtés de data/validation/"
    )
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
    if args.commande == "classes":
        _classes(config, args.annee, args.actualiser)
        return 0
    if args.commande == "crue":
        from pipeline.raster import crue as calcul_crue  # extra `raster` : importé seulement ici

        print(calcul_crue.construire(config, date.today(), args.marais, args.annee))
        return 0
    if args.commande == "crue-mois":
        from pipeline.indices import crue as agregats_crue

        for nom, agregat in agregats_crue.calculer(config, args.pct_valides_min).items():
            print(f"{nom:<14} {len(agregat):>6} lignes")
        return 0
    if args.commande == "composites":
        from pipeline.raster import composite

        ecrits = composite.construire(config, date.today(), args.annee, args.mois, args.actualiser)
        print(f"{len(ecrits)} mois écrits dans {composite.dossier_mensuel(config)}")
        return 0
    if args.commande == "composites-controle":
        from pipeline.indices import derive

        tables = derive.calculer(config)
        for nom, agregat in tables.items():
            print(f"{nom:<22} {len(agregat):>6} lignes")
        print(derive.resume(tables))
        return 0
    if args.commande == "validation":
        client = None if args.hors_ligne else ClientHttp(config.sources.http)
        resultat = validation.executer(config, client)
        for chemin in (resultat.arretes, resultat.restrictions, resultat.rapport):
            print(chemin)
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
