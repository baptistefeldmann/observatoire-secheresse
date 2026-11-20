"""Composites mensuels de Sentinel-2 (V2.2d) : choix des scènes, radiométrie, médiane, intégrité,
reprise. Sentinel-2 est simulé : aucun test ne touche au réseau."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from pipeline import referentiels
from pipeline.config import Config
from pipeline.indices import derive
from pipeline.raster import composite
from pipeline.raster.classes import chemin_classes
from pipeline.raster.cog import ecrire_cog, lire_cog
from pipeline.raster.grille import Grille
from pipeline.sources import sentinel2

AUJOURD_HUI = date(2026, 11, 14)


def _element(
    jour: str, baseline: str | None, tuile: str = "30TWS", plateforme: str = "Sentinel-2A"
) -> Any:
    heure = datetime.fromisoformat(f"{jour}T11:00:00").replace(tzinfo=UTC)
    identifiant = f"S2A_MSIL2A_{jour.replace('-', '')}_N{baseline}_{tuile}_{baseline}"
    proprietes: dict[str, Any] = {
        "s2:mgrs_tile": tuile,
        "platform": plateforme,
        "eo:cloud_cover": 12.0,
    }
    if baseline is not None:
        proprietes["s2:processing_baseline"] = baseline
    return SimpleNamespace(id=identifiant, datetime=heure, properties=proprietes)


def test_offset_selon_la_baseline(config: Config) -> None:
    assert sentinel2.offset_de(config, "03.00") == 0.0
    assert sentinel2.offset_de(config, "04.00") == -1000.0
    assert sentinel2.offset_de(config, "05.10") == -1000.0
    assert sentinel2.offset_de(config, "02.12") == 0.0


def test_scene_sans_baseline_ecartee_et_comptee(config: Config) -> None:
    r = sentinel2.retenir(config, [_element("2022-07-10", "04.00"), _element("2022-07-12", None)])
    assert [s.jour.isoformat() for s in r.scenes] == ["2022-07-10"]
    assert (r.n_trouvees, r.n_baseline_inconnue, r.n_doublons) == (2, 1, 0)


def test_doublon_baseline_la_plus_recente(config: Config) -> None:
    elements = [
        _element("2022-07-10", "04.00"),
        _element("2022-07-10", "05.10"),
        _element("2022-07-10", "05.09", tuile="30TXS"),  # autre tuile : gardée
    ]
    r = sentinel2.retenir(config, elements)
    assert sorted((s.tuile, s.baseline) for s in r.scenes) == [
        ("30TWS", "05.10"),
        ("30TXS", "05.09"),
    ]
    assert r.n_doublons == 1


def test_plan_par_jour_et_offset(config: Config) -> None:
    """Deux tuiles du même jour s'assemblent ; deux offsets ne se mélangent jamais."""
    elements = [
        _element("2021-12-20", "03.00", tuile="30TWS"),
        _element("2021-12-20", "04.00", tuile="30TXS"),
        _element("2021-12-20", "04.00", tuile="30TWT"),
    ]
    cles = {sentinel2.cle_plan(s) for s in sentinel2.retenir(config, elements).scenes}
    assert cles == {"2021-12-20|0", "2021-12-20|-1000"}


def _bandes(b04: int, b08: int, b11: int, scl: int = 4, plans: int = 1) -> dict[str, Any]:
    forme = (plans, 4, 4)
    return {
        "B04": np.full(forme, b04, np.uint16),
        "B08": np.full(forme, b08, np.uint16),
        "B11": np.full(forme, b11, np.uint16),
        "SCL": np.full(forme, scl, np.uint8),
    }


def test_indices_meme_reflectance_avec_et_sans_offset() -> None:
    """Réflectances 0,1 (B04), 0,4 (B08), 0,2 (B11) : NDVI 0,6 et NDMI 1/3, avec ou sans offset."""
    avant = _bandes(1000, 4000, 2000)
    apres = _bandes(2000, 5000, 3000)  # + 1000 de décalage BOA
    for bandes, offset in ((avant, 0.0), (apres, -1000.0)):
        ndvi, ndmi = composite.indices_par_plan(
            bandes["B04"], bandes["B08"], bandes["B11"], bandes["SCL"],
            np.array([offset], np.float32), [4, 5, 6, 7], 10000.0,
        )  # fmt: skip
        assert ndvi[0, 0, 0] == pytest.approx(0.6, abs=1e-6)
        assert ndmi[0, 0, 0] == pytest.approx(1 / 3, abs=1e-6)


