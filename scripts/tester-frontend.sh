#!/usr/bin/env bash
# Lance la suite de tests du frontend dans un conteneur jetable.
#
# Le frontend n'a pas de node_modules en local et n'est construit que par Docker : sans cette
# image, les 68 fichiers de test du projet étaient inexécutables. Voir frontend/Dockerfile.test
# pour le détail (Chromium d'Alpine, lanceur sans bac à sable, WebGL logiciel).
#
#   scripts/tester-frontend.sh              # toute la suite
#   scripts/tester-frontend.sh --couverture # avec le rapport de couverture
#
# Le code de sortie est celui de Karma : la commande échoue si un test échoue.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "→ construction de l'image de test"
docker build -q -f frontend/Dockerfile.test -t assista-crise-frontend:test frontend

if [[ "${1:-}" == "--couverture" ]]; then
  echo "→ suite + couverture"
  exec docker run --rm assista-crise-frontend:test \
    npx ng test --watch=false --browsers=ChromeHeadlessCI --code-coverage
fi

echo "→ suite"
exec docker run --rm assista-crise-frontend:test
