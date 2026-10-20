#!/bin/bash
# Secrets du monitoring + rôle PostgreSQL "monitoring" (lecture seule des statistiques) sur .114.
# Idempotent : un secret déjà présent n'est jamais régénéré, le rôle est créé ou mis à jour.
#
# Les trois fichiers sont lisibles par tous (644) : compose les monte tels quels dans des
# conteneurs qui ne tournent pas sous l'uid de sylvain (grafana 472, nobody...). Le dossier
# lui-même reste en 700, aucun autre compte de l'hôte ne peut y accéder.
set -euo pipefail

D="${SECRETS_DIR:-/home/sylvain/.config/assista-crise/secrets}"

for f in grafana_admin_password pg_monitoring_password; do
  if [ ! -s "$D/$f.txt" ]; then
    python3 -c "import secrets; print(secrets.token_urlsafe(24), end='')" > "$D/$f.txt"
    echo "Créé : $D/$f.txt"
  fi
done

# Mot de passe SMTP d'Alertmanager : le même compte no-reply@assista-crise.fr que l'application.
grep '^EMAIL_HOST_PASSWORD=' "$D/backend.env" | cut -d= -f2- | tr -d '\n' > "$D/email_password.txt"
chmod 644 "$D/grafana_admin_password.txt" "$D/pg_monitoring_password.txt" "$D/email_password.txt"

# Mot de passe transmis par stdin (\set), jamais en argument : il n'apparaît dans aucune liste
# de processus. svc_dbmaint = superuser de maintenance (voir backup-assista-db.sh).
DB=$(docker ps --format '{{.Names}}' | grep -x 'ac_db')
{
  printf "\\\\set pw '%s'\n" "$(cat "$D/pg_monitoring_password.txt")"
  cat <<'SQL'
SELECT 'CREATE ROLE monitoring LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'monitoring') \gexec
ALTER ROLE monitoring WITH LOGIN PASSWORD :'pw';
GRANT pg_monitor TO monitoring;
SQL
} | docker exec -i "$DB" psql -q -v ON_ERROR_STOP=1 -U svc_dbmaint -d assista-db
echo "Rôle PostgreSQL 'monitoring' prêt (pg_monitor)."
