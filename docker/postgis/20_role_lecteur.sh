#!/usr/bin/env bash
# Rôle en lecture seule pour QGIS et le dashboard.
#
# Exécuté automatiquement à la création du volume PostGIS, et relançable à tout
# moment avec `make db-roles` (idempotent). Les privilèges par défaut couvrent les
# schémas et tables que le pipeline créera ensuite (ref, obs, idx, rst).
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v proprietaire="$POSTGRES_USER" \
  -v base="$POSTGRES_DB" \
  -v lecteur="$POSTGRES_LECTEUR_USER" \
  -v mdp="$POSTGRES_LECTEUR_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I', :'lecteur')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'lecteur') \gexec

ALTER ROLE :"lecteur" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'mdp';
GRANT CONNECT ON DATABASE :"base" TO :"lecteur";

-- Objets à venir, créés par le propriétaire (pipeline)
ALTER DEFAULT PRIVILEGES FOR ROLE :"proprietaire" GRANT USAGE ON SCHEMAS TO :"lecteur";
ALTER DEFAULT PRIVILEGES FOR ROLE :"proprietaire" GRANT SELECT ON TABLES TO :"lecteur";

-- Objets déjà présents
SELECT format('GRANT USAGE ON SCHEMA %I TO %I', nspname, :'lecteur')
FROM pg_namespace
WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema' \gexec

SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', nspname, :'lecteur')
FROM pg_namespace
WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema' \gexec
SQL
