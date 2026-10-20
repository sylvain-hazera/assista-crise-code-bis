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
# Nœud MeshCore : à l'étape "demarrer", en plus de SERIE/TCP, un troisième choix "AUCUN" permet
# d'installer sans nœud branché (demande utilisateur du 16/10 — scénario "installation sans
# nœud connecté, mais une vraie option") : meshcore-proxy est alors gardé à 0 réplique (--scale,
# voir phase_demarrer) plutôt que de planter au démarrage sur un device /dev inexistant — tout
# le reste du satellite (détection continue, assista-crise local en profil full, etc.)
# fonctionne normalement en l'attendant. Une fois le nœud branché (plus tard, scénario 2) :
#
#   3. ./installer.sh connecter-noeud
#      -> relance la détection ponctuelle (même outil que `detecter-noeud`), écrit le device/
#         l'identifiant CompagnonMeshCore trouvés dans .env, recrée meshcore-proxy (qui ne
#         plantera plus, le device existe désormais) et appliquer-config-proxy (pour qu'il
#         reparte avec le bon MESHCORE_COMPAGNON_ID).
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

    # Mémorisé à part (comme .profil) : .env n'existe pas encore à ce stade (créé par
    # phase_demarrer) — relu et écrit dans SATELLITE_ID à l'étape 2, nécessaire à la
    # synchronisation local -> central (sync-sortant, voir synchroniser_sortant.py).
    local satellite_id
    satellite_id="$(echo "$corps" | grep -o '"id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
    if [ -n "$satellite_id" ]; then
        echo "$satellite_id" > "$REPERTOIRE_SCRIPT/.satellite_id"
        log "Identifiant du satellite mémorisé ($satellite_id) — sera écrit dans .env à l'étape 2."
    else
        log "AVERTISSEMENT : impossible d'extraire l'identifiant du satellite de la réponse ci-dessus."
        log "Notez-le manuellement, vous devrez le renseigner dans SATELLITE_ID (fichier .env)."
    fi

    log "PROCHAINE ÉTAPE (humaine, côté central) : demandez à un administrateur de valider ce"
    log "satellite depuis la page Satellites — il obtiendra un email et un mot de passe affichés"
    log "UNE SEULE FOIS à cet instant. Notez-les, vous en aurez besoin pour : $0 demarrer"
}

demander_connexion_meshcore() {
    # Remplit par référence (nameref bash) les variables nommées $1 (connexion_type) et $2
    # (serie_device) -- mutualisé, SEULE façon d'appeler ceci depuis phase_demarrer (demande
    # utilisateur du 16/10 : "installation sans nœud connecté (mais une vraie option)").
    local -n _connexion_type="$1"
    local -n _serie_device="$2"
    local saisie
    saisie="$(demander "Connexion MeshCore : SERIE (USB), TCP (LAN) ou AUCUN (pas de nœud pour l'instant -- à connecter plus tard avec '$0 connecter-noeud')" "SERIE")"
    _connexion_type="$(echo "$saisie" | tr '[:lower:]' '[:upper:]')"
    case "$_connexion_type" in
        SERIE)
            echo
            log "Devices série détectés sur cette machine :"
            ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  (aucun trouvé — branchez le nœud puis relancez, ou choisissez AUCUN pour continuer sans)"
            echo
            _serie_device="$(demander "Device série du nœud MeshCore" "/dev/ttyUSB0")"
            ;;
        TCP)
            _serie_device="/dev/ttyUSB0"
            ;;
        AUCUN)
            _serie_device="/dev/ttyUSB0"
            log "Installation sans nœud MeshCore pour l'instant — meshcore-proxy restera arrêté"
            log "(0 réplique) jusqu'à ce que vous lanciez : $0 connecter-noeud"
            ;;
        *)
            erreur "Connexion invalide : '$saisie' (attendu SERIE, TCP ou AUCUN)."
            ;;
    esac
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

