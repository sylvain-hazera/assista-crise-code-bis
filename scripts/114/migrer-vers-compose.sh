#!/bin/bash
# Migration UNIQUE de .114 : conteneurs lancés à la main (docker run) -> docker-compose.114.yml,
# tous renommés ac_<service>. Coupure du site : 1 à 3 minutes.
#
# 1. vérifie les prérequis (images :prod, secrets, config compose) -- rien n'est touché s'il manque
#    quelque chose ;
# 2. sauvegarde la base (backup-assista-db.sh, même sauvegarde chiffrée que celle de 3 h) ;
# 3. arrête les anciens conteneurs SANS les supprimer : renommés <nom>-avant-compose, redémarrage
#    automatique désactivé -- c'est le filet de sécurité ;
# 4. copie les deux volumes anonymes (fail2ban, redis) dans des volumes nommés ;
# 5. démarre tout via compose et vérifie le site public, l'API, Matrix, MAS, Element ;
# 6. en cas d'échec d'une vérification : retour arrière AUTOMATIQUE vers les anciens conteneurs.
#
# Retour arrière manuel plus tard : scripts/114/annuler-migration-compose.sh
# Suppression des anciens conteneurs une fois satisfait : voir la fin de la sortie de ce script.
set -euo pipefail
cd "$(dirname "$0")/../.."

COMPOSE=(docker compose -f docker-compose.114.yml)
SECRETS="${SECRETS_DIR:-/home/sylvain/.config/assista-crise/secrets}"
ETAT_DIR="/home/sylvain/backups/migration-compose"
ETAT="$ETAT_DIR/anciens-conteneurs.txt"
mkdir -p "$ETAT_DIR"

# Anciens conteneurs (nom actuel) -- tous ceux que compose remplace.
ANCIENS=(ac_waf ac_proxy frontend backend celery-worker redis ac_db ac_fail2ban ac_ssh_log_shipper
         synapse synapse-db mas element-web matrix-bridge
         ac_meshcore_bridge ac_meshcore_proxy meshtastic_bridge ac_meshtastic_proxy)

log() { echo "[$(date +%H:%M:%S)] $*"; }

# ------------------------------------------------------------------ 1. prérequis
log "Vérification des prérequis..."
for img in $("${COMPOSE[@]}" config --images | sort -u); do
  docker image inspect "$img" >/dev/null 2>&1 || { echo "Image absente : $img (construire d'abord)"; exit 1; }
done
for f in backend.env waf.env db.env synapse.env synapse-db.env matrix-bridge.env meshcore-bridge.env \
         meshcore-proxy.env meshtastic-bridge.env meshtastic-proxy.env fail2ban.env \
         grafana_admin_password.txt pg_monitoring_password.txt email_password.txt; do
  [ -s "$SECRETS/$f" ] || { echo "Secret absent : $SECRETS/$f (lancer scripts/114/preparer-monitoring.sh)"; exit 1; }
done
[ -s /home/sylvain/.config/assista-crise/monitoring/alertmanager.114.yml ] \
  || { echo "Config Alertmanager locale absente : ~/.config/assista-crise/monitoring/alertmanager.114.yml"; exit 1; }
"${COMPOSE[@]}" config --quiet
if [ -s "$ETAT" ]; then
  echo "Une migration a déjà eu lieu ($ETAT existe) -- rien à faire."; exit 1
fi
for c in "${ANCIENS[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || { echo "Conteneur attendu introuvable : $c"; exit 1; }
done

# ------------------------------------------------------------------ 2. sauvegarde
log "Sauvegarde de la base..."
/home/sylvain/scripts/backup-assista-db.sh >> /home/sylvain/backups/assista-db/backup.log 2>&1
log "Sauvegarde OK ($(ls -t /home/sylvain/backups/assista-db/ | head -1))"

