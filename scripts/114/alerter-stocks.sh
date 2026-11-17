#!/bin/bash
# Stocks (backend/core/alertes_stock.py) : envoie à chaque institution le relevé de ses alertes
# de stock (seuil, péremption, denrée mal rangée, prêt en retard, facture échue), seulement
# quand il a changé. Ce projet n'a pas de celery-beat : ce script, appelé par cron une fois par
# jour, est le seul déclencheur -- même motif que cloturer-crises-proposees.sh.

set -euo pipefail

BACKEND=$(docker ps --format '{{.Names}}' | grep -xE 'ac_backend|backend' | head -1)

docker exec "$BACKEND" python manage.py alerter_stocks
