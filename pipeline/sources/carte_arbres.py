"""[V2] Carte d'arbres récente (règle 2 de D15) : Impact Observatory 2023, à défaut WorldCover 2021.

Lues sur Planetary Computer (STAC) et mises sur la grille du projet.

Les bibliothèques raster (extra `raster`) sont importées à l'appel : l'API n'en a pas besoin.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer

from pipeline.config import Config, SourceArbres
from pipeline.raster.grille import Grille

log = logging.getLogger(__name__)

# Lectures par blocs d'un COG distant : reprises réseau et fusion des plages demandées
REGLAGES_GDAL = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "8",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "GDAL_HTTP_TIMEOUT": "60",
    "VSI_CACHE": "TRUE",
}


def _arbres_de(catalogue: Any, source: SourceArbres, grille: Grille) -> NDArray[np.bool_] | None:
    """Masque booléen des pixels d'arbre de la source, ou `None` si le catalogue n'a pas d'image."""
    import dask
    import odc.stac
    import planetary_computer
    from odc.geo.geobox import GeoBox

    xmin, ymin, xmax, ymax = grille.emprise
    vers_wgs84 = Transformer.from_crs(grille.crs, "EPSG:4326", always_xy=True)
    lon0, lat0 = vers_wgs84.transform(xmin, ymin)
    lon1, lat1 = vers_wgs84.transform(xmax, ymax)
    # Les quatre coins ne bornent pas toujours l'emprise après reprojection : marge de 0,05 degré
    bbox = (
        min(lon0, lon1) - 0.05,
        min(lat0, lat1) - 0.05,
        max(lon0, lon1) + 0.05,
        max(lat0, lat1) + 0.05,
    )
    elements = [
        i
        for i in catalogue.search(collections=[source.collection], bbox=bbox).items()
        # Les produits annuels datent par `start_datetime`, pas par `datetime`
        if str(i.properties.get("start_datetime") or i.datetime)[:4] == str(source.annee)
    ]
    if not elements:
        return None
    gb = GeoBox((grille.hauteur, grille.largeur), grille.transform, grille.crs)
    donnees = odc.stac.load(
        elements,
        bands=[source.bande],
        geobox=gb,
        groupby="solar_day",
        resampling="mode",
        patch_url=planetary_computer.sign,
        chunks={"x": 1024, "y": 1024},
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        valeurs = donnees[source.bande].compute().values
    classes = valeurs.max(axis=0) if valeurs.ndim == 3 else valeurs
    return np.asarray(np.isin(classes, source.classes_arbre))


def lire_arbres(config: Config, grille: Grille) -> tuple[NDArray[np.bool_], str]:
    """Masque d'arbres sur la grille et nom de la source utilisée (principale, sinon repli)."""
    import planetary_computer  # noqa: F401  (échec explicite si l'extra `raster` manque)
    from pystac_client import Client

    os.environ.update(REGLAGES_GDAL)
    carte = config.sources.occupation_sol.carte_arbres
    catalogue = Client.open(carte.stac)
    for source in (carte.principale, carte.repli):
        if source is None:
            continue
        masque = _arbres_de(catalogue, source, grille)
        if masque is not None:
            nom = f"{source.collection} {source.annee}"
            log.info("carte d'arbres : %s, %.1f %% des pixels", nom, 100 * masque.mean())
            return masque, nom
        log.warning("carte d'arbres : %s %d absente du catalogue", source.collection, source.annee)
    raise RuntimeError(
        "aucune carte d'arbres disponible (principale et repli absents du catalogue)"
    )
