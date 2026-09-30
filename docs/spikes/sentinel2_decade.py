"""Spike V0 n°4 : composite Sentinel-2 d'une décade sur le territoire, via Planetary Computer.

Enchaîne les étapes du §7.3 de la spec : recherche STAC, chargement odc-stac reprojeté sur
une grille fixe en EPSG:2154, masquage SCL, correction de l'offset BOA, NDVI et NDMI par
date, médiane sur la décade, écriture en COG int16. Mesure temps, volume et pixels valides.

    uv run python docs/spikes/sentinel2_decade.py --debut 2025-07-11 --fin 2025-07-20 \
        --sortie rasters/spike_v0

Script jetable, hors pipeline. Repris des enseignements d'eo_factory (signature des URL,
offset BOA, dtype/nodata explicites, liste blanche SCL).
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import time
from pathlib import Path
from typing import Any

import dask
import geopandas as gpd
import httpx
import numpy as np
import odc.stac
import planetary_computer
import rioxarray  # noqa: F401  (accesseur .rio)
import xarray as xr
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import geometry_mask

from pipeline.config import charger_config

CONFIG = charger_config()
S2 = CONFIG.sources.sentinel2
CRS = CONFIG.projet.crs
NODATA = -32768

# Lecture raster distante (repris d'eo_factory) : retries HTTP côté GDAL, ranges fusionnés
os.environ.update(
    {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "GDAL_HTTP_MAX_RETRY": "8",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "GDAL_HTTP_TIMEOUT": "60",
        "VSI_CACHE": "TRUE",
    }
)


class Chrono:
    def __init__(self) -> None:
        self.etapes: dict[str, float] = {}
        self._t = time.perf_counter()

    def top(self, nom: str) -> None:
        t = time.perf_counter()
        self.etapes[nom] = round(t - self._t, 1)
        self._t = t
        print(f"  {nom:<28} {self.etapes[nom]:7.1f} s")


def territoire() -> Any:
    dep = CONFIG.projet.territoire.code_departement
    url = f"{CONFIG.sources.geo_api}departements/{dep}/communes"
    params = {"format": "geojson", "geometry": "contour"}
    geojson = httpx.get(url, params=params, timeout=120).json()
    contour = gpd.GeoDataFrame.from_features(geojson["features"], crs=4326).to_crs(CRS)
    return contour.union_all().buffer(CONFIG.projet.emprise.tampon_m)


def offset_boa(item: Any) -> float:
    baseline = item.properties.get("s2:processing_baseline")
    if baseline is not None and float(baseline) >= float(S2.baseline_offset):
        return S2.offset_boa
    return 0.0


def offsets_par_date(items: list[Any], temps: np.ndarray) -> xr.DataArray:
    """Un offset par pas de temps du cube (groupby solar_day) ; erreur si baselines mêlées."""
    par_jour: dict[np.datetime64, set[float]] = {}
    for it in items:
        par_jour.setdefault(np.datetime64(it.datetime.date()), set()).add(offset_boa(it))
    valeurs = []
    for t in temps:
        jour = t.astype("datetime64[D]")
        proche = min(par_jour, key=lambda d: abs(d - jour))
        candidats = par_jour[proche]
        if len(candidats) > 1:
            raise RuntimeError(f"baselines mêlées le {jour} : {candidats}")
        valeurs.append(candidats.pop())
    return xr.DataArray(np.array(valeurs, "float32"), dims=("time",), coords={"time": temps})


def indice(a: xr.DataArray, b: xr.DataArray) -> xr.DataArray:
    return (a - b) / (a + b)


def ecrire_cog(raster: xr.DataArray, chemin: Path, nodata: int | None, predictor: int) -> None:
    raster = raster.rio.write_crs(CRS)
    if nodata is not None:
        raster = raster.rio.write_nodata(nodata)
    raster.rio.to_raster(
        chemin,
        driver="COG",
        compress="DEFLATE",
        predictor=predictor,
        overview_resampling="average",
        BLOCKSIZE=512,
    )


def ecrire_indice(valeur: xr.DataArray, chemin: Path) -> None:
    """Indice x facteur_echelle en int16 ; écrêtage AVANT le remplissage du nodata."""
    code = (valeur * S2.facteur_echelle).round().clip(-32767, 32767).fillna(NODATA)
    ecrire_cog(code.astype("int16"), chemin, NODATA, predictor=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debut", required=True)
    parser.add_argument("--fin", required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args()
    args.sortie.mkdir(parents=True, exist_ok=True)
    chrono = Chrono()
    print(f"Décade {args.debut} -> {args.fin}")

    zone = territoire()
    bbox4326 = tuple(gpd.GeoSeries([zone], crs=CRS).to_crs(4326).total_bounds)
    items = list(
        Client.open(S2.stac)
        .search(
            collections=[S2.collection],
            bbox=bbox4326,
            datetime=f"{args.debut}/{args.fin}",
            query={"eo:cloud_cover": {"lt": S2.nuages_max_scene_pct}},
        )
        .items()
    )
    chrono.top("recherche STAC")
    print(
        f"  {len(items)} scènes, {len({i.datetime.date() for i in items})} jours, "
        f"tuiles {sorted({i.properties['s2:mgrs_tile'] for i in items})}"
    )

    # Grille fixe : bords alignés sur des multiples de la résolution en EPSG:2154
    geobox = GeoBox.from_bbox(zone.bounds, crs=CRS, resolution=S2.resolution_m)
    dans_zone = xr.DataArray(
        ~geometry_mask([zone], out_shape=geobox.shape, transform=geobox.affine),
        dims=("y", "x"),
    )
    print(
        f"  grille {geobox.shape[1]} x {geobox.shape[0]} px, "
        f"{int(dans_zone.sum())} px dans le territoire"
    )

    ds = odc.stac.load(
        items,
        bands=["B04", "B08", "B11", "SCL"],
        geobox=geobox,
        chunks={"x": 2048, "y": 2048},
        groupby="solar_day",
        resampling={"*": "nearest"},
        patch_url=planetary_computer.sign,
        dtype="uint16",
        nodata=0,
    )
    valide = ds.SCL.isin(S2.scl_valides) & (ds.B04 > 0) & (ds.B08 > 0) & (ds.B11 > 0)
    offset = offsets_par_date(items, ds.time.values)
    refl = {
        b: ((ds[b].astype("float32") + offset) / S2.facteur_echelle).clip(min=0)
        for b in ("B04", "B08", "B11")
    }
    ndvi = indice(refl["B08"], refl["B04"]).where(valide)
    ndmi = indice(refl["B08"], refl["B11"]).where(valide)
    ndvi_brut = indice(ds.B08.astype("float32"), ds.B04.astype("float32")).where(valide)

    nb_obs = valide.sum("time").where(dans_zone, 0)
    med_ndvi = ndvi.chunk({"time": -1}).median("time").where(dans_zone)
    med_ndmi = ndmi.chunk({"time": -1}).median("time").where(dans_zone)
    med_brut = ndvi_brut.chunk({"time": -1}).median("time").where(dans_zone)

    with dask.config.set(scheduler="threads", num_workers=os.cpu_count()):
        med_ndvi, med_ndmi, med_brut, nb_obs = dask.compute(med_ndvi, med_ndmi, med_brut, nb_obs)
    chrono.top("chargement + composite")
    print(f"  {ds.sizes['time']} dates dans le cube")

    fichiers = {}
    for nom, val in (("ndvi", med_ndvi), ("ndmi", med_ndmi)):
        fichiers[nom] = args.sortie / f"{nom}_{args.debut}_{args.fin}.tif"
        ecrire_indice(val, fichiers[nom])
    # Qualité commune aux deux indices : observations valides par pixel, uint8, 0 hors zone
    fichiers["nb_obs"] = args.sortie / f"nb_obs_{args.debut}_{args.fin}.tif"
    ecrire_cog(nb_obs.clip(0, 255).astype("uint8"), fichiers["nb_obs"], None, predictor=1)
    chrono.top("écriture COG")

    n_zone = int(dans_zone.sum())
    obs = nb_obs.values[dans_zone.values]
    bilan = {
        "decade": [args.debut, args.fin],
        "scenes": len(items),
        "dates_cube": int(ds.sizes["time"]),
        "grille_px": list(geobox.shape),
        "px_territoire": n_zone,
        "part_pixels_valides": round(float((obs > 0).mean()), 4),
        "repartition_nb_obs": dict(
            zip(*[x.tolist() for x in np.unique(obs, return_counts=True)], strict=True)
        ),
        "ndvi_median": round(float(np.nanmedian(med_ndvi.values)), 3),
        "ndvi_median_sans_offset": round(float(np.nanmedian(med_brut.values)), 3),
        "ndmi_median": round(float(np.nanmedian(med_ndmi.values)), 3),
        "taille_mo": {k: round(v.stat().st_size / 1e6, 1) for k, v in fichiers.items()},
        "temps_s": chrono.etapes,
        "ram_max_go": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1),
    }
    (args.sortie / f"bilan_{args.debut}_{args.fin}.json").write_text(json.dumps(bilan, indent=2))
    print(json.dumps(bilan, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
