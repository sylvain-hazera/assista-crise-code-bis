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
# clé Fernet : 32 octets en base64 « urlsafe » (aucun « $ », donc sans risque dans .env)
fernet_key() { openssl rand -base64 32 | tr '+/' '-_'; }

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
# Chiffrement des données personnelles (core/crypto_fields.py, core/file_crypto.py), lues par le
# backend de dev uniquement (docker-compose.override.yml). Perdre ou changer l'une de ces clés
# rend illisibles les données chiffrées avec elle : sauvegarder .env. Jamais les clés de prod.
add_var FIELD_ENCRYPTION_KEY "$(fernet_key)"
add_var FIELD_BLIND_INDEX_KEY "$(random 64)"
add_var FILE_ENCRYPTION_KEY "$(fernet_key)"
# Comptes du broker MQTT de dev (mosquitto.dev.conf) : exporter pour le monitoring, dev pour les tests
add_var MQTT_EXPORTER_PASSWORD "$(random 32)"
add_var MQTT_DEV_PASSWORD "$(random 32)"

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
# Paire de clés des jetons de connexion à Grafana (backend/core/grafana.py) : la publique est un
# secret de Grafana, la privée est lue par le backend dans GRAFANA_JWT_PRIVATE_KEY.
JWT_KEY="$SECRETS_DIR/grafana_jwt_private.pem"
if [ -s "$JWT_KEY" ]; then
    echo "  kept      $JWT_KEY"
else
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$JWT_KEY" 2>/dev/null
    echo "  generated $JWT_KEY"
fi
chmod 600 "$JWT_KEY"
openssl pkey -in "$JWT_KEY" -pubout -out "$SECRETS_DIR/grafana_jwt_public.pem"
chmod 644 "$SECRETS_DIR/grafana_jwt_public.pem"
if [ "$SECRETS_DIR" = "./secrets" ]; then
    # dev : dans .env (PEM sur une ligne, \n littéraux) ; prod : à injecter dans l'env du backend
    add_var GRAFANA_JWT_PRIVATE_KEY "$(awk '{printf "%s\\n", $0}' "$JWT_KEY")"
else
    echo "  TODO      GRAFANA_JWT_PRIVATE_KEY in the backend environment (one line: awk '{printf \"%s\\\\n\", \$0}' $JWT_KEY)"
fi
if [ ! -s "$SECRETS_DIR/email_password.txt" ]; then
    echo "  TODO      $SECRETS_DIR/email_password.txt (production only: the SMTP password used by Alertmanager)"
fi
if [ ! -s "$SECRETS_DIR/healthchecks_url.txt" ]; then
    echo "  TODO      $SECRETS_DIR/healthchecks_url.txt (production only: ping URL of a healthchecks.io check)"
fi
echo "Done."
