"""[V2] Grille commune des rasters de la brique satellite : EPSG:2154, 10 m, calée sur des multiples
de la résolution (deux exécutions, ou deux machines, donnent la même grille)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rasterio.transform import Affine
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Grille:
    xmin: float  # bord gauche
    ymax: float  # bord haut
    largeur: int
    hauteur: int
    resolution: float
    crs: str

    @property
    def forme(self) -> tuple[int, int]:
        return (self.hauteur, self.largeur)

    @property
    def transform(self) -> Affine:
        return Affine(self.resolution, 0, self.xmin, 0, -self.resolution, self.ymax)

    @property
    def emprise(self) -> tuple[float, float, float, float]:
        """xmin, ymin, xmax, ymax."""
        return (
            self.xmin,
            self.ymax - self.hauteur * self.resolution,
            self.xmin + self.largeur * self.resolution,
            self.ymax,
        )


def grille_de(emprise: BaseGeometry, resolution: float, crs: str) -> Grille:
    """Plus petite grille alignée sur des multiples de `resolution` qui contient `emprise`."""
    xmin, ymin, xmax, ymax = emprise.bounds
    x0 = math.floor(xmin / resolution) * resolution
    y1 = math.ceil(ymax / resolution) * resolution
    largeur = math.ceil((xmax - x0) / resolution)
    hauteur = math.ceil((y1 - ymin) / resolution)
    return Grille(x0, y1, largeur, hauteur, resolution, crs)
