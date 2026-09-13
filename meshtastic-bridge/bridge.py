"""Service-pont Meshtastic <-> assista-crise — phase de test (voir doc de conception
« Maillage Terrain » et meshcore-bridge/ pour le pont équivalent MeshCore).

Contrairement à meshcore-bridge, il n'y a ici NI matériel radio NI connexion série/BLE : ce
service se connecte directement en tant que CLIENT MQTT à un broker tiers (ex: Gaulix,
mqtt.gaulix.fr — réseau communautaire Meshtastic français) et se comporte comme un nœud
Meshtastic purement logiciel. La lib officielle `meshtastic` (PyPI) ne sert ici QUE pour ses
définitions protobuf (meshtastic.protobuf.*) — elle ne pilote aucun appareil, et surtout ne
chiffre/déchiffre jamais elle-même (c'est le firmware qui fait ça normalement) : voir crypto.py,
qui réimplémente cette partie à partir du firmware officiel open-source.

IMPORTANT — non vérifié sur matériel réel : le chiffrement (nonce, dérivation de clé, hash de
canal) est dérivé directement du code source du firmware officiel (github.com/meshtastic/
firmware) et testé en aller-retour localement, mais PAS encore contre un vrai appareil. Premier
test réel à faire avec précaution (voir README.md de ce dossier) avant de considérer ce pont
fiable.

Ne PAS déployer ce service sur .114 avant d'avoir validé le matériel.
"""

import asyncio
import logging
import os
import random
import time

import httpx
import paho.mqtt.client as mqtt
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2

import crypto

logger = logging.getLogger("meshtastic-bridge")

DJANGO_API_URL = os.environ["DJANGO_API_URL"]
DJANGO_EMAIL = os.environ["DJANGO_BRIDGE_EMAIL"]
DJANGO_PASSWORD = os.environ["DJANGO_BRIDGE_PASSWORD"]
COMPAGNON_ID = os.environ["COMPAGNON_ID"]

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
CANAUX_REFRESH_INTERVAL_SECONDS = int(os.environ.get("CANAUX_REFRESH_INTERVAL_SECONDS", "60"))
CONTACTS_FLUSH_INTERVAL_SECONDS = int(os.environ.get("CONTACTS_FLUSH_INTERVAL_SECONDS", "30"))
RECONNECT_DELAY_SECONDS = int(os.environ.get("RECONNECT_DELAY_SECONDS", "10"))

BROADCAST_NUM = 0xFFFFFFFF

# Miroir de HardwareModel (meshtastic.protobuf.mesh_pb2) -> texte lisible, best-effort.
def _nom_hardware(valeur: int) -> str | None:
    try:
        return mesh_pb2.HardwareModel.Name(valeur)
    except ValueError:
        return None