def test_indices_sans_correction_est_faux() -> None:
    """Sans l'offset d'une scène récente, le NDVI serait faussé (−0,13 à −0,29 au spike)."""
    apres = _bandes(2000, 5000, 3000)
    faux, _ = composite.indices_par_plan(
        apres["B04"], apres["B08"], apres["B11"], apres["SCL"],
        np.array([0.0], np.float32), [4, 5, 6, 7], 10000.0,
    )  # fmt: skip
    assert faux[0, 0, 0] == pytest.approx(0.4286, abs=1e-3)


def test_pixels_non_valides_en_nan() -> None:
    nuage = _bandes(1000, 4000, 2000, scl=9)
    ndvi, ndmi = composite.indices_par_plan(
        nuage["B04"], nuage["B08"], nuage["B11"], nuage["SCL"],
        np.array([0.0], np.float32), [4, 5, 6, 7], 10000.0,
    )  # fmt: skip
    assert np.isnan(ndvi).all() and np.isnan(ndmi).all()
    sans_donnee = _bandes(0, 4000, 2000)
    ndvi, _ = composite.indices_par_plan(
        sans_donnee["B04"], sans_donnee["B08"], sans_donnee["B11"], sans_donnee["SCL"],
        np.array([0.0], np.float32), [4, 5, 6, 7], 10000.0,
    )  # fmt: skip
    assert np.isnan(ndvi).all()


def test_mediane_ignore_les_plans_invalides() -> None:
    ndvi = np.full((4, 2, 2), np.nan, np.float32)
    ndvi[:3, 0, 0] = [0.2, 0.9, 0.5]  # médiane 0,5, 3 observations
    ndvi[0, 0, 1] = 0.7  # une seule observation
    med, _, n_obs = composite.mediane_mois(ndvi, ndvi.copy())
    assert med[0, 0] == pytest.approx(0.5)
    assert med[0, 1] == pytest.approx(0.7)
    assert np.isnan(med[1, 1])
    assert (n_obs[0, 0], n_obs[0, 1], n_obs[1, 1]) == (3, 1, 0)


def test_mediane_identique_a_nanmedian() -> None:
    rng = np.random.default_rng(1)
    plans = rng.uniform(-0.2, 0.95, (7, 30, 30)).astype(np.float32)
    plans[rng.uniform(size=plans.shape) < 0.4] = np.nan
    attendu = np.nanmedian(np.where(np.isnan(plans).all(axis=0), 0.0, plans), axis=0)
    med, _, _ = composite.mediane_mois(plans, plans)
    vide = np.isnan(plans).all(axis=0)
    assert np.allclose(med[~vide], attendu[~vide], atol=1e-6)
    assert np.isnan(med[vide]).all()


def test_en_entier() -> None:
    v = np.array([0.6, -0.25, np.nan], np.float32)
    assert composite.en_entier(v, 10000).tolist() == [6000, -2500, composite.NODATA_INDICE]


def test_integrite() -> None:
    bandes = _bandes(1000, 4000, 2000, plans=2)
    composite.verifier_integrite(bandes["SCL"], bandes["B04"], bandes["B08"], bandes["B11"], 2.0)
    corrompu = _bandes(1000, 4000, 2000, plans=2)
    for nom in ("B04", "B08", "B11"):
        corrompu[nom][1, :2, :] = 0  # la moitié du plan sans valeur alors que SCL en a
    with pytest.raises(composite.LectureCorrompueError, match="plan 1"):
        composite.verifier_integrite(
            corrompu["SCL"], corrompu["B04"], corrompu["B08"], corrompu["B11"], 2.0
        )


# --- Chaîne complète : un département de 30 x 20 pixels, deux jours, deux baselines ---------------


@pytest.fixture
def config_comp(config: Config, tmp_path: Path) -> Config:
    chemins = config.projet.chemins.model_copy(update={"rasters": tmp_path / "rasters"})
    composites = config.projet.satellite.composites.model_copy(update={"bloc_px": 256})
    satellite = config.projet.satellite.model_copy(update={"composites": composites})
    periode = config.projet.periode_reference.model_copy(
        update={
            "sentinel2": config.projet.periode_reference.sentinel2.model_copy(
                update={"debut": 2022}
            )
        }
    )
    projet = config.projet.model_copy(
        update={"chemins": chemins, "satellite": satellite, "periode_reference": periode}
    )
    return config.model_copy(update={"projet": projet})


class _Catalogue:
    def __init__(self, elements: list[Any]) -> None:
        self.elements = elements

    def search(self, **_: Any) -> Any:
        return SimpleNamespace(items=lambda: iter(self.elements))


def _territoire(monkeypatch: pytest.MonkeyPatch) -> Grille:
    # 300 x 300 pixels de 10 m : un seul bloc de 256 plus les bords : quatre blocs
    monkeypatch.setattr(referentiels, "emprise", lambda _c: box(1000, 1000, 4000, 4000))
    return Grille(1000, 4000, 300, 300, 10, "EPSG:2154")


