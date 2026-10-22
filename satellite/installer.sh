#!/usr/bin/env bash
# =====================================================================================
#  INSTALLATION RECOMMANDÉE — une seule commande, aucune question (20/10/2026)
#
#    ./installer.sh installer <JETON>
#
#  Le jeton (et la commande complète, prête à copier) s'obtiennent sur la page Satellites du
#  central. Le script : installe Docker si besoin, enrôle ce satellite, ATTEND qu'un
#  administrateur clique « Valider » sur la page Satellites, récupère SEUL ses identifiants,
#  génère tous les secrets locaux, détecte les radios branchées (MeshCore / Meshtastic),
#  trouve la carte hors ligne du département, puis démarre. Interrompu (Ctrl+C, coupure) :
#  relancer `./installer.sh installer` (sans jeton) reprend où il en était.
#  Radio branchée plus tard : `./installer.sh connecter-noeud`.
# =====================================================================================
#
# Ancien parcours en deux temps (toujours accepté) détaillé ci-dessous.
#
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
# Mémoire de l'enrôlement (id, secret de récupération, profil, département...) : permet de
# reprendre `installer` après une interruption. Permissions restreintes (contient un secret).
FICHIER_ENROLEMENT="$REPERTOIRE_SCRIPT/.enrolement"

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
    command -v curl >/dev/null 2>&1 || erreur "curl est requis : sudo apt install -y curl"
    command -v python3 >/dev/null 2>&1 || erreur "python3 est requis : sudo apt install -y python3"
}

# Champ d'un objet JSON (vide si absent) -- python3 plutôt qu'un grep fragile : c'est un grep
# sur la mauvaise clé ("id" au lieu de "satellite_id") qui empêchait l'ancien parcours de
# mémoriser l'identifiant du satellite.
json_champ() {
    python3 -c 'import json,sys
try:
    v = json.loads(sys.argv[1]).get(sys.argv[2])
except Exception:
    v = None
print("" if v is None else v)' "$1" "$2"
}

secret_aleatoire() {
    python3 -c 'import secrets; print(secrets.token_urlsafe(36))'
}

port_occupe() {
    # port_occupe <port> -> vrai si un programme de la machine écoute déjà sur ce port TCP
    if command -v ss >/dev/null 2>&1; then
        ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$1\$"
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
    fi
}

port_libre() {
    # port_libre <port souhaité> -> ce port s'il est libre, sinon le suivant libre
    local port="$1"
    while port_occupe "$port"; do port=$((port + 1)); done
    echo "$port"
}

fixer_env() {
    # fixer_env <CLE> <valeur> : remplace ou ajoute la ligne dans .env
    if grep -qE "^$1=" "$FICHIER_ENV"; then
        sed -i "s|^$1=.*|$1=$2|" "$FICHIER_ENV"
    else
        echo "$1=$2" >> "$FICHIER_ENV"
    fi
}

cles_chiffrement() {
    # Clés de chiffrement des champs personnels du backend local (core/crypto_fields.py) :
    # sans elles il ne démarre pas (« FIELD_BLIND_INDEX_KEY n'est pas configurée », constaté le
    # 20/10/2026). Générées une seule fois : les changer rendrait les données locales illisibles.
    if [ -z "$(valeur_env FIELD_ENCRYPTION_KEY)" ]; then
        fixer_env FIELD_ENCRYPTION_KEY "$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
    fi
    if [ -z "$(valeur_env FIELD_BLIND_INDEX_KEY)" ]; then
        fixer_env FIELD_BLIND_INDEX_KEY "$(secret_aleatoire)"
    fi
}

aligner_mot_de_passe_db() {
    # La base locale garde le mot de passe de sa toute première création (volume
    # postgres_data) : une réinstallation qui régénère DB_PASS faisait échouer le backend
    # (« password authentication failed for user », constaté le 20/10/2026). On réaligne
    # toujours la base sur .env, par la connexion locale du conteneur (sans mot de passe).
    local utilisateur mot_de_passe
    utilisateur="$(valeur_env DB_USER)"; mot_de_passe="$(valeur_env DB_PASS)"
    [ -n "$utilisateur" ] && [ -n "$mot_de_passe" ] || return 0
    (cd "$REPERTOIRE_SCRIPT" && docker compose --profile full up -d db >/dev/null)
    local i
    for i in $(seq 1 30); do
        (cd "$REPERTOIRE_SCRIPT" && docker compose --profile full exec -T db pg_isready -U "$utilisateur" -d assista-db >/dev/null 2>&1) && break
        sleep 2
    done
    if (cd "$REPERTOIRE_SCRIPT" && docker compose --profile full exec -T db \
            psql -q -U "$utilisateur" -d assista-db -c "ALTER USER \"$utilisateur\" PASSWORD '$mot_de_passe';" >/dev/null 2>&1); then
        log "Mot de passe de la base locale aligné sur .env."
    else
        log "Attention : mot de passe de la base locale non réaligné (voir docker compose logs db)."
    fi
}

