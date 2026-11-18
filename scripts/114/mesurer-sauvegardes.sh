#!/usr/bin/env bash
# Mesure l'age des sauvegardes et la taille du cache de construction Docker, pour Prometheus.
#
# 18/11/2026. Une sauvegarde qui s'arrete ne fait aucun bruit : on le decouvre le jour ou l'on
# en a besoin. Ce script n'en FAIT aucune et ne lit aucun secret : il regarde la date des
# fichiers et la derniere ligne "OK" des journaux, et ecrit un fichier que node-exporter lit
# (collecteur textfile). Les alertes sont dans monitoring/prometheus/alerts.yml, groupe backups.
#
# Cron (toutes les 5 minutes) :
#   */5 * * * * /home/sylvain/scripts/mesurer-sauvegardes.sh
#
# Variables : SAUVEGARDES_BASE (dossier des dumps), JOURNAL_CONTINU (journal media + WAL),
# SUPERVISION_TEXTFILE_DIR (dossier lu par node-exporter, le meme que dans docker-compose.114.yml).
set -u

SAUVEGARDES_BASE="${SAUVEGARDES_BASE:-$HOME/backups/assista-db}"
JOURNAL_CONTINU="${JOURNAL_CONTINU:-$HOME/scripts/backup-snapshot.log}"
SORTIE_DIR="${SUPERVISION_TEXTFILE_DIR:-$HOME/supervision-textfile}"
SORTIE="$SORTIE_DIR/sauvegardes.prom"

mkdir -p "$SORTIE_DIR"
maintenant="$(date +%s)"
tmp="$(mktemp "$SORTIE_DIR/.sauvegardes.XXXXXX")"

{
    echo "# HELP assista_sauvegarde_age_secondes Age de la derniere sauvegarde reussie."
    echo "# TYPE assista_sauvegarde_age_secondes gauge"
    echo "# HELP assista_sauvegarde_octets Taille de la derniere sauvegarde de la base."
    echo "# TYPE assista_sauvegarde_octets gauge"

    # La base : le dump le plus recent. Aucun dump = on ne publie rien pour ce type, et c'est
    # l'age des autres ou BackupMetricsMissing qui parlera.
    dernier="$(ls -t "$SAUVEGARDES_BASE"/assista-db-*.age 2>/dev/null | head -1)"
    if [ -n "$dernier" ]; then
        echo "assista_sauvegarde_age_secondes{type=\"base\"} $(( maintenant - $(stat -c %Y "$dernier") ))"
        echo "assista_sauvegarde_octets{type=\"base\"} $(stat -c %s "$dernier")"
    fi

    # Medias et WAL : la derniere ligne "[type] OK" du journal, horodatee en debut de ligne.
    for type in media wal; do
        ligne="$(grep -F "[$type] OK" "$JOURNAL_CONTINU" 2>/dev/null | tail -1)"
        quand="$(date -d "${ligne%% *}" +%s 2>/dev/null || true)"
        [ -n "$ligne" ] && [ -n "$quand" ] && \
            echo "assista_sauvegarde_age_secondes{type=\"$type\"} $(( maintenant - quand ))"
    done

    # Le cache de construction Docker : il a rempli le disque a 95 % le 17/11/2026.
    cache="$(docker system df --format '{{.Type}}|{{.Size}}' 2>/dev/null | awk -F'|' '$1=="Build Cache"{print $2}')"
    octets="$(printf '%s' "${cache%B}" | tr 'kmgt' 'KMGT' | LC_ALL=C numfmt --from=si 2>/dev/null || true)"
    if [ -n "$octets" ]; then
        echo "# HELP assista_docker_cache_construction_octets Taille du cache de construction Docker."
        echo "# TYPE assista_docker_cache_construction_octets gauge"
        echo "assista_docker_cache_construction_octets $octets"
    fi
} > "$tmp"

# Remplacement atomique : node-exporter ne lit jamais un fichier a moitie ecrit.
chmod 644 "$tmp" && mv "$tmp" "$SORTIE"
