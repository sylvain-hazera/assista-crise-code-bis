#!/bin/bash
# Clôt les crises dont la clôture a été proposée et dont l'échéance de sept jours est passée
# (backend/core/cloture_crise.py). Ce projet n'a pas de celery-beat : ce script, appelé par cron
# toutes les heures, est le seul déclencheur -- même motif que expedier-brouillons-oublies.sh.
#
# POURQUOI C'EST NECESSAIRE : la proposition de clôture promet une date aux habitants (« vos
# liens fonctionnent jusqu'au… ») et aux collectivités. Sans ce script, la crise resterait
# ouverte indéfiniment après l'échéance, et les rapports gardés sur le serveur avec elle.
#
# Les crises d'essai ne sont jamais closes par ce chemin.

set -euo pipefail

BACKEND=$(docker ps --format '{{.Names}}' | grep -xE 'ac_backend|backend' | head -1)

docker exec "$BACKEND" python manage.py cloturer_crises_proposees
