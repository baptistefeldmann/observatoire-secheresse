from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd
import pytest

from pipeline import ingestion, referentiels
from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.sources import meteo, piezo

AUJOURD_HUI = date(2026, 9, 30)
DEPUIS = date(2026, 9, 1)


@pytest.fixture
def rapport(config: Config, client: ClientHttp) -> ingestion.Rapport:
    referentiels.construire(config, client, AUJOURD_HUI)
    return ingestion.ingerer(config, client, AUJOURD_HUI, DEPUIS)


def _lire(config: Config, source: str, fichier: str) -> pd.DataFrame:
    return pd.read_parquet(ingestion.dossier_brut(config, source) / fichier)


def test_toutes_les_sources_ecrites(config: Config, rapport: ingestion.Rapport) -> None:
    assert rapport.lignes["piezo"] == 9
    assert rapport.lignes["hydro"] == 2
    # 30 observations ONDE, mais seules 3 stations sur 30 sont dans le référentiel des fixtures
    assert rapport.lignes["onde"] == 3
    for source, fichier in [
        ("piezo", "chroniques_2026.parquet"),
        ("hydro", "qmj_2026.parquet"),
        ("onde", "observations_2026.parquet"),
        ("meteo", "sim_2026.parquet"),
    ]:
        assert (ingestion.dossier_brut(config, source) / fichier).exists()
    # pas de retenue sur l'île de Noirmoutier : aucun fichier, aucune erreur
    assert rapport.lignes["retenues"] == 0 and "retenues" not in rapport.fichiers


def test_stations_en_echec_signalees_sans_bloquer(rapport: ingestion.Rapport) -> None:
    # 2 piézomètres et 2 stations hydrométriques des fixtures n'ont pas de réponse enregistrée
    assert len(rapport.erreurs) == 4
    assert sum(e.startswith("piezo:") for e in rapport.erreurs) == 2
    assert sum(e.startswith("hydro:") for e in rapport.erreurs) == 2


def test_piezo_profondeur_depuis_l_altitude(config: Config, rapport: ingestion.Rapport) -> None:
    obs = _lire(config, "piezo", "chroniques_2026.parquet")
    assert (obs["profondeur"] == 2.25 - obs["niveau_ngf"]).all()  # altitude du repère : 2,25 m
    assert set(obs["station_id"]) == {"piezo:05068X0028/SP010"}


def test_onde_type_de_campagne(config: Config, rapport: ingestion.Rapport) -> None:
    obs = _lire(config, "onde", "observations_2026.parquet")
    assert obs["type_campagne"].notna().all()
    assert set(obs["modalite"]) <= {"1", "1a", "1f", "2", "3"}


def test_meteo_fusion_annuel_et_recent(config: Config, rapport: ingestion.Rapport) -> None:
    obs = _lire(config, "meteo", "sim_2026.parquet")
    mailles = gpd.read_parquet(referentiels.dossier(config) / "mailles_safran.parquet")
    # 3 jours du fichier annuel + 2 du fichier récent, dont 1 en commun : 4 jours par maille
    assert set(obs["date"]) == {date(2026, 9, d) for d in (24, 25, 26, 27)}
    assert len(obs) == 4 * len(mailles)
    assert obs.groupby("maille_id").size().eq(4).all()


def test_meteo_coordonnees_grille_retrouvees(config: Config, client: ClientHttp) -> None:
    referentiels.construire(config, client, AUJOURD_HUI)
    mailles = gpd.read_parquet(referentiels.dossier(config) / "mailles_safran.parquet")
    grille = meteo.grille(config, client)[["maille_id", "lambx", "lamby"]]
    retrouvees = meteo.coordonnees_grille(config, mailles).merge(grille, on="maille_id")
    assert (retrouvees["LAMBX"] == retrouvees["lambx"]).all()
    assert (retrouvees["LAMBY"] == retrouvees["lamby"]).all()


def test_ingestion_idempotente(
    config: Config, client: ClientHttp, rapport: ingestion.Rapport
) -> None:
    fichiers = sorted(p for chemins in rapport.fichiers.values() for p in chemins)
    avant = {p: p.read_bytes() for p in fichiers}
    ingestion.ingerer(config, client, AUJOURD_HUI, DEPUIS)
    assert {p: p.read_bytes() for p in fichiers} == avant


def test_chronique_longue_decoupee(
    config: Config, fabrique_client: Callable[..., ClientHttp]
) -> None:
    periodes: list[tuple[str | None, str | None]] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        debut = requete.url.params.get("date_debut_mesure")
        fin = requete.url.params.get("date_fin_mesure")
        periodes.append((debut, fin))
        if debut is None:  # période complète : trop de mesures
            donnees = [{"date_mesure": "1990-01-01", "niveau_nappe_eau": 1.0, "statut": "x"}]
            return httpx.Response(200, json={"count": 25000, "data": donnees})
        donnees = [{"date_mesure": debut, "niveau_nappe_eau": 1.0, "statut": "x"}]
        return httpx.Response(200, json={"count": 12500, "data": donnees})

    mesures = piezo._chronique(
        fabrique_client(gestionnaire), "https://api.test/c", "X", None, AUJOURD_HUI
    )
    assert len(mesures) == 2
    assert periodes[1][0] == "1990-01-01" and periodes[2][1] == AUJOURD_HUI.isoformat()
    assert date.fromisoformat(periodes[1][1] or "") < date.fromisoformat(periodes[2][0] or "")


def test_fichiers_hors_depot(config: Config, rapport: ingestion.Rapport, tmp_path: Path) -> None:
    # le dossier data/ des tests est temporaire : rien n'est écrit dans le dépôt
    assert str(ingestion.dossier_brut(config, "piezo")).startswith(str(tmp_path))
