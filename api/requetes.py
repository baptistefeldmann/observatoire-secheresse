"""Requêtes SQL de l'API, en lecture seule (rôle `lecteur`). Géométries renvoyées en WGS84
(GeoJSON, RFC 7946) ; contours de zones simplifiés (`api.simplification_m`)."""

from __future__ import annotations

ZONES = """
SELECT z.zone_id, z.libelle, z.type_zone, z.ponderations,
       c.semaine, c.valeur, c.classe, c.detail,
       ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(z.geom, :tolerance), 4326), 6)
           AS geometrie
FROM ref.zone z
LEFT JOIN idx.composite_zone c ON c.zone_id = z.zone_id AND c.semaine = :semaine
ORDER BY z.zone_id
"""

ZONE = "SELECT zone_id, libelle, type_zone, ponderations FROM ref.zone WHERE zone_id = :zone_id"

SERIE_COMPOSITE = """
SELECT semaine, valeur, classe, detail, version_methodo
FROM idx.composite_zone
WHERE zone_id = :zone_id AND semaine BETWEEN :debut AND :fin
ORDER BY semaine
"""

SERIE_INDICE_ZONE = """
SELECT semaine, valeur, classe, n_stations, detail, version_methodo
FROM idx.indice_zone
WHERE zone_id = :zone_id AND indice = :indice AND semaine BETWEEN :debut AND :fin
ORDER BY semaine
"""

SEMAINES = "SELECT DISTINCT semaine FROM idx.composite_zone ORDER BY semaine DESC"

# Une station porte un seul indice (IPS pour un piézomètre, débit pour une station
# hydrométrique) ; retenue et ONDE : dernier relevé ou dernière observation au dimanche.
STATIONS = """
SELECT s.station_id, s.source, s.code, s.libelle, s.en_service, s.zone_id,
       i.indice, i.valeur, i.classe, i.date_mesure, i.dans_composite, i.hors_reference,
       r.date AS date_releve, r.volume_m3, r.capacite_m3,
       round((100 * r.volume_m3 / nullif(r.capacite_m3, 0))::numeric, 1)::float8 AS remplissage_pct,
       o.date_campagne, o.modalite,
       ST_AsGeoJSON(ST_Transform(s.geom, 4326), 6) AS geometrie
FROM ref.station s
LEFT JOIN idx.indice_station i ON i.station_id = s.station_id AND i.semaine = :semaine
LEFT JOIN LATERAL (
    SELECT date, volume_m3, capacite_m3 FROM obs.retenue_semaine
    WHERE station_id = s.station_id AND date <= :dimanche ORDER BY date DESC LIMIT 1
) r ON s.source = 'retenue'
LEFT JOIN LATERAL (
    SELECT date_campagne, modalite FROM obs.onde
    WHERE station_id = s.station_id AND date_campagne <= :dimanche
    ORDER BY date_campagne DESC LIMIT 1
) o ON s.source = 'onde'
WHERE CAST(:source AS text) IS NULL OR s.source = :source
ORDER BY s.station_id
"""

STATION = """
SELECT station_id, source, code, libelle, en_service, zone_id, metadonnees,
       ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geometrie
FROM ref.station WHERE station_id = :station_id
"""

# Chronique brute par source : (requête, grandeur, unité)
CHRONIQUES = {
    "piezo": (
        "SELECT date, niveau_ngf AS valeur FROM obs.piezo_jour "
        "WHERE station_id = :station_id AND date BETWEEN :debut AND :fin ORDER BY date",
        "niveau_ngf", "m NGF",
    ),
    "hydro": (
        "SELECT date, qmj_ls AS valeur FROM obs.debit_jour "
        "WHERE station_id = :station_id AND date BETWEEN :debut AND :fin ORDER BY date",
        "qmj_ls", "l/s",
    ),
    "retenue": (
        "SELECT date, "
        "round((100 * volume_m3 / nullif(capacite_m3, 0))::numeric, 1)::float8 AS valeur, "
        "volume_m3, capacite_m3 FROM obs.retenue_semaine "
        "WHERE station_id = :station_id AND date BETWEEN :debut AND :fin ORDER BY date",
        "remplissage_pct", "%",
    ),
    "onde": (
        "SELECT date_campagne AS date, modalite AS valeur, type_campagne FROM obs.onde "
        "WHERE station_id = :station_id AND date_campagne BETWEEN :debut AND :fin "
        "ORDER BY date_campagne",
        "modalite", "",
    ),
}  # fmt: skip

