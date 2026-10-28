#!/usr/bin/env bash
# Vérifie le frontend dans des conteneurs jetables : build de production PUIS suite de tests.
#
# Le frontend n'a pas de node_modules en local et n'est construit que par Docker : sans l'image
# de test, les 68 fichiers de test du projet étaient inexécutables. Voir frontend/Dockerfile.test
# pour le détail (Chromium d'Alpine, lanceur sans bac à sable, WebGL logiciel).
#
#   scripts/tester-frontend.sh              # build de production + suite
#   scripts/tester-frontend.sh --couverture # idem, avec le rapport de couverture
#   scripts/tester-frontend.sh --tests-seuls # suite uniquement (itération rapide)
#
# LE BUILD DE PRODUCTION PASSE EN PREMIER, ET CE N'EST PAS UN DÉTAIL. `ng test` compile en JIT
# avec une vérification de template permissive ; `ng build --configuration=production` compile
# en AOT et applique les budgets. Deux familles d'erreurs ne sont donc visibles QUE par le
# build :
#
#   - un membre `private` appelé depuis le template (NG1) ;
#   - un fichier de style qui dépasse son budget.
#
# Les deux ont fait échouer un déploiement le 28/10/2026 alors que les 118 tests étaient verts,
# ce qui est exactement le genre d'échec qu'un harnais doit attraper avant la machine de prod et
# non après. Le build d'abord parce qu'il est le plus rapide à échouer et le plus coûteux à
# découvrir tard.
#
# Le code de sortie est celui de l'étape qui échoue.
set -euo pipefail

cd "$(dirname "$0")/.."

TESTS_SEULS=""
COUVERTURE=""
for arg in "$@"; do
  case "$arg" in
    --tests-seuls) TESTS_SEULS=1 ;;
    --couverture) COUVERTURE=1 ;;
    *) echo "Option inconnue : $arg" >&2; exit 2 ;;
  esac
done

if [[ -z "$TESTS_SEULS" ]]; then
  echo "→ build de production (AOT + budgets)"
  # La même cible que le déploiement (docker-compose.114.yml, service frontend) : vérifier un
  # autre build ne garantirait rien de ce qui part en production.
  docker build -q -f frontend/Dockerfile.prod -t assista-crise-frontend:verif frontend
fi

echo "→ construction de l'image de test"
docker build -q -f frontend/Dockerfile.test -t assista-crise-frontend:test frontend

if [[ -n "$COUVERTURE" ]]; then
  echo "→ suite + couverture"
  exec docker run --rm assista-crise-frontend:test \
    npx ng test --watch=false --browsers=ChromeHeadlessCI --code-coverage
fi

echo "→ suite"
exec docker run --rm assista-crise-frontend:test
