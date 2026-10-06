"""API (SPEC §8.1). Validation des paramètres sans base ; réponses sur une base PostGIS jetable
fournie par `make test-db` (variable SECHERESSE_TEST_POSTGRES_URL), ignorées sans elle."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import app as api
from pipeline import ingestion, referentiels, schema, stockage
from pipeline.config import Config
from pipeline.db import chargement
from pipeline.db.connexion import moteur
from pipeline.http import ClientHttp

URL_TEST = os.environ.get("SECHERESSE_TEST_POSTGRES_URL")
PIEZO = "piezo:05068X0028/SP010"
SEMAINE = "2026-W39"


@pytest.fixture
def client_api(config: Config) -> Iterator[TestClient]:
    api.app.dependency_overrides[api.config] = lambda: config
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_classes_depuis_la_configuration(client_api: TestClient) -> None:
    reponse = client_api.get("/classes")
    assert reponse.status_code == 200
    classes = reponse.json()["classes"]
    assert [c["classe"] for c in classes] == list(range(1, 8))
    assert classes[3] == {"classe": 4, "libelle": "Normal", "couleur": "#4daf4a"}


def test_dashboard_servi_par_l_api(client_api: TestClient) -> None:
    page = client_api.get("/dashboard/")
    assert page.status_code == 200 and "app.js" in page.text
    script = client_api.get("/dashboard/app.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]


@pytest.mark.parametrize(
    "chemin",
    [
        "/zones?semaine=2026-W54",
        "/zones?semaine=2026-39",
        "/zones/Z/series?indice=pluie",
        "/stations?source=puits",
        "/semaines/2026-W60/synthese",
        "/stations/piezo:X/series?debut=hier",
    ],
)
def test_parametres_invalides(client_api: TestClient, chemin: str) -> None:
    assert client_api.get(chemin).status_code == 422


# --- Sur une base jetable --------------------------------------------------------------------


def _indices_synthetiques(config: Config) -> None:
    """Quelques indices de la semaine pour la zone et le piézomètre des fixtures."""
    dossier = config.projet.chemins.data / "indices"
    commun = {"semaine": SEMAINE, "version_methodo": "D9"}
    tables: dict[str, tuple[dict[str, str], list[str], list[dict[str, object]]]] = {
        "indice_station": (schema.IDX_STATION, ["station_id", "semaine", "indice"], [
            {**commun, "station_id": PIEZO, "indice": "ips", "valeur": -1.5, "classe": 1,
             "periode_ref": "1991-2020", "hors_reference": False,
             "date_mesure": date(2026, 9, 25), "dans_composite": True},
        ]),
        "indice_zone": (schema.IDX_ZONE, ["zone_id", "semaine", "indice"], [
            {**commun, "zone_id": "ILE_NOIRMOUTIER", "indice": "spi_3", "valeur": -2.0,
             "classe": 1, "n_stations": None, "detail": "{}"},
        ]),
        "composite_zone": (schema.IDX_COMPOSITE, ["zone_id", "semaine"], [
            {**commun, "zone_id": "ILE_NOIRMOUTIER", "valeur": -1.7, "classe": 1,
             "detail": json.dumps({"n_composantes": 2, "partiel": False, "manquantes": []})},
        ]),
    }  # fmt: skip
    for nom, (colonnes, cles, lignes) in tables.items():
        table = schema.normaliser_observations(pd.DataFrame(lignes), colonnes, cles)
        stockage.ecrire_parquet(table, dossier / f"{nom}_2026.parquet")
    enveloppe = pd.DataFrame(
        [{"station_id": PIEZO, "indice": "ips", "pas": "mois", "periode": 9, "minimum": 0.5,
          "mediane": 1.0, "maximum": 1.5, "n_annees": 20, "periode_ref": "1991-2020",
          "hors_reference": False}]
    )  # fmt: skip
    normales = config.projet.chemins.data / "normales"
    stockage.ecrire_parquet(enveloppe, normales / "enveloppe_station.parquet")


@pytest.fixture
def client_base(config: Config, client: ClientHttp, client_api: TestClient) -> TestClient:
    if URL_TEST is None:
        pytest.skip("SECHERESSE_TEST_POSTGRES_URL non définie")
    referentiels.construire(config, client, date(2026, 9, 30))
    ingestion.ingerer(config, client, date(2026, 9, 30), date(2026, 9, 1))
    _indices_synthetiques(config)
    base = moteur(URL_TEST)
    chargement.reconstruire(config, base)
    api.app.dependency_overrides[api.moteur] = lambda: base
    return client_api


def test_zones_en_geojson_wgs84(client_base: TestClient) -> None:
    collection = client_base.get("/zones").json()
    assert collection["type"] == "FeatureCollection" and len(collection["features"]) == 1
    zone = collection["features"][0]
    assert zone["properties"]["semaine"] == SEMAINE  # dernière semaine par défaut
    assert (zone["properties"]["classe"], zone["properties"]["n_composantes"]) == (1, 2)
    longitude, latitude = zone["geometry"]["coordinates"][0][0][0]
    assert -3 < longitude < -1 and 46 < latitude < 48  # degrés, et non Lambert 93


def test_zone_sans_indice_cette_semaine(client_base: TestClient) -> None:
    zone = client_base.get("/zones?semaine=2020-W10").json()["features"][0]
    assert zone["properties"]["valeur"] is None and zone["properties"]["zone_id"]


def test_series_de_zone(client_base: TestClient) -> None:
    composite = client_base.get("/zones/ILE_NOIRMOUTIER/series").json()
    assert [p["semaine"] for p in composite["points"]] == [SEMAINE]
    spi = client_base.get("/zones/ILE_NOIRMOUTIER/series?indice=spi_3").json()
    assert spi["points"][0]["valeur"] == -2.0
    assert client_base.get("/zones/AILLEURS/series").status_code == 404


def test_stations_et_serie(client_base: TestClient) -> None:
    piezos = client_base.get("/stations?source=piezo").json()["features"]
    avec_indice = next(f for f in piezos if f["properties"]["station_id"] == PIEZO)
    assert avec_indice["properties"]["classe"] == 1
    serie = client_base.get(f"/stations/{PIEZO}/series").json()
    assert serie["chronique"]["grandeur"] == "niveau_ngf" and serie["chronique"]["points"]
    assert serie["indices"][0]["semaine"] == SEMAINE
    assert serie["enveloppe"]["pas"] == "mois" and serie["enveloppe"]["points"][0]["mediane"] == 1.0
    assert client_base.get("/stations/piezo:INCONNU/series").status_code == 404


def test_synthese_de_la_semaine(client_base: TestClient) -> None:
    synthese = client_base.get(f"/semaines/{SEMAINE}/synthese").json()
    assert synthese["composite"]["repartition"] == {"1": 1}
    assert synthese["composite"]["zones_seches"] == 1
    assert synthese["fin"] == "2026-09-27"
    assert client_base.get("/semaines/2020-W10/synthese").status_code == 404
    assert client_base.get("/").json()["derniere_semaine"] == SEMAINE
