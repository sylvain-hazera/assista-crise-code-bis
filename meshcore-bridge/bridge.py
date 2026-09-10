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


def enregistrer_ecouteurs(meshcore, django, compagnon_id, sur_deconnexion):

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

    async def _sur_deconnexion(event):
        logger.warning("Déconnecté du companion MeshCore.")
        sur_deconnexion.set()

    meshcore.subscribe(EventType.CONTACT_MSG_RECV, _sur_message)
    meshcore.subscribe(EventType.DISCONNECTED, _sur_deconnexion)


async def boucle_envoi(meshcore, django, compagnon_id):
    """Interroge périodiquement l'API pour les messages sortants en attente plutôt que
    d'exposer un port entrant sur ce conteneur — voir MessageMeshLogViewSet.a_envoyer."""
    while True:
        try:
            en_attente = await django.messages_a_envoyer(compagnon_id)
            for message in en_attente:
                try:
                    resultat = await meshcore.commands.send_msg(message["contact_pubkey_hex"], message["contenu"])
                    if resultat and resultat.type == EventType.ERROR:
                        await django.marquer_message(message["id"], "ECHEC", erreur=str(resultat.payload))
                        logger.warning("Échec d'envoi du message %s : %r", message["id"], resultat.payload)
                    else:
                        await django.marquer_message(message["id"], "ENVOYE")
                        logger.info("Message %s envoyé.", message["id"])
                except Exception as exc:
                    logger.exception("Échec d'envoi du message %s.", message["id"])
                    try:
                        await django.marquer_message(message["id"], "ECHEC", erreur=str(exc))
                    except Exception:
                        logger.exception("Échec de la mise à jour de statut après échec d'envoi.")
        except Exception:
            logger.exception("Échec de récupération des messages en attente auprès de l'API.")
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
    enregistrer_ecouteurs(meshcore, django, COMPAGNON_ID, deconnecte)

    tache_envoi = asyncio.create_task(boucle_envoi(meshcore, django, COMPAGNON_ID))
    try:
        await deconnecte.wait()
    finally:
        tache_envoi.cancel()
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
