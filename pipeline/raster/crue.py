"""[V2] Surface de crue des marais par passage Sentinel-1 (D15, point 4 ; architecture_v2.md, 9.2).

Détection par changement : un pixel est en crue si son VV filtré (médiane 3 x 3) est inférieur
de `baisse_db` à la référence sèche du même pixel (médiane d'été de la même orbite, filtrée
aussi), s'il est inférieur à `seuil_vv_db`, si la référence n'était pas déjà sombre et s'il
appartient à une tache d'au moins `taches_min_px` pixels. Seule la surface en hectares est
conservée (jamais un taux).

Domaine : `data/satellite/domaine_crue_<marais>.tif`, figé en V2.1 (0 hors domaine, 1 mesuré, 2 eau
permanente retirée). Régimes : `rasters/crue/regimes_<marais>.tif`, facultatif (couche EPMP).

La référence retenue (D16 : médiane des étés de la période de référence) est calculée avec une
variante de contrôle (`reference.variante` et `reference.controles`) : chaque passage n'est lu
qu'une fois.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import ndimage as ndi

from pipeline.config import Config, Detection, Marais
from pipeline.raster.cog import ecrire_cog, lire_cog
from pipeline.raster.grille import Grille
from pipeline.sources import sentinel1

log = logging.getLogger(__name__)

NODATA_REF = -32768  # références d'été enregistrées en centièmes de dB
ECHELLE_REF = 100.0
MESURE, EAU_PERMANENTE = 1, 2


@dataclass(frozen=True)
class DomaineCrue:
    marais: Marais
    grille: Grille
    mesure: NDArray[np.bool_]  # pixels dont la crue est comptée
    regimes: dict[str, NDArray[np.bool_]]  # régime -> pixels (le reste : « autres »)


def dossier_crue(config: Config) -> Path:
    return config.projet.chemins.rasters / "crue"


def dossier_satellite(config: Config) -> Path:
    return config.projet.chemins.data / "satellite"


def lire_domaine(config: Config, marais: Marais) -> DomaineCrue:
    code, grille, _ = lire_cog(dossier_satellite(config) / f"domaine_crue_{marais.id}.tif")
    mesure = code == MESURE
    regimes: dict[str, NDArray[np.bool_]] = {}
    if marais.regimes:
        fichier = dossier_crue(config) / f"regimes_{marais.id}.tif"
        if fichier.is_file():
            raster, grille_regimes, _ = lire_cog(fichier)
            if grille_regimes != grille:
                raise ValueError(f"{fichier} n'est pas sur la grille du domaine de crue")
            regimes = {nom: raster == valeur for nom, valeur in marais.regimes.items()}
        else:
            log.warning("%s absent : crue du total seulement pour %s", fichier, marais.id)
    return DomaineCrue(marais, grille, mesure, regimes)


# --- Référence sèche -------------------------------------------------------------------------


def annee_reference(variante: str, jour: date) -> int | None:
    """Année de l'été de référence d'un passage ; `None` pour la référence fixe."""
    if variante == "hydro":
        return jour.year if jour.month >= 10 else jour.year - 1
    if variante == "fixe":
        return None
    raise ValueError(f"variante de référence inconnue : {variante}")


def ete_complet(annee: int, aujourd_hui: date, dernier_mois: int) -> bool:
    """L'été de `annee` est terminé (dernier mois de la saison passé)."""
    return (annee, dernier_mois) < (aujourd_hui.year, aujourd_hui.month)


def mediane_ete(db: NDArray[np.float32]) -> NDArray[np.float32]:
    """Référence d'une année : médiane par pixel des passages de la saison sèche."""
    with np.errstate(all="ignore"):
        return np.asarray(np.nanmedian(db, axis=0), dtype=np.float32)


def vers_centidb(ref: NDArray[np.float32]) -> NDArray[np.int16]:
    return np.where(np.isfinite(ref), np.round(ref * ECHELLE_REF), NODATA_REF).astype(np.int16)


def depuis_centidb(brut: NDArray[np.int16]) -> NDArray[np.float32]:
    return np.where(brut == NODATA_REF, np.nan, brut / ECHELLE_REF).astype(np.float32)


def chemin_reference(config: Config, marais: Marais, annee: int | str) -> Path:
    return dossier_crue(config) / "references" / f"ref_ete_{annee}_{marais.id}.tif"