ports_publies() {
    # Ports publiés par le profil full (backend local, application web) : si un autre programme les
    # occupe déjà sur la machine (ex. une autre appli en 8000, constaté le 20/10/2026 : « failed
    # to set up container networking ... external connectivity »), on prend le suivant libre.
    # Un port déjà tenu par CE satellite (relance) est gardé tel quel.
    local cle defaut service actuel
    for cle_defaut_service in BACKEND_PORT:8010:backend WEB_PORT:80:frontend; do
        IFS=: read -r cle defaut service <<< "$cle_defaut_service"
        actuel="$(valeur_env "$cle")"; actuel="${actuel:-$defaut}"
        if port_occupe "$actuel" && [ -z "$(cd "$REPERTOIRE_SCRIPT" && docker compose ps -q "$service" 2>/dev/null)" ]; then
            local nouveau
            nouveau="$(port_libre "$((actuel + 1))")"
            log "Port $actuel déjà utilisé sur cette machine : $service publié sur $nouveau."
            actuel="$nouveau"
        fi
        fixer_env "$cle" "$actuel"
    done
}

ips_privees() {
    # Adresses IPv4 privées (RFC 1918) de la machine, hors réseaux internes de Docker : celles
    # par lesquelles un téléphone du site ouvre l'appli
    ip -4 -o addr show 2>/dev/null \
        | awk '$2 !~ /^(lo|docker|br-|veth|virbr)/ {split($4, a, "/"); print a[1]}' \
        | grep -E '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' || true
}

afficher_acces_web() {
    # URL de l'application locale et compte admin local (profil full uniquement)
    local port email mot_de_passe ip suffixe
    port="$(valeur_env WEB_PORT)"; port="${port:-80}"
    suffixe="$([ "$port" = "80" ] && echo "" || echo ":$port")"
    email="$(valeur_env DJANGO_SUPERUSER_EMAIL)"
    mot_de_passe="$(valeur_env DJANGO_SUPERUSER_PASSWORD)"
    echo
    echo "================  Accès à l'application du satellite (sans internet)  ================"
    echo "  Depuis un téléphone ou un PC connecté au même réseau (Wi-Fi / câble) :"
    local trouve=0
    for ip in $(ips_privees); do
        echo "    http://$ip$suffixe/"
        trouve=1
    done
    [ "$trouve" = 1 ] || echo "    http://<adresse IP de cette machine>$suffixe/   (aucune IP privée détectée)"
    echo "  Compte administrateur local :"
    echo "    identifiant  : ${email:-(non défini)}"
    echo "    mot de passe : ${mot_de_passe:-(non défini)}"
    echo "  Les comptes de l'institution sont aussi recopiés ici (synchronisation toutes les"
    echo "  5 min tant qu'internet est disponible) : chacun garde son identifiant habituel."
    echo "  Réafficher ces informations : $0 acces-web"
    echo "======================================================================================"
}

valeur_fichier() {
    # valeur_fichier <fichier> <CLE> -> valeur (vide si absente)
    { grep -E "^$2=" "$1" 2>/dev/null || true; } | tail -n1 | cut -d= -f2-
}

