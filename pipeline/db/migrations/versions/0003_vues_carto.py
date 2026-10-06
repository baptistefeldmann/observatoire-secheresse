"""Vues de restitution (schéma `carto`) pour QGIS, puis l'API.

Les indices n'ont pas de géométrie : chaque vue les joint à leur zone ou leur station et
ajoute, pour chaque semaine ISO, son lundi (`debut`) et son dimanche (`fin`), qui servent au
curseur temporel de QGIS. La colonne `derniere` repère la semaine la plus récente (pour ONDE,
la dernière campagne de la zone ; pour les retenues, le dernier relevé). `cle` est
l'identifiant unique de ligne demandé par QGIS pour une vue.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Lundi d'une semaine ISO « AAAA-Www »
LUNDI = """to_date({s}, 'IYYY-"W"IW')"""

VUES = f"""
CREATE SCHEMA carto;

CREATE VIEW carto.v_composite_zone AS
SELECT c.zone_id || '|' || c.semaine AS cle,
       c.zone_id, z.libelle, c.semaine,
       {LUNDI.format(s="c.semaine")} AS debut,
       {LUNDI.format(s="c.semaine")} + 6 AS fin,
       c.valeur, c.classe,
       (c.detail ->> 'n_composantes')::integer AS n_composantes,
       (c.detail ->> 'partiel')::boolean AS partiel,
       (SELECT string_agg(m, ', ' ORDER BY m)
          FROM jsonb_array_elements_text(c.detail -> 'manquantes') AS m) AS manquantes,
       c.semaine = (SELECT max(semaine) FROM idx.composite_zone) AS derniere,
       c.version_methodo, z.geom
FROM idx.composite_zone c
JOIN ref.zone z USING (zone_id);

CREATE VIEW carto.v_indice_zone AS
SELECT i.zone_id || '|' || i.semaine || '|' || i.indice AS cle,
       i.zone_id, z.libelle, i.indice, i.semaine,
       {LUNDI.format(s="i.semaine")} AS debut,
       {LUNDI.format(s="i.semaine")} + 6 AS fin,
       i.valeur, i.classe, i.n_stations,
       i.semaine = (SELECT max(semaine) FROM idx.indice_zone WHERE indice <> 'onde') AS derniere,
       i.version_methodo, z.geom
FROM idx.indice_zone i
JOIN ref.zone z USING (zone_id)
WHERE i.indice <> 'onde';

CREATE VIEW carto.v_onde_zone AS
SELECT i.zone_id || '|' || i.semaine AS cle,
       i.zone_id, z.libelle, i.semaine,
       {LUNDI.format(s="i.semaine")} AS debut,
       {LUNDI.format(s="i.semaine")} + 6 AS fin,
       (i.detail ->> 'date_campagne')::date AS date_campagne,
       i.detail ->> 'type_campagne' AS type_campagne,
       i.valeur AS part_sans_ecoulement,
       round((100 * i.valeur)::numeric, 1) AS pct_sans_ecoulement,
       i.n_stations,
       (i.detail ->> 'n_assec')::integer AS n_assec,
       (i.detail ->> 'n_rupture')::integer AS n_rupture,
       i.semaine = max(i.semaine) OVER (PARTITION BY i.zone_id) AS derniere,
       z.geom
FROM idx.indice_zone i
JOIN ref.zone z USING (zone_id)
WHERE i.indice = 'onde';

CREATE VIEW carto.v_indice_station AS
SELECT i.station_id || '|' || i.semaine || '|' || i.indice AS cle,
       i.station_id, s.libelle, s.source, s.zone_id, i.indice, i.semaine,
       {LUNDI.format(s="i.semaine")} AS debut,
       {LUNDI.format(s="i.semaine")} + 6 AS fin,
       i.valeur, i.classe, i.date_mesure,
       {LUNDI.format(s="i.semaine")} + 6 - i.date_mesure AS anciennete_jours,
       i.dans_composite, i.hors_reference, i.periode_ref,
       i.semaine = (SELECT max(semaine) FROM idx.indice_station) AS derniere,
       i.version_methodo, s.geom
FROM idx.indice_station i
JOIN ref.station s USING (station_id);

CREATE VIEW carto.v_retenue AS
SELECT r.station_id || '|' || r.date AS cle,
       r.station_id, s.libelle, s.zone_id, r.date,
       to_char(r.date, 'IYYY-"W"IW') AS semaine,
       date_trunc('week', r.date)::date AS debut,
       date_trunc('week', r.date)::date + 6 AS fin,
       r.volume_m3, r.capacite_m3,
       round((100 * r.volume_m3 / nullif(r.capacite_m3, 0))::numeric, 1) AS remplissage_pct,
       r.date = max(r.date) OVER (PARTITION BY r.station_id) AS derniere,
       s.geom
FROM obs.retenue_semaine r
JOIN ref.station s USING (station_id);
"""


def upgrade() -> None:
    op.execute(VUES)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS carto CASCADE;")