def construire_references(
    config: Config, domaine: DomaineCrue, aujourd_hui: date, catalogue: object = None
) -> dict[int, Path]:
    """Médiane d'été de chaque année complète ; une année déjà écrite est conservée (reprise)."""
    ref = config.projet.satellite.crue.reference
    debut = config.projet.periode_reference.sentinel1.debut
    orbite = config.projet.satellite.crue.orbite_publiee
    saison = sorted(ref.mois)
    chemins: dict[int, Path] = {}
    for annee in range(debut, aujourd_hui.year + 1):
        if not ete_complet(annee, aujourd_hui, saison[-1]):
            continue
        chemin = chemin_reference(config, domaine.marais, annee)
        chemins[annee] = chemin
        if chemin.is_file():
            continue
        elements = sentinel1.chercher(
            config,
            domaine.grille,
            orbite,
            date(annee, saison[0], 1),
            date(annee, saison[-1], 28) if saison[-1] == 2 else date(annee, saison[-1], 30),
            catalogue,
        )
        elements = [e for e in elements if e.datetime.month in saison]
        if not elements:
            log.warning("%s %d : aucun passage d'été, pas de référence", domaine.marais.id, annee)
            chemins.pop(annee)
            continue
        piles = [db for _, db in sentinel1.lire_db(elements, domaine.grille)]
        ref_annee = mediane_ete(np.concatenate(piles, axis=0))
        ecrire_cog(
            chemin,
            vers_centidb(ref_annee),
            domaine.grille,
            NODATA_REF,
            {
                "annee": str(annee),
                "orbite": str(orbite),
                "passages": str(sum(len(p) for p in piles)),
                "unite": "centièmes de dB (VV), médiane par pixel des passages de la saison",
            },
            predicteur=True,
        )
        log.info(
            "référence %s %d écrite (%d passages)",
            domaine.marais.id,
            annee,
            sum(len(p) for p in piles),
        )
    return chemins


def reference_fixe(config: Config, domaine: DomaineCrue, chemins: dict[int, Path]) -> Path | None:
    """Médiane par pixel des étés de la période de référence ; écrite une fois."""
    p = config.projet.periode_reference.sentinel1
    annees = [a for a in range(p.debut, p.fin + 1) if a in chemins]
    if len(annees) < (p.fin - p.debut + 1):
        log.warning("référence fixe : %d étés sur %d", len(annees), p.fin - p.debut + 1)
    if not annees:
        return None
    chemin = chemin_reference(config, domaine.marais, "fixe")
    if chemin.is_file():
        return chemin
    pile = np.stack([depuis_centidb(lire_cog(chemins[a])[0]) for a in annees])
    ecrire_cog(
        chemin,
        vers_centidb(mediane_ete(pile)),
        domaine.grille,
        NODATA_REF,
        {"annees": f"{annees[0]}-{annees[-1]}", "unite": "centièmes de dB (VV)"},
        predicteur=True,
    )
    return chemin


# --- Détection ---------------------------------------------------------------------------------


def lisser(x: NDArray[np.float32], taille: int) -> NDArray[np.float32]:
    """Médiane `taille` x `taille` ; un pixel sans valeur prend d'abord la médiane de l'image."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # image sans aucune valeur
        mediane = np.nanmedian(x)
    plein = np.where(np.isfinite(x), x, mediane)
    return np.asarray(ndi.median_filter(plein, size=taille), dtype=np.float32)


def detecter(
    db: NDArray[np.float32],
    ref: NDArray[np.float32],
    ref_lisse: NDArray[np.float32],
    parametres: Detection,
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Pixels en crue et pixels observables (passage et référence valides)."""
    ok = np.isfinite(db) & np.isfinite(ref)
    x = lisser(np.where(ok, db, np.nan).astype(np.float32), parametres.filtre_median_px)
    brut = (
        ((x - ref_lisse) < -parametres.baisse_db)
        & (x < parametres.seuil_vv_db)
        & (ref_lisse >= parametres.seuil_vv_db)
        & ok
    )
    etiquettes, _ = ndi.label(brut)
    garder = np.bincount(etiquettes.ravel()) >= parametres.taches_min_px
    garder[0] = False  # l'étiquette 0 est le fond
    return garder[etiquettes], ok


def surfaces(
    crue: NDArray[np.bool_], ok: NDArray[np.bool_], domaine: DomaineCrue, pixel_ha: float
) -> dict[str, float]:
    """Surface de crue (ha) du domaine, par régime, et part du domaine observable."""
    dans = domaine.mesure
    total_px = int(dans.sum())
    ligne: dict[str, float] = {
        "surface_ha": float((crue & dans).sum() * pixel_ha),
        "pct_valides": float((ok & dans).sum() / total_px * 100) if total_px else float("nan"),
    }
    if domaine.regimes:
        classes = np.zeros(dans.shape, dtype=bool)
        for nom, masque in domaine.regimes.items():
            ligne[f"ha_{nom}"] = float((crue & dans & masque).sum() * pixel_ha)
            classes |= masque
        ligne["ha_autres"] = float((crue & dans & ~classes).sum() * pixel_ha)
    return ligne


# --- Passages ----------------------------------------------------------------------------------


