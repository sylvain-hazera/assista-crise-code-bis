#!/bin/bash
# Crée le rôle "monitoring" (lecture seule) de postgres-exporter. Exécuté UNIQUEMENT sur une base
# neuve ; sur une base existante, le créer à la main (monitoring/README.md).
set -e

PASSWORD="$(cat /run/secrets/pg_monitoring_password)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v monitoring_password="$PASSWORD" <<'SQL'
CREATE ROLE monitoring WITH LOGIN PASSWORD :'monitoring_password';
GRANT pg_monitor TO monitoring;   -- rôle intégré : lecture des statistiques uniquement
SQL
