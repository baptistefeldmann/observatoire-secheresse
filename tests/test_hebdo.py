"""Job hebdomadaire : fenêtre d'ingestion des piézomètres, publication Git/DVC sur un dépôt
jetable (sans réseau), rapport d'exécution."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest

from pipeline import ingestion, publication, reference, referentiels, run_hebdo
from pipeline.config import Config
from pipeline.http import ClientHttp
from tests.conftest import repondre

AUJOURD_HUI = date(2026, 9, 30)
SEMAINE = "2026-W39"


# --- Ingestion des piézomètres publiés par lots --------------------------------------------


def test_piezo_relu_depuis_sa_derniere_mesure(
    config: Config, fabrique_client: Callable[..., ClientHttp]
) -> None:
    debuts: dict[str, str | None] = {}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/niveaux_nappes/chroniques"):
            debuts[requete.url.params["code_bss"]] = requete.url.params.get("date_debut_mesure")
        return repondre(requete)

    client = fabrique_client(gestionnaire)
    referentiels.construire(config, client, AUJOURD_HUI)
    # dernière mesure en stock en mars : le lot publié depuis doit être relu en entier
    dossier = ingestion.dossier_brut(config, "piezo")
    dossier.mkdir(parents=True)
    pd.DataFrame(
        {"station_id": ["piezo:05068X0028/SP010"], "date": [date(2026, 3, 15)]}
    ).to_parquet(dossier / "chroniques_2026.parquet")
    ingestion.ingerer(config, client, AUJOURD_HUI, date(2026, 7, 2))

    assert debuts.pop("05068X0028/SP010") == "2026-03-15"
    assert debuts and set(debuts.values()) == {"2026-07-02"}  # stations sans stock : 90 jours


# --- Publication -------------------------------------------------------------------------


def _git(racine: Path, *args: str) -> str:
    return publication.executer(["git", *args], racine)


@pytest.fixture
def depot(tmp_path: Path) -> Path:
    """Dépôt Git sur `main` avec data/raw.dvc et data/indices.dvc, et un remote nu local."""
    distant = tmp_path / "distant.git"
    racine = tmp_path / "depot"
    subprocess.run(["git", "init", "--quiet", "--bare", str(distant)], check=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(racine)], check=True)
    for cle, valeur in (("user.name", "Test"), ("user.email", "test@example.org")):
        _git(racine, "config", cle, valeur)
    (racine / "data").mkdir()
    for nom in ("raw.dvc", "indices.dvc"):
        (racine / "data" / nom).write_text("md5: 0\n")
    (racine / "README.md").write_text("version 1\n")
    _git(racine, "add", ".")
    _git(racine, "commit", "--quiet", "-m", "initial")
    _git(racine, "remote", "add", "origin", str(distant))
    _git(racine, "push", "--quiet", "origin", "main")
    return racine


@pytest.fixture
def config_depot(config: Config, depot: Path) -> Config:
    chemins = config.projet.chemins.model_copy(update={"data": depot / "data"})
    return config.model_copy(
        update={"projet": config.projet.model_copy(update={"chemins": chemins})}
    )


def _lanceur(depot: Path, empreinte: str | None, echec_dvc: bool = False) -> publication.Executer:
    """DVC simulé (`dvc add` réécrit data/indices.dvc si `empreinte`), Git réel."""

    def lancer(commande: list[str], racine: Path) -> str:
        if commande[0] == sys.executable:  # python -m dvc ...
            if echec_dvc:
                raise RuntimeError("dvc push : remote injoignable")
            if commande[3] == "add" and empreinte is not None:
                (depot / "data" / "indices.dvc").write_text(f"md5: {empreinte}\n")
            return ""
        return publication.executer(commande, racine)

    return lancer


def test_publication_commit_etiquette_et_envoi(config_depot: Config, depot: Path) -> None:
    # travail en cours de l'utilisateur, indexé : il ne doit pas entrer dans le commit
    (depot / "README.md").write_text("version 2\n")
    _git(depot, "add", "README.md")

    resultat = publication.publier(config_depot, SEMAINE, "résumé", depot, _lanceur(depot, "1"))

    assert not resultat.erreurs and resultat.commit and resultat.etiquette == "data-2026-W39"
    assert _git(depot, "show", "--name-only", "--format=", "HEAD") == "data/indices.dvc"
    assert _git(depot, "log", "-1", "--format=%s") == "Données 2026-W39"
    assert _git(depot, "diff", "--cached", "--name-only") == "README.md"  # toujours indexé
    distant = depot.parent / "distant.git"
    assert _git(distant, "rev-parse", "main") == _git(depot, "rev-parse", "HEAD")
    assert _git(distant, "rev-parse", "data-2026-W39^{commit}") == _git(depot, "rev-parse", "HEAD")


def test_publication_idempotente(config_depot: Config, depot: Path) -> None:
    publication.publier(config_depot, SEMAINE, "résumé", depot, _lanceur(depot, "1"))
    tete = _git(depot, "rev-parse", "HEAD")
    etiquette = _git(depot, "rev-parse", "data-2026-W39")

    resultat = publication.publier(config_depot, SEMAINE, "résumé", depot, _lanceur(depot, "1"))

    assert resultat.commit is None and not resultat.erreurs
    assert "données inchangées : pas de commit" in resultat.messages
    assert _git(depot, "rev-parse", "HEAD") == tete
    assert _git(depot, "rev-parse", "data-2026-W39") == etiquette  # étiquette non recréée


def test_publication_apres_correction_deplace_l_etiquette(
    config_depot: Config, depot: Path
) -> None:
    publication.publier(config_depot, SEMAINE, "résumé", depot, _lanceur(depot, "1"))
    resultat = publication.publier(config_depot, SEMAINE, "résumé", depot, _lanceur(depot, "2"))
    assert resultat.commit and "étiquette data-2026-W39 déplacée" in resultat.messages
    distant = depot.parent / "distant.git"
    assert _git(distant, "rev-parse", "data-2026-W39^{commit}") == _git(depot, "rev-parse", "HEAD")


def test_publication_hors_de_la_branche(config_depot: Config, depot: Path) -> None:
    _git(depot, "switch", "--quiet", "-c", "essai")
    resultat = publication.publier(config_depot, SEMAINE, "résumé", depot, _lanceur(depot, "1"))
    assert resultat.commit is None and "branche « essai »" in resultat.erreurs[0]
    assert _git(depot, "log", "-1", "--format=%s") == "initial"


def test_publication_sans_dvc_pas_de_commit(config_depot: Config, depot: Path) -> None:
    lancer = _lanceur(depot, "1", echec_dvc=True)
    resultat = publication.publier(config_depot, SEMAINE, "résumé", depot, lancer)
    assert resultat.erreurs[0].startswith("DVC") and resultat.commit is None
    assert _git(depot, "tag", "--list") == ""


# --- Contrôles et job complet ------------------------------------------------------------


def test_controles_de_vraisemblance(config: Config) -> None:
    for source, prefixe, table in [
        ("hydro", "qmj", {"station_id": ["hydro:Q"] * 2, "qmj_ls": [-1.0, 5.0]}),
        ("meteo", "sim", {"maille_id": [1, 2], "precip_mm": [250.0, 3.0]}),
        ("retenues", "retenues",
         {"station_id": ["retenue:R"] * 2, "volume_m3": [120.0, 50.0], "capacite_m3": 100.0}),
    ]:  # fmt: skip
        dossier = ingestion.dossier_brut(config, source)
        dossier.mkdir(parents=True)
        donnees = pd.DataFrame(table).assign(date=[date(2026, 9, 20), date(2026, 9, 21)])
        donnees.to_parquet(dossier / f"{prefixe}_2026.parquet")
    anomalies = run_hebdo.controler(config, date(2026, 7, 2))
    assert len(anomalies) == 3
    assert anomalies[0] == "hydro : 1 débit(s) négatif(s)"
    assert "maille 1" in anomalies[1] and "105 %" in anomalies[2]
    assert run_hebdo.controler(config, date(2026, 9, 22)) == []  # hors de la fenêtre


def test_job_complet_sans_publication(config: Config, client: ClientHttp, tmp_path: Path) -> None:
    # fixtures : quelques jours de septembre 2026, donc normales vides et pas d'indice
    referentiels.construire(config, client, AUJOURD_HUI)
    ingestion.ingerer(config, client, AUJOURD_HUI, date(2026, 9, 1))
    reference.calculer(config)

    rapport = run_hebdo.executer(config, client, AUJOURD_HUI, tmp_path, None, publier=False)

    assert rapport.semaine == SEMAINE and not rapport.echecs
    assert rapport.statut == "partiel"  # stations sans réponse enregistrée
    texte = run_hebdo.ecrire_rapport(config, rapport).read_text(encoding="utf-8")
    assert texte.startswith("# Job hebdomadaire — semaine 2026-W39")
    assert "Statut : **partiel**" in texte and "Non demandée." in texte
    assert "pluie (SIM) jusqu'au 2026-09-27" in texte  # dimanche couvert
    assert (config.projet.chemins.rapports / "2026-W39.md").is_file()
