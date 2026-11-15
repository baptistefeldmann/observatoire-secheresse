"""[V2] Lecture et écriture de COG sur la grille du projet (EPSG:2154, 10 m)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from pipeline.raster.grille import Grille


def ecrire_cog(
    chemin: Path,
    tableau: NDArray[Any],
    grille: Grille,
    nodata: float,
    tags: dict[str, str],
    predicteur: bool = False,
) -> None:
    """COG d'une seule bande (deflate, aperçus par le mode), écrit via un fichier temporaire."""
    import rasterio
    import rasterio.shutil

    chemin.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.MemoryFile() as memoire:
        with memoire.open(
            driver="GTiff",
            height=grille.hauteur,
            width=grille.largeur,
            count=1,
            dtype=str(tableau.dtype),
            crs=grille.crs,
            transform=grille.transform,
            nodata=nodata,
        ) as dst:
            dst.write(tableau, 1)
            dst.update_tags(**tags)
        temporaire = chemin.with_suffix(".tmp.tif")
        options: dict[str, Any] = {"compress": "DEFLATE", "overview_resampling": "mode"}
        if predicteur:
            options["predictor"] = "YES"
        with memoire.open() as src:
            rasterio.shutil.copy(src, temporaire, driver="COG", **options)
    temporaire.replace(chemin)


def lire_cog(chemin: Path) -> tuple[NDArray[Any], Grille, dict[str, str]]:
    """Tableau (première bande), grille et étiquettes d'un COG du projet."""
    import rasterio

    if not chemin.is_file():
        raise FileNotFoundError(f"{chemin} absent")
    with rasterio.open(chemin) as src:
        transform = src.transform
        grille = Grille(
            transform.c, transform.f, src.width, src.height, float(transform.a), src.crs.to_string()
        )
        etiquettes = {k: v for k, v in src.tags().items() if k != "AREA_OR_POINT"}
        return np.asarray(src.read(1)), grille, etiquettes
