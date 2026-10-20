#!/bin/bash
# Mise en place (une fois, 20/10/2026) des pages admin Supervision WAF / Fail2ban :
# Loki + Alloy, journal de fail2ban dans un fichier, nouveaux tableaux de bord Grafana.
# Relançable sans risque : l'historique n'est importé que si le journal est encore vide.
#   scripts/114/activer-supervision-securite.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

# 1. Historique : fail2ban écrivait jusqu'ici dans `docker logs` (ancien conteneur d'avant compose,
#    puis l'actuel). On le recopie au début de son nouveau fichier de journal, pour que la page
#    Fail2ban montre aussi les bans passés. Sans les "failed to parse timeText" (bruit corrigé par
#    le datepattern de la jail modsecurity).
docker volume create ac_fail2ban_logs >/dev/null
if docker run --rm -v ac_fail2ban_logs:/l alpine:3.20 test -s /l/fail2ban.log; then
  echo "Journal fail2ban déjà présent : historique non réimporté."
else
  {
    docker logs ac_fail2ban-avant-compose 2>&1 || true
    docker logs ac_fail2ban 2>&1
  } | grep -v 'failed to parse timeText' \
    | docker run --rm -i -v ac_fail2ban_logs:/l alpine:3.20 sh -c 'cat > /l/fail2ban.log'
  echo "Historique fail2ban importé : $(docker run --rm -v ac_fail2ban_logs:/l alpine:3.20 sh -c 'wc -l < /l/fail2ban.log') lignes."
fi

# 2. fail2ban (journal dans le fichier + correctifs de fuseau horaire de ~/.config/assista-crise/
#    fail2ban), Loki, Alloy, Grafana (source Loki + tableaux de bord), frontend (pages admin).
scripts/114/deployer.sh fail2ban loki alloy grafana frontend

# 3. Prometheus relit prometheus.114.yml (nouvelles cibles loki et alloy).
docker kill -s HUP ac_prometheus >/dev/null
echo "Prometheus rechargé."
