"""Surface de crue par passage Sentinel-1 (V2.2) : références d'été, détection par changement,
surfaces par régime, reprise. Sentinel-1 est simulé : aucun test ne touche au réseau."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pipeline.config import Config
from pipeline.raster import crue
from pipeline.raster.cog import ecrire_cog, lire_cog
from pipeline.raster.grille import Grille
from pipeline.sources import sentinel1

GRILLE = Grille(1000, 1600, 60, 60, 10, "EPSG:2154")
AUJOURD_HUI = date(2026, 11, 14)


@pytest.fixture
def config_crue(config: Config, tmp_path: Path) -> Config:
    chemins = config.projet.chemins.model_copy(update={"rasters": tmp_path / "rasters"})
    return config.model_copy(
        update={"projet": config.projet.model_copy(update={"chemins": chemins})}
    )


def _ecrire_domaine(config: Config) -> None:
    code = np.zeros(GRILLE.forme, np.uint8)
    code[10:50, 10:50] = 1  # domaine mesuré : 40 x 40 pixels = 16 ha
    code[10:15, 10:15] = 2  # eau permanente retirée
    ecrire_cog(
        crue.dossier_satellite(config) / "domaine_crue_marais_poitevin.tif", code, GRILLE, 255, {}
    )
    regimes = np.zeros(GRILLE.forme, np.uint8)
    regimes[10:50, 10:30] = 1  # moitié gauche : marais mouillé
    regimes[10:50, 30:40] = 3  # puis desséché ; le reste du domaine : « autres »
    ecrire_cog(crue.dossier_crue(config) / "regimes_marais_poitevin.tif", regimes, GRILLE, 255, {})


def _db(sec: float = -10.0) -> np.ndarray:
    return np.full(GRILLE.forme, sec, np.float32)


# --- fonctions pures ----------------------------------------------------------------------------


def test_annee_de_reference() -> None:
    with pytest.raises(ValueError):
        crue.annee_reference("precedent", date(2016, 1, 10))  # variante abandonnée (D16)
    assert crue.annee_reference("hydro", date(2016, 1, 10)) == 2015
    assert crue.annee_reference("hydro", date(2016, 9, 30)) == 2015
    assert crue.annee_reference("hydro", date(2016, 10, 1)) == 2016  # nouvel été complet
    assert crue.annee_reference("fixe", date(2016, 1, 10)) is None
    with pytest.raises(ValueError, match="inconnue"):
        crue.annee_reference("autre", date(2016, 1, 1))


def test_ete_complet() -> None:
    assert crue.ete_complet(2025, AUJOURD_HUI, 9)
    assert crue.ete_complet(2026, AUJOURD_HUI, 9)
    assert not crue.ete_complet(2026, date(2026, 9, 15), 9)  # saison en cours
    assert not crue.ete_complet(2027, AUJOURD_HUI, 9)


def test_centidb_aller_retour() -> None:
    ref = np.array([[-12.345, np.nan], [-7.0, -20.0]], np.float32)
    retour = crue.depuis_centidb(crue.vers_centidb(ref))
    assert np.isnan(retour[0, 1])
    assert np.allclose(retour[~np.isnan(retour)], ref[~np.isnan(ref)], atol=0.006)


def test_en_decibels() -> None:
    puissance = np.array([1.0, 0.1, 0.0, -5.0, -32768.0, np.nan], np.float32)
    db = sentinel1.en_decibels(puissance)
    assert db[0] == pytest.approx(0.0)
    assert db[1] == pytest.approx(-10.0, abs=1e-5)
    assert np.isnan(db[2:]).all()


def test_mediane_ete_ignore_les_nan() -> None:
    pile = np.stack([_db(-10), _db(-12), _db(-30)])
    pile[0, 0, 0] = np.nan
    ref = crue.mediane_ete(pile)
    assert ref[1, 1] == -12
    assert ref[0, 0] == pytest.approx(-21)  # médiane de -12 et -30


def test_detection_par_changement(config: Config) -> None:
    p = config.projet.satellite.crue.detection
    ref = _db(-10)
    ref_lisse = crue.lisser(ref, p.filtre_median_px)
    db = _db(-10)
    db[20:40, 20:40] = -20  # crue de 20 x 20 pixels
    db[2:4, 2:4] = -20  # tache de 4 pixels : trop petite
    db[55:58, 5:8] = -13  # baisse de 3 dB seulement et au-dessus de -16 dB : pas de l'eau
    masque, ok = crue.detecter(db, ref, ref_lisse, p)
    # le filtre médian 3 x 3 arrondit les quatre coins du carré (1 pixel chacun)
    assert int(masque.sum()) == 396
    assert masque[21:39, 21:39].all()
    assert not masque[20, 20]
    assert ok.all()


def test_detection_ignore_une_reference_deja_sombre(config: Config) -> None:
    p = config.projet.satellite.crue.detection
    ref = _db(-10)
    ref[20:40, 20:40] = -18  # déjà de l'eau en été (eau permanente non masquée)
    db = _db(-10)
    db[20:40, 20:40] = -24
    masque, _ = crue.detecter(db, ref, crue.lisser(ref, p.filtre_median_px), p)
    assert not masque.any()


def test_detection_sans_donnees(config: Config) -> None:
    p = config.projet.satellite.crue.detection
    ref = _db(-10)
    db = np.full(GRILLE.forme, np.nan, np.float32)
    masque, ok = crue.detecter(db, ref, crue.lisser(ref, p.filtre_median_px), p)
    assert not masque.any()
    assert not ok.any()


def test_surfaces_par_regime(config_crue: Config) -> None:
    _ecrire_domaine(config_crue)
    marais = config_crue.projet.satellite.crue.marais[0]
    domaine = crue.lire_domaine(config_crue, marais)
    assert int(domaine.mesure.sum()) == 40 * 40 - 25
    masque = np.zeros(GRILLE.forme, bool)
    masque[10:50, 10:50] = True  # tout le domaine, et même l'eau permanente et les bords
    masque[0:5, 0:5] = True  # hors domaine : jamais compté
    ok = np.ones(GRILLE.forme, bool)
    ok[10:30, :] = False  # un tiers du domaine non observable
    ligne = crue.surfaces(masque, ok, domaine, 0.01)
    assert ligne["surface_ha"] == pytest.approx((1600 - 25) * 0.01)
    assert ligne["pct_valides"] == pytest.approx(100 * (1575 - (20 * 40 - 25)) / 1575)
    regimes = (
        ligne["ha_mouille"] + ligne["ha_intermediaire"] + ligne["ha_desseche"] + ligne["ha_autres"]
    )
    assert regimes == pytest.approx(ligne["surface_ha"])
    assert ligne["ha_intermediaire"] == 0
    assert ligne["ha_mouille"] == pytest.approx((20 * 40 - 25) * 0.01)


def test_regimes_facultatifs(config_crue: Config) -> None:
    _ecrire_domaine(config_crue)
    (crue.dossier_crue(config_crue) / "regimes_marais_poitevin.tif").unlink()
    domaine = crue.lire_domaine(config_crue, config_crue.projet.satellite.crue.marais[0])
    assert domaine.regimes == {}
    ligne = crue.surfaces(np.zeros(GRILLE.forme, bool), np.ones(GRILLE.forme, bool), domaine, 0.01)
    assert set(ligne) == {"surface_ha", "pct_valides"}


def test_regimes_sur_une_autre_grille(config_crue: Config) -> None:
    _ecrire_domaine(config_crue)
    autre = Grille(1010, 1600, 60, 60, 10, "EPSG:2154")
    ecrire_cog(
        crue.dossier_crue(config_crue) / "regimes_marais_poitevin.tif",
        np.zeros(GRILLE.forme, np.uint8),
        autre,
        255,
        {},
    )
    with pytest.raises(ValueError, match="grille"):
        crue.lire_domaine(config_crue, config_crue.projet.satellite.crue.marais[0])


# --- chaîne complète avec Sentinel-1 simulé ----------------------------------------------------


def _faux_sentinel1(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Passages simulés : trois par été de 2015 à 2026 et des crues les 10 janvier 2015 à 2017."""
    appels: list[str] = []
    calendrier = [date(a, m, 15) for a in range(2015, 2027) for m in (7, 8, 9)]
    calendrier += [date(2015, 1, 10), date(2016, 1, 10), date(2017, 1, 10)]

    def element(jour: date) -> Any:
        return SimpleNamespace(
            datetime=datetime(jour.year, jour.month, jour.day, 6, 0, tzinfo=UTC),
            properties={"sat:relative_orbit": 81},
        )

    def chercher(
        config: Config, grille: Grille, orbite: int, debut: date, fin: date, catalogue: Any = None
    ) -> list[Any]:
        appels.append(f"recherche {debut}")
        return [element(j) for j in sorted(calendrier) if debut <= j <= fin]

    def lire_db(elements: list[Any], grille: Grille, lot: int = 6) -> Any:
        appels.append(f"lecture {len(elements)}")
        for e in elements:
            jour = e.datetime.date()
            db = _db(-10)
            if jour.month == 1 and jour.year in (2015, 2016, 2017):
                db[20:40, 20:40] = -20  # crue de 20 x 20 pixels, coins arrondis par le filtre : 396
                db[10:15, 10:15] = -20  # sur l'eau permanente (code 2) : jamais comptée
            yield [jour], db[None]

    monkeypatch.setattr(sentinel1, "chercher", chercher)
    monkeypatch.setattr(sentinel1, "lire_db", lire_db)
    return appels


