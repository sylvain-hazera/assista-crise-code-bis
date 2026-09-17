#!/usr/bin/env bash
# Wizard d'installation d'un satellite — voir le cadrage "Chantier B" (plan) : Raspberry Pi OS
# standard + Docker, PAS une image disque pré-construite (décision du 2026-09-17).
#
# En deux phases, parce que la validation d'un satellite est un geste humain volontaire côté
# central (SatelliteViewSet.valider, un administrateur clique dans la page Satellites) — ce
# script ne peut pas se l'auto-accorder, ni récupérer les identifiants à la place de cet
# administrateur (affichés UNE SEULE FOIS à qui clique "Valider") :
#
#   1. ./installer.sh enroler <jeton> <nom> <profil>
#        - jeton : généré par un administrateur central (page Satellites -> "Générer un
#          jeton"), valable 24h, usage unique.
#        - nom : nom de ce satellite (ex: "satellite-mairie-xyz").
#        - profil : gw ou full.
#      -> crée l'entrée EN_ATTENTE côté central, affiche l'UUID du satellite. Un administrateur
#         doit ensuite le valider depuis la page Satellites et vous communiquer les
#         identifiants affichés à cet instant (email + mot de passe), à saisir à l'étape 2.
#
#   2. ./installer.sh demarrer
#      -> installe Docker si besoin, demande les informations restantes de façon interactive
#         (identifiants reçus à l'étape 1, connexion au(x) nœud(s) radio), écrit .env, lance
#         `docker compose --profile <profil> up -d`.
#
# Non testé sur un vrai Raspberry Pi à ce jour (rédigé sans matériel sous la main, voir le
# commit qui l'introduit) — l'installation de Docker et la détection série sont les points à
# vérifier en priorité au premier vrai essai.
set -euo pipefail

REPERTOIRE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FICHIER_ENV="$REPERTOIRE_SCRIPT/.env"

log() { echo "==> $*"; }
erreur() { echo "ERREUR : $*" >&2; exit 1; }

demander() {
    # demander "Question" "valeur_par_defaut" -> imprime la réponse sur stdout.
    local question="$1" defaut="${2:-}" reponse
    if [ -n "$defaut" ]; then
        read -r -p "$question [$defaut] : " reponse
        echo "${reponse:-$defaut}"
    else
        read -r -p "$question : " reponse
        echo "$reponse"
    fi
}

demander_secret() {
    local question="$1" reponse
    read -r -s -p "$question : " reponse
    echo >&2
    echo "$reponse"
}

verifier_prerequis() {
    command -v curl >/dev/null 2>&1 || erreur "curl est requis (apt install curl)."
}

phase_enroler() {
    local jeton="$1" nom="$2" profil="$3" profil_api
    [ "$profil" = "gw" ] || [ "$profil" = "full" ] || erreur "profil doit être 'gw' ou 'full' (reçu : $profil)."
    # L'API (ProfilSatellite, backend/core/models.py) attend "GW"/"FULL" en majuscules — pas la
    # même convention que --profile de docker compose (minuscules) utilisé partout ailleurs
    # dans ce script. Trouvé en testant pour de vrai contre .113 (sinon 400 "profil requis",
    # message trompeur qui ne dit pas que c'est une question de casse).
    profil_api="$(echo "$profil" | tr '[:lower:]' '[:upper:]')"

    local central_url
    central_url="$(demander "URL du central" "https://assista-crise.fr")"

    log "Enrôlement auprès de $central_url..."
    local reponse code corps
    reponse="$(curl -sS -w '\n%{http_code}' -X POST "${central_url%/}/api/satellites/enroler/" \
        -H 'Content-Type: application/json' \
        -d "{\"jeton\": \"$jeton\", \"nom\": \"$nom\", \"profil\": \"$profil_api\"}")"
    code="$(echo "$reponse" | tail -n1)"
    corps="$(echo "$reponse" | sed '$d')"

    if [ "$code" != "201" ]; then
        erreur "L'enrôlement a échoué (HTTP $code) : $corps"
    fi

    log "Enrôlé avec succès :"
    echo "$corps"
    echo
    log "PROCHAINE ÉTAPE (humaine, côté central) : demandez à un administrateur de valider ce"
    log "satellite depuis la page Satellites — il obtiendra un email et un mot de passe affichés"
    log "UNE SEULE FOIS à cet instant. Notez-les, vous en aurez besoin pour : $0 demarrer"
}

installer_docker_si_absent() {
    if command -v docker >/dev/null 2>&1; then
        log "Docker déjà installé ($(docker --version))."
        return
    fi
    log "Docker absent — installation via le script officiel get.docker.com..."
    curl -fsSL https://get.docker.com | sh
    log "Docker installé. Vous devrez peut-être vous reconnecter (ou relancer ce script) pour"
    log "que l'appartenance au groupe 'docker' prenne effet sans sudo."
}

