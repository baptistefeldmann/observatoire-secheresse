"""[V2] Classes de la brique satellite mises à la grille (D15, point 2) : `ocs_<annee>_<slug>.tif`.

Chaque pixel de 10 m reçoit le code d'une classe de `config/nomenclature_ocs.yaml` :

1. BD Forêt V2 : postes de forêt, mis à la grille après érosion d'un pixel (pixel « pur ») ;
2. règle 2 (partie « encore un arbre ») : un pixel de forêt qui n'est plus un arbre sur la carte
   récente repasse hors classes, sauf les classes exemptées (peupleraie, landes) ;
3. règle 1 : le RPG de l'année prime ; toute parcelle déclarée efface ce qui était là (sur son
   emprise non érodée), puis les classes de culture sont posées sur les parcelles érodées.

Le seuil de NDVI d'été de la règle 2 et le feuillage de la règle 3 demandent les composites
Sentinel-2 (V2.2) : ils ne sont pas appliqués ici.

Les couches sources et la carte d'arbres sont gardées dans `rasters/classes/sources/` (régénérables,
non versionnées) ; `actualiser=True` les relit.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
from numpy.typing import NDArray
from rasterio.features import rasterize
from shapely.geometry.base import BaseGeometry

from pipeline import referentiels
from pipeline.config import Config, NomenclatureOcs
from pipeline.http import ClientHttp
from pipeline.raster.cog import ecrire_cog
from pipeline.raster.grille import Grille, grille_de
from pipeline.sources import carte_arbres, ign_classes

log = logging.getLogger(__name__)


@dataclass
class Bilan:
    """Pixels par code de classe, pour contrôle (surfaces à confronter au spike n°7)."""

    annee: int
    carte_arbres: str
    pixels: dict[int, int] = field(default_factory=dict)
    forets_retirees_pixels: int = 0  # forêt devenue hors classes (plus d'arbre sur la carte)
    forets_effacees_rpg_pixels: int = 0  # forêt effacée par une parcelle du RPG
    arbres_ajoutes_pixels: int = 0  # pixels ajoutés à la carte d'arbres par la BD Forêt


def dossier_classes(config: Config) -> Path:
    return config.projet.chemins.rasters / "classes"


def chemin_arbres(config: Config) -> Path:
    return dossier_classes(config) / f"arbres_{config.projet.territoire.slug}.tif"


def chemin_classes(config: Config, annee: int) -> Path:
    return dossier_classes(config) / f"ocs_{annee}_{config.projet.territoire.slug}.tif"


def empreinte_nomenclature(nomenclature: NomenclatureOcs) -> str:
    """Empreinte courte de la nomenclature : change si une classe, un code ou une règle change."""
    return hashlib.sha256(nomenclature.model_dump_json().encode()).hexdigest()[:12]


def _rasteriser(
    formes: Iterable[tuple[BaseGeometry, int]], grille: Grille, defaut: int = 0
) -> NDArray[np.uint8]:
    liste = [(g, v) for g, v in formes if not g.is_empty]
    if not liste:
        return np.full(grille.forme, defaut, dtype=np.uint8)
    resultat: NDArray[np.uint8] = rasterize(
        liste, out_shape=grille.forme, transform=grille.transform, fill=defaut, dtype="uint8"
    )
    return resultat


def _eroder(gdf: gpd.GeoDataFrame, distance_m: float) -> gpd.GeoSeries:
    return gdf.geometry.buffer(-distance_m) if distance_m > 0 else gdf.geometry


def codes_tfv(nomenclature: NomenclatureOcs) -> dict[str, int | None]:
    """code_tfv -> code de classe, ou `None` pour un poste en réserve ou exclu (hors classes)."""
    table: dict[str, int | None] = {}
    for classe in nomenclature.foret.classes:
        for code in classe.code_tfv:
            table[code] = classe.code
    for poste in (*nomenclature.foret.reserve, *nomenclature.foret.exclues):
        for code in poste.code_tfv:
            table[code] = None
    return table


def classes_foret(
    grille: Grille, nomenclature: NomenclatureOcs, bdforet: gpd.GeoDataFrame
) -> NDArray[np.uint8]:
    """Forêt (BD Forêt, polygones érodés) sur la grille ; levée si un poste est inconnu."""
    table = codes_tfv(nomenclature)
    inconnus = sorted(set(bdforet["code_tfv"]) - set(table))
    if inconnus:
        raise ValueError(
            f"postes de la BD Forêt absents de nomenclature_ocs.yaml : {', '.join(inconnus)}"
        )
    codes = bdforet["code_tfv"].map(table)
    garde = codes.notna()
    erodes = _eroder(bdforet[garde], nomenclature.regles.erosion_m)
    return _rasteriser(zip(erodes, codes[garde].astype(int), strict=True), grille)


def completer_arbres(
    arbres: NDArray[np.bool_],
    grille: Grille,
    nomenclature: NomenclatureOcs,
    bdforet: gpd.GeoDataFrame,
) -> tuple[NDArray[np.bool_], int]:
    """Carte d'arbres complétée : les polygones entiers des postes `arbres_complement_tfv` de la BD
    Forêt y sont ajoutés (bosquets et haies que la carte récente ne voit pas)."""
    postes = nomenclature.regles.arbres_complement_tfv
    if not postes:
        return arbres, 0
    ilots = bdforet[bdforet["code_tfv"].isin(postes)]
    ajout = _rasteriser(((g, 1) for g in ilots.geometry), grille).astype(bool)
    return arbres | ajout, int((ajout & ~arbres).sum())


def retirer_non_arbres(
    base: NDArray[np.uint8], arbres: NDArray[np.bool_], nomenclature: NomenclatureOcs
) -> tuple[NDArray[np.uint8], int]:
    """Règle 2, partie « encore un arbre » : hors classes les pixels de forêt sans arbre."""
    soumises = [c.code for c in nomenclature.foret.classes if c.controle_foret]
    a_retirer = np.isin(base, soumises) & ~arbres
    resultat = base.copy()
    resultat[a_retirer] = nomenclature.codes_speciaux.hors_classes
    return resultat, int(a_retirer.sum())


def appliquer_rpg(
    base: NDArray[np.uint8], grille: Grille, nomenclature: NomenclatureOcs, rpg: gpd.GeoDataFrame
) -> tuple[NDArray[np.uint8], int]:
    """Règle 1 : le RPG prime. Renvoie la grille et le nombre de pixels de forêt effacés."""
    hors = nomenclature.codes_speciaux.hors_classes
    resultat = base.copy()
    if not nomenclature.regles.rpg_prime:
        declare = np.zeros(grille.forme, dtype=bool)
    else:
        declare = _rasteriser(((g, 1) for g in rpg.geometry), grille).astype(bool)
    effaces = int(((resultat != hors) & declare).sum())
    resultat[declare] = hors
    par_groupe = {g: c.code for c in nomenclature.cultures.classes for g in c.code_group}
    codes = rpg["code_group"].map(par_groupe)
    garde = codes.notna()
    erodes = _eroder(rpg[garde], nomenclature.regles.erosion_m)
    cultures = _rasteriser(zip(erodes, codes[garde].astype(int), strict=True), grille)
    resultat[cultures > 0] = cultures[cultures > 0]
    return resultat, effaces


def classer(
    grille: Grille,
    nomenclature: NomenclatureOcs,
    bdforet: gpd.GeoDataFrame,
    rpg: gpd.GeoDataFrame,
    arbres: NDArray[np.bool_],
    annee: int,
    source_arbres: str,
    emprise: BaseGeometry | None = None,
) -> tuple[NDArray[np.uint8], Bilan]:
    """Grille de classes d'une année ; hors `emprise` (si donnée), le code nodata."""
    foret = classes_foret(grille, nomenclature, bdforet)
    foret, retirees = retirer_non_arbres(foret, arbres, nomenclature)
    grille_classes, effacees = appliquer_rpg(foret, grille, nomenclature, rpg)
    if emprise is not None:
        dedans = _rasteriser([(emprise, 1)], grille).astype(bool)
        grille_classes[~dedans] = nomenclature.codes_speciaux.nodata
    codes, nombres = np.unique(grille_classes, return_counts=True)
    bilan = Bilan(
        annee,
        source_arbres,
        {int(c): int(n) for c, n in zip(codes, nombres, strict=True)},
        retirees,
        effacees,
    )
    return grille_classes, bilan


