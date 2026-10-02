"""Job hebdomadaire (SPEC §7.1) : `make hebdo`.

1. Ingestion incrémentale : `fenetre_reingestion_jours` derniers jours, et pour un piézomètre
   publié par lots, depuis sa dernière mesure en stock.
2. Indices de tout l'historique (quelques dizaines de secondes) : toute correction ou tout lot
   reçu se répercute sur les semaines concernées, et un calcul inchangé réécrit des fichiers
   identiques.
3. Publication : DVC, commit des `data/*.dvc`, étiquette `data-AAAA-Www` (`pipeline.publication`).
4. Rechargement de PostGIS.
5. Rapport d'exécution dans `chemins.rapports/<semaine>.md`.

Une étape en échec est consignée et n'empêche pas les suivantes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine

from pipeline import indices, ingestion, publication
from pipeline.config import Config
from pipeline.db import chargement
from pipeline.http import ClientHttp
from pipeline.indices import commun

log = logging.getLogger(__name__)


@dataclass
class RapportHebdo:
    semaine: str
    aujourd_hui: date
    ingestion: ingestion.Rapport | None = None
    indices: dict[str, pd.DataFrame] = field(default_factory=dict)
    couverture: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    publication: publication.Publication | None = None
    base: dict[str, int] = field(default_factory=dict)
    echecs: list[str] = field(default_factory=list)  # étapes en échec

    @property
    def statut(self) -> str:
        if self.echecs:
            return "échec"
        partiel = (self.ingestion and self.ingestion.erreurs) or (
            self.publication and self.publication.erreurs
        )
        return "partiel" if partiel else "ok"


def _lire_recent(config: Config, source: str, depuis: date) -> pd.DataFrame:
    """Observations d'une source datées de `depuis` ou après (fichiers des années concernées)."""
    s = ingestion.STOCKAGE[source]
    fichiers = sorted(ingestion.dossier_brut(config, source).glob(f"{s.prefixe}_*.parquet"))
    tables = [pd.read_parquet(f) for f in fichiers if int(f.stem.rsplit("_", 1)[1]) >= depuis.year]
    if not tables:
        return pd.DataFrame()
    table = pd.concat(tables, ignore_index=True)
    return table[pd.to_datetime(table[s.colonne_date]) >= pd.Timestamp(depuis)]


def controler(config: Config, depuis: date) -> list[str]:
    """Valeurs invraisemblables parmi les observations réingérées (sans effet sur les données)."""
    seuils = config.projet.hebdo.controles
    anomalies = []
    debits = _lire_recent(config, "hydro", depuis)
    if not debits.empty and (n := int((debits["qmj_ls"] < 0).sum())):
        anomalies.append(f"hydro : {n} débit(s) négatif(s)")
    pluie = _lire_recent(config, "meteo", depuis)
    if not pluie.empty:
        hors = pluie[(pluie["precip_mm"] < 0) | (pluie["precip_mm"] > seuils.pluie_max_mm_jour)]
        if len(hors):
            anomalies.append(
                f"meteo : {len(hors)} pluie(s) journalière(s) hors de [0, "
                f"{seuils.pluie_max_mm_jour:g}] mm (maille {hors['maille_id'].iloc[0]}, "
                f"{hors['date'].iloc[0]})"
            )
    retenues = _lire_recent(config, "retenues", depuis)
    if not retenues.empty:
        taux = retenues["volume_m3"] / retenues["capacite_m3"]
        if n := int((taux > seuils.remplissage_max).sum()):
            limite = f"{seuils.remplissage_max * 100:g} %"
            anomalies.append(f"retenues : {n} remplissage(s) au-delà de {limite}")
    return anomalies


def couverture(config: Config, semaine: str, tables: dict[str, pd.DataFrame]) -> list[str]:
    """Ce dont dispose le calcul de la semaine : dernière pluie, stations retenues."""
    dimanche = commun.dimanche(semaine)
    lignes = []
    pluie = _lire_recent(config, "meteo", dimanche - timedelta(days=7))
    derniere = max(pluie["date"]) if not pluie.empty else None
    complete = derniere is not None and derniere >= dimanche
    manque = "" if complete else " : **pluie du dimanche manquante**"
    lignes.append(f"pluie (SIM) jusqu'au {derniere or '—'}{manque}")
    station = tables["indice_station"]
    station = station[station["semaine"] == semaine]
    piezo = station[station["indice"] == "ips"]
    lignes.append(
        f"piézomètres : {int(piezo['dans_composite'].sum())} au composite sur {len(piezo)} "
        f"avec IPS "
        f"(mesure de moins de {config.projet.indices.ips.fraicheur_max_jours} jours)"
    )
    n_debit = int((station["indice"] == "debit").sum())
    lignes.append(f"stations hydrométriques avec Q7 du dimanche : {n_debit}")
    return lignes


