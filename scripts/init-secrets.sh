#!/bin/bash
# Prépare .env et les secrets du monitoring, sans JAMAIS écraser une valeur existante.
#   dev  : ./scripts/init-secrets.sh
#   prod : sudo SECRETS_DIR=/etc/assista-crise/secrets ./scripts/init-secrets.sh
# Une nouvelle valeur ne change pas un mot de passe déjà stocké dans un volume existant
# (voir monitoring/README.md).
set -euo pipefail

cd "$(dirname "$0")/.."
SECRETS_DIR="${SECRETS_DIR:-./secrets}"
ENV_FILE="${ENV_FILE:-.env}"

# lettres et chiffres uniquement : Compose interpréterait un « $ » dans .env
random() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | cut -c1-"$1"; }

echo "Variables in $ENV_FILE:"
touch "$ENV_FILE"
# un .env sans retour à la ligne final collerait la ligne ajoutée à la précédente
[ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ] && echo >> "$ENV_FILE"
add_var() {
    if grep -q "^$1=" "$ENV_FILE"; then
        echo "  kept      $1"
    else
        echo "$1=$2" >> "$ENV_FILE"
        echo "  generated $1"
    fi
}
add_var DB_USER admin
add_var DB_PASS "$(random 32)"
add_var SECRET_KEY "$(random 64)"
add_var COMPOSE_PROFILES monitoring

echo "Monitoring secrets in $SECRETS_DIR:"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"   # protects the folder on the host
create_secret() {
    local file="$SECRETS_DIR/$1.txt"
    if [ -s "$file" ]; then
        echo "  kept      $file"
    else
        random "$2" > "$file"
        echo "  generated $file"
    fi
    # lisible par les conteneurs, qui tournent sous d'autres uid (postgres 999, grafana 472)
    chmod 644 "$file"
}
create_secret grafana_admin_password 24
create_secret pg_monitoring_password 32
if [ ! -s "$SECRETS_DIR/email_password.txt" ]; then
    echo "  TODO      $SECRETS_DIR/email_password.txt (production only: the SMTP password used by Alertmanager)"
fi
if [ ! -s "$SECRETS_DIR/healthchecks_url.txt" ]; then
    echo "  TODO      $SECRETS_DIR/healthchecks_url.txt (production only: ping URL of a healthchecks.io check)"
fi
echo "Done."