def ecrire_classes(
    chemin: Path,
    grille_classes: NDArray[np.uint8],
    grille: Grille,
    nodata: int,
    tags: dict[str, str],
) -> None:
    """COG de classes (8 bits, deflate, aperçus par le mode), écrit via un fichier temporaire."""
    ecrire_cog(chemin, grille_classes, grille, nodata, tags)


def _sources(
    config: Config, client: ClientHttp, grille: Grille, annees: list[int], actualiser: bool
) -> tuple[gpd.GeoDataFrame, dict[int, gpd.GeoDataFrame], NDArray[np.bool_], str]:
    dossier = dossier_classes(config) / "sources"
    dossier.mkdir(parents=True, exist_ok=True)
    slug = config.projet.territoire.slug

    fichier_bdforet = dossier / f"bdforet_{slug}.parquet"
    if actualiser or not fichier_bdforet.exists():
        ign_classes.ingerer_bdforet(config, client, grille.emprise).to_parquet(fichier_bdforet)
    bdforet = gpd.read_parquet(fichier_bdforet)

    rpg: dict[int, gpd.GeoDataFrame] = {}
    for annee in annees:
        fichier = dossier / f"rpg_{annee}_{slug}.parquet"
        if actualiser or not fichier.exists():
            ign_classes.ingerer_rpg(config, client, annee, grille.emprise).to_parquet(fichier)
        rpg[annee] = gpd.read_parquet(fichier)

    fichier_arbres = dossier / f"arbres_{slug}.npz"
    if actualiser or not fichier_arbres.exists():
        masque, nom = carte_arbres.lire_arbres(config, grille)
        np.savez_compressed(fichier_arbres, arbres=masque, source=nom)
    with np.load(fichier_arbres) as f:
        arbres, nom = f["arbres"].astype(bool), str(f["source"])
    return bdforet, rpg, arbres, nom


