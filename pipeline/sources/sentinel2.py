"""[V2] Sentinel-2 L2A de Planetary Computer : scènes d'un mois, lecture de B04, B08, B11 et SCL.

Radiométrie identique pour toutes les scènes (D15, point 5).

Règles de radiométrie, dans l'ordre :
1. **L2A uniquement** (collection `sentinel-2-l2a`) ;
2. une scène sans baseline de traitement connue est écartée et comptée (jamais déduite de la date) ;
3. **une seule scène par tuile et par jour, la baseline la plus récente** (le catalogue en a deux
   versions pour la moitié des couples tuile-jour en 2022 et 2023) ;
4. l'offset BOA (−1000 depuis la baseline 04.00) est un attribut de la scène : le regroupement des
   scènes en plans de pixels se fait par jour **et** par offset, jamais en mélangeant deux offsets.

Les bibliothèques raster (extra `raster`) sont importées à l'appel : l'API n'en a pas besoin.
"""

from __future__ import annotations

import calendar
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from numpy.typing import NDArray

from pipeline.config import Config
from pipeline.raster.grille import Grille
from pipeline.sources.sentinel1 import REGLAGES_GDAL, bbox_wgs84

log = logging.getLogger(__name__)

BANDES = ("B04", "B08", "B11", "SCL")


@dataclass(frozen=True)
class Scene:
    """Une scène retenue : identifiant, tuile, jour, plateforme, baseline et offset BOA."""

    id: str
    tuile: str
    jour: date
    plateforme: str
    baseline: str
    offset: float
    nuages_pct: float


@dataclass
class Recherche:
    """Résultat de la recherche d'un mois : scènes retenues, éléments STAC, scènes écartées."""

    scenes: list[Scene]
    elements: list[Any]
    n_trouvees: int
    n_baseline_inconnue: int
    n_doublons: int


def baseline_de(element: Any) -> str | None:
    valeur = element.properties.get("s2:processing_baseline")
    return None if valeur in (None, "") else str(valeur)


def _numero(baseline: str) -> float:
    try:
        return float(baseline)
    except ValueError:
        return -1.0


def offset_de(config: Config, baseline: str) -> float:
    """Offset BOA à ajouter aux nombres numériques : 0 avant la baseline de coupure."""
    source = config.sources.sentinel2
    return source.offset_boa if _numero(baseline) >= _numero(source.baseline_offset) else 0.0


def cle_plan(scene: Scene) -> str:
    """Un plan de pixels = un jour et un offset (deux tuiles du même jour s'y mosaïquent)."""
    return f"{scene.jour.isoformat()}|{scene.offset:g}"


def retenir(config: Config, elements: list[Any]) -> Recherche:
    """Écarte les scènes sans baseline, puis garde la baseline la plus récente par tuile et jour."""
    inconnues = 0
    candidates: dict[tuple[str, date], list[tuple[Scene, Any]]] = {}
    for element in elements:
        baseline = baseline_de(element)
        if baseline is None:
            inconnues += 1
            continue
        proprietes = element.properties
        scene = Scene(
            id=element.id,
            tuile=str(proprietes.get("s2:mgrs_tile", element.id.split("_")[1])),
            jour=element.datetime.date(),
            plateforme=str(proprietes.get("platform", "")),
            baseline=baseline,
            offset=offset_de(config, baseline),
            nuages_pct=float(proprietes.get("eo:cloud_cover", float("nan"))),
        )
        candidates.setdefault((scene.tuile, scene.jour), []).append((scene, element))
    scenes: list[Scene] = []
    retenus: list[Any] = []
    doublons = 0
    for cle in sorted(candidates):
        # la plus récente : baseline la plus haute, puis identifiant le plus grand
        meilleure = max(candidates[cle], key=lambda c: (_numero(c[0].baseline), c[0].id))
        doublons += len(candidates[cle]) - 1
        scenes.append(meilleure[0])
        retenus.append(meilleure[1])
    return Recherche(scenes, retenus, len(elements), inconnues, doublons)


def chercher(
    config: Config, grille: Grille, annee: int, mois: int, catalogue: Any = None
) -> Recherche:
    """Scènes L2A du mois civil sur l'emprise de la grille, nuages de scène sous le seuil."""
    from pystac_client import Client

    source = config.sources.sentinel2
    if catalogue is None:
        catalogue = Client.open(source.stac)
    dernier = calendar.monthrange(annee, mois)[1]
    recherche = catalogue.search(
        collections=[source.collection],
        bbox=bbox_wgs84(grille),
        datetime=f"{annee}-{mois:02d}-01/{annee}-{mois:02d}-{dernier:02d}",
        query={"eo:cloud_cover": {"lt": source.nuages_max_scene_pct}},
    )
    return retenir(config, list(recherche.items()))


def lire_scenes(
    elements: list[Any],
    scenes: list[Scene],
    geobox: Any,
) -> tuple[list[str], dict[str, NDArray[Any]]]:
    """Plans de pixels d'une fenêtre : clés des plans (jour|offset) et tableaux (plan, y, x).

    `geobox` est un `odc.geo.geobox.GeoBox` (une fenêtre de la grille du projet). B11, à 20 m, est
    ramenée à 10 m au plus proche voisin."""
    import dask
    import odc.stac
    import planetary_computer

    os.environ.update(REGLAGES_GDAL)
    cles = {element.id: cle_plan(scene) for element, scene in zip(elements, scenes, strict=True)}
    donnees = odc.stac.load(
        elements,
        bands=list(BANDES),
        geobox=geobox,
        groupby=lambda element, _parse, _i: cles[element.id],
        resampling="nearest",
        chunks={"x": 1024, "y": 1024},
        patch_url=planetary_computer.sign,
        dtype="uint16",
        nodata=0,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        donnees = donnees.compute()
    # odc.stac trie les groupes par clé (ordre des chaînes) : l'ordre des plans en découle. Les
    # retrouver par l'heure est ambigu quand un même jour a deux offsets.
    ordre = sorted(set(cles.values()))
    if len(ordre) != donnees.sizes["time"]:
        raise RuntimeError(f"{len(ordre)} plans attendus, {donnees.sizes['time']} lus")
    return ordre, {bande: donnees[bande].values for bande in BANDES}
