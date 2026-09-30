"""Enregistre des réponses réelles, réduites, pour les tests des retenues (réseau requis).

    uv run python tests/fixtures/enregistrer_retenues.py

Table ArcGIS du territoire : 2 retenues sur 3 semaines de 2026 plus un relevé sans volume,
découpées en deux pages pour tester la pagination. Couche nationale : 2 retenues vendéennes
(dont une à renommer par alias), une hors territoire et une sans relevé récent.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from pipeline.config import charger_config

ICI = Path(__file__).parent / "retenues"


def main() -> None:
    config = charger_config()
    assert config.stations.retenues is not None
    table = config.stations.retenues.table_arcgis
    ICI.mkdir(exist_ok=True)

    def requete(where: str) -> list[dict[str, object]]:
        reponse = httpx.get(
            f"{table}/query",
            params={"where": where, "outFields": "*", "orderByFields": "ObjectId", "f": "json"},
            timeout=120,
        ).json()
        return list(reponse["features"])

    releves = requete(
        "RETENUES IN ('MERVENT','SORIN/FINFARINE') AND ANNEE=2026 "
        "AND SEMAINE LIKE 'Semaine 3%' AND SEMAINE NOT LIKE 'Semaine 30%'"
    )[:6]
    sans_volume = requete("RETENUES='MOULIN PAPON' AND ANNEE=2019 AND SEMAINE LIKE 'Semaine 01 %'")
    entites = releves + sans_volume
    for nom, morceau, suite in (("page_1", entites[:4], True), ("page_2", entites[4:], False)):
        page = {"features": morceau, "exceededTransferLimit": suite}
        (ICI / f"arcgis_{nom}.json").write_text(json.dumps(page, ensure_ascii=False, indent=1))

    national = httpx.get(
        config.sources.retenues_national.wfs,
        params={
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": config.sources.retenues_national.couche,
            "SRSNAME": "EPSG:4326", "OUTPUTFORMAT": "application/json",
        },
        timeout=120,
    ).json()  # fmt: skip
    garder = {"MERVENT-RETENUE", "FINFARINE-RETENUE", "Auzay"}
    choisies = [f for f in national["features"] if f["properties"]["nom1"] in garder]
    hors_territoire = next(
        f for f in national["features"]
        if f["properties"].get("date_mesure") and f["geometry"]["coordinates"][0][1] > 48
    )  # fmt: skip
    national["features"] = [*choisies, hors_territoire]
    (ICI / "national.json").write_text(json.dumps(national, ensure_ascii=False, indent=1))
    print(len(entites), "relevés ArcGIS,", len(national["features"]), "retenues nationales")


if __name__ == "__main__":
    main()
