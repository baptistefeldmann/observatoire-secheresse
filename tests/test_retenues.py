from __future__ import annotations

from collections.abc import Callable
from datetime import date

import httpx
import pandas as pd
import pytest
from shapely.geometry import box

from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.sources import retenues
from tests.conftest import repondre

AUJOURD_HUI = date(2026, 9, 30)
EMPRISE = box(280_000, 6_570_000, 460_000, 6_720_000)  # Vendée et ses abords, EPSG:2154


@pytest.mark.parametrize(
    ("nom", "alias", "attendu"),
    [
        ("SORIN/FINFARINE", {}, "SORIN_FINFARINE"),
        ("MERVENT-RETENUE", {}, "MERVENT"),
        ("FINFARINE-RETENUE", {"FINFARINE": "SORIN_FINFARINE"}, "SORIN_FINFARINE"),
        ("Moulin Papon", {}, "MOULIN_PAPON"),
        ("Péault", {}, "PEAULT"),
    ],
)
def test_code_retenue(nom: str, alias: dict[str, str], attendu: str) -> None:
    assert retenues.code_retenue(nom, alias) == attendu


def test_observations_table_du_territoire(config: Config, client: ClientHttp) -> None:
    obs = retenues.ingerer_observations(config, client, EMPRISE, AUJOURD_HUI)
    # 2 pages ArcGIS : 6 relevés valides, le relevé sans volume est écarté
    assert len(obs) == 6
    assert set(obs["station_id"]) == {"retenue:MERVENT", "retenue:SORIN_FINFARINE"}
    assert set(obs["date"]) == {date(2026, 9, 13), date(2026, 9, 20), date(2026, 9, 27)}
    assert (obs["source_donnee"] == "territoire").all()
    mervent = obs[(obs["station_id"] == "retenue:MERVENT") & (obs["date"] == date(2026, 9, 27))]
    assert mervent["volume_m3"].tolist() == [4_090_000]
    assert mervent["capacite_m3"].tolist() == [8_300_000]
    assert (obs["ingere_le"] == AUJOURD_HUI).all()


def test_repli_sur_la_couche_nationale(
    config: Config, fabrique_client: Callable[..., ClientHttp]
) -> None:
    def arcgis_en_panne(requete: httpx.Request) -> httpx.Response:
        if requete.url.host.endswith("arcgis.com"):
            return httpx.Response(503)
        return repondre(requete)

    obs = retenues.ingerer_observations(
        config, fabrique_client(arcgis_en_panne), EMPRISE, AUJOURD_HUI
    )
    # Auzay (sans relevé) et la retenue bretonne (hors emprise) sont écartées ;
    # FINFARINE est renommée par l'alias du territoire
    assert list(obs["station_id"]) == ["retenue:MERVENT", "retenue:SORIN_FINFARINE"]
    assert (obs["source_donnee"] == "national").all()
    assert list(obs["volume_m3"]) == [4_100_000, 420_000]


def test_couche_nationale_sans_source_du_territoire(config: Config, client: ClientHttp) -> None:
    sans_local = config.model_copy(
        update={"stations": config.stations.model_copy(update={"retenues": None})}
    )
    obs = retenues.ingerer_observations(sans_local, client, EMPRISE, AUJOURD_HUI)
    # pas d'alias sans configuration du territoire : FINFARINE garde son nom national
    assert list(obs["station_id"]) == ["retenue:FINFARINE", "retenue:MERVENT"]


def test_stations_des_retenues(config: Config, client: ClientHttp) -> None:
    stations = retenues.ingerer_stations(config, client, EMPRISE).set_index("station_id")
    assert list(stations.index) == ["retenue:MERVENT", "retenue:SORIN_FINFARINE"]
    assert stations.crs.to_epsg() == 2154
    assert stations.loc["retenue:MERVENT", "libelle"] == "MERVENT"
    assert '"capacite_m3": 8300000' in stations.loc["retenue:MERVENT", "metadonnees"]


def test_aucune_retenue_sur_le_territoire(config: Config, client: ClientHttp) -> None:
    stations = retenues.ingerer_stations(config, client, box(0, 0, 1, 1))
    assert stations.empty and "station_id" in stations.columns


def test_releve_decale_d_une_semaine_ramene_a_la_semaine_vide(
    config: Config,
    client: ClientHttp,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D14 : un relevé daté hors dimanche n'est déplacé que si sa semaine ISO contient déjà un
    autre relevé de la retenue et que la semaine précédente est vide. Les autres sont laissés
    tels quels ; une semaine qui garde plusieurs relevés est signalée."""

    def releve(code: str, jour: date, volume: float) -> dict[str, object]:
        return {
            "code": code, "libelle": code, "date": jour, "volume_m3": volume,
            "capacite_m3": 8_300_000.0, "longitude": -0.8, "latitude": 46.7,
        }  # fmt: skip

    brut = pd.DataFrame(
        [
            # « Semaine 08 (au mardi 25/02/2025) » : la W08 est vide, la W09 a deux relevés
            releve("SORIN_FINFARINE", date(2025, 2, 16), 800_000.0),
            releve("SORIN_FINFARINE", date(2025, 2, 25), 900_000.0),
            releve("SORIN_FINFARINE", date(2025, 3, 2), 950_000.0),
            # relevé du vendredi, seul dans sa semaine ISO : laissé tel quel
            releve("JAUNAY", date(2024, 6, 16), 3_690_000.0),
            releve("JAUNAY", date(2024, 6, 21), 3_680_000.0),
            releve("JAUNAY", date(2024, 6, 30), 3_640_000.0),
            # deux relevés dans la W09 mais la W08 est déjà occupée : rien à déplacer, à signaler
            releve("MERVENT", date(2025, 2, 23), 4_000_000.0),
            releve("MERVENT", date(2025, 2, 25), 4_100_000.0),
            releve("MERVENT", date(2025, 3, 2), 4_200_000.0),
        ]
    )
    monkeypatch.setattr(retenues, "_releves_arcgis", lambda *_: brut)
    with caplog.at_level("INFO"):
        obs = retenues.ingerer_observations(config, client, EMPRISE, AUJOURD_HUI)
    dates = {
        (s, d): v for s, d, v in zip(obs["station_id"], obs["date"], obs["volume_m3"], strict=True)
    }
    assert dates == {
        ("retenue:SORIN_FINFARINE", date(2025, 2, 16)): 800_000.0,
        ("retenue:SORIN_FINFARINE", date(2025, 2, 23)): 900_000.0,  # ramené du mardi 25
        ("retenue:SORIN_FINFARINE", date(2025, 3, 2)): 950_000.0,
        ("retenue:JAUNAY", date(2024, 6, 16)): 3_690_000.0,
        ("retenue:JAUNAY", date(2024, 6, 21)): 3_680_000.0,  # inchangé
        ("retenue:JAUNAY", date(2024, 6, 30)): 3_640_000.0,
        ("retenue:MERVENT", date(2025, 2, 23)): 4_000_000.0,
        ("retenue:MERVENT", date(2025, 2, 25)): 4_100_000.0,  # inchangé
        ("retenue:MERVENT", date(2025, 3, 2)): 4_200_000.0,
    }
    assert "SORIN_FINFARINE : relevé du 2025-02-25 ramené au 2025-02-23" in caplog.text
    assert "MERVENT : 2 relevés dans la semaine ISO 202509, à examiner" in caplog.text
    assert "JAUNAY" not in caplog.text
