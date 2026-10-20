#!/bin/bash
# Déploiement courant sur .114 : reconstruit puis recrée les services donnés, rien d'autre.
#   scripts/114/deployer.sh backend frontend
#   scripts/114/deployer.sh proxy
# Remplace les `docker stop && docker rm && docker run ...` à la main.
set -euo pipefail
cd "$(dirname "$0")/../.."

COMPOSE=(docker compose -f docker-compose.114.yml)
[ $# -gt 0 ] || { echo "Usage : $0 <service> [service...]  (services : $("${COMPOSE[@]}" config --services | sort | tr '\n' ' '))"; exit 1; }

SERVICES=("$@")
# celery-worker tourne sur l'image du backend : toujours redéployé avec lui.
if printf '%s\n' "${SERVICES[@]}" | grep -qx backend && ! printf '%s\n' "${SERVICES[@]}" | grep -qx celery-worker; then
  SERVICES+=(celery-worker)
fi

"${COMPOSE[@]}" build "${SERVICES[@]}"
"${COMPOSE[@]}" up -d --no-deps "${SERVICES[@]}"

# ac_proxy résout backend/frontend une seule fois au démarrage : sans reload, il continue
# d'envoyer vers l'ancienne IP du conteneur recréé (502 par intermittence).
if printf '%s\n' "${SERVICES[@]}" | grep -qxE 'backend|frontend'; then
  docker exec ac_proxy nginx -s reload
fi

"${COMPOSE[@]}" ps "${SERVICES[@]}"
