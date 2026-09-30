from __future__ import annotations

from collections.abc import Callable
from datetime import date

import httpx
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