def _resume(rapport: RapportHebdo) -> str:
    """Quelques lignes pour le commit et l'étiquette."""
    composites = rapport.indices.get("composite_zone", pd.DataFrame())
    if len(composites):
        composites = composites[composites["semaine"] == rapport.semaine]
    semaine = composites
    classes = semaine["classe"].value_counts().sort_index() if len(semaine) else pd.Series()
    lignes = [f"Job hebdomadaire du {rapport.aujourd_hui}, semaine {rapport.semaine}."]
    if len(classes):
        repartition = ", ".join(f"classe {c} : {n}" for c, n in classes.items())
        lignes.append(f"Composite : {len(semaine)} zones ({repartition}).")
    if rapport.ingestion and rapport.ingestion.erreurs:
        lignes.append(f"Ingestion : {len(rapport.ingestion.erreurs)} erreur(s).")
    return "\n".join(lignes)


def executer(
    config: Config,
    client: ClientHttp,
    aujourd_hui: date,
    racine: Path,
    moteur: Callable[[], Engine] | None,
    publier: bool = True,
    lancer: publication.Executer = publication.executer,
) -> RapportHebdo:
    """Job complet pour la dernière semaine complète ; `moteur` None : pas de rechargement."""
    rapport = RapportHebdo(commun.derniere_semaine_complete(aujourd_hui), aujourd_hui)
    depuis = aujourd_hui - timedelta(days=config.projet.ingestion.fenetre_reingestion_jours)

    try:
        rapport.ingestion = ingestion.ingerer(config, client, aujourd_hui, depuis)
        rapport.anomalies = controler(config, depuis)
    except Exception as exc:
        log.exception("ingestion en échec")
        rapport.echecs.append(f"ingestion : {exc}")

    try:
        debut = f"{config.projet.indices.historique_debut}-W01"
        rapport.indices = indices.calculer(config, debut, rapport.semaine)
        rapport.couverture = couverture(config, rapport.semaine, rapport.indices)
    except Exception as exc:
        log.exception("indices en échec")
        rapport.echecs.append(f"indices : {exc}")

    if publier and not rapport.echecs:
        rapport.publication = publication.publier(
            config, rapport.semaine, _resume(rapport), racine, lancer
        )
    if moteur is not None:
        try:
            rapport.base = chargement.reconstruire(config, moteur())
        except Exception as exc:
            log.exception("rechargement de PostGIS en échec")
            rapport.echecs.append(f"PostGIS : {exc}")
    return rapport


def _tableau_composite(config: Config, rapport: RapportHebdo) -> list[str]:
    composites = rapport.indices.get("composite_zone")
    if composites is None or composites.empty:
        return ["Aucun composite calculé."]
    semaine = composites[composites["semaine"] == rapport.semaine].set_index("zone_id")
    libelles = {c.classe: c.libelle for c in config.classes.classes}
    lignes = ["| Zone | Composite | Classe | Composantes manquantes |", "|---|---|---|---|"]
    for zone in config.zonage.zones:
        if zone.zone_id not in semaine.index:
            lignes.append(f"| {zone.libelle} | — | — | toutes |")
            continue
        ligne = semaine.loc[zone.zone_id]
        detail = json.loads(str(ligne["detail"]))
        manquantes = ", ".join(detail["manquantes"]) or "—"
        classe = int(str(semaine.at[zone.zone_id, "classe"]))
        lignes.append(
            f"| {zone.libelle} | {ligne['valeur']:.2f} | {classe} ({libelles[classe]}) "
            f"| {manquantes} |"
        )
    return lignes


def rediger(config: Config, rapport: RapportHebdo) -> str:
    """Rapport Markdown de l'exécution."""
    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M")
    texte = [f"# Job hebdomadaire — semaine {rapport.semaine}", "",
             f"Exécuté le {horodatage}. Statut : **{rapport.statut}**.", ""]  # fmt: skip
    if rapport.echecs:
        texte += ["## Étapes en échec", "", *[f"- {e}" for e in rapport.echecs], ""]

    texte += ["## Ingestion", ""]
    if rapport.ingestion:
        texte += ["| Source | Valeurs relues | Fichiers |", "|---|---|---|"]
        for source, n in rapport.ingestion.lignes.items():
            texte.append(f"| {source} | {n} | {len(rapport.ingestion.fichiers.get(source, ()))} |")
        erreurs = rapport.ingestion.erreurs
        texte += ["", f"{len(erreurs)} station(s) ou source(s) en échec."]
        texte += [f"- {e}" for e in erreurs]
    texte += ["", "## Anomalies de valeur", ""]
    texte += [f"- {a}" for a in rapport.anomalies] or ["Aucune."]
    texte += ["", "## Données de la semaine", "", *[f"- {c}" for c in rapport.couverture], ""]
    texte += ["## Indice composite", "", *_tableau_composite(config, rapport), ""]

    texte += ["## Publication", ""]
    if rapport.publication is None:
        texte.append("Non demandée." if not rapport.echecs else "Non faite (étape en échec).")
    else:
        texte += [f"- {m}" for m in rapport.publication.messages]
        texte += [f"- **{e}**" for e in rapport.publication.erreurs]
    texte += ["", "## PostGIS", ""]
    texte += [f"- {t} : {n} lignes" for t, n in rapport.base.items()] or ["Non rechargé."]
    return "\n".join(texte) + "\n"


def ecrire_rapport(config: Config, rapport: RapportHebdo) -> Path:
    chemin = config.projet.chemins.rapports / f"{rapport.semaine}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(rediger(config, rapport), encoding="utf-8")
    return chemin
