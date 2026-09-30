"""Schéma initial : ref, obs, idx, rst (SPEC §5.3, méthodologie D5 et D6).

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA ref;
CREATE SCHEMA obs;
CREATE SCHEMA idx;
CREATE SCHEMA rst;

-- Référentiels ---------------------------------------------------------------
CREATE TABLE ref.zone (
    zone_id       text PRIMARY KEY,
    libelle       text NOT NULL,
    type_zone     text NOT NULL CHECK (type_zone IN ('hydrogeol', 'alerte')),
    ponderations  jsonb NOT NULL,
    geom          geometry(MultiPolygon, 2154) NOT NULL
);
CREATE TABLE ref.commune (
    code_insee    text PRIMARY KEY,
    nom           text NOT NULL,
    geom          geometry(MultiPolygon, 2154) NOT NULL
);
CREATE TABLE ref.maille_safran (
    maille_id     integer PRIMARY KEY,
    geom          geometry(Polygon, 2154) NOT NULL
);
CREATE TABLE ref.station (
    station_id    text PRIMARY KEY,
    source        text NOT NULL CHECK (source IN ('piezo', 'hydro', 'onde', 'retenue')),
    code          text NOT NULL,
    libelle       text,
    en_service    boolean NOT NULL,
    masse_eau     text,
    zone_id       text REFERENCES ref.zone,
    metadonnees   jsonb NOT NULL DEFAULT '{}',
    geom          geometry(Point, 2154) NOT NULL
);

-- Observations ---------------------------------------------------------------
CREATE TABLE obs.piezo_jour (
    station_id    text NOT NULL REFERENCES ref.station,
    date          date NOT NULL,
    niveau_ngf    double precision NOT NULL,
    profondeur    double precision,
    qualification text,
    ingere_le     date NOT NULL,
    PRIMARY KEY (station_id, date)
);
CREATE TABLE obs.debit_jour (
    station_id    text NOT NULL REFERENCES ref.station,
    date          date NOT NULL,
    qmj_ls        double precision NOT NULL,
    qualification text,
    ingere_le     date NOT NULL,
    PRIMARY KEY (station_id, date)
);
CREATE TABLE obs.onde (
    station_id    text NOT NULL REFERENCES ref.station,
    date_campagne date NOT NULL,
    modalite      text NOT NULL,
    type_campagne text,
    ingere_le     date NOT NULL,
    PRIMARY KEY (station_id, date_campagne)
);
CREATE TABLE obs.meteo_jour (
    maille_id     integer NOT NULL REFERENCES ref.maille_safran,
    date          date NOT NULL,
    precip_mm     double precision,
    etp_mm        double precision,
    swi           double precision,
    ingere_le     date NOT NULL,
    PRIMARY KEY (maille_id, date)
);
CREATE TABLE obs.retenue_semaine (
    station_id    text NOT NULL REFERENCES ref.station,
    date          date NOT NULL,
    volume_m3     double precision NOT NULL,
    capacite_m3   double precision,
    source_donnee text,
    ingere_le     date NOT NULL,
    PRIMARY KEY (station_id, date)
);

-- Indices hebdomadaires --------------------------------------------------------
CREATE TABLE idx.indice_station (
    station_id      text NOT NULL REFERENCES ref.station,
    semaine         text NOT NULL CHECK (semaine ~ '^[0-9]{4}-W[0-9]{2}$'),
    indice          text NOT NULL,
    valeur          double precision,
    classe          smallint CHECK (classe BETWEEN 1 AND 7),
    periode_ref     text,
    version_methodo text NOT NULL,
    PRIMARY KEY (station_id, semaine, indice)
);
CREATE TABLE idx.indice_zone (
    zone_id         text NOT NULL REFERENCES ref.zone,
    semaine         text NOT NULL CHECK (semaine ~ '^[0-9]{4}-W[0-9]{2}$'),
    indice          text NOT NULL,
    valeur          double precision,
    classe          smallint CHECK (classe BETWEEN 1 AND 7),
    n_stations      integer,
    version_methodo text NOT NULL,
    PRIMARY KEY (zone_id, semaine, indice)
);
CREATE TABLE idx.composite_zone (
    zone_id         text NOT NULL REFERENCES ref.zone,
    semaine         text NOT NULL CHECK (semaine ~ '^[0-9]{4}-W[0-9]{2}$'),
    valeur          double precision,
    classe          smallint CHECK (classe BETWEEN 1 AND 7),
    detail          jsonb,
    version_methodo text NOT NULL,
    PRIMARY KEY (zone_id, semaine)
);

-- Catalogue raster [V2] ---------------------------------------------------------
CREATE TABLE rst.produit (
    produit_id         serial PRIMARY KEY,
    indice             text NOT NULL,
    date_debut         date NOT NULL,
    date_fin           date NOT NULL,
    resolution_m       integer NOT NULL,
    chemin             text NOT NULL,
    pct_pixels_valides real,
    emprise            geometry(Polygon, 2154)
);

-- Index spatiaux et de consultation ------------------------------------------------
CREATE INDEX ON ref.zone USING gist (geom);
CREATE INDEX ON ref.commune USING gist (geom);
CREATE INDEX ON ref.maille_safran USING gist (geom);
CREATE INDEX ON ref.station USING gist (geom);
CREATE INDEX ON ref.station (source);
CREATE INDEX ON ref.station (zone_id);
CREATE INDEX ON rst.produit USING gist (emprise);
CREATE INDEX ON obs.meteo_jour (date);
CREATE INDEX ON idx.indice_station (semaine);
CREATE INDEX ON idx.indice_zone (semaine);
CREATE INDEX ON idx.composite_zone (semaine);
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS rst, idx, obs, ref CASCADE;")
