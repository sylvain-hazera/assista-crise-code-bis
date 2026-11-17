#!/bin/bash
# Appels aux dons (backend/core/appels_dons.py) : rappelle les engagements qui vont être rendus
# aux autres faute d'envoi annoncé, et prévient ceux qui l'ont été. Ce projet n'a pas de
# celery-beat : ce script, appelé par cron toutes les heures, est le seul déclencheur des
# rappels -- même motif que cloturer-crises-proposees.sh.
#
# Sans lui, les engagements en retard sont quand même relâchés (à la lecture suivante de
# l'appel), mais personne n'est prévenu : ni avant, ni après.

set -euo pipefail

BACKEND=$(docker ps --format '{{.Names}}' | grep -xE 'ac_backend|backend' | head -1)

docker exec "$BACKEND" python manage.py rappeler_engagements_dons
