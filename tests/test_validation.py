"""Validation par les arrêtés sécheresse : lecture VigiEau, niveaux hebdomadaires, mesures."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import validation
from pipeline.config import Config, Zonage, Zone
from pipeline.http import ClientHttp
from pipeline.sources import vigieau
from pipeline.validation import arretes as niveaux
from pipeline.validation import rapport
from tests.conftest import FIXTURES

CSV = FIXTURES / "vigieau" / "arretes.csv"


def _zone(zone_id: str, arretes: dict[str, list[str]]) -> Zone:
    return Zone(
        zone_id=zone_id, libelle=zone_id.title(), type_zone="hydrogeol", masses_eau=["FRGG000"],
        ponderations={"spi_3": 0.4, "ips": 0.3, "debit": 0.3}, zones_alerte_arretes=arretes,
    )  # fmt: skip


@pytest.fixture
def config_v(config: Config) -> Config:
    zonage = Zonage(
        fragment_max_km2=20,
        zones=[
            _zone("LAY", {"SUP": ["Lay"]}),
            _zone("VENDEE", {"SUP": ["Vendée", "Vendée superficiel", "Autize superficiel"]}),
            _zone("COTIERS", {"SUP": ["Côtiers Vendéens"]}),
            _zone("ILE", {}),
        ],
    )
    return config.model_copy(update={"zonage": zonage})


def test_lire_arretes() -> None:
    t = vigieau.lire_arretes(CSV, "85")
    assert t.columns.tolist() == vigieau.COLONNES
    assert sorted(t["arrete_id"].unique()) == [1, 3, 4, 5]  # l'arrêté de l'Ain est écarté
    sans_zone = t[t["arrete_id"] == 1]
    assert len(sans_zone) == 1 and sans_zone["nom_zone_alerte"].isna().all()
    assert len(t[t["arrete_id"] == 3]) == 3  # une ligne par zone d'alerte
    en_vigueur = t[t["arrete_id"] == 5]
    assert en_vigueur["date_fin"].isna().all()  # « null » : arrêté sans date de fin
    assert en_vigueur["date_debut"].tolist() == [date(2026, 9, 14)] * 3
    assert set(en_vigueur["niveau_gravite"]) == {"vigilance", "crise", "alerte_renforcee"}


def test_ingerer_arretes(config: Config, client: ClientHttp) -> None:
    t = vigieau.ingerer_arretes(config, client)  # ressource « Arrêtés », pas « Arrêtés 2024 »
    assert t.equals(vigieau.lire_arretes(CSV, "85"))


@pytest.mark.parametrize(
    ("nom", "cle"),
    [("Côtiers Vendéens", "cotiers vendeens"), ("COTIERS VENDEENS", "cotiers vendeens"),
     ("Logne - Boulogne et Grand-Lieu", "logne boulogne et grand lieu"),
     ("Bassin de l'Autize", "bassin de l autize")],
)  # fmt: skip
def test_cle_nom(nom: str, cle: str) -> None:
    assert niveaux.cle_nom(nom) == cle


def test_rattachement(config_v: Config) -> None:
    t = niveaux.rattacher(config_v, vigieau.lire_arretes(CSV, "85"))
    assert niveaux.non_rattachees(t) == [("SOU", "NAPPE PLAINE-BOCAGE")]
    assert t.loc[t["nom_zone_alerte"] == "COTIERS VENDEENS", "zone_id"].tolist() == ["COTIERS"]
    assert niveaux.premiere_annee(t) == 2012  # 2011 : zones non détaillées


def test_niveaux_hebdo(config_v: Config) -> None:
    t = niveaux.niveaux_hebdo(config_v, vigieau.lire_arretes(CSV, "85"), "2026-W40")
    assert set(t["zone_id"]) == {"LAY", "VENDEE", "COTIERS"}  # ILE : aucune zone d'alerte
    assert t["semaine"].min() == "2012-W01"
    assert t.groupby("zone_id").size().nunique() == 1  # grille complète

    def niveau(zone: str, semaine: str) -> int:
        return int(t.loc[(t["zone_id"] == zone) & (t["semaine"] == semaine), "niveau"].iloc[0])

    assert niveau("LAY", "2012-W30") == 0  # dimanche 29 juillet
    assert niveau("LAY", "2012-W31") == 4  # dimanche 5 août : arrêté 3 (crise) commencé le 4
    assert niveau("LAY", "2012-W34") == 2  # dimanche 26 août : l'arrêté 4, plus récent, l'emporte
    assert niveau("LAY", "2012-W39") == 2  # dimanche 30 septembre : dernier jour de l'arrêté 4
    assert niveau("LAY", "2012-W40") == 0
    assert niveau("VENDEE", "2012-W33") == 2
    # arrêté en vigueur sans date de fin ; zone au niveau le plus sévère de ses zones d'alerte
    assert niveau("VENDEE", "2026-W40") == 4
    detail = t.loc[(t["zone_id"] == "VENDEE") & (t["semaine"] == "2026-W40"), "zones_alerte"]
    assert detail.tolist() == ["SUP Autize superficiel"]
    assert niveau("COTIERS", "2026-W38") == 3
    assert niveau("COTIERS", "2026-W37") == 0  # dimanche 13 septembre : pas encore en vigueur


def test_auc() -> None:
    assert rapport.auc([True, True, False, False], [-2.0, -1.0, 0.5, 1.0]) == 1.0
    assert rapport.auc([True, True, False, False], [1.0, 0.5, -1.0, -2.0]) == 0.0
    assert rapport.auc([True, False], [0.0, 0.0]) == 0.5
    assert rapport.auc([True, False, False], [-1.0, np.nan, 1.0]) == 1.0  # NaN ignoré
    assert np.isnan(rapport.auc([False, False], [0.0, 1.0]))


def _indices(config: Config) -> None:
    """Composite et SPI de zone synthétiques : secs quand le Lay est en crise (été 2012)."""
    lignes = []
    for d in pd.date_range("2012-01-01", "2012-12-30", freq="W-SUN"):
        semaine = d.strftime("%G-W%V")
        sec = date(2012, 8, 4) <= d.date() <= date(2012, 9, 30)
        for zone in ("LAY", "VENDEE", "COTIERS", "ILE"):
            valeur = -1.5 if sec and zone == "LAY" else 0.5
            lignes.append((zone, semaine, valeur, 1 if valeur < -1.28 else 5))
    composite = pd.DataFrame(lignes, columns=["zone_id", "semaine", "valeur", "classe"])
    composite["version_methodo"] = "D9"
    spi = composite.assign(indice="spi_3")[["zone_id", "semaine", "indice", "valeur"]]
    dossier = config.projet.chemins.data / "indices"
    dossier.mkdir(parents=True)
    composite.to_parquet(dossier / "composite_zone_2012.parquet")
    spi.to_parquet(dossier / "indice_zone_2012.parquet")


def test_executer_idempotent(config_v: Config, client: ClientHttp) -> None:
    _indices(config_v)
    resultat = validation.executer(config_v, client)
    assert resultat.non_rattachees == [("SOU", "NAPPE PLAINE-BOCAGE")]
    texte = resultat.rapport.read_text(encoding="utf-8")
    assert "4 arrêtés du département, dont 3 listent leurs zones d'alerte" in texte
    assert "Zones sans zone d'alerte rattachée** (hors comparaison) : Ile." in texte
    assert "| Lay | 27 | 33 % | 1,00 | 1,00 |  |  |" in texte  # composite parfait sur le Lay
    assert (
        "Corrélation de rang entre années (part sous alerte\net composite moyen) : non calculable"
        in texte
    )
    restrictions = pd.read_parquet(resultat.restrictions)
    assert restrictions["semaine"].max() == "2012-W52"  # dernière semaine des indices
    # sans réseau, mêmes fichiers au bit près
    avant = {p: p.read_bytes() for p in (resultat.restrictions, resultat.rapport)}
    validation.executer(config_v, None)
    assert {p: p.read_bytes() for p in avant} == avant


def test_hors_ligne_sans_arretes(config_v: Config) -> None:
    with pytest.raises(FileNotFoundError, match="sans --hors-ligne"):
        validation.executer(config_v, None)
