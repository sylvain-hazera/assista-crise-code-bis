"""Correspondance User <-> identifiant Matrix, et petits calculs partagés par les vues et le
service-pont matrix-bridge (voir doc de conception "Matrix / Element" -- positionnement
permanent en mission + 1 salon privé par équipe, indépendant de MeshCore qui reste en place
pour son propre usage, voir CanalMeshCore).

Pas de table de correspondance stockée : le localpart Matrix est calculé de façon déterministe
à partir de l'UUID du User (`u` + hex sans tirets, seuls caractères autorisés par la spec
Matrix pour un localpart) -- Django et le pont recalculent la même valeur indépendamment,
aucune synchronisation à maintenir. Le même localpart est aussi exposé en claim OIDC
(`preferred_username`, voir core/oidc.py).

IMPORTANT (incident réel du 17/10, voir Laura) : avec la délégation MAS active (voir plus bas),
NE JAMAIS précréer un compte Matrix via l'API admin Synapse legacy pour quelqu'un qui ne s'est
jamais connecté -- MAS, pas Synapse, est désormais la source d'autorité des comptes
(`external_ids`, lié au `sub` OIDC). Sous Synapse natif (avant l'adoption de MAS), le
provisioning JIT à la connexion SSO retombait silencieusement sur un compte pré-créé de même
localpart ; sous MAS, un tel compte reste orphelin (external_ids vide) et bloque la première
connexion réelle avec l'erreur "Localpart not available". Voir _compte_matrix_existe : toutes
les fonctions de ce module qui provisionnent un compte vérifient désormais qu'il existe déjà
avant d'y toucher, plutôt que de le créer à l'aveugle."""
import json
import logging
import os
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MATRIX_SERVER_NAME = os.environ.get("MATRIX_SERVER_NAME", "matrix.assista-crise.local")

# Le compte-bot (pont-matrix) n'a PAS de mot de passe utilisable : passwords.enabled est à
# false côté Synapse dès que la délégation MAS est active (voir mémoire de session -- seule
# mas-cli manage issue-compatibility-token peut lui donner un jeton, une fois, au bootstrap).
# Django relit le même jeton déjà persisté par matrix-bridge/bridge.py (TOKEN_FILE, sur le
# volume `matrix_bridge_data` partagé en lecture seule avec ce conteneur).
#
# Piège rencontré le 24/09 : l'API admin Synapse "login as user"
# (/_synapse/admin/v1/users/<id>/login), qui aurait permis d'émettre un jeton PERSONNEL pour
# l'utilisateur connecté et de laisser le navigateur parler en direct au Client-Server API,
# répond 404 M_UNRECOGNIZED dès que matrix_authentication_service est activé -- comme pour
# /login et l'inscription HMAC, MAS retire cet endpoint natif de Synapse puisqu'il devient seul
# responsable de l'émission de jetons. mas-cli sait le faire (issue-compatibility-token), mais
# uniquement en CLI dans le conteneur mas, pas via une API HTTP que Django pourrait appeler par
# requête -- et monter le socket Docker dans le backend pour l'exécuter à distance serait une
# bien plus grosse surface de risque que ce que la fonctionnalité justifie.
#
# Le chat intégré (voir TeamViewSet.salon_matrix_messages) relaie donc TOUJOURS les messages
# via le jeton du bot (jamais un jeton personnel exposé au navigateur -- accessoirement plus
# sûr aussi), avec le nom réel de l'expéditeur préfixé dans le corps du message + porté dans un
# champ d'extension `com.assistacrise.expediteur_id` (ignoré par les clients Matrix standards,
# relu par notre propre frontend pour distinguer "mes" messages). Un message envoyé depuis
# Element (X ou classique) directement reste attribué au vrai compte Matrix de son auteur --
# seuls les messages composés depuis ce panneau passent par le bot.
SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")
_TOKEN_FILE = Path(os.environ.get("TOKEN_FILE", "/data/bridge_token.json"))
_EXT_EXPEDITEUR_ID = "com.assistacrise.expediteur_id"
# Message urgent (ouvert à tout le monde, y compris un intervenant isolé, décision utilisateur
# du 26/09) : simple clé d'extension supplémentaire dans le content, même esprit que
# _EXT_EXPEDITEUR_ID -- ignorée par les clients Matrix standards.
_EXT_URGENT = "com.assistacrise.urgent"
# Clé de réaction posée par le bouton "Vu" (accusé de réception réservé aux cadres) -- un simple
# emoji, comme n'importe quelle réaction Matrix (Element l'affiche nativement même pour un
# intervenant isolé sans notre interface).
CLE_REACTION_VU = "✅"


def _bot_access_token() -> str:
    return json.loads(_TOKEN_FILE.read_text())["access_token"]


def _bot_headers() -> dict:
    return {"Authorization": f"Bearer {_bot_access_token()}"}


