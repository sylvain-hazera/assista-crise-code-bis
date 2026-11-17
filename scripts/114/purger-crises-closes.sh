#!/bin/bash
# RGPD : purge les demandes, offres et signalements des habitants pour les crises closes depuis
# plus de trente jours (backend/core/management/commands/cleanup_crises.py). La crise, sa main
# courante, ses rapports et son suivi post-critique sont conservés. Ce projet n'a pas de
# celery-beat : ce script, appelé par cron une fois par nuit, est le seul déclencheur -- même
# motif que cloturer-crises-proposees.sh.

set -euo pipefail

BACKEND=$(docker ps --format '{{.Names}}' | grep -xE 'ac_backend|backend' | head -1)

docker exec "$BACKEND" python manage.py cleanup_crises