def chemin_passages(config: Config, marais: Marais, annee: int) -> Path:
    return dossier_crue(config) / "passages" / f"passages_{annee}_{marais.id}.parquet"


def _charger_reference(chemin: Path | None) -> NDArray[np.float32] | None:
    if chemin is None or not chemin.is_file():
        return None
    return depuis_centidb(lire_cog(chemin)[0])


def calculer_passages(
    config: Config,
    marais: Marais,
    annee: int,
    refs: dict[str, dict[int | None, Path]],
    domaine: DomaineCrue,
    catalogue: object = None,
) -> pd.DataFrame:
    """Surface de crue de tous les passages de `annee`, pour chaque variante de référence."""
    crue = config.projet.satellite.crue
    pixel_ha = domaine.grille.resolution**2 / 1e4
    elements = sentinel1.chercher(
        config,
        domaine.grille,
        crue.orbite_publiee,
        date(annee, 1, 1),
        date(annee, 12, 31),
        catalogue,
    )
    cache: dict[Path, tuple[NDArray[np.float32], NDArray[np.float32]]] = {}

    def reference(chemin: Path) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        if chemin not in cache:
            brute = _charger_reference(chemin)
            if brute is None:
                raise FileNotFoundError(chemin)
            cache[chemin] = (brute, lisser(brute, crue.detection.filtre_median_px))
        return cache[chemin]

    lignes: list[dict[str, object]] = []
    for jours, pile in sentinel1.lire_db(elements, domaine.grille):
        for k, jour in enumerate(jours):
            socle = {"marais": marais.id, "date": jour.isoformat(), "orbite": crue.orbite_publiee}
            for variante in crue.reference.variantes:
                cle = annee_reference(variante, jour)
                chemin = refs.get(variante, {}).get(cle)
                if chemin is None:
                    lignes.append({**socle, "variante": variante, "annee_ref": cle})
                    continue
                ref, ref_lisse = reference(chemin)
                masque_crue, ok = detecter(pile[k], ref, ref_lisse, crue.detection)
                lignes.append(
                    {
                        **socle,
                        "variante": variante,
                        "annee_ref": cle,
                        **surfaces(masque_crue, ok, domaine, pixel_ha),
                    }
                )
    return pd.DataFrame(lignes)


def fichier_passages(config: Config) -> Path:
    return dossier_satellite(config) / "crue_passages.parquet"


def fusionner_passages(config: Config) -> Path:
    """Réunit les passages enregistrés par marais et par année dans `crue_passages.parquet`."""
    parties = sorted((dossier_crue(config) / "passages").glob("passages_*.parquet"))
    if not parties:
        raise FileNotFoundError("aucun passage enregistré : lancer `make crue`")
    tout = pd.concat([pd.read_parquet(p) for p in parties], ignore_index=True)
    # les années déjà calculées peuvent contenir une variante abandonnée (D16)
    tout = tout[tout["variante"].isin(config.projet.satellite.crue.reference.variantes)]
    tout = tout.sort_values(["marais", "date", "variante"], ignore_index=True)
    chemin = fichier_passages(config)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tout.to_parquet(chemin, index=False)
    return chemin


def construire(
    config: Config,
    aujourd_hui: date,
    identifiants: list[str] | None = None,
    annees: list[int] | None = None,
    catalogue: object = None,
) -> Path:
    """Crue de tous les passages 2015 à l'année en cours, par marais. Reprenable : une année
    complète déjà calculée est conservée ; l'année en cours est recalculée à chaque appel."""
    crue = config.projet.satellite.crue
    debut = config.projet.periode_reference.sentinel1.debut
    marais_choisis = [m for m in crue.marais if identifiants is None or m.id in identifiants]
    if not marais_choisis:
        raise ValueError(
            f"aucun marais parmi {identifiants} (configurés : {[m.id for m in crue.marais]})"
        )
    for marais in marais_choisis:
        domaine = lire_domaine(config, marais)
        chemins = construire_references(config, domaine, aujourd_hui, catalogue)
        fixe = reference_fixe(config, domaine, chemins)
        refs: dict[str, dict[int | None, Path]] = {
            "hydro": {a: c for a, c in chemins.items()},
            "fixe": {None: fixe} if fixe else {},
        }
        for annee in annees or range(debut, aujourd_hui.year + 1):
            sortie = chemin_passages(config, marais, annee)
            if sortie.is_file() and annee < aujourd_hui.year:
                continue
            passages = calculer_passages(config, marais, annee, refs, domaine, catalogue)
            sortie.parent.mkdir(parents=True, exist_ok=True)
            passages.to_parquet(sortie, index=False)
            log.info("%s %d : %d lignes", marais.id, annee, len(passages))
    return fusionner_passages(config)