def test_chaine_complete(config_crue: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    _ecrire_domaine(config_crue)
    appels = _faux_sentinel1(monkeypatch)
    chemin = crue.construire(config_crue, AUJOURD_HUI, ["marais_poitevin"])
    table = pd.read_parquet(chemin)
    assert set(table["variante"]) == {"hydro", "fixe"}  # la retenue et son contrôle (D16)
    janvier_2016 = table[table["date"] == "2016-01-10"].set_index("variante")
    assert janvier_2016["surface_ha"].to_dict() == pytest.approx({"hydro": 3.96, "fixe": 3.96})
    assert janvier_2016.loc["hydro", "annee_ref"] == 2015
    # 2015 : le catalogue n'a pas d'été 2014, donc pas de référence « hydro »
    janvier_2015 = table[table["date"] == "2015-01-10"].set_index("variante")
    assert pd.isna(janvier_2015.loc["hydro", "surface_ha"])
    assert janvier_2015.loc["fixe", "surface_ha"] == pytest.approx(3.96)
    # régimes : mouillé (colonnes 20 à 29) et desséché (30 à 39) : 198 pixels chacun
    assert janvier_2016.loc["fixe", "ha_mouille"] == pytest.approx(1.98)
    assert janvier_2016.loc["fixe", "ha_desseche"] == pytest.approx(1.98)
    # les étés sans crue donnent 0 ha
    assert table[table["date"] == "2018-08-15"]["surface_ha"].eq(0).all()
    # références écrites pour chaque été complet, de 2015 à 2026, plus la référence fixe
    refs = sorted((crue.dossier_crue(config_crue) / "references").glob("ref_ete_*.tif"))
    assert len(refs) == 12 + 1
    brut, grille, etiquettes = lire_cog(
        crue.chemin_reference(config_crue, config_crue.projet.satellite.crue.marais[0], 2016)
    )
    assert grille == GRILLE
    assert etiquettes["passages"] == "3"
    assert (crue.depuis_centidb(brut) == -10).all()
    # reprise : années complètes conservées, seule l'année en cours est relue
    appels.clear()
    crue.construire(config_crue, AUJOURD_HUI, ["marais_poitevin"])
    assert appels == ["recherche 2026-01-01", "lecture 3"]
    assert pd.read_parquet(chemin).equals(table)


def test_marais_inconnu(config_crue: Config) -> None:
    with pytest.raises(ValueError, match="aucun marais"):
        crue.construire(config_crue, AUJOURD_HUI, ["inconnu"])
