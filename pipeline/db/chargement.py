"""Reconstruction de PostGIS depuis les fichiers de `data/` (SPEC §3 : PostGIS n'est jamais la
source de vérité). Tout se fait dans une seule transaction : en cas d'échec, la base précédente
reste intacte."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from sqlalchemy import Connection, Engine, text

from pipeline.config import Config
from pipeline.db import migrations

log = logging.getLogger(__name__)

NUL = r"\N"
SOMME_EMPREINTES = "coalesce(sum(hashtextextended(t::text, 0)), 0)"
SCHEMAS = ("rst", "idx", "obs", "ref")


@dataclass(frozen=True)
class Table:
    nom: str  # schéma.table
    motif: str  # fichiers sous data/
    colonnes: tuple[str, ...]  # colonnes cible ; « geom » vient de la géométrie du GeoParquet
    geometrie: bool = False


# Ordre de chargement : les référentiels avant les observations (clés étrangères).
TABLES = (
    Table("ref.zone", "referentiels/zones.parquet",
          ("zone_id", "libelle", "type_zone", "ponderations", "geom"), geometrie=True),
    Table("ref.commune", "referentiels/communes.parquet",
          ("code_insee", "nom", "geom"), geometrie=True),
    Table("ref.maille_safran", "referentiels/mailles_safran.parquet",
          ("maille_id", "geom"), geometrie=True),
    Table("ref.station", "referentiels/stations.parquet",
          ("station_id", "source", "code", "libelle", "en_service", "masse_eau", "zone_id",
           "metadonnees", "geom"), geometrie=True),
    Table("obs.piezo_jour", "raw/piezo/chroniques_*.parquet",
          ("station_id", "date", "niveau_ngf", "profondeur", "qualification", "ingere_le")),
    Table("obs.debit_jour", "raw/hydro/qmj_*.parquet",
          ("station_id", "date", "qmj_ls", "qualification", "ingere_le")),
    Table("obs.onde", "raw/onde/observations_*.parquet",
          ("station_id", "date_campagne", "modalite", "type_campagne", "ingere_le")),
    Table("obs.meteo_jour", "raw/meteo/sim_*.parquet",
          ("maille_id", "date", "precip_mm", "etp_mm", "swi", "ingere_le")),
    Table("obs.retenue_semaine", "raw/retenues/retenues_*.parquet",
          ("station_id", "date", "volume_m3", "capacite_m3", "source_donnee", "ingere_le")),
    Table("idx.indice_station", "indices/indice_station_*.parquet",
          ("station_id", "semaine", "indice", "valeur", "classe", "periode_ref",
           "hors_reference", "date_mesure", "dans_composite", "version_methodo")),
    Table("idx.indice_zone", "indices/indice_zone_*.parquet",
          ("zone_id", "semaine", "indice", "valeur", "classe", "n_stations", "detail",
           "version_methodo")),
    Table("idx.composite_zone", "indices/composite_zone_*.parquet",
          ("zone_id", "semaine", "valeur", "classe", "detail", "version_methodo")),
)  # fmt: skip


def vers_csv(table: pd.DataFrame, colonnes: tuple[str, ...], srid: int | None) -> str:
    """Texte CSV pour COPY : géométrie en EWKB hexadécimal, valeurs manquantes à `\\N`."""
    donnees = pd.DataFrame(table).copy()
    if srid is not None:
        geometries = shapely.set_srid(table.geometry.values, srid)
        donnees["geom"] = shapely.to_wkb(geometries, hex=True, include_srid=True)
    tampon = io.StringIO()
    donnees[list(colonnes)].to_csv(tampon, index=False, header=False, na_rep=NUL)
    return tampon.getvalue()


def _lire(dossier: Path, table: Table) -> pd.DataFrame:
    fichiers = sorted(dossier.glob(table.motif))
    if not fichiers:
        return pd.DataFrame(columns=list(table.colonnes))
    lire = gpd.read_parquet if table.geometrie else pd.read_parquet
    resultat: pd.DataFrame = pd.concat([lire(f) for f in fichiers], ignore_index=True)
    return resultat


def _charger(connexion: Connection, table: Table, donnees: pd.DataFrame, srid: int) -> None:
    if donnees.empty:
        return
    csv = vers_csv(donnees, table.colonnes, srid if table.geometrie else None)
    colonnes = ", ".join(table.colonnes)
    curseur = connexion.connection.driver_connection.cursor()  # type: ignore[union-attr]
    requete = f"COPY {table.nom} ({colonnes}) FROM STDIN WITH (FORMAT csv, NULL '{NUL}')"
    with curseur.copy(requete) as copie:
        copie.write(csv)


def reconstruire(config: Config, moteur: Engine) -> dict[str, int]:
    """Supprime et recrée les schémas, puis charge toutes les tables ; renvoie les effectifs."""
    dossier = config.projet.chemins.data
    srid = int(config.projet.crs.split(":")[1])
    effectifs: dict[str, int] = {}
    with moteur.begin() as connexion:
        connexion.execute(text(f"DROP SCHEMA IF EXISTS {', '.join(SCHEMAS)} CASCADE"))
        connexion.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        migrations.appliquer(connexion)
        for table in TABLES:
            donnees = _lire(dossier, table)
            _charger(connexion, table, donnees, srid)
            en_base: int = connexion.execute(text(f"SELECT count(*) FROM {table.nom}")).scalar_one()
            if en_base != len(donnees):
                raise RuntimeError(
                    f"{table.nom} : {en_base} lignes en base pour {len(donnees)} lues"
                )
            effectifs[table.nom] = en_base
            log.info("%s : %d lignes", table.nom, en_base)
    with moteur.connect() as connexion:
        connexion.execution_options(isolation_level="AUTOCOMMIT").execute(text("ANALYZE"))
    return effectifs


def empreinte(moteur: Engine) -> dict[str, tuple[int, int]]:
    """Effectif et somme des empreintes de lignes par table : deux bases identiques ont la même
    empreinte, indépendamment de l'ordre physique des lignes."""
    resultat = {}
    with moteur.connect() as connexion:
        for table in TABLES:
            n, somme = connexion.execute(
                text(f"SELECT count(*), {SOMME_EMPREINTES} FROM {table.nom} t")
            ).one()
            resultat[table.nom] = (int(n), int(somme))
    return resultat