def construire(
    config: Config,
    client: ClientHttp,
    annees: list[int] | None = None,
    actualiser: bool = False,
) -> dict[int, Bilan]:
    """Écrit `rasters/classes/ocs_<annee>_<slug>.tif` par année (défaut : celles du RPG configuré).

    Idempotent : mêmes sources et même nomenclature donnent le même fichier."""
    annees = annees or sorted(config.sources.occupation_sol.rpg)
    territoire = referentiels.emprise(config)
    grille = grille_de(territoire, config.sources.sentinel2.resolution_m, config.projet.crs)
    nomenclature = config.nomenclature_ocs
    bdforet, rpg, arbres_brut, nom_arbres = _sources(config, client, grille, annees, actualiser)
    arbres, ajoutes = completer_arbres(arbres_brut, grille, nomenclature, bdforet)
    complement = nomenclature.regles.arbres_complement_tfv
    if complement:
        nom_arbres = f"{nom_arbres} + BD Forêt {', '.join(complement)}"
    log.info("carte d'arbres : %s, %d pixels ajoutés par la BD Forêt", nom_arbres, ajoutes)
    ecrire_classes(
        chemin_arbres(config),
        arbres.astype(np.uint8),
        grille,
        nomenclature.codes_speciaux.nodata,
        {"carte_arbres": nom_arbres, "valeurs": "1 = arbre, 0 = pas un arbre"},
    )
    bilans: dict[int, Bilan] = {}
    for annee in annees:
        grille_classes, bilan = classer(
            grille, nomenclature, bdforet, rpg[annee], arbres, annee, nom_arbres, territoire
        )
        ecrire_classes(
            chemin_classes(config, annee),
            grille_classes,
            grille,
            nomenclature.codes_speciaux.nodata,
            {
                "annee_rpg": str(annee),
                "carte_arbres": nom_arbres,
                "nomenclature": empreinte_nomenclature(nomenclature),
                "version_methodo": config.projet.satellite.version_methodo,
            },
        )
        bilan.arbres_ajoutes_pixels = ajoutes
        bilans[annee] = bilan
        log.info("classes %d écrites : %s", annee, chemin_classes(config, annee))
    return bilans