# Valeur d'une variable du .env du satellite (vide si absente).
valeur_env() {
    grep -E "^$1=" "$FICHIER_ENV" 2>/dev/null | tail -n1 | cut -d= -f2-
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
        demander_connexion_meshcore connexion_type serie_device
        if [ "$connexion_type" = "AUCUN" ]; then
            compagnon_id=""
            touch "$REPERTOIRE_SCRIPT/.sans_noeud"
        else
            compagnon_id="$(demander "UUID du CompagnonMeshCore (laisser vide si pas encore créé)" "")"
            rm -f "$REPERTOIRE_SCRIPT/.sans_noeud"
        fi

        local satellite_id
        satellite_id="$(cat "$REPERTOIRE_SCRIPT/.satellite_id" 2>/dev/null || echo "")"
        satellite_id="$(demander "Identifiant du satellite (SATELLITE_ID, mémorisé à l'enrôlement)" "$satellite_id")"

        # "AUCUN" n'est compris que par ce script (voir .sans_noeud, le vrai signal lu par le
        # bloc docker compose up ci-dessous) -- jamais écrit tel quel dans .env, qui doit rester
        # une valeur SERIE/TCP valide pour tout autre lecteur (meshcore-proxy, appliquer-config-
        # proxy) -- SERIE ici n'est qu'un placeholder dormant tant que meshcore-proxy est à 0
        # réplique, remplacé par le vrai device dès `connecter-noeud`.
        local connexion_type_env
        connexion_type_env="$([ "$connexion_type" = "AUCUN" ] && echo "SERIE" || echo "$connexion_type")"

        cat > "$FICHIER_ENV" <<EOF
CENTRAL_URL=$central_url
SATELLITE_EMAIL=$satellite_email
SATELLITE_PASSWORD=$satellite_password
SATELLITE_ID=$satellite_id
SATELLITE_NOM=$satellite_nom
MESHCORE_CONNEXION_TYPE=$connexion_type_env
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

    # .sans_noeud (posé par demander_connexion_meshcore si "AUCUN" choisi, retiré dès
    # connecter-noeud) -- relu à CHAQUE lancement de phase_demarrer, pas seulement à la première
    # configuration ci-dessus, pour qu'un simple "demarrer" répété garde meshcore-proxy à 0
    # réplique tant que connecter-noeud n'a pas été lancé (sinon il planterait sur un device
    # /dev inexistant, voir docker-compose.yml:meshcore-proxy).
    local scale_args=()
    if [ -f "$REPERTOIRE_SCRIPT/.sans_noeud" ]; then
        log "Pas de nœud MeshCore connecté -- meshcore-proxy restera à 0 réplique jusqu'à :"
        log "  $0 connecter-noeud"
        scale_args=(--scale meshcore-proxy=0)
    fi

    # Périphériques série absents (PC sans radio branchée, nœud débranché) : docker compose
    # refuse de démarrer un service dont le device /dev n'existe pas, et fait alors échouer TOUT
    # le démarrage ("error gathering device information ... no such file or directory", constaté
    # le 20/10/2026 sur un PC portable). Le service concerné est mis en attente (0 réplique) ; le
    # reste du satellite démarre normalement. Rebrancher la radio puis relancer "demarrer".
    local connexion meshcore_dev meshtastic_dev
    connexion="$(valeur_env MESHCORE_CONNEXION_TYPE)"
    meshcore_dev="$(valeur_env MESHCORE_SERIE_DEVICE)"; meshcore_dev="${meshcore_dev:-/dev/ttyUSB0}"
    meshtastic_dev="$(valeur_env MESHTASTIC_SERIE_DEVICE)"; meshtastic_dev="${meshtastic_dev:-/dev/ttyACM0}"
    if [ ! -f "$REPERTOIRE_SCRIPT/.sans_noeud" ] && [ "${connexion:-SERIE}" = "SERIE" ] && [ ! -e "$meshcore_dev" ]; then
        log "Nœud MeshCore introuvable ($meshcore_dev) -- meshcore-proxy mis en attente (0 réplique)."
        scale_args+=(--scale meshcore-proxy=0)
    fi
    if [ ! -e "$meshtastic_dev" ]; then
        log "Radio Meshtastic introuvable ($meshtastic_dev) -- meshtastic-bridge mis en attente (0 réplique)."
        scale_args+=(--scale meshtastic-bridge=0)
    fi

    log "Démarrage (profil $profil)..."
    (cd "$REPERTOIRE_SCRIPT" && docker compose --profile "$profil" up -d --build "${scale_args[@]}")

    log "Terminé. Vérifier l'état :"
    echo "  cd $REPERTOIRE_SCRIPT && docker compose --profile $profil ps"
    echo "  docker compose --profile $profil logs -f meshcore-proxy meshcore-bridge"
}

phase_connecter_noeud() {
    # Scénario "installer un nœud USB plus tard" (demande utilisateur du 16/10) : réutilise
    # l'outil de détection ponctuelle déjà existant (detecter-noeud, voir sa propre docstring et
    # detecter_noeud_serie.py) plutôt que de dupliquer la logique de détection en bash -- il
    # sait déjà distinguer MeshCore/Meshtastic, s'enregistrer auprès du central (idempotent par
    # pubkey_hex) et persister le résultat.
    [ -f "$FICHIER_ENV" ] || erreur "$FICHIER_ENV introuvable — lancez d'abord : $0 demarrer"
    installer_docker_si_absent

    log "Détection du nœud MeshCore branché (peut prendre quelques secondes)..."
    local resultat
    resultat="$(cd "$REPERTOIRE_SCRIPT" && docker compose --profile outillage run --rm detecter-noeud 2>/dev/null | tail -n1)"

    if [ -z "$resultat" ] || [ "$resultat" = "null" ]; then
        erreur "Aucun nœud détecté — vérifiez le branchement USB (ou la connexion TCP) et relancez cette commande."
    fi
    log "Détecté : $resultat"

    local protocole device compagnon_id
    protocole="$(echo "$resultat" | grep -o '"protocole"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
    device="$(echo "$resultat" | grep -o '"device"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"
    compagnon_id="$(echo "$resultat" | grep -o '"compagnon_id"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/')"

    if [ "$protocole" != "meshcore" ]; then
        erreur "Nœud détecté en $protocole, pas MeshCore (voir meshtastic-bridge pour un nœud Meshtastic)."
    fi
    [ -n "$device" ] || erreur "Device introuvable dans la réponse de détection : $resultat"

    # Réécriture CIBLÉE de .env (sed en place, pas une réécriture complète) -- ne doit jamais
    # perdre les identifiants déjà présents (SATELLITE_EMAIL/PASSWORD, SECRET_KEY si full...).
    sed -i \
        -e "s|^MESHCORE_CONNEXION_TYPE=.*|MESHCORE_CONNEXION_TYPE=SERIE|" \
        -e "s|^MESHCORE_SERIE_DEVICE=.*|MESHCORE_SERIE_DEVICE=$device|" \
        "$FICHIER_ENV"
    if [ -n "$compagnon_id" ]; then
        sed -i "s|^MESHCORE_COMPAGNON_ID=.*|MESHCORE_COMPAGNON_ID=$compagnon_id|" "$FICHIER_ENV"
        log "Enregistré côté central sous CompagnonMeshCore $compagnon_id."
    else
        log "AVERTISSEMENT : pas encore enregistré côté central (central injoignable au moment"
        log "de la détection) — relancez '$0 connecter-noeud' une fois la connexion rétablie,"
        log "appliquer-config-proxy ne pourra pas suivre la config central sans cet identifiant."
    fi
    rm -f "$REPERTOIRE_SCRIPT/.sans_noeud"

    local profil
    profil="$(cat "$REPERTOIRE_SCRIPT/.profil" 2>/dev/null || echo "gw")"

    # --no-deps : ne recrée QUE ces deux services (pas meshcore-bridge, qui ne parle qu'à
    # meshcore-proxy en local via TCP 127.0.0.1 et n'a donc jamais besoin d'être recréé pour un
    # changement de device -- même principe qu'appliquer_config_proxy.py, voir sa docstring sur
    # pourquoi une recréation et pas un simple restart).
    log "Device configuré ($device) -- recréation de meshcore-proxy et appliquer-config-proxy..."
    (cd "$REPERTOIRE_SCRIPT" && docker compose --profile "$profil" up -d --no-deps meshcore-proxy appliquer-config-proxy)

    log "Terminé. Vérifier :"
    echo "  cd $REPERTOIRE_SCRIPT && docker compose --profile $profil logs -f meshcore-proxy meshcore-bridge"
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
    connecter-noeud)
        verifier_prerequis
        phase_connecter_noeud
        ;;
    *)
        echo "Usage :"
        echo "  $0 enroler <jeton> <nom> <gw|full>   # étape 1 : s'enrôler auprès du central"
        echo "  $0 demarrer                          # étape 2 : configurer et démarrer, une fois validé"
        echo "  $0 connecter-noeud                   # si démarré sans nœud (AUCUN) : à lancer une fois branché"
        exit 1
        ;;
esac