class DjangoClient:
    """Même patron que meshcore-bridge/bridge.py:DjangoClient (JWT, ré-authentification
    automatique sur 401)."""

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
            await self._authenticate()
            headers = {"Authorization": f"Bearer {self._access_token}"}
            response = await self._client.request(method, f"{self._base_url}{path}", headers=headers, **kwargs)
        response.raise_for_status()
        return response

    async def rapporter_etat(self, compagnon_id, etat, erreur=None):
        payload = {"etat": etat}
        if erreur:
            payload["erreur"] = erreur
        await self._request("POST", f"/compagnons-meshtastic/{compagnon_id}/rapporter-etat/", json=payload)

    async def get_companion(self, compagnon_id):
        response = await self._request("GET", f"/compagnons-meshtastic/{compagnon_id}/")
        return response.json()

    async def get_companion_avec_cle_privee(self, compagnon_id):
        """Contrairement à get_companion, expose x25519_private_key_hex — nécessaire au calcul
        de l'échange Diffie-Hellman d'un DM chiffré par clé publique (PKI), jamais renvoyé par
        la sérialisation normale."""
        response = await self._request("GET", f"/compagnons-meshtastic/{compagnon_id}/avec-cle-privee/")
        return response.json()

    async def synchroniser_contacts(self, compagnon_id, contacts):
        if not contacts:
            return
        await self._request("POST", f"/compagnons-meshtastic/{compagnon_id}/synchroniser-contacts/", json={"contacts": contacts})

    async def canaux_avec_cle(self):
        response = await self._request("GET", "/canaux-meshtastic/avec-cle/")
        return response.json()

    async def dm_a_envoyer(self, compagnon_id):
        response = await self._request("GET", "/messages-meshtastic/a-envoyer/", params={"compagnon": compagnon_id})
        return response.json()

    async def marquer_dm(self, message_id, statut, erreur=None):
        payload = {"statut": statut}
        if erreur:
            payload["erreur"] = erreur
        await self._request("PATCH", f"/messages-meshtastic/{message_id}/", json=payload)

    async def logger_dm_entrant(self, compagnon_id, canal_id, contact_node_num, contenu):
        await self._request("POST", "/messages-meshtastic/", json={
            "compagnon": compagnon_id, "canal": canal_id, "direction": "ENTRANT",
            "contact_node_num": contact_node_num, "contenu": contenu,
        })

    async def canal_a_envoyer(self, canal_id):
        response = await self._request("GET", "/messages-canal-meshtastic/a-envoyer/", params={"canal": canal_id})
        return response.json()

    async def marquer_message_canal(self, message_id, statut, erreur=None):
        payload = {"statut": statut}
        if erreur:
            payload["erreur"] = erreur
        await self._request("PATCH", f"/messages-canal-meshtastic/{message_id}/", json=payload)

    async def logger_canal_entrant(self, canal_id, contact_node_num, contenu):
        await self._request("POST", "/messages-canal-meshtastic/", json={
            "canal": canal_id, "direction": "ENTRANT",
            "contact_node_num": contact_node_num, "contenu": contenu,
        })


class RegistreCanaux:
    """Cache local des canaux actifs (nom -> {id, psk_hex en octets, clé résolue}) — rafraîchi
    périodiquement depuis Django (voir boucle_rafraichissement_canaux). Le nom du canal EST la
    clé de recherche : c'est lui qui identifie le canal dans le topic MQTT
    (`<topic_racine>/2/e/<nom>/<node_id>`), pas un index local comme pour MeshCore."""

    def __init__(self):
        self._par_nom = {}

    def mettre_a_jour(self, canaux_json):
        nouveau = {}
        for c in canaux_json:
            psk_hex = c.get("psk_hex") or ""
            try:
                psk = bytes.fromhex(psk_hex) if psk_hex else b""
            except ValueError:
                logger.warning("PSK invalide (hex) pour le canal %s, ignoré.", c["nom"])
                continue
            nouveau[c["nom"]] = {"id": c["id"], "psk": psk}
        self._par_nom = nouveau

    def get(self, nom):
        return self._par_nom.get(nom)

    def tous(self):
        return dict(self._par_nom)


async def boucle_rafraichissement_canaux(django, registre):
    while True:
        try:
            registre.mettre_a_jour(await django.canaux_avec_cle())
        except Exception:
            logger.exception("Échec du rafraîchissement des canaux.")
        await asyncio.sleep(CANAUX_REFRESH_INTERVAL_SECONDS)


class TamponContacts:
    """Accumule les nœuds découverts (NodeInfo/Position) en mémoire, flush périodique vers
    Django par lot — évite un POST HTTP par paquet MQTT reçu, potentiellement très fréquent sur
    un relais régional actif."""

    def __init__(self):
        self._par_node_num = {}

    def maj_identite(self, node_num, long_name=None, short_name=None, hardware_model=None, public_key_hex=None):
        entree = self._par_node_num.setdefault(node_num, {"node_num": node_num})
        if long_name is not None:
            entree["long_name"] = long_name
        if short_name is not None:
            entree["short_name"] = short_name
        if hardware_model is not None:
            entree["hardware_model"] = hardware_model
        if public_key_hex:
            entree["public_key_hex"] = public_key_hex

    def maj_position(self, node_num, latitude, longitude):
        entree = self._par_node_num.setdefault(node_num, {"node_num": node_num})
        entree["latitude"] = latitude
        entree["longitude"] = longitude
        entree["dernier_advert"] = time.time()

    def extraire(self):
        contacts = list(self._par_node_num.values())
        self._par_node_num.clear()
        return contacts