phase_demarrer() {
    installer_docker_si_absent

    if [ -f "$FICHIER_ENV" ]; then
        log "$FICHIER_ENV existe déjà — relancé tel quel sans écraser vos réponses précédentes."
    else
        log "Configuration du satellite (Entrée pour garder la valeur par défaut entre crochets)."
        local central_url satellite_nom satellite_email satellite_password profil
        central_url="$(demander "URL du central" "https://assista-crise.fr")"
        satellite_nom="$(demander "Nom de ce satellite" "satellite-1")"
        satellite_email="$(demander "Email du compte de service (reçu de l'administrateur)" "")"
        satellite_password="$(demander_secret "Mot de passe du compte de service (reçu de l'administrateur)")"
        profil="$(demander "Profil (gw ou full)" "gw")"

        local connexion_type serie_device compagnon_id
        connexion_type="$(demander "Connexion MeshCore : SERIE (USB) ou TCP (LAN)" "SERIE")"
        if [ "$connexion_type" = "SERIE" ]; then
            echo
            log "Devices série détectés sur cette machine :"
            ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  (aucun trouvé — branchez le nœud puis relancez si besoin)"
            echo
            serie_device="$(demander "Device série du nœud MeshCore" "/dev/ttyUSB0")"
        else
            serie_device="/dev/ttyUSB0"
        fi
        compagnon_id="$(demander "UUID du CompagnonMeshCore (laisser vide si pas encore créé)" "")"

        cat > "$FICHIER_ENV" <<EOF
CENTRAL_URL=$central_url
SATELLITE_EMAIL=$satellite_email
SATELLITE_PASSWORD=$satellite_password
SATELLITE_NOM=$satellite_nom
MESHCORE_CONNEXION_TYPE=$connexion_type
MESHCORE_SERIE_DEVICE=$serie_device
MESHCORE_TCP_HOST=
MESHCORE_TCP_PORT=5000
MESHCORE_PROXY_PORT=5050
MESHCORE_COMPAGNON_ID=$compagnon_id
LOCAL_API_URL=
LOG_LEVEL=INFO
EOF
        if [ "$profil" = "full" ]; then
            log "Profil full : quelques réglages supplémentaires."
            {
                echo "SECRET_KEY=$(demander_secret 'SECRET_KEY Django (une chaîne aléatoire longue)')"
                echo "DB_USER=assista_app"
                echo "DB_PASS=$(demander_secret 'Mot de passe de la base de données locale')"
                echo "DJANGO_SUPERUSER_EMAIL=$(demander 'Email admin local' "$satellite_email")"
                echo "DJANGO_SUPERUSER_PASSWORD=$(demander_secret 'Mot de passe admin local')"
                echo "SATELLITE_DEPARTEMENT=$(demander 'Code département (pour les tuiles offline)' '38')"
                echo "PMTILES_SOURCE=$(demander 'URL du build PMTiles (https://maps.protomaps.com/builds)' '')"
            } >> "$FICHIER_ENV"
        fi
        chmod 600 "$FICHIER_ENV"
        log "$FICHIER_ENV écrit (permissions restreintes — contient des identifiants)."

        # Le profil choisi à l'installation n'est pas relu automatiquement au prochain
        # `up -d` : on le mémorise à part pour que ce script sache quoi relancer.
        echo "$profil" > "$REPERTOIRE_SCRIPT/.profil"
    fi

    local profil
    profil="$(cat "$REPERTOIRE_SCRIPT/.profil" 2>/dev/null || demander "Profil à démarrer (gw ou full)" "gw")"

    log "Démarrage (profil $profil)..."
    (cd "$REPERTOIRE_SCRIPT" && docker compose --profile "$profil" up -d --build)

    log "Terminé. Vérifier l'état :"
    echo "  cd $REPERTOIRE_SCRIPT && docker compose --profile $profil ps"
    echo "  docker compose --profile $profil logs -f meshcore-proxy meshcore-bridge"
}

case "${1:-}" in
    enroler)
        verifier_prerequis
        [ $# -eq 4 ] || erreur "Usage : $0 enroler <jeton> <nom> <gw|full>"
        phase_enroler "$2" "$3" "$4"
        ;;
    demarrer)
        verifier_prerequis
        phase_demarrer
        ;;
    *)
        echo "Usage :"
        echo "  $0 enroler <jeton> <nom> <gw|full>   # étape 1 : s'enrôler auprès du central"
        echo "  $0 demarrer                          # étape 2 : configurer et démarrer, une fois validé"
        exit 1
        ;;
esac
