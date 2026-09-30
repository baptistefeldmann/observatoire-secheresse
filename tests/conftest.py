"""Réponses API enregistrées (tests/fixtures/) servies par un transport httpx simulé."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from pipeline.config import Config, Zonage, Zone, charger_config
from pipeline.http import ClientHttp

RACINE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"

# (hôte, fin du chemin, paramètre de requête discriminant ou None) -> fichier de fixture
ROUTES = {
    ("hubeau.eaufrance.fr", "/niveaux_nappes/stations", None): "hubeau/piezo_stations.json",
    ("hubeau.eaufrance.fr", "/hydrometrie/referentiel/stations", None):
        "hubeau/hydro_stations.json",
    ("hubeau.eaufrance.fr", "/ecoulement/stations", None): "hubeau/onde_stations.json",
    ("geo.api.gouv.fr", "/departements/85/communes", None): "geoapi/communes_85.geojson",
    ("www.data.gouv.fr", "/datasets/6569b27598256cc583c917a7/", None): "sim/jeu_datagouv.json",
    ("sim.test", "/SHP_SIM_FRANCE.shp", None): "sim/SHP_SIM_FRANCE.shp",
    ("sim.test", "/SHP_SIM_FRANCE.shx", None): "sim/SHP_SIM_FRANCE.shx",
    ("sim.test", "/SHP_SIM_FRANCE.dbf", None): "sim/SHP_SIM_FRANCE.dbf",
    ("services.sandre.eaufrance.fr", "/geo/sandre",
        ("TYPENAMES", "sa:PolygMasseDEauSouterraine_VEDL2019_FXX")):
        "sandre/masses_eau_polygones.json",
    ("services.sandre.eaufrance.fr", "/geo/sandre",
        ("TYPENAMES", "sa:MasseDEauSouterraine_VEDL2019_FXX")):
        "sandre/masses_eau_noms.json",
    ("services-eu1.arcgis.com", "/FeatureServer/0/query", ("resultOffset", "0")):
        "retenues/arcgis_page_1.json",
    ("services-eu1.arcgis.com", "/FeatureServer/0/query", ("resultOffset", "4")):
        "retenues/arcgis_page_2.json",
    ("geobretagne.fr", "/geoserver/dreal_b/wfs", None): "retenues/national.json",
    # Observations : un seul piézomètre et une seule station hydrométrique ont une fixture ;
    # les autres stations des fixtures répondent 404 (erreurs par station, SPEC §7.2).
    ("hubeau.eaufrance.fr", "/niveaux_nappes/chroniques", ("code_bss", "05068X0028/SP010")):
        "observations/piezo_chroniques.json",
    ("hubeau.eaufrance.fr", "/hydrometrie/obs_elab", ("code_entite", "M702241010")):
        "observations/hydro_qmnj.json",
    ("hubeau.eaufrance.fr", "/ecoulement/observations", None):
        "observations/onde_observations.json",
    ("hubeau.eaufrance.fr", "/ecoulement/campagnes", None): "observations/onde_campagnes.json",
    ("sim.test", "/QUOT_SIM2_2026.csv.gz", None): "sim/QUOT_SIM2_2026.csv.gz",
    ("sim.test", "/QUOT_SIM2_latest.csv.gz", None): "sim/QUOT_SIM2_latest.csv.gz",
}  # fmt: skip

# Zonage adapté aux deux communes des fixtures (île de Noirmoutier)
ZONAGE_FIXTURES = Zonage(
    fragment_max_km2=20,
    zones=[
        Zone(
            zone_id="ILE_NOIRMOUTIER",
            libelle="Île de Noirmoutier",
            type_zone="hydrogeol",
            masses_eau=["FRGG036"],
            ponderations={"spi_3": 0.4, "ips": 0.6},
        )
    ],
)


def repondre(requete: httpx.Request) -> httpx.Response:
    for (hote, fin, parametre), fichier in ROUTES.items():
        if (
            requete.url.host == hote
            and requete.url.path.endswith(fin)
            and (parametre is None or requete.url.params.get(parametre[0]) == parametre[1])
        ):
            return httpx.Response(200, content=(FIXTURES / fichier).read_bytes())
    return httpx.Response(404, text=f"pas de fixture pour {requete.url}")


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Configuration du dépôt, `data/` redirigé vers un dossier temporaire et zonage réduit à
    l'emprise des fixtures."""
    base = charger_config(RACINE / "config")
    chemins = base.projet.chemins.model_copy(update={"data": tmp_path / "data"})
    projet = base.projet.model_copy(update={"chemins": chemins})
    return base.model_copy(update={"projet": projet, "zonage": ZONAGE_FIXTURES})


@pytest.fixture
def fabrique_client(config: Config) -> Callable[..., ClientHttp]:
    def fabriquer(gestionnaire: Callable[[httpx.Request], httpx.Response] = repondre) -> ClientHttp:
        return ClientHttp(config.sources.http, httpx.MockTransport(gestionnaire), attente_max_s=0)

    return fabriquer


@pytest.fixture
def client(fabrique_client: Callable[..., ClientHttp]) -> ClientHttp:
    return fabrique_client()