async def boucle_flush_contacts(django, compagnon_id, tampon):
    while True:
        await asyncio.sleep(CONTACTS_FLUSH_INTERVAL_SECONDS)
        contacts = tampon.extraire()
        if not contacts:
            continue
        try:
            await django.synchroniser_contacts(compagnon_id, contacts)
            logger.info("Contacts Meshtastic synchronisés : %d.", len(contacts))
        except Exception:
            logger.exception("Échec de synchronisation des contacts.")


def _traiter_paquet_dechiffre(payload, node_num, to_node, canal_id, canal_nom, tampon, django, compagnon_id, boucle):
    """Décodage du Data protobuf déjà déchiffré — dispatch par portnum. Retourne une coroutine
    à planifier si un appel réseau est nécessaire (log message entrant), sinon None."""
    data = mesh_pb2.Data()
    data.ParseFromString(payload)

    if data.portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
        contenu = data.payload.decode("utf-8", errors="replace")
        if to_node == compagnon_id["node_num"]:
            logger.info("DM Meshtastic reçu de %08x : %s", node_num, contenu)
            return django.logger_dm_entrant(compagnon_id["id"], canal_id, node_num, contenu)
        if to_node == BROADCAST_NUM:
            logger.info("Message de canal '%s' reçu de %08x : %s", canal_nom, node_num, contenu)
            return django.logger_canal_entrant(canal_id, node_num, contenu)
        # Adressé à un AUTRE nœud que nous, sur un canal dont on a la clé : on peut le
        # déchiffrer mais ce n'est pas notre conversation — on ne le journalise pas (on
        # n'agrège pas indiscriminément les DM d'autrui).
        return None

    if data.portnum == portnums_pb2.PortNum.NODEINFO_APP:
        user = mesh_pb2.User()
        user.ParseFromString(data.payload)
        tampon.maj_identite(
            node_num, long_name=user.long_name, short_name=user.short_name,
            hardware_model=_nom_hardware(user.hw_model),
            public_key_hex=bytes(user.public_key).hex() if user.public_key else None,
        )
        return None

    if data.portnum == portnums_pb2.PortNum.POSITION_APP:
        position = mesh_pb2.Position()
        position.ParseFromString(data.payload)
        if position.latitude_i and position.longitude_i:
            tampon.maj_position(node_num, position.latitude_i * 1e-7, position.longitude_i * 1e-7)
        return None

    return None