def _fiche_compte_matrix(user):
    """Fiche Synapse du compte (dict, displayname compris), ou None s'il n'existe pas encore --
    voir _compte_matrix_existe pour la règle (ne jamais le créer ici)."""
    reponse = requests.get(
        f"{SYNAPSE_URL}/_synapse/admin/v2/users/{matrix_user_id(user)}",
        headers=_bot_headers(), timeout=10,
    )
    return reponse.json() if reponse.status_code == 200 else None


def _accorder_nom_affiche(user, fiche, displayname=None) -> None:
    """Pose le nom affiché seulement s'il diffère de celui que Synapse connaît déjà. Le réécrire à
    l'identique n'est pas anodin : Synapse republie alors la fiche de membre de la personne dans
    TOUS ses salons (tâche de fond « update_join_states ») -- appelé à chaque rafraîchissement
    du panneau de messagerie (toutes les 8 s), ces tâches s'empilaient jusqu'à ce que Synapse
    limite le débit (429, erreur 500 sur la messagerie unifiée, constaté le 22/10/2026 avec une
    tâche en cours depuis 41 h)."""
    voulu = displayname or str(user)
    if (fiche or {}).get("displayname") == voulu:
        return
    requests.put(
        f"{SYNAPSE_URL}/_synapse/admin/v2/users/{matrix_user_id(user)}",
        headers=_bot_headers(), json={"displayname": voulu},
        timeout=10,
    ).raise_for_status()


# Une adhésion déjà assurée n'est pas revérifiée avant ce délai (voir assurer_membre_salon) ; une
# personne sans compte Matrix l'est un peu plus souvent, pour voir arriver sa première connexion.
DUREE_MEMOIRE_ADHESION_S = 6 * 3600
DUREE_MEMOIRE_SANS_COMPTE_S = 5 * 60


def _compte_matrix_existe(user) -> bool:
    """True si ce compte a déjà été provisionné côté Synapse, peu importe par qui -- NE JAMAIS
    créer un compte via PUT /_synapse/admin/v2/users/ pour quelqu'un qui n'existe pas encore :
    dans ce déploiement, MAS (pas Synapse) est la source d'autorité des comptes
    (`external_ids`, lié à l'identité OIDC) -- un compte créé directement via cette API legacy
    reste orphelin (external_ids vide, jamais lié à aucun `sub` OIDC) et bloque ensuite la
    PREMIÈRE connexion SSO réelle de la personne avec l'erreur "Localpart not available"
    (incident réel du 17/10 -- voir Laura, compte précréé par assurer_membre_salon lors de son
    ajout à une équipe, avant toute connexion). Tant que la personne ne s'est jamais connectée
    au moins une fois via MAS, l'absence de compte ici est normale, pas une erreur -- les
    appelants doivent juste renoncer pour cette fois (retenté au prochain passage, voir
    assurer_membre_salon/_assurer_compte_matrix/matrix-bridge/bridge.py::assurer_compte)."""
    reponse = requests.get(
        f"{SYNAPSE_URL}/_synapse/admin/v2/users/{matrix_user_id(user)}",
        headers=_bot_headers(), timeout=10,
    )
    return reponse.status_code == 200


def assurer_membre_salon(user, room_id, displayname=None) -> None:
    """Garantit que `user` a rejoint `room_id`, SI son compte Matrix existe déjà (voir
    _compte_matrix_existe -- ne le crée jamais ici) -- nécessaire pour qu'un régulateur qui gère
    l'équipe sans en être membre (matrix-bridge ne synchronise que les membres de l'équipe, voir
    boucle_positions/provisionner_salons dans bridge.py) apparaisse comme membre du salon, même
    si ses messages transitent par le bot. Idempotent -- y compris quand l'utilisateur a DÉJÀ
    rejoint le salon par un autre biais (ex: Element X en direct) : contrairement à son nom,
    `/_synapse/admin/v1/join/` répond 403 M_FORBIDDEN "already in the room" plutôt que de
    réussir silencieusement dans ce cas (constaté le 2026-10-04 sur la Cellule de crise, dont
    l'équipe n'a formellement aucun membre Django -- est_membre est donc toujours faux, ce qui
    déclenchait cet appel à CHAQUE accès, bloquant durablement la page pour quiconque avait déjà
    rejoint une fois). Ne fait rien (silencieusement, retenté au prochain appel) si le compte
    n'existe pas encore."""
    from django.core.cache import cache

    # Appelé à chaque rafraîchissement du panneau de messagerie (toutes les 8 s) : une adhésion
    # déjà faite est mémorisée, sans quoi chaque rafraîchissement refaisait trois appels
    # d'administration à Synapse (voir _accorder_nom_affiche pour la conséquence).
    cle = f"matrix-adhesion:{user.pk}:{room_id}"
    cle_sans_compte = f"matrix-sans-compte:{user.pk}"
    if cache.get(cle) or cache.get(cle_sans_compte):
        return
    fiche = _fiche_compte_matrix(user)
    if fiche is None:
        cache.set(cle_sans_compte, True, DUREE_MEMOIRE_SANS_COMPTE_S)
        return
    _accorder_nom_affiche(user, fiche, displayname)
    mid = matrix_user_id(user)
    reponse = requests.post(
        f"{SYNAPSE_URL}/_synapse/admin/v1/join/{room_id}",
        headers=_bot_headers(), json={"user_id": mid},
        timeout=10,
    )
    if not (reponse.status_code == 403 and "already in the room" in reponse.text):
        reponse.raise_for_status()
    cache.set(cle, True, DUREE_MEMOIRE_ADHESION_S)


