"""API de l'observatoire (SPEC §8.1), en lecture seule sur PostGIS (rôle `lecteur`).

Lancement : service `api` de docker-compose (`make up`), port 8010 limité à la machine ;
documentation interactive sur `/docs`. Les semaines sont des semaines ISO « AAAA-Www », les
géométries du GeoJSON en WGS84."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from sqlalchemy import Connection, Engine, create_engine, text

from api import requetes
from pipeline.config import Config, Environnement, charger_config
from pipeline.indices.commun import dimanche

MOTIF_SEMAINE = r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$"
Semaine = Annotated[str, Query(pattern=MOTIF_SEMAINE, description="Semaine ISO, ex. 2026-W39")]
IndiceZone = Literal["composite", "spi_1", "spi_3", "spi_6", "ips", "debit", "onde"]
Source = Literal["piezo", "hydro", "onde", "retenue"]
PREMIERE, DERNIERE = "0000-W01", "9999-W53"

app = FastAPI(
    title="Observatoire de la sécheresse",
    description="Indices hebdomadaires de sécheresse par zone et par station (lecture seule).",
    version="1.0",
)


@lru_cache
def config() -> Config:
    return charger_config()


@lru_cache
def moteur() -> Engine:
    return create_engine(Environnement().url_lecteur, pool_pre_ping=True)


def connexion(base: Annotated[Engine, Depends(moteur)]) -> Any:
    with base.connect() as c:
        yield c


Base = Annotated[Connection, Depends(connexion)]
Configuration = Annotated[Config, Depends(config)]


def _lignes(base: Connection, requete: str, **parametres: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in base.execute(text(requete), parametres).mappings()]


def _derniere_semaine(base: Connection) -> str:
    semaine: str | None = base.execute(
        text("SELECT max(semaine) FROM idx.composite_zone")
    ).scalar_one()
    if semaine is None:
        raise HTTPException(503, "aucun indice en base : lancer make indices puis make db-rebuild")
    return str(semaine)


def _collection(lignes: list[dict[str, Any]]) -> dict[str, Any]:
    """FeatureCollection GeoJSON ; la colonne `geometrie` porte la géométrie."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(ligne.pop("geometrie")),
                "properties": ligne,
            }
            for ligne in lignes
        ],
    }


def _composite(detail: dict[str, Any] | None) -> dict[str, Any]:
    detail = detail or {}
    return {
        "n_composantes": detail.get("n_composantes"),
        "partiel": detail.get("partiel"),
        "manquantes": detail.get("manquantes"),
        "composantes": detail.get("composantes"),
    }


# --- Généralités -----------------------------------------------------------------------------


@app.get("/", summary="Territoire et état des données")
def accueil(base: Base, cfg: Configuration) -> dict[str, Any]:
    territoire = cfg.projet.territoire
    return {
        "territoire": territoire.nom,
        "slug": territoire.slug,
        "version_methodo": cfg.projet.indices.version_methodo,
        "derniere_semaine": _derniere_semaine(base),
        "documentation": "/docs",
    }


@app.get("/sante", summary="Disponibilité de la base")
def sante(base: Base) -> dict[str, str]:
    base.execute(text("SELECT 1"))
    return {"base": "ok"}


@app.get("/classes", summary="Échelle à 7 classes : seuils, libellés, couleurs")
def classes(cfg: Configuration) -> dict[str, Any]:
    return {
        "seuils": cfg.classes.seuils,
        "classes": [c.model_dump() for c in cfg.classes.classes],
    }


@app.get("/semaines", summary="Semaines disponibles, de la plus récente à la plus ancienne")
def semaines(base: Base) -> dict[str, Any]:
    liste = [r["semaine"] for r in _lignes(base, requetes.SEMAINES)]
    return {"derniere": liste[0] if liste else None, "semaines": liste}


# --- Zones -----------------------------------------------------------------------------------


@app.get("/zones", summary="Zones (GeoJSON) avec l'indice composite d'une semaine")
def zones(base: Base, cfg: Configuration, semaine: Semaine | None = None) -> dict[str, Any]:
    """Semaine la plus récente par défaut. Une zone sans composite cette semaine-là garde ses
    propriétés, avec un indice vide."""
    semaine = semaine or _derniere_semaine(base)
    lignes = _lignes(
        base, requetes.ZONES, semaine=semaine, tolerance=cfg.projet.api.simplification_m
    )
    for ligne in lignes:
        ligne["semaine"] = semaine
        ligne.update(_composite(ligne.pop("detail")))
    return _collection(lignes)


@app.get("/zones/{zone_id}/series", summary="Série hebdomadaire d'un indice de zone")
def serie_zone(
    base: Base,
    zone_id: Annotated[str, Path(description="Identifiant de zone, ex. SUD_VENDEE")],
    indice: IndiceZone = "composite",
    debut: Semaine | None = None,
    fin: Semaine | None = None,
) -> dict[str, Any]:
    zone = _lignes(base, requetes.ZONE, zone_id=zone_id)
    if not zone:
        raise HTTPException(404, f"zone inconnue : {zone_id}")
    bornes = {"zone_id": zone_id, "debut": debut or PREMIERE, "fin": fin or DERNIERE}
    if indice == "composite":
        points = _lignes(base, requetes.SERIE_COMPOSITE, **bornes)
        for point in points:
            point.update(_composite(point.pop("detail")))
    else:
        points = _lignes(base, requetes.SERIE_INDICE_ZONE, indice=indice, **bornes)
    return {"zone_id": zone_id, "libelle": zone[0]["libelle"], "indice": indice, "points": points}