def demarrer_mqtt(compagnon, registre, tampon, django, boucle, file_a_planifier, cle_privee_hex):
    """paho-mqtt tourne dans son propre thread (loop_start) — chaque callback poste les
    coroutines réseau à exécuter dans la boucle asyncio principale via
    call_soon_threadsafe, jamais d'appel réseau direct depuis le thread MQTT."""

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("Connecté au broker MQTT %s:%s.", compagnon["broker_host"], compagnon["broker_port"])
            client.subscribe(f"{compagnon['topic_racine']}/2/e/#")
            boucle.call_soon_threadsafe(
                file_a_planifier.put_nowait, django.rapporter_etat(compagnon["id"], "CONNECTE"),
            )
        else:
            logger.error("Échec de connexion MQTT : %s", reason_code)
            boucle.call_soon_threadsafe(
                file_a_planifier.put_nowait,
                django.rapporter_etat(compagnon["id"], "ERREUR", erreur=str(reason_code)),
            )

    def on_disconnect(client, userdata, flags, reason_code, properties=None):
        logger.warning("Déconnecté du broker MQTT : %s", reason_code)
        boucle.call_soon_threadsafe(
            file_a_planifier.put_nowait, django.rapporter_etat(compagnon["id"], "DECONNECTE"),
        )

    def on_message(client, userdata, msg):
        try:
            enveloppe = mqtt_pb2.ServiceEnvelope()
            enveloppe.ParseFromString(msg.payload)
            paquet = enveloppe.packet
            canal_nom = enveloppe.channel_id
            canal = registre.get(canal_nom)

            node_num = getattr(paquet, "from")
            to_node = paquet.to
            packet_id = paquet.id
            canal_id = canal["id"] if canal else None

            if paquet.HasField("decoded"):
                payload = paquet.decoded.SerializeToString()
            elif paquet.pki_encrypted:
                # DM chiffré par clé publique (PKI, firmware 2.5+) — indépendant de tout canal,
                # voir crypto.py. On ne peut de toute façon déchiffrer que ce qui nous est
                # adressé (il faudrait NOTRE clé privée, jamais celle d'un tiers).
                if to_node != compagnon["node_num"] or not paquet.encrypted or not paquet.public_key:
                    return
                try:
                    payload = crypto.dechiffrer_pkc(
                        cle_privee_hex, bytes(paquet.public_key).hex(), packet_id, node_num, bytes(paquet.encrypted),
                    )
                except Exception:
                    logger.exception("Échec de déchiffrement PKI depuis %08x.", node_num)
                    return
            elif canal is not None and paquet.HasField("encrypted") and paquet.encrypted:
                payload = crypto.dechiffrer(canal["psk"], packet_id, node_num, bytes(paquet.encrypted))
            else:
                return  # Canal qu'on ne connaît pas (pas la clé) : rien à faire pour nous.

            coro = _traiter_paquet_dechiffre(
                payload, node_num, to_node, canal_id, canal_nom, tampon, django, {"id": compagnon["id"], "node_num": compagnon["node_num"]}, boucle,
            )
            if coro is not None:
                boucle.call_soon_threadsafe(file_a_planifier.put_nowait, coro)
        except Exception:
            logger.exception("Échec de traitement d'un message MQTT entrant.")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(compagnon["broker_host"], compagnon["broker_port"], keepalive=60)
    client.loop_start()
    return client


async def boucle_execution_planifiee(file_a_planifier):
    """Exécute, dans la boucle asyncio principale, les coroutines postées depuis le thread
    MQTT (paho-mqtt) — jamais d'appel réseau httpx directement depuis ce thread."""
    while True:
        coro = await file_a_planifier.get()
        try:
            await coro
        except Exception:
            logger.exception("Échec d'une tâche planifiée depuis le thread MQTT.")


