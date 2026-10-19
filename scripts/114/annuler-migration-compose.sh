#!/bin/bash
# Retour arrière manuel de migrer-vers-compose.sh : arrête la pile compose et redémarre les
# anciens conteneurs (<nom>-avant-compose), tant qu'ils n'ont pas été supprimés.
set -uo pipefail
cd "$(dirname "$0")/../.."
ETAT="/home/sylvain/backups/migration-compose/anciens-conteneurs.txt"
[ -s "$ETAT" ] || { echo "Aucune migration à annuler ($ETAT absent)."; exit 1; }

docker compose -f docker-compose.114.yml down --remove-orphans
while IFS='|' read -r ancien politique; do
  [ -n "$ancien" ] || continue
  docker rename "$ancien-avant-compose" "$ancien" && docker update --restart="$politique" "$ancien" >/dev/null
done < "$ETAT"
# bases d'abord, WAF en dernier
for c in ac_db synapse-db redis synapse mas backend celery-worker frontend element-web matrix-bridge \
         ac_meshcore_bridge ac_meshcore_proxy meshtastic_bridge ac_meshtastic_proxy ac_fail2ban \
         ac_ssh_log_shipper ac_proxy ac_waf; do
  docker start "$c" >/dev/null || echo "Impossible de redémarrer $c"
done
sleep 5
docker exec ac_proxy nginx -s reload
mv "$ETAT" "$ETAT.annule-$(date +%Y%m%d-%H%M%S)"
docker ps --format 'table {{.Names}}\t{{.Status}}'
