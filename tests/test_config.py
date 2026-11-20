from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pipeline.config import ClasseForet, PosteForet, charger_config

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


def test_couleur_de_classe_invalide(copie_config: Path) -> None:
    classes = [{"classe": n, "libelle": str(n), "couleur": "#c8102e"} for n in range(1, 8)]
    classes[3]["couleur"] = "vert"
    _modifier(copie_config / "classes.yaml", {"classes": classes})
    with pytest.raises(ValidationError, match="pattern"):
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


def _modifier_imbrique(fichier: Path, chemin: list[str], valeur: object) -> None:
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    cible = contenu
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")


def test_config_satellite_du_depot() -> None:
    config = charger_config(DOSSIER_CONFIG)
    sat = config.projet.satellite
    assert sat.version_methodo == "D16"
    # D16 : référence fixe publiée, référence « hydro » en contrôle seulement
    assert sat.crue.reference.variante == "fixe"
    assert sat.crue.reference.variantes == ["fixe", "hydro"]
    assert sat.crue.orbite_publiee == 81
    comp = sat.composites
    assert comp.bloc_px >= 256 and comp.seuil_derive == 0.03
    assert comp.cibles_derive == ["pin_maritime", "chenes_decidus"]
    assert comp.derive_fenetre_jours == 7 and comp.derive_plans_min == 5
    assert 0 < comp.derive_couverture_min <= 1
    assert [m.id for m in sat.crue.marais] == ["marais_poitevin", "marais_breton"]
    ref = config.projet.periode_reference
    # D10 : références figées à 2025, 2026 n'y entre jamais
    assert (ref.sentinel2.debut, ref.sentinel2.fin, ref.sentinel2.annee_gel) == (2018, 2025, 2025)
    assert (ref.sentinel1.debut, ref.sentinel1.fin, ref.sentinel1.annee_gel) == (2015, 2025, 2025)


def test_cibles_de_derive_inconnues(copie_config: Path) -> None:
    """Une cible de dérive absente de la nomenclature est refusée au chargement."""
    _modifier_imbrique(
        copie_config / "projet.yaml",
        ["satellite", "composites", "cibles_derive"],
        ["classe_inconnue"],
    )
    with pytest.raises(ValidationError, match="classe_inconnue"):
        charger_config(copie_config)


def test_orbite_publiee_aussi_en_controle(copie_config: Path) -> None:
    _modifier_imbrique(
        copie_config / "projet.yaml",
        ["satellite", "crue", "marais"],
        [
            {
                "id": "m",
                "nom": "M",
                "motif_site": "M",
                "orbites_controle": [81],
                "station_maree": "S",
            }
        ],
    )
    with pytest.raises(ValidationError, match="orbite publiée"):
        charger_config(copie_config)


def test_motif_de_site_invalide(copie_config: Path) -> None:
    _modifier_imbrique(
        copie_config / "projet.yaml",
        ["satellite", "crue", "marais"],
        [{"id": "m", "nom": "M", "motif_site": "(", "station_maree": "S"}],
    )
    with pytest.raises(ValidationError, match="expression régulière"):
        charger_config(copie_config)


def test_filtre_median_pair(copie_config: Path) -> None:
    _modifier_imbrique(
        copie_config / "projet.yaml", ["satellite", "crue", "detection", "filtre_median_px"], 4
    )
    with pytest.raises(ValidationError, match="impaire"):
        charger_config(copie_config)


def test_nomenclature_ocs_du_depot() -> None:
    ocs = charger_config(DOSSIER_CONFIG).nomenclature_ocs
    assert len(ocs.foret.classes) == 7
    assert len(ocs.cultures.classes) == 9
    # les 27 codes de la BD Forêt de la Vendée (28 libellés : FF1-49-49 en a deux graphies)
    postes: list[ClasseForet | PosteForet] = [
        *ocs.foret.classes,
        *ocs.foret.reserve,
        *ocs.foret.exclues,
    ]
    tous = {c for p in postes for c in p.code_tfv}
    assert len(tous) == 27
    # D15 : la peupleraie et les landes échappent à la règle « encore un arbre »
    libres = {c.id for c in ocs.foret.classes if not c.controle_foret}
    assert libres == {"peupleraie", "landes"}
    # classes de confiance : forêts (hors peupleraie, landes) et prairies permanentes
    confiance = {c.id for c in ocs.foret.classes if c.confiance}
    confiance |= {c.id for c in ocs.cultures.classes if c.confiance}
    assert "prairies_permanentes" in confiance and "pin_maritime" in confiance
    assert "mais" not in confiance


def test_code_tfv_affecte_deux_fois(copie_config: Path) -> None:
    fichier = copie_config / "nomenclature_ocs.yaml"
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    contenu["foret"]["reserve"][0]["code_tfv"].append("FF1G01-01")  # déjà dans chenes_decidus
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError, match="plusieurs classes"):
        charger_config(copie_config)


def test_code_de_classe_en_double(copie_config: Path) -> None:
    fichier = copie_config / "nomenclature_ocs.yaml"
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    contenu["foret"]["classes"][1]["code"] = contenu["foret"]["classes"][0]["code"]
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError, match="code de classe en double"):
        charger_config(copie_config)


def test_code_group_affecte_deux_fois(copie_config: Path) -> None:
    fichier = copie_config / "nomenclature_ocs.yaml"
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    contenu["cultures"]["classes"][1]["code_group"].append(18)
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError, match="code_group"):
        charger_config(copie_config)


def test_complement_d_arbres_vers_un_poste_inconnu(copie_config: Path) -> None:
    fichier = copie_config / "nomenclature_ocs.yaml"
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    contenu["regles"]["arbres_complement_tfv"] = ["XX9"]
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError, match="XX9"):
        charger_config(copie_config)
