"""[V2] Sentinel-1 RTC (VV) de Planetary Computer : recherche des passages d'une orbite relative et
lecture en décibels sur la grille du projet.

Les bibliothèques raster (extra `raster`) sont importées à l'appel : l'API n'en a pas besoin.
Le catalogue RTC commence en octobre 2014 : pas d'été 2014 pour une référence.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer

from pipeline.config import Config
from pipeline.raster.grille import Grille

log = logging.getLogger(__name__)

COLLECTION = "sentinel-1-rtc"
NODATA_RTC = -32768
REGLAGES_GDAL = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "8",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "GDAL_HTTP_TIMEOUT": "60",
    "VSI_CACHE": "TRUE",
}


def en_decibels(puissance: NDArray[np.floating[Any]]) -> NDArray[np.float32]:
    """Puissance rétrodiffusée (VV, linéaire) en dB ; nodata, zéros et valeurs négatives en NaN."""
    valide = np.isfinite(puissance) & (puissance > 0)
    db = 10 * np.log10(np.where(valide, puissance, 1))
    return np.where(valide, db, np.nan).astype(np.float32)


def bbox_wgs84(grille: Grille) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = grille.emprise
    vers = Transformer.from_crs(grille.crs, "EPSG:4326", always_xy=True)
    lon0, lat0 = vers.transform(xmin, ymin)
    lon1, lat1 = vers.transform(xmax, ymax)
    return (min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))


def chercher(
    config: Config, grille: Grille, orbite: int, debut: date, fin: date, catalogue: Any = None
) -> list[Any]:
    """Éléments STAC de l'orbite `orbite` entre `debut` et `fin` (inclus), triés par date."""
    from pystac_client import Client

    if catalogue is None:
        catalogue = Client.open(config.sources.sentinel2.stac)
    recherche = catalogue.search(
        collections=[COLLECTION],
        bbox=bbox_wgs84(grille),
        datetime=f"{debut.isoformat()}/{fin.isoformat()}",
    )
    elements = [i for i in recherche.items() if i.properties.get("sat:relative_orbit") == orbite]
    return sorted(elements, key=lambda i: i.datetime)


def lire_db(
    elements: list[Any], grille: Grille, lot: int = 6
) -> Iterator[tuple[list[date], NDArray[np.float32]]]:
    """Passages en dB sur la grille, par lots de dates (scènes d'un même jour fusionnées)."""
    import dask
    import odc.stac
    import planetary_computer
    from odc.geo.geobox import GeoBox

    os.environ.update(REGLAGES_GDAL)
    gb = GeoBox((grille.hauteur, grille.largeur), grille.transform, grille.crs)
    # Les scènes d'un même passage tiennent dans le même lot : une date ne se lit pas en deux fois
    par_jour: dict[date, list[Any]] = {}
    for element in elements:
        par_jour.setdefault(element.datetime.date(), []).append(element)
    jours = sorted(par_jour)
    for i in range(0, len(jours), lot):
        scenes = [e for j in jours[i : i + lot] for e in par_jour[j]]
        donnees = odc.stac.load(
            scenes,
            bands=["vv"],
            geobox=gb,
            groupby="solar_day",
            chunks={"x": 2048, "y": 2048},
            patch_url=planetary_computer.sign,
            dtype="float32",
            nodata=NODATA_RTC,
        )
        with dask.config.set(scheduler="threads", num_workers=8):
            valeurs = donnees.vv.compute().values
        dates = [date.fromisoformat(str(t)[:10]) for t in donnees.time.values]
        yield dates, en_decibels(valeurs)
