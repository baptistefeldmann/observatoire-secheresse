"""[V2] Composites mensuels de NDVI et de NDMI de Sentinel-2 sur tout le département (D15).

Pour chaque mois civil : les scènes retenues (une par tuile et par jour, baseline la plus récente,
offset BOA par scène : voir `pipeline.sources.sentinel2`) sont lues par blocs de la grille 10 m ;
pour chaque plan de pixels (jour et offset) on calcule le NDVI et le NDMI **avant** la médiane, puis
la médiane des plans du mois (la moyenne laisserait passer voiles et ombres).

    NDVI = (B08 − B04) / (B08 + B04)        NDMI = (B08 − B11) / (B08 + B11)
    réflectance = max(0, (DN + offset) / 10 000) ; valide : SCL dans `scl_valides`, bandes > 0

Sorties de `rasters/mensuel/AAAA-MM/` (non versionnées) : `ndvi.tif` et `ndmi.tif` (int16, indice
× 10 000, nodata −32768), `n_obs.tif` (observations valides, uint8), `plans.parquet` (un plan par
ligne), `derive.parquet` (médiane par plan et par classe stable), `rapport.json`.

Contrôles : intégrité (le nodata de SCL doit coïncider avec celui des bandes, sinon la lecture est
corrompue et le bloc est relu avec des URL re-signées) ; contrôle de dérive sur des classes stables
(voir `pipeline.indices.derive`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline import referentiels
from pipeline.config import ClasseCulture, ClasseForet, Config
from pipeline.raster.classes import chemin_classes
from pipeline.raster.cog import ecrire_cog, lire_cog
from pipeline.raster.grille import Grille, grille_de
from pipeline.sources import sentinel2
from pipeline.sources.sentinel2 import Recherche, Scene, cle_plan

log = logging.getLogger(__name__)

NODATA_INDICE = -32768
NODATA_N = 255


class LectureCorrompueError(RuntimeError):
    """Le nodata de SCL et celui des bandes diffèrent : les URL signées ont probablement expiré."""


def dossier_mensuel(config: Config) -> Path:
    return config.projet.chemins.rasters / "mensuel"


def dossier_mois(config: Config, annee: int, mois: int) -> Path:
    return dossier_mensuel(config) / f"{annee}-{mois:02d}"


def dossier_satellite(config: Config) -> Path:
    return config.projet.chemins.data / "satellite"


# --- Calcul par plan et par bloc ----------------------------------------------------------------


def verifier_integrite(
    scl: NDArray[Any], b04: NDArray[Any], b08: NDArray[Any], b11: NDArray[Any], max_pct: float
) -> None:
    """Refuse un bloc dont un plan a, hors nodata partagé, SCL et bandes en désaccord."""
    couvert = scl > 0
    for k in range(scl.shape[0]):
        bandes = (b04[k] > 0) | (b08[k] > 0) | (b11[k] > 0)
        union = int((couvert[k] | bandes).sum())
        if union == 0:
            continue
        desaccord = int((couvert[k] ^ bandes).sum())
        if 100 * desaccord / union > max_pct:
            raise LectureCorrompueError(
                f"plan {k} : {100 * desaccord / union:.1f} % de pixels où SCL et les bandes "
                f"ne s'accordent pas (maximum {max_pct} %)"
            )


def indices_par_plan(
    b04: NDArray[Any],
    b08: NDArray[Any],
    b11: NDArray[Any],
    scl: NDArray[Any],
    offsets: NDArray[np.float32],
    scl_valides: list[int],
    facteur: float,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """NDVI et NDMI de chaque plan (plan, y, x) ; NaN où le pixel n'est pas valide."""
    decalage = offsets[:, None, None]

    def refl(bande: NDArray[Any]) -> NDArray[np.float32]:
        resultat: NDArray[np.float32] = np.clip(
            (bande.astype(np.float32) + decalage) / facteur, 0, None
        )
        return resultat

    r04, r08, r11 = refl(b04), refl(b08), refl(b11)
    valide = (np.isin(scl, scl_valides) & (b04 > 0) & (b08 > 0) & (b11 > 0) & ((r08 + r04) > 0)) & (
        (r08 + r11) > 0
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = np.where(valide, (r08 - r04) / (r08 + r04), np.nan).astype(np.float32)
        ndmi = np.where(valide, (r08 - r11) / (r08 + r11), np.nan).astype(np.float32)
    return ndvi, ndmi


def _mediane_sans_nan(plans: NDArray[np.float32]) -> NDArray[np.float32]:
    """Médiane des valeurs non NaN le long du premier axe (NaN s'il n'y en a aucune).

    Plus rapide que `np.nanmedian` pour quelques plans sur des millions de pixels : tri puis lecture
    des deux valeurs centrales."""
    tri = np.sort(plans, axis=0)  # les NaN passent en dernier
    n = np.isfinite(plans).sum(axis=0)
    bas = np.clip((n - 1) // 2, 0, None)[None]
    haut = (n // 2)[None]
    centre = np.concatenate(
        [np.take_along_axis(tri, bas, 0), np.take_along_axis(tri, haut, 0)], axis=0
    )
    resultat: NDArray[np.float32] = np.where(n > 0, centre.mean(axis=0), np.nan).astype(np.float32)
    return resultat


def mediane_mois(
    ndvi: NDArray[np.float32], ndmi: NDArray[np.float32]
) -> tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.uint8]]:
    """Médiane des plans valides, et nombre d'observations valides par pixel."""
    n_obs = np.isfinite(ndvi).sum(axis=0).clip(0, 254).astype(np.uint8)
    return _mediane_sans_nan(ndvi), _mediane_sans_nan(ndmi), n_obs


def en_entier(valeurs: NDArray[np.float32], facteur: float) -> NDArray[np.int16]:
    """Indice (NaN = manquant) en entier de 16 bits, indice × facteur."""
    return np.where(np.isfinite(valeurs), np.rint(valeurs * facteur), NODATA_INDICE).astype(
        np.int16
    )


# --- Suivi d'un mois ----------------------------------------------------------------------------


@dataclass
class SuiviMois:
    """Ce qui est accumulé bloc après bloc : échantillons de dérive et compteurs."""

    derive: dict[tuple[str, str], tuple[list[NDArray[np.float32]], list[NDArray[np.float32]]]] = (
        field(default_factory=dict)
    )
    pixels_valides: int = 0
    pixels_jamais_valides: int = 0
    observations: int = 0
    relectures: int = 0

    def ajouter(
        self, cle: str, classe: str, ndvi: NDArray[np.float32], ndmi: NDArray[np.float32]
    ) -> None:
        listes = self.derive.setdefault((cle, classe), ([], []))
        listes[0].append(ndvi)
        listes[1].append(ndmi)


def _fenetres(grille: Grille, bloc: int) -> list[tuple[int, int, int, int]]:
    """Fenêtres (ligne, colonne, hauteur, largeur) couvrant la grille."""
    return [
        (i, j, min(bloc, grille.hauteur - i), min(bloc, grille.largeur - j))
        for i in range(0, grille.hauteur, bloc)
        for j in range(0, grille.largeur, bloc)
    ]


def _geobox(grille: Grille, fenetre: tuple[int, int, int, int]) -> Any:
    from odc.geo.geobox import GeoBox
    from rasterio.transform import Affine

    i, j, h, w = fenetre
    return GeoBox((h, w), grille.transform @ Affine.translation(j, i), grille.crs)


def _lire_bloc(
    config: Config,
    recherche: Recherche,
    grille: Grille,
    fenetre: tuple[int, int, int, int],
    lecteur: Any,
    suivi: SuiviMois,
) -> tuple[list[str], dict[str, NDArray[Any]]]:
    """Lecture d'un bloc, relue si elle est corrompue (jetons expirés, lectures tronquées)."""

    def compter(_etat: Any) -> None:
        suivi.relectures += 1

    tentative = retry(
        retry=retry_if_exception_type((LectureCorrompueError, OSError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=30),
        before_sleep=compter,
        reraise=True,
    )

    @tentative
    def lire() -> tuple[list[str], dict[str, NDArray[Any]]]:
        cles, bandes = lecteur(recherche.elements, recherche.scenes, _geobox(grille, fenetre))
        verifier_integrite(
            bandes["SCL"],
            bandes["B04"],
            bandes["B08"],
            bandes["B11"],
            config.projet.satellite.composites.integrite_max_pct,
        )
        return cles, bandes

    return lire()


def _classes_cibles(config: Config, annee: int) -> tuple[NDArray[np.uint8], dict[str, int]] | None:
    """Raster des classes de l'année (ou de la dernière année disponible) et codes des cibles."""
    nomenclature = config.nomenclature_ocs
    classes: list[ClasseForet | ClasseCulture] = [
        *nomenclature.foret.classes,
        *nomenclature.cultures.classes,
    ]
    codes = {c.id: c.code for c in classes}
    cibles = {c: codes[c] for c in config.projet.satellite.composites.cibles_derive}
    disponibles = [
        a
        for a in range(annee, annee - 10, -1)
        if chemin_classes(config, a).is_file()  # la plus récente année ≤ annee
    ]
    if not disponibles:
        return None
    tableau, _, _ = lire_cog(chemin_classes(config, disponibles[0]))
    return tableau.astype(np.uint8), cibles


@dataclass
class ResultatMois:
    ndvi: NDArray[np.int16]
    ndmi: NDArray[np.int16]
    n_obs: NDArray[np.uint8]
    suivi: SuiviMois
    plans: pd.DataFrame


def calculer_mois(
    config: Config,
    grille: Grille,
    recherche: Recherche,
    annee: int,
    mois: int,
    territoire: NDArray[np.bool_] | None = None,
    classes: tuple[NDArray[np.uint8], dict[str, int]] | None = None,
    lecteur: Any = None,
) -> ResultatMois:
    """NDVI et NDMI médians du mois sur toute la grille, bloc par bloc."""
    source = config.sources.sentinel2
    lecteur = lecteur or sentinel2.lire_scenes
    composites = config.projet.satellite.composites
    par_cle: dict[str, list[Scene]] = {}
    for scene in recherche.scenes:
        par_cle.setdefault(cle_plan(scene), []).append(scene)

    ndvi_final = np.full(grille.forme, NODATA_INDICE, np.int16)
    ndmi_final = np.full(grille.forme, NODATA_INDICE, np.int16)
    n_obs_final = np.zeros(grille.forme, np.uint8)
    suivi = SuiviMois()
    fenetres = _fenetres(grille, composites.bloc_px)
    for numero, fenetre in enumerate(fenetres, 1):
        i, j, h, w = fenetre
        zone = (slice(i, i + h), slice(j, j + w))
        if territoire is not None and not territoire[zone].any():
            continue  # bloc hors du département
        cles, bandes = _lire_bloc(config, recherche, grille, fenetre, lecteur, suivi)
        offsets = np.array([par_cle[c][0].offset for c in cles], np.float32)
        ndvi, ndmi = indices_par_plan(
            bandes["B04"],
            bandes["B08"],
            bandes["B11"],
            bandes["SCL"],
            offsets,
            source.scl_valides,
            float(source.facteur_echelle),
        )
        if territoire is not None:
            hors = ~territoire[zone]
            ndvi[:, hors] = np.nan
            ndmi[:, hors] = np.nan
        med_ndvi, med_ndmi, n_obs = mediane_mois(ndvi, ndmi)
        ndvi_final[zone] = en_entier(med_ndvi, source.facteur_echelle)
        ndmi_final[zone] = en_entier(med_ndmi, source.facteur_echelle)
        n_obs_final[zone] = n_obs
        dedans = territoire[zone] if territoire is not None else np.ones((h, w), bool)
        suivi.pixels_valides += int((np.isfinite(med_ndvi) & dedans).sum())
        suivi.pixels_jamais_valides += int((~np.isfinite(med_ndvi) & dedans).sum())
        suivi.observations += int(n_obs[dedans].sum())
        if classes is not None:
            tableau, cibles = classes
            codes_bloc = tableau[zone]
            for nom, code in cibles.items():
                masque = codes_bloc == code
                if not masque.any():
                    continue
                for k, cle in enumerate(cles):
                    v, m = ndvi[k][masque], ndmi[k][masque]
                    bons = np.isfinite(v) & np.isfinite(m)
                    if bons.any():
                        suivi.ajouter(cle, nom, v[bons], m[bons])
        log.info("%d-%02d bloc %d/%d : %d plans", annee, mois, numero, len(fenetres), len(cles))
    return ResultatMois(ndvi_final, ndmi_final, n_obs_final, suivi, _plans(par_cle))


def _plans(par_cle: dict[str, list[Scene]]) -> pd.DataFrame:
    lignes = []
    for cle, scenes in sorted(par_cle.items()):
        lignes.append(
            {
                "cle": cle,
                "date": scenes[0].jour.isoformat(),
                "offset": scenes[0].offset,
                "plateformes": ",".join(sorted({s.plateforme for s in scenes})),
                "baselines": ",".join(sorted({s.baseline for s in scenes})),
                "tuiles": ",".join(sorted(s.tuile for s in scenes)),
                "n_scenes": len(scenes),
                "nuages_pct": float(np.mean([s.nuages_pct for s in scenes])),
            }
        )
    return pd.DataFrame(lignes)


def _derive(plans: pd.DataFrame, suivi: SuiviMois) -> pd.DataFrame:
    """Médiane de NDVI et de NDMI de chaque classe stable, par plan (tous blocs réunis)."""
    colonnes = [
        "cle",
        "date",
        "plateformes",
        "baselines",
        "offset",
        "classe",
        "n_px",
        "ndvi",
        "ndmi",
    ]
    infos = plans.set_index("cle") if not plans.empty else plans
    lignes = []
    for (cle, classe), (v, m) in sorted(suivi.derive.items()):
        ndvi, ndmi = np.concatenate(v), np.concatenate(m)
        info = infos.loc[cle]
        lignes.append(
            {
                "cle": cle,
                "date": info["date"],
                "plateformes": info["plateformes"],
                "baselines": info["baselines"],
                "offset": info["offset"],
                "classe": classe,
                "n_px": int(ndvi.size),
                "ndvi": float(np.median(ndvi)),
                "ndmi": float(np.median(ndmi)),
            }
        )
    return pd.DataFrame(lignes, columns=colonnes)


# --- Fichiers -----------------------------------------------------------------------------------


def _termine(dossier: Path, complet: bool, version: str) -> bool:
    rapport = dossier / "rapport.json"
    if not (complet and rapport.is_file()):
        return False
    return bool(json.loads(rapport.read_text(encoding="utf-8")).get("version") == version)


def _ecrire(
    config: Config,
    grille: Grille,
    recherche: Recherche,
    resultat: ResultatMois,
    annee: int,
    mois: int,
    complet: bool,
) -> Path:
    dossier = dossier_mois(config, annee, mois)
    dossier.mkdir(parents=True, exist_ok=True)
    tags = {
        "annee": str(annee),
        "mois": str(mois),
        "version_methodo": config.projet.satellite.version_methodo,
        "facteur": str(config.sources.sentinel2.facteur_echelle),
    }
    ecrire_cog(dossier / "ndvi.tif", resultat.ndvi, grille, NODATA_INDICE, tags, predicteur=True)
    ecrire_cog(dossier / "ndmi.tif", resultat.ndmi, grille, NODATA_INDICE, tags, predicteur=True)
    ecrire_cog(dossier / "n_obs.tif", resultat.n_obs, grille, NODATA_N, tags)
    resultat.plans.to_parquet(dossier / "plans.parquet", index=False)
    _derive(resultat.plans, resultat.suivi).to_parquet(dossier / "derive.parquet", index=False)
    suivi = resultat.suivi
    total = suivi.pixels_valides + suivi.pixels_jamais_valides
    rapport = {
        "version": config.projet.satellite.version_methodo,
        "annee": annee,
        "mois": mois,
        "complet": complet,
        "scenes_trouvees": recherche.n_trouvees,
        "scenes_baseline_inconnue": recherche.n_baseline_inconnue,
        "scenes_doublons_ecartes": recherche.n_doublons,
        "scenes_retenues": len(recherche.scenes),
        "plans": len(resultat.plans),
        "pct_jamais_valide": round(100 * suivi.pixels_jamais_valides / total, 3) if total else None,
        "observations_moyennes": round(suivi.observations / suivi.pixels_valides, 2)
        if suivi.pixels_valides
        else None,
        "relectures": suivi.relectures,
    }
    (dossier / "rapport.json").write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return dossier


def mois_a_calculer(debut: int, aujourd_hui: date) -> list[tuple[int, int]]:
    """Tous les mois de `debut` au mois en cours inclus."""
    return [
        (a, m)
        for a in range(debut, aujourd_hui.year + 1)
        for m in range(1, 13)
        if (a, m) <= (aujourd_hui.year, aujourd_hui.month)
    ]


def construire(
    config: Config,
    aujourd_hui: date,
    annees: list[int] | None = None,
    mois_choisis: list[int] | None = None,
    actualiser: bool = False,
    catalogue: Any = None,
    lecteur: Any = None,
) -> list[Path]:
    """Composites mensuels de 2018 (début de `periode_reference.sentinel2`) au mois en cours.

    Reprenable : un mois terminé déjà écrit est conservé ; le mois en cours est recalculé."""
    debut = config.projet.periode_reference.sentinel2.debut
    source = config.sources.sentinel2
    territoire_geom = referentiels.emprise(config)
    grille = grille_de(territoire_geom, source.resolution_m, config.projet.crs)
    territoire = _masque_territoire(grille, territoire_geom)
    ecrits: list[Path] = []
    for annee, mois in mois_a_calculer(debut, aujourd_hui):
        if (annees and annee not in annees) or (mois_choisis and mois not in mois_choisis):
            continue
        complet = (annee, mois) < (aujourd_hui.year, aujourd_hui.month)
        dossier = dossier_mois(config, annee, mois)
        if not actualiser and _termine(dossier, complet, config.projet.satellite.version_methodo):
            continue
        recherche = sentinel2.chercher(config, grille, annee, mois, catalogue)
        if not recherche.scenes:
            log.warning("%d-%02d : aucune scène utilisable", annee, mois)
            continue
        classes = _classes_cibles(config, annee)
        resultat = calculer_mois(
            config, grille, recherche, annee, mois, territoire, classes, lecteur
        )
        ecrits.append(_ecrire(config, grille, recherche, resultat, annee, mois, complet))
        log.info("%d-%02d écrit : %s", annee, mois, ecrits[-1])
    return ecrits


def _masque_territoire(grille: Grille, territoire: Any) -> NDArray[np.bool_]:
    from rasterio.features import geometry_mask

    masque: NDArray[np.bool_] = ~geometry_mask(
        [territoire], out_shape=grille.forme, transform=grille.transform
    )
    return masque
