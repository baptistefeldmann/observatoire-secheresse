"""Spike V0 n°1 : données SIM quotidiennes de Météo-France.

Mesure le délai de mise à disposition, décrit le format, sélectionne les mailles SAFRAN du
territoire configuré et compare le fichier annuel en cours au fichier `latest`.

    uv run python docs/spikes/sim_meteo.py --cache <dossier> --sortie <dossier>

Les fichiers téléchargés sont conservés dans le cache. Script jetable, hors pipeline.
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import httpx
import numpy as np
import pandas as pd
from shapely.geometry import box

from pipeline.config import charger_config

CONFIG = charger_config()
SIM = CONFIG.sources.sim
DEP = CONFIG.projet.territoire.code_departement
CRS = CONFIG.projet.crs
VARIABLES = ["PRELIQ", "PRENEI", "ETP", "SWI", "T"]

client = httpx.Client(timeout=600, follow_redirects=True)


def ressources() -> dict[str, str]:
    """Titre de ressource -> URL de téléchargement."""
    d = client.get(f"{SIM.api_datagouv}datasets/{SIM.jeu_datagouv}/").json()
    return {r["title"]: r["url"] for r in d["resources"]}


def telecharger(url: str, chemin: Path) -> float:
    if chemin.exists():
        return 0.0
    debut = time.perf_counter()
    with client.stream("GET", url) as r, chemin.open("wb") as f:
        r.raise_for_status()
        for bloc in r.iter_bytes():
            f.write(bloc)
    return time.perf_counter() - debut


def contour() -> Any:
    url = f"{CONFIG.sources.geo_api}departements/{DEP}/communes"
    geojson = client.get(url, params={"format": "geojson", "geometry": "contour"}).json()
    return gpd.GeoDataFrame.from_features(geojson["features"], crs=4326).to_crs(CRS).union_all()


def mailles(points: pd.DataFrame) -> gpd.GeoDataFrame:
    """Carrés de `pas_grille_m` centrés sur les points LAMBX/LAMBY, reprojetés."""
    u, demi = SIM.unite_coordonnees_m, SIM.pas_grille_m / 2
    geoms = [
        box(x * u - demi, y * u - demi, x * u + demi, y * u + demi)
        for x, y in zip(points.LAMBX, points.LAMBY, strict=True)
    ]
    return gpd.GeoDataFrame(points, geometry=geoms, crs=SIM.crs_grille).to_crs(CRS)


def lire(chemin: Path, cles: set[tuple[int, int]]) -> tuple[pd.DataFrame, float]:
    debut = time.perf_counter()
    d = pd.read_csv(chemin, sep=";")
    d = d[[k in cles for k in zip(d.LAMBX, d.LAMBY, strict=True)]]
    return d, time.perf_counter() - debut


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.sortie.mkdir(parents=True, exist_ok=True)
    annee = date.today().year

    urls = ressources()
    fichiers = {}
    for titre in ("QUOT_SIM2_latest", f"QUOT_SIM2_{annee}", f"QUOT_SIM2_{annee - 1}"):
        chemin = args.cache / f"{titre}.csv.gz"
        duree = telecharger(urls[titre], chemin)
        fichiers[titre] = chemin
        print(f"{titre:<20} {chemin.stat().st_size / 1e6:6.1f} Mo  téléchargé en {duree:4.1f} s")

    latest = pd.read_csv(fichiers["QUOT_SIM2_latest"], sep=";")
    delai = (date.today() - pd.to_datetime(str(latest.DATE.max())).date()).days
    print(f"\nlatest : {latest.DATE.min()} -> {latest.DATE.max()}, délai {delai} j")
    print(f"colonnes : {', '.join(latest.columns)}")

    dep = contour()
    grille = mailles(latest[["LAMBX", "LAMBY"]].drop_duplicates())
    sel = grille[grille.intersects(dep.buffer(CONFIG.projet.emprise.tampon_m))].copy()
    sel["part_dans_territoire"] = sel.intersection(dep).area / sel.area
    couverture = sel.intersection(dep).area.sum() / dep.area
    print(
        f"\nmailles : {len(grille)} en métropole, {len(sel)} pour le territoire "
        f"(tampon {CONFIG.projet.emprise.tampon_m:.0f} m), couverture {couverture:.2%}"
    )
    sel.to_file(args.sortie / "mailles_sim.gpkg")

    cles = set(zip(sel.LAMBX, sel.LAMBY, strict=True))
    an, t_an = lire(fichiers[f"QUOT_SIM2_{annee}"], cles)
    prec, t_prec = lire(fichiers[f"QUOT_SIM2_{annee - 1}"], cles)
    lat, _ = lire(fichiers["QUOT_SIM2_latest"], cles)
    print(f"\nfichier {annee} : {an.DATE.min()} -> {an.DATE.max()}, lecture {t_an:.0f} s")
    print(f"fichier {annee - 1} : {len(prec)} lignes pour le territoire, lecture {t_prec:.0f} s")

    commun = an.merge(lat, on=["LAMBX", "LAMBY", "DATE"], suffixes=("_an", "_lat"))
    print(f"\n{annee} / latest : {commun.DATE.nunique()} jours communs")
    for v in VARIABLES:
        ecart = (commun[f"{v}_an"] - commun[f"{v}_lat"]).abs()
        print(f"  {v:<7} identiques {np.mean(ecart < 1e-9):6.1%}  écart max {ecart.max():.3f}")
    print(f"\nSWI : de {lat.SWI.min():.3f} à {lat.SWI.max():.3f} (fraction, pas des %)")


if __name__ == "__main__":
    main()
