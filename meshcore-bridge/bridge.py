"""Service-pont MeshCore <-> assista-crise — phase de test (voir doc de conception
« Maillage Terrain »).

Se connecte à UN SEUL companion MeshCore (série, BLE ou TCP selon la configuration), relaie les
messages directs reçus vers l'API assista-crise, et envoie ceux mis en attente côté API par un
testeur humain (via le Django admin ou l'API directement — pas encore de page Angular dédiée
tant que le matériel n'a pas confirmé l'usage).

IMPORTANT — non vérifié sur matériel réel : les noms de champs lus dans les événements MeshCore
(`pubkey_prefix`, `text`, `public_key`...) viennent de la documentation publique du protocole,
pas d'un test avec un vrai companion. Les payloads bruts sont journalisés en DEBUG pour pouvoir
ajuster rapidement si un nom de champ diffère en pratique.

Ne PAS déployer ce service sur .114 avant d'avoir validé le matériel — voir le README de ce
dossier et la branche git dédiée.
"""

import asyncio
import logging
import os
import sys

import httpx
from meshcore import EventType, MeshCore

logger = logging.getLogger("meshcore-bridge")

DJANGO_API_URL = os.environ["DJANGO_API_URL"]
DJANGO_EMAIL = os.environ["DJANGO_BRIDGE_EMAIL"]
DJANGO_PASSWORD = os.environ["DJANGO_BRIDGE_PASSWORD"]
COMPAGNON_ID = os.environ["COMPAGNON_ID"]

CONNEXION_TYPE = os.environ.get("MESHCORE_CONNEXION_TYPE", "TCP").upper()
TCP_HOST = os.environ.get("MESHCORE_TCP_HOST")
TCP_PORT = int(os.environ.get("MESHCORE_TCP_PORT", "5000"))
SERIE_DEVICE = os.environ.get("MESHCORE_SERIE_DEVICE")
BLE_ADRESSE = os.environ.get("MESHCORE_BLE_ADRESSE")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
RECONNECT_DELAY_SECONDS = int(os.environ.get("RECONNECT_DELAY_SECONDS", "10"))
# Nombre de tentatives d'envoi d'un DM avant abandon (voir boucle_envoi/send_msg_with_retry) —
# un réseau maillé multi-saut perd couramment un premier essai, d'où plusieurs tentatives par
# défaut plutôt qu'un aller simple.
MESSAGE_SEND_MAX_ATTEMPTS = int(os.environ.get("MESSAGE_SEND_MAX_ATTEMPTS", "3"))
CONTACTS_SYNC_INTERVAL_SECONDS = int(os.environ.get("CONTACTS_SYNC_INTERVAL_SECONDS", "300"))
# Même cadence par défaut que la synchro de contacts : suivi de position actif pendant une
# mission EN_COURS (voir boucle_positions_missions) — interroge activement (req_telemetry,
# BinaryReqType.TELEMETRY) chaque nœud personnel concerné, ce qui sollicite sa radio/batterie,
# d'où un intervalle prudent plutôt qu'un rafraîchissement continu.
POSITIONS_MISSIONS_POLL_INTERVAL_SECONDS = int(os.environ.get("POSITIONS_MISSIONS_POLL_INTERVAL_SECONDS", "300"))
# Canaux d'équipe (voir TeamViewSet.provisionner_canal_meshcore) : un canal se configure
# localement sur l'appareil (set_channel), jamais à distance — ce pont doit donc le faire pour
# le companion partagé auquel il est connecté. Slots 1..CANAL_IDX_MAX sondés pour trouver un
# index libre (0 réservé, généralement "Public" par défaut sur le firmware) — non vérifié sur
# matériel réel, comme le reste de ce fichier (voir avertissement en tête).
CANAUX_POLL_INTERVAL_SECONDS = int(os.environ.get("CANAUX_POLL_INTERVAL_SECONDS", "60"))
CANAL_IDX_MAX = int(os.environ.get("CANAL_IDX_MAX", "8"))
POSITIONS_MISSIONS_REQ_TIMEOUT_SECONDS = int(os.environ.get("POSITIONS_MISSIONS_REQ_TIMEOUT_SECONDS", "20"))

# Miroir de AdvType (meshcore/packets.py) -> TypeContactMeshCore côté Django (voir models.py).
TYPE_CONTACT_PAR_ADV_TYPE = {
    0: "INCONNU",
    1: "COMPANION",
    2: "REPEATER",
    3: "ROOM",
    4: "SENSOR",
}


