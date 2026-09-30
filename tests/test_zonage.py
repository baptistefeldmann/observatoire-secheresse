"""Découpage en zones sur des géométries synthétiques (carrés en EPSG:2154)."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from pipeline import zonage
from pipeline.config import Config, Zonage, Zone

KM = 1000
TERRITOIRE = box(0, 0, 10 * KM, 10 * KM)  # 100 km²
POIDS = {"spi_3": 0.5, "debit": 0.5}


def _gdf(lignes: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(lignes, geometry="geometry", crs=2154)


# Deux masses d'eau séparées par une lacune de 1 m (bruit des référentiels),
# deux zones d'alerte qui coupent le territoire en bas / haut.
MASSES = _gdf(
    [
        {"code": "M1", "nom": "Ouest", "geometry": box(0, 0, 5 * KM, 10 * KM)},
        {"code": "M2", "nom": "Est", "geometry": box(5 * KM + 1, 0, 10 * KM, 10 * KM)},
    ]
)
ALERTES = _gdf(
    [
        {"code": 1, "libelle": "Sud", "type": "SUP", "geometry": box(0, 0, 10 * KM, 5 * KM)},
        {"code": 2, "libelle": "Nord", "type": "SUP", "geometry": box(0, 5 * KM, 10 * KM, 10 * KM)},
    ]
)


def _zone(zone_id: str, masses: list[str], alertes: list[int] | None = None) -> Zone:
    return Zone(
        zone_id=zone_id,
        libelle=zone_id,
        type_zone="hydrogeol",
        masses_eau=masses,
        zones_alerte=alertes or [],
        ponderations=POIDS,
    )


def _avec_zones(config: Config, *zones: Zone) -> Config:
    return config.model_copy(update={"zonage": Zonage(fragment_max_km2=1, zones=list(zones))})


def test_decoupage_masses_et_alertes(config: Config) -> None:
    config = _avec_zones(
        config,
        _zone("OUEST", ["M1"]),
        _zone("EST_SUD", ["M2"], [1]),
        _zone("EST_NORD", ["M2"], [2]),
    )
    zones = zonage.construire_zones(config, MASSES, ALERTES, TERRITOIRE).set_index("zone_id")
    attendu = {"EST_NORD": 25e6, "EST_SUD": 25e6, "OUEST": 50e6}
    for zone_id, surface in attendu.items():
        assert zones.area[zone_id] == pytest.approx(surface, abs=0.02e6)
    # la lacune de 1 m est rattachée : couverture exacte, sans chevauchement
    assert zones.union_all().area == pytest.approx(TERRITOIRE.area)
    assert zones.area.sum() == pytest.approx(TERRITOIRE.area)


def test_fragment_isole_rattache_a_la_zone_voisine(config: Config) -> None:
    # une enclave de 0,5 km² de l'alerte Nord au milieu de l'alerte Sud, côté M2 :
    # elle appartient à EST_NORD mais n'y touche pas -> rattachée à EST_SUD qui l'entoure
    enclave = box(8 * KM, 2 * KM, 9 * KM, 2.5 * KM)
    alertes = ALERTES.copy()
    alertes.loc[0, "geometry"] = box(0, 0, 10 * KM, 5 * KM).difference(enclave)
    alertes.loc[1, "geometry"] = box(0, 5 * KM, 10 * KM, 10 * KM).union(enclave)
    config = _avec_zones(
        config,
        _zone("OUEST", ["M1"]),
        _zone("EST_SUD", ["M2"], [1]),
        _zone("EST_NORD", ["M2"], [2]),
    )
    zones = zonage.construire_zones(config, MASSES, alertes, TERRITOIRE).set_index("zone_id")
    assert zones.loc["EST_SUD", "geometry"].contains(Point(8.5 * KM, 2.25 * KM))
    assert not zones.loc["EST_NORD", "geometry"].intersects(Point(8.5 * KM, 2.25 * KM))
    assert zones.area.sum() == pytest.approx(TERRITOIRE.area)


def test_lacune_importante_refusee(config: Config) -> None:
    config = _avec_zones(config, _zone("OUEST", ["M1"]))
    with pytest.raises(ValueError, match="non couvert"):
        zonage.construire_zones(config, MASSES, ALERTES, TERRITOIRE)


def test_chevauchement_refuse(config: Config) -> None:
    config = _avec_zones(config, _zone("A", ["M1"]), _zone("B", ["M1", "M2"]))
    with pytest.raises(ValueError, match="chevauche"):
        zonage.construire_zones(config, MASSES, ALERTES, TERRITOIRE)


@pytest.mark.parametrize(
    ("zone", "message"),
    [(_zone("A", ["M9"]), "masse\\(s\\) d'eau absente"), (_zone("A", ["M1"], [7]), "inconnue")],
)
def test_codes_inconnus_refuses(config: Config, zone: Zone, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        zonage.construire_zones(_avec_zones(config, zone), MASSES, ALERTES, TERRITOIRE)


def test_rattacher_stations(config: Config) -> None:
    config = _avec_zones(config, _zone("OUEST", ["M1"]), _zone("EST", ["M2"]))
    zones = zonage.construire_zones(config, MASSES, ALERTES, TERRITOIRE)
    stations = _gdf(
        [
            {"station_id": "a", "geometry": Point(2 * KM, 2 * KM)},  # dans OUEST
            {"station_id": "b", "geometry": Point(10.5 * KM, 5 * KM)},  # 500 m au large de EST
            {"station_id": "c", "geometry": Point(20 * KM, 5 * KM)},  # trop loin
        ]
    )
    resultat = zonage.rattacher_stations(stations, zones, distance_max_m=1000)
    assert resultat["zone_id"].tolist()[:2] == ["OUEST", "EST"]
    assert resultat["zone_id"].isna().tolist() == [False, False, True]