def _lecteur(corrompu_une_fois: bool = False) -> Any:
    etat = {"appels": 0}

    def lire(elements: list[Any], scenes: list[Any], geobox: Any) -> Any:
        etat["appels"] += 1
        h, w = geobox.shape
        cles = sorted({sentinel2.cle_plan(s) for s in scenes})
        # chaque plan a la même réflectance : le DN porte l'offset de sa scène
        decalage = {c: (1000 if c.endswith("|-1000") else 0) for c in cles}
        b04 = np.stack([np.full((h, w), 1000 + decalage[c], np.uint16) for c in cles])
        b08 = np.stack([np.full((h, w), 4000 + decalage[c], np.uint16) for c in cles])
        b11 = np.stack([np.full((h, w), 2000 + decalage[c], np.uint16) for c in cles])
        scl = np.full((len(cles), h, w), 4, np.uint8)
        if corrompu_une_fois and etat["appels"] == 1:
            b04[:, : h // 2] = 0
            b08[:, : h // 2] = 0
            b11[:, : h // 2] = 0
        return cles, {"B04": b04, "B08": b08, "B11": b11, "SCL": scl}

    lire.etat = etat  # type: ignore[attr-defined]
    return lire


def _catalogue_juillet() -> _Catalogue:
    return _Catalogue(
        [
            _element("2022-07-02", "03.00"),  # sans offset
            _element("2022-07-07", "04.00", plateforme="Sentinel-2B"),
            _element("2022-07-07", "05.10", plateforme="Sentinel-2B"),  # remplace la 04.00
            _element("2022-07-12", None),  # écartée
        ]
    )


def test_chaine_complete(config_comp: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    grille = _territoire(monkeypatch)
    lecteur = _lecteur()
    ecrits = composite.construire(
        config_comp, AUJOURD_HUI, [2022], [7], catalogue=_catalogue_juillet(), lecteur=lecteur
    )
    dossier = composite.dossier_mois(config_comp, 2022, 7)
    assert ecrits == [dossier]
    ndvi, g, etiquettes = lire_cog(dossier / "ndvi.tif")
    assert g.forme == grille.forme and etiquettes["version_methodo"] == "D16"
    # les deux plans ont la même réflectance malgré des offsets différents : NDVI 0,6 partout
    assert (ndvi == 6000).all()
    n_obs, _, _ = lire_cog(dossier / "n_obs.tif")
    assert (n_obs == 2).all()
    rapport = json.loads((dossier / "rapport.json").read_text(encoding="utf-8"))
    assert rapport["scenes_trouvees"] == 4
    assert rapport["scenes_baseline_inconnue"] == 1
    assert rapport["scenes_doublons_ecartes"] == 1
    assert rapport["plans"] == 2 and rapport["pct_jamais_valide"] == 0.0
    plans = pd.read_parquet(dossier / "plans.parquet").set_index("date")
    assert plans.loc["2022-07-07", "baselines"] == "05.10"
    assert plans.loc["2022-07-02", "offset"] == 0.0


def test_reprise_et_recalcul_du_mois_en_cours(
    config_comp: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    _territoire(monkeypatch)
    premier = _lecteur()
    composite.construire(
        config_comp, AUJOURD_HUI, [2022], [7], catalogue=_catalogue_juillet(), lecteur=premier
    )
    second = _lecteur()
    composite.construire(
        config_comp, AUJOURD_HUI, [2022], [7], catalogue=_catalogue_juillet(), lecteur=second
    )
    assert second.etat["appels"] == 0  # mois terminé : conservé
    composite.construire(config_comp, AUJOURD_HUI, [2022], [7], True, _catalogue_juillet(), second)
    assert second.etat["appels"] > 0
    en_cours = _lecteur()
    composite.construire(
        config_comp,
        date(2022, 7, 20),
        [2022],
        [7],
        catalogue=_catalogue_juillet(),
        lecteur=en_cours,
    )
    assert en_cours.etat["appels"] > 0  # le mois en cours est recalculé à chaque appel


def test_lecture_corrompue_relue(config_comp: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    _territoire(monkeypatch)
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)
    lecteur = _lecteur(corrompu_une_fois=True)
    composite.construire(
        config_comp, AUJOURD_HUI, [2022], [7], catalogue=_catalogue_juillet(), lecteur=lecteur
    )
    dossier = composite.dossier_mois(config_comp, 2022, 7)
    ndvi, _, _ = lire_cog(dossier / "ndvi.tif")
    assert (ndvi == 6000).all()  # la lecture corrompue n'est pas entrée dans le composite
    assert json.loads((dossier / "rapport.json").read_text(encoding="utf-8"))["relectures"] == 1


def test_classes_stables_suivies(config_comp: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    grille = _territoire(monkeypatch)
    classes = np.zeros(grille.forme, np.uint8)
    classes[:100, :100] = 3  # pin maritime
    classes[100:150, :100] = 2  # chênes décidus
    ecrire_cog(chemin_classes(config_comp, 2022), classes, grille, 255, {})
    composite.construire(
        config_comp, AUJOURD_HUI, [2022], [7], catalogue=_catalogue_juillet(), lecteur=_lecteur()
    )
    d = pd.read_parquet(composite.dossier_mois(config_comp, 2022, 7) / "derive.parquet")
    assert set(d["classe"]) == {"pin_maritime", "chenes_decidus"}
    pin = d[(d["classe"] == "pin_maritime") & (d["date"] == "2022-07-02")].iloc[0]
    assert pin["n_px"] == 100 * 100 and pin["ndvi"] == pytest.approx(0.6)
    assert pin["plateformes"] == "Sentinel-2A"


# --- Contrôle de dérive ---------------------------------------------------------------------------


def _derive(lignes: list[tuple[str, str, float, float, float]]) -> pd.DataFrame:
    """Un plan par ligne : (date, plateforme, offset, ndvi, ndmi)."""
    return pd.DataFrame(
        [
            {"classe": "pin", "mois": d[:7], "date": d, "plateformes": p, "offset": o,
             "ndvi": v, "ndmi": w, "n_px": 100, "cle": f"{d}|{o}", "baselines": "x"}
            for d, p, o, v, w in lignes
        ]
    )  # fmt: skip


def _serie(biais_2c: float) -> pd.DataFrame:
    """Un plan tous les 2 jours en juillet 2022, de plus en plus vert (la phénologie), 2A/2B/2C en
    alternance ; le satellite 2C a un biais constant de NDVI."""
    plateformes = ["Sentinel-2A", "Sentinel-2B", "Sentinel-2C"]
    return _derive(
        [
            (f"2022-07-{jour:02d}", plateformes[k % 3], 0.0,
             0.5 + 0.01 * jour + (biais_2c if k % 3 == 2 else 0.0), 0.3)
            for k, jour in enumerate(range(1, 29, 2))
        ]
    )  # fmt: skip


def test_phenologie_sans_derive_ne_fait_pas_d_alerte() -> None:
    # le NDVI monte de 0,02 tous les 2 jours (0,14 sur le mois) : sans biais, aucun écart
    res = derive.residus(_serie(0.0), fenetre_jours=7, couverture_min=0.5)
    g = derive.groupes(res, plans_min=3)
    e = derive.ecarts(g, 0.03).query("critere == 'plateforme'")
    assert len(e) == 1 and e["ecart_ndvi"].iloc[0] < 0.01
    assert not e["anormal"].iloc[0]


def test_biais_d_un_satellite_detecte() -> None:
    res = derive.residus(_serie(0.06), fenetre_jours=7, couverture_min=0.5)
    e = derive.ecarts(derive.groupes(res, plans_min=3), 0.03).query("critere == 'plateforme'")
    assert e["anormal"].iloc[0]
    assert e["ecart_ndvi"].iloc[0] > 0.03
    assert e["groupes"].iloc[0] == "Sentinel-2A,Sentinel-2B,Sentinel-2C"


def test_plans_trop_couverts_par_les_nuages_ecartes() -> None:
    d = _serie(0.0)
    d.loc[d["date"] == "2022-07-05", ["n_px", "ndvi"]] = [10, 0.1]  # voit 10 % de la classe
    res = derive.residus(d, fenetre_jours=7, couverture_min=0.5)
    assert "2022-07-05" not in set(res["date"].dt.strftime("%Y-%m-%d"))
    assert res["residu_ndvi"].abs().max() < 0.05  # l'aberration (0,4) n'a pas faussé les voisins


def test_ecart_entre_offsets_un_seul_groupe_ignore() -> None:
    lignes = [(f"2022-01-{j:02d}", "Sentinel-2A", -1000.0 if j % 6 < 3 else 0.0, 0.6, 0.3)
              for j in range(1, 21, 2)]  # fmt: skip
    res = derive.residus(_derive(lignes), fenetre_jours=7, couverture_min=0.5)
    e = derive.ecarts(derive.groupes(res, plans_min=2), 0.03)
    assert e[e["critere"] == "offset"]["ecart_ndvi"].iloc[0] == pytest.approx(0.0)
    assert e[e["critere"] == "plateforme"].empty  # une seule plateforme