INDICES_STATION = """
SELECT semaine, indice, valeur, classe, date_mesure, dans_composite, hors_reference,
       periode_ref, version_methodo
FROM idx.indice_station
WHERE station_id = :station_id AND semaine BETWEEN :debut AND :fin
ORDER BY semaine
"""

ENVELOPPE_STATION = """
SELECT indice, pas, periode, minimum, mediane, maximum, n_annees, periode_ref, hors_reference
FROM idx.enveloppe_station WHERE station_id = :station_id ORDER BY periode
"""

# Retenues : enveloppe des années complètes précédentes (D6), par semaine ISO
ENVELOPPE_RETENUE = """
WITH taux AS (
    SELECT extract(isoyear FROM date)::int AS annee, extract(week FROM date)::int AS periode,
           100 * volume_m3 / nullif(capacite_m3, 0) AS remplissage
    FROM obs.retenue_semaine
    WHERE station_id = :station_id AND extract(isoyear FROM date) < :annee
)
SELECT periode, min(remplissage) AS minimum,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY remplissage) AS mediane,
       max(remplissage) AS maximum, count(DISTINCT annee) AS n_annees,
       min(annee) || '-' || max(annee) AS periode_ref
FROM taux GROUP BY periode ORDER BY periode
"""

SYNTHESE_COMPOSITE = """
SELECT c.zone_id, z.libelle, c.valeur, c.classe, c.detail
FROM idx.composite_zone c JOIN ref.zone z USING (zone_id)
WHERE c.semaine = :semaine ORDER BY c.valeur
"""

SYNTHESE_STATIONS = """
WITH parclasse AS (
    SELECT indice, classe, count(*) AS n, count(*) FILTER (WHERE dans_composite) AS au_composite
    FROM idx.indice_station WHERE semaine = :semaine GROUP BY indice, classe
)
SELECT indice, sum(n)::int AS n, sum(au_composite)::int AS au_composite,
       jsonb_object_agg(classe, n ORDER BY classe) AS repartition
FROM parclasse GROUP BY indice ORDER BY indice
"""

SYNTHESE_ONDE = """
SELECT DISTINCT ON (i.zone_id) i.zone_id, z.libelle, i.semaine, i.valeur, i.n_stations,
       i.detail
FROM idx.indice_zone i JOIN ref.zone z USING (zone_id)
WHERE i.indice = 'onde' AND i.semaine <= :semaine
  AND left(i.semaine, 4) = left(:semaine, 4)
ORDER BY i.zone_id, i.semaine DESC
"""

# Total des retenues : relevés de la semaine, comparés aux mêmes semaines des années
# précédentes (somme des volumes / somme des capacités, D6)
SYNTHESE_RETENUES = """
WITH semaines AS (
    SELECT extract(isoyear FROM date)::int AS annee, extract(week FROM date)::int AS semaine,
           sum(volume_m3) AS volume, sum(capacite_m3) AS capacite, count(*) AS n, max(date) AS date
    FROM obs.retenue_semaine GROUP BY 1, 2
)
SELECT
    (SELECT row_to_json(c) FROM (
        SELECT volume AS volume_m3, capacite AS capacite_m3, n AS n_retenues, date,
               round((100 * volume / capacite)::numeric, 1)::float8 AS remplissage_pct
        FROM semaines WHERE annee = :annee AND semaine = :numero) c) AS courant,
    (SELECT row_to_json(e) FROM (
        SELECT round(min(100 * volume / capacite)::numeric, 1)::float8 AS minimum,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY 100 * volume / capacite))
                     ::numeric, 1)::float8 AS mediane,
               round(max(100 * volume / capacite)::numeric, 1)::float8 AS maximum,
               min(annee) || '-' || max(annee) AS periode_ref
        FROM semaines WHERE annee < :annee AND semaine = :numero) e) AS enveloppe
"""