async def boucle_envoi_dm(mqtt_client, compagnon, registre, django, cle_privee_hex):
    while True:
        try:
            for message in await django.dm_a_envoyer(compagnon["id"]):
                canal_id = message.get("canal")
                canal_nom = None
                for nom, infos in registre.tous().items():
                    if infos["id"] == canal_id:
                        canal_nom = nom
                        break
                if canal_nom is None:
                    await django.marquer_dm(message["id"], "ECHEC", erreur="Aucun canal (donc aucune clé) associé à ce DM.")
                    continue

                canal = registre.get(canal_nom)
                packet_id = random.randint(1, 0xFFFFFFFF)
                data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, payload=message["contenu"].encode("utf-8"))
                paquet = mesh_pb2.MeshPacket()
                setattr(paquet, "from", compagnon["node_num"])
                paquet.to = message["contact_node_num"]
                paquet.id = packet_id
                paquet.channel = crypto.hash_canal(canal_nom, canal["psk"])
                paquet.hop_limit = 3
                paquet.want_ack = True

                # DM chiffré par clé publique (PKI) si on connaît déjà celle du destinataire
                # (voir MessageMeshtasticLogViewSet.a_envoyer, contact_public_key_hex) — sinon
                # repli sur la PSK du canal choisi, moins confidentiel (voir README) mais
                # utilisable dès la première conversation, avant tout NodeInfo échangé.
                destinataire_pubkey_hex = message.get("contact_public_key_hex")
                if destinataire_pubkey_hex:
                    paquet.pki_encrypted = True
                    paquet.public_key = bytes.fromhex(crypto.cle_publique_depuis_privee_hex(cle_privee_hex))
                    paquet.encrypted = crypto.chiffrer_pkc(
                        cle_privee_hex, destinataire_pubkey_hex, packet_id, compagnon["node_num"], data.SerializeToString(),
                    )
                    mode = "PKI"
                else:
                    chiffre = crypto.chiffrer(canal["psk"], packet_id, compagnon["node_num"], data.SerializeToString())
                    if chiffre is None:
                        paquet.decoded.CopyFrom(data)
                    else:
                        paquet.encrypted = chiffre
                    mode = "PSK canal"

                enveloppe = mqtt_pb2.ServiceEnvelope(
                    packet=paquet, channel_id=canal_nom, gateway_id=f"!{compagnon['node_num']:08x}",
                )
                topic = f"{compagnon['topic_racine']}/2/e/{canal_nom}/!{compagnon['node_num']:08x}"
                info = mqtt_client.publish(topic, enveloppe.SerializeToString())
                info.wait_for_publish(timeout=10)

                await django.marquer_dm(message["id"], "ENVOYE")
                logger.info("DM Meshtastic (%s) publié vers %08x sur '%s'.", mode, message["contact_node_num"], canal_nom)
        except Exception:
            logger.exception("Échec du cycle d'envoi des DM.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def boucle_envoi_canaux(mqtt_client, compagnon, registre, django):
    while True:
        try:
            for canal_nom, canal in registre.tous().items():
                for message in await django.canal_a_envoyer(canal["id"]):
                    packet_id = random.randint(1, 0xFFFFFFFF)
                    data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, payload=message["contenu"].encode("utf-8"))
                    paquet = mesh_pb2.MeshPacket()
                    setattr(paquet, "from", compagnon["node_num"])
                    paquet.to = BROADCAST_NUM
                    paquet.id = packet_id
                    paquet.channel = crypto.hash_canal(canal_nom, canal["psk"])
                    paquet.hop_limit = 3

                    chiffre = crypto.chiffrer(canal["psk"], packet_id, compagnon["node_num"], data.SerializeToString())
                    if chiffre is None:
                        paquet.decoded.CopyFrom(data)
                    else:
                        paquet.encrypted = chiffre

                    enveloppe = mqtt_pb2.ServiceEnvelope(
                        packet=paquet, channel_id=canal_nom, gateway_id=f"!{compagnon['node_num']:08x}",
                    )
                    topic = f"{compagnon['topic_racine']}/2/e/{canal_nom}/!{compagnon['node_num']:08x}"
                    info = mqtt_client.publish(topic, enveloppe.SerializeToString())
                    info.wait_for_publish(timeout=10)

                    await django.marquer_message_canal(message["id"], "ENVOYE")
                    logger.info("Message de canal '%s' publié.", canal_nom)
        except Exception:
            logger.exception("Échec du cycle d'envoi des messages de canal.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

    django = DjangoClient(DJANGO_API_URL, DJANGO_EMAIL, DJANGO_PASSWORD)
    compagnon = await django.get_companion(COMPAGNON_ID)
    cle_privee = await django.get_companion_avec_cle_privee(COMPAGNON_ID)
    cle_privee_hex = cle_privee["x25519_private_key_hex"]
    logger.info(
        "Companion Meshtastic '%s' (node_num=%08x, clé publique X25519 %s...).",
        compagnon["nom"], compagnon["node_num"], cle_privee["x25519_public_key_hex"][:12],
    )

    registre = RegistreCanaux()
    registre.mettre_a_jour(await django.canaux_avec_cle())
    tampon = TamponContacts()

    boucle = asyncio.get_running_loop()
    file_a_planifier = asyncio.Queue()

    mqtt_client = demarrer_mqtt(compagnon, registre, tampon, django, boucle, file_a_planifier, cle_privee_hex)

    try:
        await asyncio.gather(
            boucle_execution_planifiee(file_a_planifier),
            boucle_rafraichissement_canaux(django, registre),
            boucle_flush_contacts(django, COMPAGNON_ID, tampon),
            boucle_envoi_dm(mqtt_client, compagnon, registre, django, cle_privee_hex),
            boucle_envoi_canaux(mqtt_client, compagnon, registre, django),
        )
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