def lister_messages_salon(room_id, limite=30) -> list:
    """Les `limite` derniers messages texte du salon (bot inclus s'il a lui-même posté, jamais
    le cas ici), en ordre chronologique, avec leurs réactions Matrix éventuelles (voir
    CLE_REACTION_VU -- accusé de réception "Vu", filtré par cadre côté TeamViewSet
    .salon_matrix_messages, pas ici). Le champ `moi` n'est PAS calculé ici (dépend de qui
    consulte), voir TeamViewSet.salon_matrix_messages.

    `/messages` renvoie tous les types d'événements du salon dans le même `chunk` (pas de second
    appel réseau nécessaire pour les réactions) -- seul `/sync`/`/context` bundle nativement les
    réactions sur leur événement cible (`unsigned.m.relations`), ce qui n'est pas utilisé ici."""
    response = requests.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/messages",
        headers=_bot_headers(), params={"dir": "b", "limit": str(limite)},
        timeout=10,
    )
    response.raise_for_status()
    chunk = response.json().get("chunk", [])

    messages = [
        e for e in chunk
        if e.get("type") == "m.room.message" and e.get("content", {}).get("msgtype") == "m.text"
    ]
    messages.reverse()

    reactions_par_event: dict = {}
    for e in chunk:
        if e.get("type") != "m.reaction":
            continue
        relates_to = e.get("content", {}).get("m.relates_to", {})
        if relates_to.get("rel_type") != "m.annotation":
            continue
        cible = relates_to.get("event_id")
        if not cible:
            continue
        expediteur_id = e.get("content", {}).get(_EXT_EXPEDITEUR_ID)
        if not expediteur_id:
            # Réaction posée directement depuis Element (pas via le bot) : le sender Matrix
            # brut identifie déjà le bon compte, contrairement à une réaction du bot (voir
            # envoyer_reaction_salon -- toutes les réactions "Vu" y transitent, le sender serait
            # sinon systématiquement le bot lui-même).
            uid = user_id_from_matrix_id(e.get("sender"))
            expediteur_id = str(uid) if uid else None
        reactions_par_event.setdefault(cible, []).append({
            "cle": relates_to.get("key"),
            "expediteur_id": expediteur_id,
        })

    resultat = []
    for e in messages:
        expediteur_id = e["content"].get(_EXT_EXPEDITEUR_ID)
        if not expediteur_id:
            # Pas passé par le bot (posté directement depuis Element) -- retrouver l'UUID
            # Django si c'est un compte géré par cette appli, sinon rester anonyme.
            uid = user_id_from_matrix_id(e.get("sender"))
            expediteur_id = str(uid) if uid else None
        resultat.append({
            "event_id": e["event_id"],
            "texte": e["content"].get("body", ""),
            "horodatage": e.get("origin_server_ts"),
            "expediteur_id": expediteur_id,
            "urgent": bool(e["content"].get(_EXT_URGENT)),
            "reactions": reactions_par_event.get(e["event_id"], []),
        })
    return resultat


def _assurer_compte_matrix(user, displayname=None) -> bool:
    """Si le compte Matrix de `user` existe déjà (voir _compte_matrix_existe -- ne le crée
    JAMAIS ici), met à jour son displayname -- préalable à une invitation (DM ou salon).
    Factorisé hors d'assurer_membre_salon, qui fait la même chose puis rejoint EN PLUS un salon
    précis. Renvoie False si le compte n'existe pas encore (personne jamais connectée via MAS)
    -- aux appelants (voir envoyer_dm) de renoncer proprement pour cette fois plutôt que de
    planter ou de précréer un compte orphelin."""
    fiche = _fiche_compte_matrix(user)
    if fiche is None:
        return False
    _accorder_nom_affiche(user, fiche, displayname)
    return True