class DjangoClient:
    """Client HTTP vers l'API assista-crise — authentification JWT avec ré-obtention
    automatique du token d'accès (durée de vie 1h côté serveur, voir SIMPLE_JWT dans
    backend/config/settings.py). Le compte utilisé doit être un compte de service dédié,
    authentifié (IsAuthenticated suffit pour les actions que ce pont appelle)."""

    def __init__(self, base_url, email, password):
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._access_token = None
        self._client = httpx.AsyncClient(timeout=15)

    async def _authenticate(self):
        response = await self._client.post(
            f"{self._base_url}/token/", json={"email": self._email, "password": self._password}
        )
        response.raise_for_status()
        self._access_token = response.json()["access"]
        logger.info("Authentifié auprès de l'API assista-crise.")

    async def _request(self, method, path, **kwargs):
        if self._access_token is None:
            await self._authenticate()
        headers = {"Authorization": f"Bearer {self._access_token}"}
        response = await self._client.request(method, f"{self._base_url}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            # Token expiré entre-temps : une ré-authentification, puis on rejoue une fois.
            await self._authenticate()
            headers = {"Authorization": f"Bearer {self._access_token}"}
            response = await self._client.request(method, f"{self._base_url}{path}", headers=headers, **kwargs)
        response.raise_for_status()
        return response

    async def synchroniser_contacts(self, compagnon_id, contacts):
        await self._request("POST", f"/compagnons-meshcore/{compagnon_id}/synchroniser-contacts/", json={"contacts": contacts})

    async def pubkeys_a_suivre(self, compagnon_id):
        """Clés publiques des nœuds personnels à interroger activement maintenant — voir
        CompagnonMeshCoreViewSet.pubkeys_a_suivre : uniquement les nœuds d'utilisateurs
        membres d'une équipe dont la mission courante est EN_COURS, jamais en dehors."""
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/pubkeys-a-suivre/")
        return response.json().get("pubkeys", [])

    async def rapporter_etat(self, compagnon_id, etat, pubkey_hex=None, erreur=None):
        payload = {"etat": etat}
        if pubkey_hex:
            payload["pubkey_hex"] = pubkey_hex
        if erreur:
            payload["erreur"] = erreur
        await self._request("POST", f"/compagnons-meshcore/{compagnon_id}/rapporter-etat/", json=payload)

    async def logger_message_entrant(self, compagnon_id, contact_pubkey_hex, contenu):
        await self._request("POST", "/messages-meshcore/", json={
            "compagnon": compagnon_id, "direction": "ENTRANT",
            "contact_pubkey_hex": contact_pubkey_hex, "contenu": contenu,
        })

    async def messages_a_envoyer(self, compagnon_id):
        response = await self._request("GET", "/messages-meshcore/a-envoyer/", params={"compagnon": compagnon_id})
        return response.json()

    async def marquer_message(self, message_id, statut, erreur=None):
        payload = {"statut": statut}
        if erreur:
            payload["erreur"] = erreur
        await self._request("PATCH", f"/messages-meshcore/{message_id}/", json=payload)

    async def canaux_a_provisionner(self, compagnon_id):
        """Canaux d'équipe pas encore configurés localement sur ce companion — voir
        CompagnonMeshCoreViewSet.canaux_a_provisionner."""
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/canaux-a-provisionner/")
        return response.json()

    async def rapporter_canal_provisionne(self, compagnon_id, canal_id, canal_idx):
        await self._request(
            "POST", f"/compagnons-meshcore/{compagnon_id}/rapporter-canal-provisionne/",
            json={"canal_id": canal_id, "canal_idx": canal_idx},
        )

    async def messages_canal_a_envoyer(self):
        response = await self._request("GET", "/messages-canal-meshcore/a-envoyer/")
        return response.json()

    async def logger_message_canal_entrant(self, canal_id, contenu):
        await self._request("POST", "/messages-canal-meshcore/", json={
            "canal": canal_id, "direction": "ENTRANT", "contenu": contenu,
        })

    async def marquer_message_canal(self, message_id, statut, erreur=None):
        payload = {"statut": statut}
        if erreur:
            payload["erreur"] = erreur
        await self._request("PATCH", f"/messages-canal-meshcore/{message_id}/", json=payload)

    async def aclose(self):
        await self._client.aclose()


async def connecter_meshcore():
    if CONNEXION_TYPE == "TCP":
        if not TCP_HOST:
            raise RuntimeError("MESHCORE_TCP_HOST est requis pour une connexion TCP.")
        logger.info("Connexion TCP à %s:%s...", TCP_HOST, TCP_PORT)
        return await MeshCore.create_tcp(TCP_HOST, TCP_PORT)
    if CONNEXION_TYPE == "SERIE":
        if not SERIE_DEVICE:
            raise RuntimeError("MESHCORE_SERIE_DEVICE est requis pour une connexion série (ex: /dev/ttyUSB0).")
        logger.info("Connexion série à %s...", SERIE_DEVICE)
        return await MeshCore.create_serial(SERIE_DEVICE, 115200)
    if CONNEXION_TYPE == "BLE":
        if not BLE_ADRESSE:
            raise RuntimeError("MESHCORE_BLE_ADRESSE est requis pour une connexion BLE.")
        logger.info("Connexion BLE à %s...", BLE_ADRESSE)
        return await MeshCore.create_ble(BLE_ADRESSE)
    raise RuntimeError(f"MESHCORE_CONNEXION_TYPE inconnu : {CONNEXION_TYPE!r} (attendu TCP, SERIE ou BLE).")


async def obtenir_pubkey(meshcore):
    """Interroge le nœud pour ses propres informations (EventType.SELF_INFO, via
    send_appstart()). Non bloquant si ça échoue : la connexion reste utilisable, seul le
    rapprochement `pubkey_hex` sur CompagnonMeshCore restera vide — à surveiller au premier
    test réel."""
    try:
        resultat = await meshcore.commands.send_appstart()
        logger.debug("Réponse APP_START : %r", getattr(resultat, "payload", None))
        if resultat and resultat.type == EventType.SELF_INFO:
            payload = resultat.payload or {}
            return payload.get("public_key") or payload.get("pubkey")
    except Exception:
        logger.exception("Impossible de récupérer la clé publique du companion (non bloquant).")
    return None


def enregistrer_ecouteurs(meshcore, django, compagnon_id, sur_deconnexion, canaux_idx_map):
    """`canaux_idx_map` (dict canal_idx -> canal_id, partagé avec boucle_provisionnement_canaux)
    permet de rattacher un message de canal entrant au bon CanalMeshCore — un canal n'a pas
    d'identité serveur à ce niveau protocolaire, seulement un index local (voir
    PacketType.CHANNEL_MSG_RECV, aucun champ clé/id de canal dans la trame)."""

    async def _sur_message(event):
        payload = event.payload or {}
        logger.debug("Événement CONTACT_MSG_RECV brut : %r", payload)
        pubkey_prefix = payload.get("pubkey_prefix") or payload.get("pubkey") or "inconnu"
        texte = payload.get("text", "")
        logger.info("Message reçu de %s (%d caractères).", pubkey_prefix, len(texte))
        try:
            await django.logger_message_entrant(compagnon_id, pubkey_prefix, texte)
        except Exception:
            logger.exception("Échec de journalisation d'un message entrant côté API.")

    async def _sur_message_canal(event):
        payload = event.payload or {}
        logger.debug("Événement CHANNEL_MSG_RECV brut : %r", payload)
        canal_idx = payload.get("channel_idx")
        texte = payload.get("text", "")
        canal_id = canaux_idx_map.get(canal_idx)
        if canal_id is None:
            logger.warning("Message reçu sur le canal local %s, non rattaché à un CanalMeshCore connu — ignoré.", canal_idx)
            return
        logger.info("Message reçu sur le canal %s (%d caractères).", canal_id, len(texte))
        try:
            await django.logger_message_canal_entrant(canal_id, texte)
        except Exception:
            logger.exception("Échec de journalisation d'un message de canal entrant côté API.")

    async def _sur_deconnexion(event):
        logger.warning("Déconnecté du companion MeshCore.")
        sur_deconnexion.set()

    meshcore.subscribe(EventType.CONTACT_MSG_RECV, _sur_message)
    meshcore.subscribe(EventType.CHANNEL_MSG_RECV, _sur_message_canal)
    meshcore.subscribe(EventType.DISCONNECTED, _sur_deconnexion)


async def boucle_envoi(meshcore, django, compagnon_id):
    """Interroge périodiquement l'API pour les messages sortants en attente plutôt que
    d'exposer un port entrant sur ce conteneur — voir MessageMeshLogViewSet.a_envoyer.

    Utilise send_msg_with_retry plutôt que send_msg seul : send_msg ne fait qu'un aller simple
    et n'attend qu'un accusé LOCAL (le companion a bien pris le message en charge), pas une
    confirmation que le destinataire l'a réellement reçu — sur un réseau maillé multi-saut,
    un seul essai échoue couramment (route pas encore établie, saut intermédiaire hors
    portée...). send_msg_with_retry réessaie plusieurs fois, bascule en mode flood après
    quelques échecs directs, et surtout attend un vrai EventType.ACK de bout en bout avant de
    considérer l'envoi réussi (voir meshcore/commands/messaging.py) — un simple accusé local
    ne suffisait pas à garantir que le message était vraiment arrivé, ce qui explique des
    messages jamais reçus côté destinataire malgré un envoi local qui semblait aboutir."""
    while True:
        try:
            en_attente = await django.messages_a_envoyer(compagnon_id)
            for message in en_attente:
                try:
                    resultat = await meshcore.commands.send_msg_with_retry(
                        message["contact_pubkey_hex"], message["contenu"],
                        max_attempts=MESSAGE_SEND_MAX_ATTEMPTS,
                    )
                    if resultat is None:
                        await django.marquer_message(
                            message["id"], "ECHEC",
                            erreur=f"Aucun accusé de réception après {MESSAGE_SEND_MAX_ATTEMPTS} tentative(s).",
                        )
                        logger.warning("Échec d'envoi du message %s : pas d'accusé de réception après relances.", message["id"])
                    else:
                        await django.marquer_message(message["id"], "ENVOYE")
                        logger.info("Message %s envoyé (accusé de réception reçu).", message["id"])
                except Exception as exc:
                    logger.exception("Échec d'envoi du message %s.", message["id"])
                    try:
                        await django.marquer_message(message["id"], "ECHEC", erreur=str(exc))
                    except Exception:
                        logger.exception("Échec de la mise à jour de statut après échec d'envoi.")
        except Exception:
            logger.exception("Échec de récupération des messages en attente auprès de l'API.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def boucle_contacts(meshcore, django, compagnon_id):
    """Le firmware du companion tient déjà son propre répertoire de contacts (nom, type,
    position pour les répéteurs) — on le relit périodiquement plutôt que de le reconstruire :
    voir EventType.CONTACTS, dispatché par la lib avec le dict complet en fin de CONTACT_END."""
    while True:
        try:
            resultat = await meshcore.commands.get_contacts()
            if resultat and resultat.type == EventType.CONTACTS:
                contacts_bruts = resultat.payload or {}
                contacts = []
                for pubkey_hex, c in contacts_bruts.items():
                    contact = {
                        "pubkey_hex": pubkey_hex,
                        "nom": c.get("adv_name", ""),
                        "type_contact": TYPE_CONTACT_PAR_ADV_TYPE.get(c.get("type"), "INCONNU"),
                    }
                    lat, lon = c.get("adv_lat"), c.get("adv_lon")
                    if lat and lon:  # (0, 0) = pas de position GPS valide côté firmware
                        contact["latitude"], contact["longitude"] = lat, lon
                    if c.get("last_advert"):
                        contact["dernier_advert"] = c["last_advert"]
                    contacts.append(contact)
                if contacts:
                    await django.synchroniser_contacts(compagnon_id, contacts)
                    logger.info("Contacts synchronisés : %d.", len(contacts))
        except Exception:
            logger.exception("Échec de synchronisation des contacts.")
        await asyncio.sleep(CONTACTS_SYNC_INTERVAL_SECONDS)


async def boucle_positions_missions(meshcore, django, compagnon_id):
    """Suivi de position actif d'un nœud personnel, UNIQUEMENT pendant qu'une mission de
    l'équipe de son porteur est EN_COURS (voir doc de conception « Maillage Terrain » —
    demande explicite : jamais de suivi en continu, seulement pendant une mission active).

    Interroge la télémétrie du nœud (BinaryReqType.TELEMETRY, req_telemetry_sync) : plus
    fraîche qu'une simple annonce périodique, mais sollicite sa radio/batterie à chaque appel
    — d'où l'intervalle prudent (POSITIONS_MISSIONS_POLL_INTERVAL_SECONDS) plutôt qu'un
    rafraîchissement continu. `req_telemetry_sync` accepte directement la clé publique en
    hexadécimal comme destination (voir meshcore/commands/base.py, _validate_destination) —
    pas besoin de retrouver l'objet contact complet. La position, si présente, est le canal
    LPP de type "gps" (channel/type/value avec latitude/longitude/altitude — voir
    meshcore/lpp_json_encoder.py) : absente si le nœud interrogé n'a pas de GPS ou ne l'a pas
    activé en télémétrie, auquel cas ce nœud est silencieusement ignoré pour ce passage."""
    while True:
        try:
            pubkeys = await django.pubkeys_a_suivre(compagnon_id)
            if pubkeys:
                logger.info("Suivi de position actif pendant mission : %d nœud(s) à interroger.", len(pubkeys))
            contacts_rafraichis = []
            for pubkey_hex in pubkeys:
                try:
                    lpp = await meshcore.commands.req_telemetry_sync(
                        pubkey_hex, timeout=POSITIONS_MISSIONS_REQ_TIMEOUT_SECONDS, min_timeout=5,
                    )
                except Exception:
                    logger.exception("Échec de la requête de télémétrie pour %s.", pubkey_hex)
                    continue
                if not lpp:
                    logger.debug("Pas de réponse de télémétrie pour %s (nœud hors portée ?).", pubkey_hex)
                    continue
                position = next((canal for canal in lpp if canal.get("type") == "gps"), None)
                if not position or not isinstance(position.get("value"), dict):
                    logger.debug("Télémétrie reçue de %s sans canal GPS.", pubkey_hex)
                    continue
                lat = position["value"].get("latitude")
                lon = position["value"].get("longitude")
                if lat and lon:
                    contacts_rafraichis.append({"pubkey_hex": pubkey_hex, "latitude": lat, "longitude": lon})

            if contacts_rafraichis:
                await django.synchroniser_contacts(compagnon_id, contacts_rafraichis)
                logger.info("Position rafraîchie pour %d nœud(s) en mission.", len(contacts_rafraichis))
        except Exception:
            logger.exception("Échec du cycle de suivi de position en mission.")
        await asyncio.sleep(POSITIONS_MISSIONS_POLL_INTERVAL_SECONDS)


async def _trouver_slot_canal_libre(meshcore):
    """Sonde les index de canal locaux (1..CANAL_IDX_MAX, 0 réservé — généralement "Public"
    par défaut sur le firmware) pour trouver le premier non configuré. Non vérifié sur
    matériel réel : on traite comme libre à la fois une absence de nom ET une erreur
    protocolaire sur get_channel, faute de savoir laquelle des deux le firmware renvoie
    réellement pour un slot vide."""
    for idx in range(1, CANAL_IDX_MAX + 1):
        try:
            resultat = await meshcore.commands.get_channel(idx)
        except Exception:
            logger.exception("Échec de lecture du canal local %s.", idx)
            continue
        if resultat is None or resultat.type == EventType.ERROR:
            return idx
        nom_existant = (resultat.payload or {}).get("channel_name", "")
        if not nom_existant:
            return idx
    return None


async def boucle_provisionnement_canaux(meshcore, django, compagnon_id, canaux_idx_map):
    """Configure localement (set_channel) les canaux d'équipe pas encore présents sur CE
    companion — voir docstring de CanalMeshCore : impossible de pousser cette configuration à
    distance sur le nœud d'un membre, mais le pont peut le faire pour son propre companion
    partagé, afin de pouvoir y envoyer/recevoir en son nom."""
    while True:
        try:
            a_provisionner = await django.canaux_a_provisionner(compagnon_id)
            for canal in a_provisionner:
                canal_id, nom, cle_hex = canal["id"], canal["nom"], canal.get("cle_partagee_hex")
                if not cle_hex:
                    logger.warning("Canal %s sans clé partagée, provisionnement ignoré.", canal_id)
                    continue
                idx = await _trouver_slot_canal_libre(meshcore)
                if idx is None:
                    logger.error("Aucun slot de canal local disponible (max %d) pour provisionner « %s ».", CANAL_IDX_MAX, nom)
                    continue
                try:
                    secret = bytes.fromhex(cle_hex)
                    resultat = await meshcore.commands.set_channel(idx, nom, secret)
                except Exception:
                    logger.exception("Échec de configuration locale du canal « %s » (slot %s).", nom, idx)
                    continue
                if resultat and resultat.type == EventType.ERROR:
                    logger.error("Échec de configuration locale du canal « %s » (slot %s) : %r", nom, idx, resultat.payload)
                    continue
                canaux_idx_map[idx] = canal_id
                await django.rapporter_canal_provisionne(compagnon_id, canal_id, idx)
                logger.info("Canal « %s » configuré localement sur le slot %s.", nom, idx)
        except Exception:
            logger.exception("Échec du cycle de provisionnement des canaux.")
        await asyncio.sleep(CANAUX_POLL_INTERVAL_SECONDS)


async def boucle_envoi_canaux(meshcore, django):
    """Même principe que boucle_envoi, pour les messages de canal — nécessite que le canal
    soit déjà provisionné localement (canal_idx connu, voir boucle_provisionnement_canaux) ;
    un message dont le canal n'est pas encore prêt est simplement resservi au cycle suivant."""
    while True:
        try:
            en_attente = await django.messages_canal_a_envoyer()
            for message in en_attente:
                canal_idx = message.get("canal_idx")
                if canal_idx is None:
                    continue
                try:
                    resultat = await meshcore.commands.send_chan_msg(canal_idx, message["contenu"])
                    if resultat and resultat.type == EventType.ERROR:
                        await django.marquer_message_canal(message["id"], "ECHEC", erreur=str(resultat.payload))
                        logger.warning("Échec d'envoi du message de canal %s : %r", message["id"], resultat.payload)
                    else:
                        await django.marquer_message_canal(message["id"], "ENVOYE")
                        logger.info("Message de canal %s envoyé.", message["id"])
                except Exception as exc:
                    logger.exception("Échec d'envoi du message de canal %s.", message["id"])
                    try:
                        await django.marquer_message_canal(message["id"], "ECHEC", erreur=str(exc))
                    except Exception:
                        logger.exception("Échec de la mise à jour de statut après échec d'envoi de canal.")
        except Exception:
            logger.exception("Échec de récupération des messages de canal en attente.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def executer_une_session(django):
    try:
        meshcore = await connecter_meshcore()
    except Exception as exc:
        logger.error("Connexion au companion MeshCore impossible : %s", exc)
        await django.rapporter_etat(COMPAGNON_ID, "ERREUR", erreur=str(exc))
        return

    pubkey = await obtenir_pubkey(meshcore)
    await django.rapporter_etat(COMPAGNON_ID, "CONNECTE", pubkey_hex=pubkey)
    logger.info("Connecté au companion MeshCore (pubkey=%s).", pubkey or "inconnue")

    deconnecte = asyncio.Event()
    # canal_idx (local) -> canal_id (Django) : peuplé par boucle_provisionnement_canaux, lu
    # par le listener CHANNEL_MSG_RECV pour rattacher un message entrant à son CanalMeshCore.
    canaux_idx_map = {}
    enregistrer_ecouteurs(meshcore, django, COMPAGNON_ID, deconnecte, canaux_idx_map)

    tache_envoi = asyncio.create_task(boucle_envoi(meshcore, django, COMPAGNON_ID))
    tache_contacts = asyncio.create_task(boucle_contacts(meshcore, django, COMPAGNON_ID))
    tache_positions = asyncio.create_task(boucle_positions_missions(meshcore, django, COMPAGNON_ID))
    tache_canaux_provisionnement = asyncio.create_task(boucle_provisionnement_canaux(meshcore, django, COMPAGNON_ID, canaux_idx_map))
    tache_canaux_envoi = asyncio.create_task(boucle_envoi_canaux(meshcore, django))
    try:
        await deconnecte.wait()
    finally:
        tache_envoi.cancel()
        tache_contacts.cancel()
        tache_positions.cancel()
        tache_canaux_provisionnement.cancel()
        tache_canaux_envoi.cancel()
        try:
            await django.rapporter_etat(COMPAGNON_ID, "DECONNECTE")
        except Exception:
            logger.exception("Échec du rapport d'état DECONNECTE.")


async def main():
    django = DjangoClient(DJANGO_API_URL, DJANGO_EMAIL, DJANGO_PASSWORD)
    logger.info(
        "Démarrage du service-pont MeshCore — companion %s, connexion %s.",
        COMPAGNON_ID, CONNEXION_TYPE,
    )
    try:
        while True:
            await executer_une_session(django)
            logger.warning("Nouvelle tentative de connexion dans %ds...", RECONNECT_DELAY_SECONDS)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
    finally:
        await django.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
