from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pipeline.config import charger_config

DOSSIER_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def copie_config(tmp_path: Path) -> Path:
    dossier = tmp_path / "config"
    shutil.copytree(DOSSIER_CONFIG, dossier)
    return dossier


def _modifier(fichier: Path, modification: dict[str, object]) -> None:
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    contenu.update(modification)
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")


def test_config_du_depot_valide() -> None:
    config = charger_config(DOSSIER_CONFIG)
    assert config.projet.territoire.code_departement == "85"
    assert config.projet.crs == "EPSG:2154"
    assert len(config.classes.classes) == 7


def test_dossier_depuis_variable_environnement(
    copie_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _modifier(
        copie_config / "projet.yaml",
        {"territoire": {"code_departement": "17", "nom": "Charente-Maritime", "slug": "cmar"}},
    )
    monkeypatch.setenv("SECHERESSE_CONFIG", str(copie_config))
    assert charger_config().projet.territoire.slug == "cmar"


def test_ponderations_ne_sommant_pas_a_un(copie_config: Path) -> None:
    _modifier(
        copie_config / "zones.yaml",
        {
            "zones": [
                {
                    "zone_id": "A",
                    "libelle": "A",
                    "type_zone": "hydrogeol",
                    "masses_eau": ["FRGG001"],
                    "ponderations": {"spi_3": 0.5, "ips": 0.3},
                }
            ]
        },
    )
    with pytest.raises(ValidationError, match="sommer à 1"):
        charger_config(copie_config)


def test_composante_inconnue(copie_config: Path) -> None:
    _modifier(
        copie_config / "zones.yaml",
        {
            "zones": [
                {
                    "zone_id": "A",
                    "libelle": "A",
                    "type_zone": "hydrogeol",
                    "masses_eau": ["FRGG001"],
                    "ponderations": {"spi3": 1.0},
                }
            ]
        },
    )
    with pytest.raises(ValidationError):
        charger_config(copie_config)


def test_zone_en_double(copie_config: Path) -> None:
    zone = {
        "zone_id": "A",
        "libelle": "A",
        "type_zone": "alerte",
        "masses_eau": ["FRGG001"],
        "ponderations": {"debit": 1.0},
    }
    _modifier(copie_config / "zones.yaml", {"zones": [zone, zone]})
    with pytest.raises(ValidationError, match="en double"):
        charger_config(copie_config)


def test_crs_geographique_refuse(copie_config: Path) -> None:
    _modifier(copie_config / "projet.yaml", {"crs": "EPSG:4326"})
    with pytest.raises(ValidationError, match="projeté"):
        charger_config(copie_config)


def test_seuils_et_classes_incoherents(copie_config: Path) -> None:
    _modifier(copie_config / "classes.yaml", {"seuils": [-1.0, 0.0, 1.0]})
    with pytest.raises(ValidationError, match="une classe de plus"):
        charger_config(copie_config)


def test_stations_yaml_facultatif(copie_config: Path) -> None:
    (copie_config / "stations.yaml").unlink()
    assert charger_config(copie_config).stations.raccordements_hydro == []


def test_station_dans_deux_raccordements(copie_config: Path) -> None:
    raccordement = {"site": "S", "libelle": "S", "stations": ["A", "B"], "verification": "-"}
    _modifier(
        copie_config / "stations.yaml",
        {"raccordements_hydro": [raccordement, {**raccordement, "stations": ["B", "C"]}]},
    )
    with pytest.raises(ValidationError, match="plusieurs raccordements"):
        charger_config(copie_config)


def test_onde_hors_composite(copie_config: Path) -> None:
    zone = {
        "zone_id": "A",
        "libelle": "A",
        "type_zone": "hydrogeol",
        "masses_eau": ["FRGG001"],
        "ponderations": {"spi_3": 0.85, "onde": 0.15},
    }
    _modifier(copie_config / "zones.yaml", {"zones": [zone]})
    with pytest.raises(ValidationError):
        charger_config(copie_config)