# --- Stations --------------------------------------------------------------------------------


@app.get("/stations", summary="Stations (GeoJSON) avec leur indice ou dernier relevé")
def stations(
    base: Base, source: Source | None = None, semaine: Semaine | None = None
) -> dict[str, Any]:
    """Piézomètre et station hydrométrique : indice de la semaine. Retenue et station ONDE :
    dernier relevé ou dernière observation au dimanche de la semaine."""
    semaine = semaine or _derniere_semaine(base)
    lignes = _lignes(
        base, requetes.STATIONS, semaine=semaine, dimanche=dimanche(semaine), source=source
    )
    for ligne in lignes:
        ligne["semaine"] = semaine
    return _collection(lignes)


@app.get("/stations/{station_id:path}/series", summary="Chronique brute, indice et normale")
def serie_station(
    base: Base,
    station_id: Annotated[str, Path(description="Ex. piezo:05634X0013/SF3")],
    debut: Annotated[date | None, Query(description="Première date de la chronique")] = None,
    fin: Annotated[date | None, Query(description="Dernière date de la chronique")] = None,
) -> dict[str, Any]:
    """Chronique brute (niveau, débit journalier, remplissage, modalité ONDE), indices
    hebdomadaires de la période et enveloppe de la normale (minimum, médiane, maximum)."""
    trouvee = _lignes(base, requetes.STATION, station_id=station_id)
    if not trouvee:
        raise HTTPException(404, f"station inconnue : {station_id}")
    station = _collection(trouvee)["features"][0]
    source = station["properties"]["source"]
    debut, fin = debut or date(1900, 1, 1), fin or date(2999, 12, 31)
    requete, grandeur, unite = requetes.CHRONIQUES[source]
    chronique = _lignes(base, requete, station_id=station_id, debut=debut, fin=fin)

    semaine_debut = f"{debut.isocalendar()[0]:04d}-W{debut.isocalendar()[1]:02d}"
    semaine_fin = f"{fin.isocalendar()[0]:04d}-W{fin.isocalendar()[1]:02d}"
    indices = _lignes(
        base, requetes.INDICES_STATION, station_id=station_id, debut=semaine_debut, fin=semaine_fin
    )
    enveloppe: dict[str, Any]
    if source == "retenue":
        enveloppe = {
            "indice": "remplissage", "pas": "semaine", "unite": "%",
            "points": _lignes(base, requetes.ENVELOPPE_RETENUE, station_id=station_id,
                              annee=date.today().isocalendar()[0]),
        }  # fmt: skip
    else:
        points = _lignes(base, requetes.ENVELOPPE_STATION, station_id=station_id)
        enveloppe = {
            "indice": points[0]["indice"] if points else None,
            "pas": points[0]["pas"] if points else None,
            "unite": unite,
            "points": points,
        }
    return {
        "station": station,
        "chronique": {"grandeur": grandeur, "unite": unite, "points": chronique},
        "indices": indices,
        "enveloppe": enveloppe,
    }


# --- Synthèse --------------------------------------------------------------------------------


@app.get("/semaines/{semaine}/synthese", summary="Synthèse départementale d'une semaine")
def synthese(
    base: Base,
    cfg: Configuration,
    semaine: Annotated[str, Path(pattern=MOTIF_SEMAINE, description="Ex. 2026-W39")],
) -> dict[str, Any]:
    composites = _lignes(base, requetes.SYNTHESE_COMPOSITE, semaine=semaine)
    if not composites:
        raise HTTPException(404, f"aucun indice pour la semaine {semaine}")
    for ligne in composites:
        ligne.update(_composite(ligne.pop("detail")))
    repartition: dict[int, int] = {}
    for ligne in composites:
        repartition[ligne["classe"]] = repartition.get(ligne["classe"], 0) + 1
    annee, numero = int(semaine[:4]), int(semaine[6:])
    retenues = _lignes(base, requetes.SYNTHESE_RETENUES, annee=annee, numero=numero)[0]
    onde = _lignes(base, requetes.SYNTHESE_ONDE, semaine=semaine)
    for ligne in onde:
        ligne.update(ligne.pop("detail") or {})
    fin_semaine = dimanche(semaine)
    return {
        "semaine": semaine,
        "debut": date.fromordinal(fin_semaine.toordinal() - 6),
        "fin": fin_semaine,
        "version_methodo": cfg.projet.indices.version_methodo,
        "composite": {
            "zones": composites,
            "repartition": dict(sorted(repartition.items())),
            "zones_seches": sum(n for c, n in repartition.items() if c <= 2),
        },
        "stations": _lignes(base, requetes.SYNTHESE_STATIONS, semaine=semaine),
        "onde": onde,
        "retenues": {"total": retenues["courant"], "enveloppe": retenues["enveloppe"]},
    }
