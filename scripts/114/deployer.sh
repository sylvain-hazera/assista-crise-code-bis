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
# Même image pour le worker des travaux lourds (22/11/2026), l'ingestion des observateurs
# MeshCore et l'analyse des orages (19/11/2026).
for meme_image in celery-worker-lourd observateurs-meshcore orages blitzortung; do
  if printf '%s\n' "${SERVICES[@]}" | grep -qx backend && ! printf '%s\n' "${SERVICES[@]}" | grep -qx "$meme_image"; then
    SERVICES+=("$meme_image")
  fi
done

# L'image d'analyse météo (service orages) est construite SUR celle du backend : le backend
# d'abord, sinon elle repartirait de l'ancienne image et embarquerait l'ancien code.
if printf '%s\n' "${SERVICES[@]}" | grep -qx backend; then
  "${COMPOSE[@]}" build backend
  AUTRES=()
  for s in "${SERVICES[@]}"; do [ "$s" = backend ] || AUTRES+=("$s"); done
  [ ${#AUTRES[@]} -eq 0 ] || "${COMPOSE[@]}" build "${AUTRES[@]}"
else
  "${COMPOSE[@]}" build "${SERVICES[@]}"
fi
"${COMPOSE[@]}" up -d --no-deps "${SERVICES[@]}"

# ac_proxy résout backend/frontend une seule fois au démarrage : sans reload, il continue
# d'envoyer vers l'ancienne IP du conteneur recréé (502 par intermittence).
if printf '%s\n' "${SERVICES[@]}" | grep -qxE 'backend|frontend'; then
  docker exec ac_proxy nginx -s reload
fi

"${COMPOSE[@]}" ps "${SERVICES[@]}"