# ------------------------------------------------------------------ 3. arrêt des anciens
retour_arriere() {
  log "!!! RETOUR ARRIÈRE vers les anciens conteneurs"
  "${COMPOSE[@]}" down --remove-orphans || true
  # ordre : bases d'abord, WAF en dernier
  while IFS='|' read -r ancien politique; do
    [ -n "$ancien" ] || continue
    docker rename "$ancien-avant-compose" "$ancien" 2>/dev/null || true
    docker update --restart="$politique" "$ancien" >/dev/null || true
  done < "$ETAT"
  for c in ac_db synapse-db redis synapse mas backend celery-worker frontend element-web matrix-bridge \
           ac_meshcore_bridge ac_meshcore_proxy meshtastic_bridge ac_meshtastic_proxy ac_fail2ban \
           ac_ssh_log_shipper ac_proxy ac_waf; do
    docker start "$c" >/dev/null || log "Impossible de redémarrer $c"
  done
  sleep 5
  docker exec ac_proxy nginx -s reload || true
  mv "$ETAT" "$ETAT.annule-$(date +%Y%m%d-%H%M%S)"
  log "Retour arrière terminé : état d'avant la migration."
}

log "Arrêt des anciens conteneurs (conservés, renommés <nom>-avant-compose)..."
: > "$ETAT"
for c in "${ANCIENS[@]}"; do
  echo "$c|$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$c")" >> "$ETAT"
done
trap 'log "Erreur inattendue ligne $LINENO"; retour_arriere; exit 1' ERR
for c in "${ANCIENS[@]}"; do
  docker update --restart=no "$c" >/dev/null
  docker stop -t 20 "$c" >/dev/null
  docker rename "$c" "$c-avant-compose"
done
# Conteneur orphelin jamais démarré (créé le 07/09, sans nom choisi).
docker rm gracious_taussig >/dev/null 2>&1 || true

# ------------------------------------------------------------------ 4. volumes anonymes -> nommés
copier_volume() {   # $1 = ancien conteneur, $2 = point de montage, $3 = volume nommé
  local src
  src=$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" "$1-avant-compose")
  docker volume create "$3" >/dev/null
  docker run --rm -v "$src":/de:ro -v "$3":/vers alpine sh -c 'cp -a /de/. /vers/'
  log "Volume $src ($1:$2) copié dans $3"
}
copier_volume ac_fail2ban /data ac_fail2ban_data
copier_volume redis /data ac_redis_data

# ------------------------------------------------------------------ 5. démarrage compose
log "Démarrage de la pile compose..."
"${COMPOSE[@]}" up -d
trap - ERR

verifier() {   # $1 = libellé, $2 = URL, $3 = regex des codes acceptés
  local code=000
  for _ in $(seq 1 36); do      # jusqu'à 3 minutes (le backend migre + collectstatic au démarrage)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$2" || true)
    if [[ "$code" =~ ^($3)$ ]]; then log "OK  $1 ($code)"; return 0; fi
    sleep 5
  done
  log "ÉCHEC $1 : $2 a répondu $code"
  return 1
}

ok=1
verifier "site public"   "https://assista-crise.fr/"                                   "200"     || ok=0
verifier "API"           "https://www.assista-crise.fr/api/institution-types/"         "200|401|403" || ok=0
verifier "Matrix"        "https://matrix.assista-crise.fr/_matrix/client/versions"     "200"     || ok=0
verifier "MAS"           "https://auth.assista-crise.fr/.well-known/openid-configuration" "200"  || ok=0
verifier "Element"       "https://chat.assista-crise.fr/"                              "200"     || ok=0
# Sans cookie d'administrateur : 401 attendu = le proxy route bien /grafana/ ET le contrôle
# d'accès répond (un 200 ici voudrait dire Grafana ouvert à tous).
verifier "Grafana"       "https://www.assista-crise.fr/grafana/api/health"             "401"     || ok=0
arretes=$("${COMPOSE[@]}" ps -a --status exited --status restarting --services)
[ -z "$arretes" ] || { log "Services arrêtés ou en boucle : $arretes"; ok=0; }

if [ "$ok" != 1 ]; then
  "${COMPOSE[@]}" ps -a
  for s in $arretes; do "${COMPOSE[@]}" logs --tail 30 "$s"; done
  retour_arriere
  exit 1
fi

"${COMPOSE[@]}" ps --format 'table {{.Name}}\t{{.Status}}'
cat <<FIN

Migration réussie. Les anciens conteneurs sont arrêtés et conservés (<nom>-avant-compose).
Retour arrière possible tant qu'ils existent : scripts/114/annuler-migration-compose.sh
Une fois satisfait (quelques jours), pour les supprimer :
  docker rm $(printf '%s-avant-compose ' "${ANCIENS[@]}")
FIN
