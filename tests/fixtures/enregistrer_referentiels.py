"""Enregistre des réponses réelles, réduites, pour les tests des référentiels (réseau requis).

    uv run python tests/fixtures/enregistrer_referentiels.py <dossier SHP_SIM_FRANCE>

Deux communes voisines (L'Épine et Noirmoutier-en-l'Île), trois stations par réseau, les
points de grille SIM dans un rayon de 30 km autour de ces communes, et les masses d'eau
SANDRE de l'emprise, découpées à l'emprise pour alléger les fichiers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import httpx

ICI = Path(__file__).parent
COMMUNES = ["85083", "85163"]
HUBEAU = {
    "piezo_stations": "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/stations",
    "hydro_stations": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations",
    "onde_stations": "https://hubeau.eaufrance.fr/api/v1/ecoulement/stations",
}


def main(dossier_shp: Path) -> None:
    (ICI / "hubeau").mkdir(exist_ok=True)
    for nom, url in HUBEAU.items():
        page = httpx.get(
            url, params={"code_departement": "85", "size": 3, "format": "json"}, timeout=120
        ).json()
        page.update(count=len(page["data"]), next=None)  # une seule page de 3 stations
        (ICI / "hubeau" / f"{nom}.json").write_text(json.dumps(page, ensure_ascii=False, indent=1))

    (ICI / "geoapi").mkdir(exist_ok=True)
    geojson = httpx.get(
        "https://geo.api.gouv.fr/departements/85/communes",
        params={"format": "geojson", "geometry": "contour", "fields": "code,nom"},
        timeout=120,
    ).json()
    geojson["features"] = [f for f in geojson["features"] if f["properties"]["code"] in COMMUNES]
    (ICI / "geoapi" / "communes_85.geojson").write_text(json.dumps(geojson, ensure_ascii=False))

    communes = gpd.GeoDataFrame.from_features(geojson["features"], crs=4326).to_crs(27572)
    zone = communes.union_all().buffer(30_000)
    points = gpd.read_file(dossier_shp / "SHP_SIM_FRANCE.shp")
    lambert = gpd.GeoSeries(gpd.points_from_xy(points.lambx * 100, points.lamby * 100), crs=27572)
    sous_ensemble = points[lambert.within(zone).values]
    (ICI / "sim").mkdir(exist_ok=True)
    sous_ensemble.to_file(ICI / "sim" / "SHP_SIM_FRANCE.shp")
    jeu = {
        "resources": [
            {"title": f"SHP_SIM_FRANCE.{ext}", "url": f"https://sim.test/SHP_SIM_FRANCE.{ext}"}
            for ext in ("shp", "shx", "dbf")
        ]
    }
    (ICI / "sim" / "jeu_datagouv.json").write_text(json.dumps(jeu, indent=1))
    emprise = communes.to_crs(2154).union_all().buffer(1000)
    x0, y0, x1, y1 = emprise.bounds
    urn = "urn:ogc:def:crs:EPSG::2154"
    (ICI / "sandre").mkdir(exist_ok=True)
    for couche, fichier in [
        ("sa:PolygMasseDEauSouterraine_VEDL2019_FXX", "masses_eau_polygones.json"),
        ("sa:MasseDEauSouterraine_VEDL2019_FXX", "masses_eau_noms.json"),
    ]:
        reponse = httpx.get(
            "https://services.sandre.eaufrance.fr/geo/sandre",
            params={
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": couche,
                "SRSNAME": urn,
                "OUTPUTFORMAT": "geojson",
                "BBOX": f"{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},{urn}",
            },
            timeout=300,
        ).json()
        gdf = gpd.GeoDataFrame.from_features(reponse["features"], crs=2154).clip(emprise.envelope)
        (ICI / "sandre" / fichier).write_text(gdf.to_json(drop_id=True))
    print(f"{len(sous_ensemble)} points SIM, {len(geojson['features'])} communes")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