def envoyer_dm(user, texte, displayname=None) -> None:
    """Envoie un message privé (DM) du bot à `user` -- utilisé pour les alertes qui doivent
    atteindre une personne précise sans dépendre d'un salon d'équipe déjà existant (ex: alerte
    SOS mesh vers les administrateurs, panne companion vers l'institution propriétaire, demande
    utilisateur du 10/10). Réutilise un salon DM déjà existant entre le bot et cette personne
    (compte `m.direct` du bot, convention standard des clients Matrix -- voir
    https://spec.matrix.org/latest/client-server-api/#dm-rooms) plutôt que d'en créer un
    nouveau à chaque appel, ce qui disperserait la conversation sur plusieurs salons distincts
    au fil du temps. `whoami` interrogé à chaque appel plutôt que mis en cache : ce n'est jamais
    un chemin chaud (quelques alertes au plus par jour), pas la peine d'introduire un état
    partagé pour économiser un aller-retour réseau. N'envoie rien (silencieusement, journalisé)
    si `user` ne s'est jamais connecté à Matrix -- voir _assurer_compte_matrix/
    _compte_matrix_existe : mieux vaut un DM manqué qu'un compte orphelin qui bloquerait sa
    future connexion."""
    if not _assurer_compte_matrix(user, displayname):
        logger.info("DM Matrix ignoré pour %s : jamais connecté à Matrix (pas encore de compte MAS).", user)
        return
    headers = _bot_headers()
    cible_mid = matrix_user_id(user)

    whoami = requests.get(f"{SYNAPSE_URL}/_matrix/client/v3/account/whoami", headers=headers, timeout=10)
    whoami.raise_for_status()
    bot_mid = whoami.json()["user_id"]

    direct = requests.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/user/{bot_mid}/account_data/m.direct",
        headers=headers, timeout=10,
    )
    mapping = direct.json() if direct.status_code == 200 else {}
    room_id = next(iter(mapping.get(cible_mid) or []), None)

    if not room_id:
        creation = requests.post(
            f"{SYNAPSE_URL}/_matrix/client/v3/createRoom",
            headers=headers,
            json={"is_direct": True, "invite": [cible_mid], "preset": "trusted_private_chat"},
            timeout=10,
        )
        creation.raise_for_status()
        room_id = creation.json()["room_id"]
        mapping[cible_mid] = [room_id]
        requests.put(
            f"{SYNAPSE_URL}/_matrix/client/v3/user/{bot_mid}/account_data/m.direct",
            headers=headers, json=mapping, timeout=10,
        ).raise_for_status()

    txn_id = uuid.uuid4().hex
    response = requests.put(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
        headers=headers, json={"msgtype": "m.text", "body": texte}, timeout=10,
    )
    response.raise_for_status()


def envoyer_message_salon(room_id, user, nom, texte, urgent=False) -> None:
    txn_id = uuid.uuid4().hex
    content = {
        "msgtype": "m.text",
        "body": f"{nom} : {texte}",
        _EXT_EXPEDITEUR_ID: str(user.id),
    }
    if urgent:
        content[_EXT_URGENT] = True
    response = requests.put(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
        headers=_bot_headers(), json=content, timeout=10,
    )
    response.raise_for_status()


def envoyer_reaction_salon(room_id, event_id, user, cle=CLE_REACTION_VU) -> None:
    """Pose une réaction Matrix (m.reaction/m.annotation) sur `event_id` -- utilisé pour
    l'accusé de réception "Vu" (réservé aux cadres, voir TeamViewSet.salon_matrix_reagir).
    Toujours postée par le bot (jamais un jeton personnel, voir doc de conception en tête de
    fichier) : porte donc `_EXT_EXPEDITEUR_ID`, exactement comme envoyer_message_salon, sinon
    le sender Matrix brut serait systématiquement le bot lui-même et on perdrait qui a vraiment
    cliqué "Vu"."""
    txn_id = uuid.uuid4().hex
    response = requests.put(
        f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/send/m.reaction/{txn_id}",
        headers=_bot_headers(),
        json={
            "m.relates_to": {"rel_type": "m.annotation", "event_id": event_id, "key": cle},
            _EXT_EXPEDITEUR_ID: str(user.id),
        },
        timeout=10,
    )
    response.raise_for_status()


def matrix_localpart(user) -> str:
    return f"u{user.id.hex}"


def matrix_user_id(user) -> str:
    return f"@{matrix_localpart(user)}:{MATRIX_SERVER_NAME}"


def user_id_from_matrix_id(matrix_user_id_str: str):
    """Décode `@u<hex>:serveur` -> UUID du User, ou None si le format ne correspond pas
    (compte Matrix non géré par cette appli, ex: le bot du pont lui-même)."""
    if not matrix_user_id_str or not matrix_user_id_str.startswith("@"):
        return None
    localpart = matrix_user_id_str[1:].split(":", 1)[0]
    if not localpart.startswith("u") or len(localpart) != 33:
        return None
    try:
        return uuid.UUID(localpart[1:])
    except ValueError:
        return None
