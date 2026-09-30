from __future__ import annotations

import json
from datetime import date

import geopandas as gpd
import pytest

from pipeline import referentiels
from pipeline.config import Config
from pipeline.http import ClientHttp
from pipeline.sources import communes, meteo, piezo

AUJOURD_HUI = date(2026, 10, 1)


def test_construire_ecrit_les_quatre_referentiels(config: Config, client: ClientHttp) -> None:
    chemins = referentiels.construire(config, client, AUJOURD_HUI)
    assert set(chemins) == {"communes", "zones", "mailles_safran", "stations"}
    for chemin in chemins.values():
        gdf = gpd.read_parquet(chemin)
        assert gdf.crs.to_epsg() == 2154
        assert not gdf.empty


def test_stations_normalisees(config: Config, client: ClientHttp) -> None:
    referentiels.construire(config, client, AUJOURD_HUI)
    stations = gpd.read_parquet(referentiels.dossier(config) / "stations.parquet")
    assert len(stations) == 9
    assert stations["station_id"].is_monotonic_increasing
    assert stations["station_id"].is_unique
    assert set(stations["source"]) == {"piezo", "hydro", "onde"}
    assert all(
        s.startswith(f"{src}:") for s, src in zip(stations.station_id, stations.source, strict=True)
    )
    assert set(stations.geom_type) == {"Point"}
    assert str(stations["zone_id"].dtype) == "string"
    # seul le piézomètre de L'Épine est sur l'île ; les autres stations des fixtures sont loin
    avec_zone = stations.dropna(subset=["zone_id"])
    assert list(avec_zone["station_id"]) == ["piezo:05068X0028/SP010"]
    assert avec_zone["zone_id"].iloc[0] == "ILE_NOIRMOUTIER"
    piezo_1 = stations.set_index("station_id").loc["piezo:05068X0028/SP010"]
    assert piezo_1["masse_eau"] == "GG036"
    assert json.loads(piezo_1["metadonnees"])["date_fin_mesure"] == "2026-09-18"


@pytest.mark.parametrize(
    ("aujourd_hui", "attendu"), [(AUJOURD_HUI, True), (date(2028, 1, 1), False)]
)
def test_piezo_en_service_selon_derniere_mesure(
    config: Config, client: ClientHttp, aujourd_hui: date, attendu: bool
) -> None:
    stations = piezo.ingerer_stations(config, client, aujourd_hui)
    assert (stations["en_service"] == attendu).all()


def test_communes_multipolygones(config: Config, client: ClientHttp) -> None:
    gdf = communes.ingerer_communes(config, client)
    assert list(gdf["code_insee"]) == ["85083", "85163"]
    assert set(gdf.geom_type) == {"MultiPolygon"}


def test_mailles_du_territoire(config: Config, client: ClientHttp) -> None:
    territoire = communes.contour(communes.ingerer_communes(config, client)).buffer(1000)
    toutes = meteo.grille(config, client)
    retenues = meteo.ingerer_mailles(config, client, territoire)
    assert 0 < len(retenues) < len(toutes)
    assert retenues.intersects(territoire).all()
    assert list(retenues.columns) == ["maille_id", "geometry"]
    # carrés de 8 km en Lambert II étendu, reprojetés : environ 64 km²
    assert retenues.area.between(63e6, 65e6).all()


def test_zones_couvrent_le_territoire(config: Config, client: ClientHttp) -> None:
    referentiels.construire(config, client, AUJOURD_HUI)
    zones = gpd.read_parquet(referentiels.dossier(config) / "zones.parquet")
    territoire = communes.contour(
        gpd.read_parquet(referentiels.dossier(config) / "communes.parquet")
    )
    assert list(zones["zone_id"]) == ["ILE_NOIRMOUTIER"]
    assert set(zones.geom_type) == {"MultiPolygon"}
    assert zones.area.sum() == pytest.approx(territoire.area, rel=1e-6)
    assert json.loads(zones["ponderations"].iloc[0]) == {"ips": 0.6, "spi_3": 0.4}


def test_idempotent(config: Config, client: ClientHttp) -> None:
    premiers = referentiels.construire(config, client, AUJOURD_HUI)
    contenus = {n: c.read_bytes() for n, c in premiers.items()}
    seconds = referentiels.construire(config, client, AUJOURD_HUI)
    assert {n: c.read_bytes() for n, c in seconds.items()} == contenus
