"""Chargement PostGIS. Le test d'intégration demande une base PostGIS jetable, fournie par
`make test-db` (variable SECHERESSE_TEST_POSTGRES_URL). Sans elle, il est ignoré : les tests
n'exigent ni réseau ni service externe.
"""

from __future__ import annotations

import os
from datetime import date

import geopandas as gpd
import pandas as pd
import pytest
import shapely
from shapely.geometry import Point
from sqlalchemy import text

from pipeline import ingestion, referentiels
from pipeline.config import Config
from pipeline.db import chargement
from pipeline.db.connexion import moteur
from pipeline.http import ClientHttp

URL_TEST = os.environ.get("SECHERESSE_TEST_POSTGRES_URL")


def test_csv_pour_copy() -> None:
    table = gpd.GeoDataFrame(
        {"id": ["a", "b"], "json": ['{"x": 1}', None], "actif": [True, False]},
        geometry=[Point(1, 2), Point(3, 4)],
        crs=2154,
    )
    lignes = chargement.vers_csv(table, ("id", "json", "actif", "geom"), 2154).splitlines()
    assert lignes[1].startswith(r"b,\N,False,")
    geom = shapely.from_wkb(lignes[0].rsplit(",", 1)[1])
    assert shapely.get_srid(geom) == 2154 and geom.equals(Point(1, 2))


def test_csv_sans_geometrie() -> None:
    table = pd.DataFrame({"station_id": ["x"], "date": [date(2026, 9, 1)], "v": [float("nan")]})
    assert chargement.vers_csv(table, ("station_id", "date", "v"), None) == "x,2026-09-01,\\N\n"


@pytest.mark.skipif(URL_TEST is None, reason="SECHERESSE_TEST_POSTGRES_URL non définie")
def test_reconstruction_depuis_data(config: Config, client: ClientHttp) -> None:
    referentiels.construire(config, client, date(2026, 9, 30))
    ingestion.ingerer(config, client, date(2026, 9, 30), date(2026, 9, 1))
    base = moteur(URL_TEST)

    effectifs = chargement.reconstruire(config, base)
    assert effectifs["ref.zone"] == 1
    assert effectifs["obs.piezo_jour"] == 9
    assert effectifs["obs.meteo_jour"] > 0
    premiere = chargement.empreinte(base)

    # « make db-rebuild reconstruit PostGIS à l'identique à partir des seuls Parquet » (SPEC §12)
    chargement.reconstruire(config, base)
    assert chargement.empreinte(base) == premiere

    with base.connect() as connexion:
        srid: list[int] = list(
            connexion.execute(text("SELECT DISTINCT ST_SRID(geom) FROM ref.station")).scalars()
        )
        assert srid == [2154]
        rattachee: str = connexion.execute(
            text("SELECT zone_id FROM ref.station WHERE station_id = 'piezo:05068X0028/SP010'")
        ).scalar_one()
        assert rattachee == "ILE_NOIRMOUTIER"
        # vues de restitution (migration 0003) : présentes, interrogeables, géométrie typée
        vues: list[str] = list(
            connexion.execute(
                text("SELECT f_table_name FROM geometry_columns WHERE f_table_schema = 'carto'")
            ).scalars()
        )
        assert sorted(vues) == [
            "v_composite_zone", "v_indice_station", "v_indice_zone", "v_onde_zone", "v_retenue",
        ]  # fmt: skip
        for vue in vues:
            connexion.execute(text(f"SELECT * FROM carto.{vue} WHERE derniere LIMIT 1")).all()
