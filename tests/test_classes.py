"""Classes de la brique satellite mises à la grille (V2.1b) : règles 1 et 2 de D15, érosion,
lecture des couches WFS, écriture du COG. Aucun test ne touche au réseau."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import geopandas as gpd
import httpx
import numpy as np
import pytest
import rasterio
from shapely.geometry import box, mapping

from pipeline.config import Config, NomenclatureOcs
from pipeline.http import ClientHttp
from pipeline.raster import classes
from pipeline.raster.grille import Grille, grille_de
from pipeline.sources import ign_classes

CHENE, PIN, PEUPLERAIE, LANDES = 2, 3, 6, 7
BLE, PRAIRIE_PERMANENTE = 103, 101
HORS, NODATA = 0, 255

# Grille de 40 x 40 pixels de 10 m dont le coin haut gauche est en (1000, 1400)
GRILLE = Grille(1000, 1400, 40, 40, 10, "EPSG:2154")


@pytest.fixture
def nomenclature(config: Config) -> NomenclatureOcs:
    return config.nomenclature_ocs


def _carre(x: float, y: float, cote: float) -> Any:
    """Carré de `cote` mètres dont le coin haut gauche est à (x, y) en mètres depuis la grille."""
    return box(1000 + x, 1400 - y - cote, 1000 + x + cote, 1400 - y)


def _bdforet(*postes: tuple[str, Any]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"code_tfv": [p[0] for p in postes]}, geometry=[p[1] for p in postes], crs="EPSG:2154"
    )


def _rpg(*parcelles: tuple[int, Any]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"code_cultu": ["X"] * len(parcelles), "code_group": [p[0] for p in parcelles]},
        geometry=[p[1] for p in parcelles],
        crs="EPSG:2154",
    )


def test_grille_alignee_sur_la_resolution() -> None:
    g = grille_de(box(1003, 2007, 1045, 2058), 10, "EPSG:2154")
    assert (g.xmin, g.ymax) == (1000, 2060)
    assert g.emprise == (1000, 2000, 1050, 2060)
    assert g.forme == (6, 5)


def test_erosion_d_un_pixel(nomenclature: NomenclatureOcs) -> None:
    # polygone de 10 x 10 pixels : 8 x 8 pixels purs (érosion de 10 m)
    foret = classes.classes_foret(
        GRILLE, nomenclature, _bdforet(("FF1G01-01", _carre(100, 100, 100)))
    )
    assert int((foret == CHENE).sum()) == 64
    assert foret[10:20, 10:20].sum() == 64 * CHENE
    assert foret[10, 10] == HORS  # pixel de bord


def test_postes_de_la_bd_foret(nomenclature: NomenclatureOcs) -> None:
    foret = classes.classes_foret(
        GRILLE,
        nomenclature,
        _bdforet(
            ("FF2-51-51", _carre(0, 0, 100)),  # pin maritime
            ("FF1-10-10", _carre(200, 0, 100)),  # châtaignier : en réserve
            ("FF0", _carre(0, 200, 100)),  # sans couvert : exclu
        ),
    )
    assert set(np.unique(foret)) == {HORS, PIN}


def test_poste_inconnu_refuse(nomenclature: NomenclatureOcs) -> None:
    with pytest.raises(ValueError, match="XX9"):
        classes.classes_foret(GRILLE, nomenclature, _bdforet(("XX9", _carre(0, 0, 100))))


def test_regle_2_pixels_sans_arbre(nomenclature: NomenclatureOcs) -> None:
    base = classes.classes_foret(
        GRILLE,
        nomenclature,
        _bdforet(
            ("FF1G01-01", _carre(0, 0, 100)),  # chênes
            ("FP", _carre(200, 0, 100)),  # peupleraie : exemptée
            ("LA4", _carre(0, 200, 100)),  # landes : exemptées
        ),
    )
    arbres = np.zeros(GRILLE.forme, dtype=bool)  # aucun arbre sur la carte récente
    resultat, retires = classes.retirer_non_arbres(base, arbres, nomenclature)
    assert retires == 64
    assert int((resultat == CHENE).sum()) == 0
    assert int((resultat == PEUPLERAIE).sum()) == 64
    assert int((resultat == LANDES).sum()) == 64


def test_regle_2_arbres_gardes(nomenclature: NomenclatureOcs) -> None:
    base = classes.classes_foret(GRILLE, nomenclature, _bdforet(("FF1G01-01", _carre(0, 0, 100))))
    resultat, retires = classes.retirer_non_arbres(base, np.ones(GRILLE.forme, bool), nomenclature)
    assert retires == 0
    assert np.array_equal(resultat, base)


def test_regle_1_le_rpg_prime(nomenclature: NomenclatureOcs) -> None:
    # forêt de chênes de 10 x 10 pixels ; une parcelle de ble la recouvre en partie (moitié droite)
    base = classes.classes_foret(GRILLE, nomenclature, _bdforet(("FF1G01-01", _carre(0, 0, 100))))
    ble = _carre(50, 0, 100)
    # parcelle d'un groupe hors classes (gel, groupe 11) : efface aussi, sans poser de classe
    gel = _carre(0, 200, 100)
    resultat, effaces = classes.appliquer_rpg(base, GRILLE, nomenclature, _rpg((1, ble), (11, gel)))
    assert effaces > 0
    # côté gauche (pixels purs de forêt hors de la parcelle) : chêne conservé
    assert resultat[3, 2] == CHENE
    # côté droit : le ble remplace le chêne sur les pixels purs de la parcelle
    assert resultat[3, 8] == BLE
    # pixel de forêt sous l'emprise non érodée de la parcelle, mais sur son bord érodé : effacé
    assert resultat[3, 5] != CHENE
    # groupe hors classes : rien posé
    assert set(np.unique(resultat[20:30, 0:10])) == {HORS}


def test_rpg_sans_effet_si_desactive(nomenclature: NomenclatureOcs) -> None:
    regles = nomenclature.regles.model_copy(update={"rpg_prime": False})
    sans = nomenclature.model_copy(update={"regles": regles})
    base = classes.classes_foret(GRILLE, sans, _bdforet(("FF1G01-01", _carre(0, 0, 100))))
    resultat, effaces = classes.appliquer_rpg(base, GRILLE, sans, _rpg((1, _carre(0, 0, 100))))
    assert effaces == 0
    assert int((resultat == CHENE).sum()) == 0  # mais la culture est posée par-dessus
    assert int((resultat == BLE).sum()) == 64


def test_classer_marque_le_hors_emprise(nomenclature: NomenclatureOcs) -> None:
    grille_classes, bilan = classes.classer(
        GRILLE,
        nomenclature,
        _bdforet(("FF2-51-51", _carre(0, 0, 100))),
        _rpg((18, _carre(200, 0, 100))),
        np.ones(GRILLE.forme, bool),
        2025,
        "test",
        emprise=_carre(0, 0, 300),  # les 30 premiers pixels seulement
    )
    assert grille_classes[0, 39] == NODATA
    assert bilan.pixels[PIN] == 64
    assert bilan.pixels[PRAIRIE_PERMANENTE] == 64
    assert bilan.pixels[NODATA] == 40 * 40 - 30 * 30


def test_ecriture_cog_et_idempotence(tmp_path: Path, nomenclature: NomenclatureOcs) -> None:
    grille_classes, _ = classes.classer(
        GRILLE,
        nomenclature,
        _bdforet(("FF2-51-51", _carre(0, 0, 100))),
        _rpg((1, _carre(200, 0, 100))),
        np.ones(GRILLE.forme, bool),
        2025,
        "test",
    )
    chemin = tmp_path / "classes" / "ocs_2025_test.tif"
    tags = {"annee_rpg": "2025", "nomenclature": classes.empreinte_nomenclature(nomenclature)}
    classes.ecrire_classes(chemin, grille_classes, GRILLE, NODATA, tags)
    premier = chemin.read_bytes()
    classes.ecrire_classes(chemin, grille_classes, GRILLE, NODATA, tags)
    assert chemin.read_bytes() == premier
    assert not list(chemin.parent.glob("*.tmp.tif"))
    with rasterio.open(chemin) as src:
        assert src.crs.to_epsg() == 2154
        assert src.dtypes == ("uint8",)
        assert src.nodata == NODATA
        assert src.res == (10, 10)
        assert tuple(src.bounds) == (1000, 1000, 1400, 1400)
        assert src.tags()["annee_rpg"] == "2025"
        assert np.array_equal(src.read(1), grille_classes)


def test_empreinte_de_nomenclature_change(nomenclature: NomenclatureOcs) -> None:
    autre = nomenclature.model_copy(
        update={"regles": nomenclature.regles.model_copy(update={"ndvi_ete_min": 0.5})}
    )
    assert classes.empreinte_nomenclature(nomenclature) != classes.empreinte_nomenclature(autre)


# --- lecture des couches WFS --------------------------------------------------------------------


def _page(objets: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"type": "FeatureCollection", "features": objets})


def _objet(identifiant: str, geometrie: Any, **proprietes: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": identifiant,  # identifiant GeoJSON de l'objet, hors des propriétés (RPG)
        "geometry": mapping(geometrie),
        "properties": dict(proprietes),
    }


@pytest.fixture
def config_pages(config: Config) -> Config:
    """Pages WFS de deux objets pour exercer la pagination."""
    source = config.sources.occupation_sol.model_copy(update={"page": 2})
    return config.model_copy(
        update={"sources": config.sources.model_copy(update={"occupation_sol": source})}
    )


def test_bd_foret_paginee(config_pages: Config, fabrique_client: Callable[..., ClientHttp]) -> None:
    demandes: list[dict[str, str]] = []
    pages = [
        [
            _objet("a", _carre(0, 0, 50), code_tfv="FP"),
            _objet("b", _carre(60, 0, 50), code_tfv="FF0"),
        ],
        [
            _objet("b", _carre(60, 0, 50), code_tfv="FF0"),
            _objet("c", _carre(0, 60, 50), code_tfv="LA4"),
        ],
        [],
    ]

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        demandes.append(dict(requete.url.params))
        return _page(pages[int(requete.url.params["STARTINDEX"]) // 2])

    client = fabrique_client(gestionnaire)
    gdf = ign_classes.ingerer_bdforet(config_pages, client, (1000, 1000, 1400, 1400))
    assert sorted(gdf["code_tfv"]) == ["FF0", "FP", "LA4"]  # « b » lu deux fois, gardé une
    assert [d["STARTINDEX"] for d in demandes] == ["0", "2", "4"]
    assert demandes[0]["SORTBY"] == "id"
    assert demandes[0]["TYPENAMES"] == config_pages.sources.occupation_sol.bdforet
    assert demandes[0]["BBOX"] == "1000,1000,1400,1400,urn:ogc:def:crs:EPSG::2154"
    assert gdf.crs.to_epsg() == 2154


def test_rpg_codes_en_entiers(
    config_pages: Config, fabrique_client: Callable[..., ClientHttp]
) -> None:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if requete.url.params["STARTINDEX"] != "0":
            return _page([])
        return _page(
            [
                _objet("p1", _carre(0, 0, 50), code_cultu="BTH", code_group="1"),
                _objet("p2", _carre(60, 0, 50), code_cultu="PPH", code_group="18"),
            ]
        )

    client = fabrique_client(gestionnaire)
    gdf = ign_classes.ingerer_rpg(config_pages, client, 2018, (1000, 1000, 1400, 1400))
    assert gdf["code_group"].tolist() == [1, 18]
    assert gdf["code_group"].dtype.kind == "i"


def test_rpg_tri_selon_l_annee(
    config_pages: Config, fabrique_client: Callable[..., ClientHttp]
) -> None:
    tris: dict[int, str] = {}
    for annee in (2024, 2025):

        def gestionnaire(requete: httpx.Request, annee: int = annee) -> httpx.Response:
            tris[annee] = requete.url.params["SORTBY"]
            return _page([_objet("p", _carre(0, 0, 50), code_cultu="BTH", code_group="1")])

        ign_classes.ingerer_rpg(
            config_pages, fabrique_client(gestionnaire), annee, (1000, 1000, 1400, 1400)
        )
    assert tris == {2024: "id_parcel", 2025: "num_parcel"}


def test_rpg_annee_sans_couche(config: Config, client: ClientHttp) -> None:
    with pytest.raises(ValueError, match="1999"):
        ign_classes.ingerer_rpg(config, client, 1999, (0, 0, 1, 1))


def test_couche_vide_refusee(config: Config, fabrique_client: Callable[..., ClientHttp]) -> None:
    client = fabrique_client(lambda requete: _page([]))
    with pytest.raises(RuntimeError, match="aucun objet"):
        ign_classes.ingerer_bdforet(config, client, (0, 0, 1, 1))


def test_page_vide_relue(
    config: Config, fabrique_client: Callable[..., ClientHttp], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt

    # même reprise que la production, sans attente
    monkeypatch.setattr(
        ign_classes,
        "_relire",
        retry(retry=retry_if_exception_type(ValueError), stop=stop_after_attempt(3), reraise=True),
    )
    reponses = iter(
        [
            httpx.Response(200, content=b""),  # corps vide : reprise
            _page([_objet("a", _carre(0, 0, 50), code_tfv="FP")]),
        ]
    )
    client = fabrique_client(lambda requete: next(reponses))
    gdf = ign_classes.ingerer_bdforet(config, client, (1000, 1000, 1400, 1400))
    assert gdf["code_tfv"].tolist() == ["FP"]


def test_page_toujours_invalide_leve(
    config: Config, fabrique_client: Callable[..., ClientHttp], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt

    monkeypatch.setattr(
        ign_classes,
        "_relire",
        retry(retry=retry_if_exception_type(ValueError), stop=stop_after_attempt(2), reraise=True),
    )
    client = fabrique_client(lambda requete: httpx.Response(200, content=b"<html>"))
    with pytest.raises(ValueError):
        ign_classes.ingerer_bdforet(config, client, (1000, 1000, 1400, 1400))


def test_complement_de_la_carte_d_arbres(nomenclature: NomenclatureOcs) -> None:
    arbres = np.zeros(GRILLE.forme, dtype=bool)
    arbres[0:5, 0:5] = True  # 25 pixels d'arbres déjà connus, hors des îlots
    bdforet = _bdforet(("FF1-00", _carre(100, 100, 100)), ("FF1G01-01", _carre(250, 250, 100)))
    complete, ajoutes = classes.completer_arbres(arbres, GRILLE, nomenclature, bdforet)
    assert ajoutes == 100  # polygone entier de 10 x 10 pixels, pas érodé
    assert int(complete.sum()) == 125
    assert not complete[26:30, 26:30].any()  # un autre poste n'est pas ajouté
    assert np.array_equal(arbres[0:5, 0:5], complete[0:5, 0:5])


def test_les_ilots_survivent_a_la_regle_2(nomenclature: NomenclatureOcs) -> None:
    bdforet = _bdforet(("FF1-00", _carre(100, 100, 100)), ("FF1G01-01", _carre(250, 250, 100)))
    aucun_arbre = np.zeros(GRILLE.forme, dtype=bool)
    arbres, _ = classes.completer_arbres(aucun_arbre, GRILLE, nomenclature, bdforet)
    grille_classes, bilan = classes.classer(
        GRILLE, nomenclature, bdforet, _rpg((19, _carre(0, 300, 50))), arbres, 2025, "test"
    )
    feuillus_melanges = 1
    assert bilan.pixels[feuillus_melanges] == 64  # îlot gardé (pixels purs)
    assert CHENE not in bilan.pixels  # chêne hors îlots : plus d'arbre, retiré
    assert grille_classes[12, 12] == feuillus_melanges


def test_complement_vide(nomenclature: NomenclatureOcs) -> None:
    sans = nomenclature.model_copy(
        update={"regles": nomenclature.regles.model_copy(update={"arbres_complement_tfv": []})}
    )
    arbres = np.zeros(GRILLE.forme, dtype=bool)
    complete, ajoutes = classes.completer_arbres(
        arbres, GRILLE, sans, _bdforet(("FF1-00", _carre(0, 0, 100)))
    )
    assert ajoutes == 0
    assert not complete.any()