# Docker juste installé : l'utilisateur n'est pas encore dans le groupe "docker" (il faudrait
# se reconnecter) -- on passe alors par sudo plutôt que d'arrêter l'installation.
DOCKER_SUDO=0
docker() {
    if [ "$DOCKER_SUDO" = 1 ]; then sudo docker "$@"; else command docker "$@"; fi
}
preparer_acces_docker() {
    if command docker info >/dev/null 2>&1; then
        DOCKER_SUDO=0
    elif sudo docker info >/dev/null 2>&1; then
        DOCKER_SUDO=1
        log "Docker utilisé via sudo (reconnectez-vous plus tard pour vous en passer)."
    else
        erreur "Docker ne répond pas (même via sudo) : vérifiez son installation (sudo systemctl status docker)."
    fi
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
    satellite_id="$(json_champ "$corps" satellite_id)"
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
            log "Devices série détectés sur cette machine (préférez un nom /dev/serial/by-id/... :"
            log "il suit la radio, alors que /dev/ttyACM0 et /dev/ttyACM1 peuvent s'inverser au redémarrage) :"
            ls -l /dev/serial/by-id/ 2>/dev/null | sed -n 's/^.* \(usb-[^ ]*\) -> .*\/\(tty[^/]*\)$/  \/dev\/serial\/by-id\/\1  (\2)/p'
            ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  (aucun trouvé — branchez le nœud puis relancez, ou choisissez AUCUN pour continuer sans)"
            echo
            _serie_device="$(demander "Device série du nœud MeshCore" "$(ls /dev/serial/by-id/* 2>/dev/null | head -n1 || true)")"
            _serie_device="${_serie_device:-/dev/ttyUSB0}"
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
    # type -P : le binaire, pas la fonction docker() définie plus haut (qui existe toujours).
    if type -P docker >/dev/null 2>&1; then
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
    # `|| true` : une clé absente n'est pas une erreur (set -o pipefail arrêtait sinon le script
    # en silence sur un .env plus ancien, constaté le 20/10/2026).
    { grep -E "^$1=" "$FICHIER_ENV" 2>/dev/null || true; } | tail -n1 | cut -d= -f2-
}

phase_demarrer() {
    installer_docker_si_absent

    if [ -f "$FICHIER_ENV" ]; then
        log "Configuration existante réutilisée ($FICHIER_ENV)."
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
    if [ -f "$REPERTOIRE_SCRIPT/.sans_meshtastic" ] || [ ! -e "$meshtastic_dev" ]; then
        log "Radio Meshtastic introuvable ($meshtastic_dev) -- meshtastic-bridge mis en attente (0 réplique)."
        scale_args+=(--scale meshtastic-bridge=0)
    fi

    # version affichée sur la page Satellites (signal de vie, etat_connectivite.py)
    fixer_env VERSION_LOGICIELLE "$(git -C "$REPERTOIRE_SCRIPT" describe --always 2>/dev/null || echo inconnue)"
    if [ "$profil" = "full" ]; then
        cles_chiffrement
        ports_publies
        aligner_mot_de_passe_db
    fi

    log "Démarrage (profil $profil)..."
    (cd "$REPERTOIRE_SCRIPT" && docker compose --profile "$profil" up -d --build "${scale_args[@]}")

    log "Terminé. Vérifier l'état :"
    echo "  cd $REPERTOIRE_SCRIPT && docker compose --profile $profil ps"
    echo "  docker compose --profile $profil logs -f meshcore-proxy meshcore-bridge"
    if [ "$profil" = "full" ]; then
        afficher_acces_web
    fi
}

configurer_radios() {
    # Détecte TOUTES les radios branchées (outil detecter-noeud, mode DETECTION_TOUTES), les
    # enregistre au central et écrit leur configuration dans .env -- aucune question. Une radio
    # absente met simplement son service en attente (.sans_noeud / .sans_meshtastic).
    log "Recherche des radios branchées (MeshCore / Meshtastic)..."
    local radios
    radios="$(cd "$REPERTOIRE_SCRIPT" && docker compose --profile outillage run --rm -e DETECTION_TOUTES=true detecter-noeud 2>/dev/null | tail -n1)"
    [ -n "$radios" ] || radios="[]"

    local meshcore meshtastic
    meshcore="$(python3 -c 'import json,sys
r = [x for x in json.loads(sys.argv[1] or "[]") if x.get("protocole") == "meshcore"]
print(json.dumps(r[0]) if r else "")' "$radios" 2>/dev/null || true)"
    meshtastic="$(python3 -c 'import json,sys
r = [x for x in json.loads(sys.argv[1] or "[]") if x.get("protocole") == "meshtastic"]
print(json.dumps(r[0]) if r else "")' "$radios" 2>/dev/null || true)"

    if [ -n "$meshcore" ]; then
        local device compagnon
        device="$(json_champ "$meshcore" device)"; compagnon="$(json_champ "$meshcore" compagnon_id)"
        sed -i -e "s|^MESHCORE_CONNEXION_TYPE=.*|MESHCORE_CONNEXION_TYPE=SERIE|" \
               -e "s|^MESHCORE_SERIE_DEVICE=.*|MESHCORE_SERIE_DEVICE=$device|" \
               -e "s|^MESHCORE_COMPAGNON_ID=.*|MESHCORE_COMPAGNON_ID=$compagnon|" "$FICHIER_ENV"
        rm -f "$REPERTOIRE_SCRIPT/.sans_noeud"
        log "  MeshCore    : $device${compagnon:+ (enregistré au central)}"
    else
        touch "$REPERTOIRE_SCRIPT/.sans_noeud"
        log "  MeshCore    : aucune radio -- service en attente"
    fi
    if [ -n "$meshtastic" ]; then
        local device
        device="$(json_champ "$meshtastic" device)"
        if grep -q "^MESHTASTIC_SERIE_DEVICE=" "$FICHIER_ENV"; then
            sed -i "s|^MESHTASTIC_SERIE_DEVICE=.*|MESHTASTIC_SERIE_DEVICE=$device|" "$FICHIER_ENV"
        else
            echo "MESHTASTIC_SERIE_DEVICE=$device" >> "$FICHIER_ENV"
        fi
        rm -f "$REPERTOIRE_SCRIPT/.sans_meshtastic"
        log "  Meshtastic  : $device"
    else
        touch "$REPERTOIRE_SCRIPT/.sans_meshtastic"
        log "  Meshtastic  : aucune radio -- service en attente"
    fi
}

phase_installer() {
    local jeton="${1:-}" nom="${2:-}"
    installer_docker_si_absent
    preparer_acces_docker

    # --- 1. Enrôlement (ou reprise d'une installation interrompue)
    if [ -f "$FICHIER_ENROLEMENT" ]; then
        log "Reprise de l'installation du satellite « $(valeur_fichier "$FICHIER_ENROLEMENT" SATELLITE_NOM) »."
    else
        [ -n "$jeton" ] || erreur "Usage : $0 installer <JETON>  (jeton et commande complète : page Satellites du central)"
        local central_url="${CENTRAL_URL:-https://assista-crise.fr}"
        nom="${nom:-$(hostname)}"
        log "Enrôlement de « $nom » auprès de $central_url..."
        local reponse code corps
        reponse="$(curl -sS -w '\n%{http_code}' -X POST "${central_url%/}/api/satellites/enroler/" \
            -H 'Content-Type: application/json' \
            -d "{\"jeton\": \"$jeton\", \"nom\": \"$nom\", \"version_logicielle\": \"$(git -C "$REPERTOIRE_SCRIPT" describe --always 2>/dev/null || echo inconnue)\"}")"
        code="$(echo "$reponse" | tail -n1)"
        corps="$(echo "$reponse" | sed '$d')"
        [ "$code" = "201" ] || erreur "Enrôlement refusé (HTTP $code) : $(json_champ "$corps" error) -- jeton expiré ou déjà utilisé ? Générez-en un nouveau sur la page Satellites."
        local satellite_id secret
        satellite_id="$(json_champ "$corps" satellite_id)"; secret="$(json_champ "$corps" secret_recuperation)"
        [ -n "$satellite_id" ] && [ -n "$secret" ] || erreur "Réponse d'enrôlement inattendue : $corps"
        umask 077
        cat > "$FICHIER_ENROLEMENT" <<EOF
CENTRAL_URL=${central_url%/}
SATELLITE_ID=$satellite_id
SECRET_RECUPERATION=$secret
SATELLITE_NOM=$(json_champ "$corps" nom)
PROFIL=$(json_champ "$corps" profil | tr '[:upper:]' '[:lower:]')
DEPARTEMENT=$(json_champ "$corps" departement)
INSTITUTION=$(json_champ "$corps" institution_nom)
EOF
        echo "$satellite_id" > "$REPERTOIRE_SCRIPT/.satellite_id"
        log "Enrôlé : « $nom » pour $(valeur_fichier "$FICHIER_ENROLEMENT" INSTITUTION) (profil $(valeur_fichier "$FICHIER_ENROLEMENT" PROFIL))."
    fi
    local central_url satellite_id secret satellite_nom profil departement
    central_url="$(valeur_fichier "$FICHIER_ENROLEMENT" CENTRAL_URL)"
    satellite_id="$(valeur_fichier "$FICHIER_ENROLEMENT" SATELLITE_ID)"
    secret="$(valeur_fichier "$FICHIER_ENROLEMENT" SECRET_RECUPERATION)"
    satellite_nom="$(valeur_fichier "$FICHIER_ENROLEMENT" SATELLITE_NOM)"
    profil="$(valeur_fichier "$FICHIER_ENROLEMENT" PROFIL)"; profil="${profil:-gw}"
    departement="$(valeur_fichier "$FICHIER_ENROLEMENT" DEPARTEMENT)"

    # --- 2. Validation par un administrateur, puis identifiants récupérés automatiquement
    if [ ! -f "$FICHIER_ENV" ]; then
        echo
        log "ÉTAPE ADMINISTRATEUR : sur $central_url/admin/satellites, cliquez « Valider » sur la"
        log "ligne « $satellite_nom ». Ce script attend et continue tout seul (Ctrl+C possible :"
        log "relancez '$0 installer' pour reprendre)."
        local reponse code corps email password
        while true; do
            reponse="$(curl -sS -w '\n%{http_code}' -X POST "$central_url/api/satellites/$satellite_id/recuperer-identifiants/" \
                -H 'Content-Type: application/json' -d "{\"secret\": \"$secret\"}" 2>/dev/null || echo -e "\n000")"
            code="$(echo "$reponse" | tail -n1)"; corps="$(echo "$reponse" | sed '$d')"
            case "$code" in
                200) email="$(json_champ "$corps" email)"; password="$(json_champ "$corps" password)"; echo; break ;;
                202|000) printf '.'; sleep 10 ;;   # en attente de validation (ou réseau coupé : on réessaie)
                410) echo; erreur "Ce satellite a été révoqué sur le central." ;;
                *) echo; erreur "$(json_champ "$corps" error) (HTTP $code)" ;;
            esac
        done
        log "Validé : identifiants reçus automatiquement."

        # --- 3. Configuration complète, sans question (secrets générés ici, jamais affichés)
        umask 077
        cat > "$FICHIER_ENV" <<EOF
CENTRAL_URL=$central_url
SATELLITE_EMAIL=$email
SATELLITE_PASSWORD=$password
SATELLITE_ID=$satellite_id
SATELLITE_NOM=$satellite_nom
MESHCORE_CONNEXION_TYPE=SERIE
MESHCORE_SERIE_DEVICE=/dev/ttyUSB0
MESHCORE_TCP_HOST=
MESHCORE_TCP_PORT=5000
MESHCORE_PROXY_PORT=5050
MESHCORE_COMPAGNON_ID=
MESHTASTIC_SERIE_DEVICE=/dev/ttyACM0
LOCAL_API_URL=
LOG_LEVEL=INFO
EOF
        if [ "$profil" = "full" ]; then
            cat >> "$FICHIER_ENV" <<EOF
SECRET_KEY=$(secret_aleatoire)
DB_USER=assista_app
DB_PASS=$(secret_aleatoire)
DJANGO_SUPERUSER_EMAIL=admin-local@service.assista-crise.local
DJANGO_SUPERUSER_PASSWORD=$(secret_aleatoire)
SATELLITE_DEPARTEMENT=${departement:-38}
PMTILES_SOURCE=
EOF
        fi
        chmod 600 "$FICHIER_ENV"
        echo "$profil" > "$REPERTOIRE_SCRIPT/.profil"
        log "Configuration écrite ($FICHIER_ENV, lisible par vous seul)."
    fi

    # --- 4. Radios, puis démarrage
    configurer_radios
    phase_demarrer

    echo
    log "Satellite « $satellite_nom » installé (profil $profil). Il apparaît « Actif » sur la page"
    log "Satellites du central d'ici une minute. Radio branchée plus tard : $0 connecter-noeud"
}

phase_connecter_noeud() {
    # Radio branchée après l'installation : même détection automatique que `installer`
    # (MeshCore et/ou Meshtastic), puis recréation des seuls services radio concernés.
    [ -f "$FICHIER_ENV" ] || erreur "$FICHIER_ENV introuvable — installez d'abord : $0 installer <JETON>"
    installer_docker_si_absent
    preparer_acces_docker
    configurer_radios
    phase_demarrer
}

case "${1:-}" in
    installer)
        verifier_prerequis
        phase_installer "${2:-}" "${3:-}"
        ;;
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
    acces-web)
        afficher_acces_web
        ;;
    *)
        echo "Usage :"
        echo "  $0 installer <JETON>    # installation complète, sans question (recommandé)"
        echo "  $0 installer            # reprendre une installation interrompue"
        echo "  $0 connecter-noeud      # radio branchée après l'installation"
        echo "  $0 demarrer             # redémarrer le satellite (après une mise à jour : git pull d'abord)"
        echo "  $0 acces-web            # URL de l'application et compte admin local (profil full)"
        echo
        echo "Ancien parcours (installations commencées avant le 20/10/2026) :"
        echo "  $0 enroler <jeton> <nom> <gw|full>  puis  $0 demarrer"
        exit 1
        ;;
esac
