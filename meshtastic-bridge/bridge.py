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

# Annonce périodique de notre propre position (Position_APP) — voir boucle_annonce_position.
# Hypothèse à vérifier : Gaulix semble router les BROADCASTS (diffusion à tout un canal) vers
# une "bulle" locale déterminée par la position/département connus de l'ÉMETTEUR (voir leur
# doc "Logique de routage MQTT"), contrairement aux messages adressés à un node_num précis qui
# sont bien arrivés sans qu'on ait jamais annoncé de position — un companion logiciel sans GPS
# n'a jusqu'ici jamais donné à Gaulix de quoi nous placer géographiquement.
POSITION_ANNONCE_INTERVAL_SECONDS = int(os.environ.get("POSITION_ANNONCE_INTERVAL_SECONDS", "900"))
POSITION_ANNONCE_LATITUDE = float(os.environ.get("POSITION_ANNONCE_LATITUDE", "0")) or None
POSITION_ANNONCE_LONGITUDE = float(os.environ.get("POSITION_ANNONCE_LONGITUDE", "0")) or None
POSITION_ANNONCE_CANAL = os.environ.get("POSITION_ANNONCE_CANAL", "Fr_Tech")

# Annonce de notre propre identité (NodeInfo : long_name/short_name/clé publique) sur TOUS les
# canaux connus — sans ça, aucun appareil réel ne nous a jamais "rencontrés" et peut ignorer nos
# paquets comme venant d'un nœud jamais annoncé (voir doc de conception, remarque explicite :
# un vrai client Meshtastic diffuse systématiquement son NodeInfo, jamais juste des messages).
NODEINFO_ANNONCE_INTERVAL_SECONDS = int(os.environ.get("NODEINFO_ANNONCE_INTERVAL_SECONDS", "300"))

# Désactivé par défaut (13/09) : voir le commentaire détaillé dans boucle_envoi_dm. Un DM
# chiffré par clé publique envoyé par nous n'a jamais été confirmé reçu en conditions réelles,
# contrairement à un DM chiffré par PSK de canal, testé et confirmé à deux reprises vers deux
# destinataires différents. Repasser à "1" pour ré-expérimenter une fois la cause identifiée.
ENVOI_PKI_ACTIF = os.environ.get("ENVOI_PKI_ACTIF", "0") == "1"

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
            nouveau[c["nom"]] = {"id": c["id"], "psk": psk, "principal": bool(c.get("principal"))}
        self._par_nom = nouveau

    def get(self, nom):
        return self._par_nom.get(nom)

    def tous(self):
        return dict(self._par_nom)

    def nom_par_id(self, canal_id):
        for nom, infos in self._par_nom.items():
            if infos["id"] == canal_id:
                return nom
        return None

    def nom_principal(self):
        """Canal utilisé par défaut pour le nommage du topic MQTT d'un DM chiffré par clé
        publique (PKI) — dans ce mode le canal ne sert à rien pour le chiffrement ni la
        conversation, juste une contrainte technique du protocole (voir docstring du modèle
        Django CanalMeshtastic.principal). Retombe sur le premier canal connu si aucun n'est
        marqué principal, plutôt que de bloquer un DM PKI pour un simple oubli de configuration."""
        for nom, infos in self._par_nom.items():
            if infos["principal"]:
                return nom
        return next(iter(self._par_nom), None)


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
    # Compagnon jamais rafraîchi après le démarrage (comme broker_host/topic_racine) : la valeur
    # de chiffrement_supporte est donc figée pour la durée du process, un redémarrage du pont
    # suffit à prendre en compte un changement fait en admin.
    chiffrement_supporte = bool(compagnon.get("chiffrement_supporte"))
    while True:
        try:
            for message in await django.dm_a_envoyer(compagnon["id"]):
                canal_id = message.get("canal")
                canal_nom = registre.nom_par_id(canal_id) if canal_id else None
                destinataire_pubkey_hex = message.get("contact_public_key_hex")

                packet_id = random.randint(1, 0xFFFFFFFF)
                data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, payload=message["contenu"].encode("utf-8"))
                paquet = mesh_pb2.MeshPacket()
                setattr(paquet, "from", compagnon["node_num"])
                paquet.to = message["contact_node_num"]
                paquet.id = packet_id
                paquet.hop_limit = 7
                paquet.hop_start = 7
                paquet.want_ack = True

                if not chiffrement_supporte:
                    # CompagnonMeshtastic.chiffrement_supporte décoché (cas Gaulix, jamais
                    # confirmé relayer un paquet chiffré PSK ou PKI) : on force le clair pour CE
                    # broker quoi qu'il arrive, sans même tenter PKI/PSK — voir modèle Django.
                    if canal_nom is None:
                        canal_nom = registre.nom_principal()
                    if canal_nom is None:
                        await django.marquer_dm(message["id"], "ECHEC", erreur="Aucun canal disponible pour ce DM.")
                        continue
                    canal = registre.get(canal_nom)
                    paquet.channel = crypto.hash_canal(canal_nom, canal["psk"]) if canal else 0
                    paquet.decoded.CopyFrom(data)
                    canal_id_mqtt = canal_nom
                    mode = "clair (forcé, chiffrement non supporté par ce broker)"
                # Un vrai DM 1-à-1 chiffré DOIT passer par PKI : le firmware officiel rejette
                # délibérément un texte adressé (`to=`) déchiffré via la PSK *partagée* d'un
                # canal ("Rejecting legacy DM", Router.cpp::perhapsDecode) — seul un broadcast
                # ou un message non adressé peut utiliser la PSK de canal. Trouvé le 13/09 en
                # lisant le firmware officiel (github.com/meshtastic/firmware), après un test
                # comparatif contrôlé qui avait montré un DM PSK canal confirmé reçu (test3)
                # contre un DM PKI jamais confirmé (test5) envoyés dans les mêmes conditions.
                elif ENVOI_PKI_ACTIF and destinataire_pubkey_hex:
                    # Deuxième bug trouvé le même jour : le firmware ne tente le déchiffrement
                    # PKI que si `packet.channel == 0` (Router.cpp::perhapsDecode) et publie/
                    # attend le topic/channel_id MQTT littéral "PKI", pas un nom de canal
                    # (MQTT.cpp::onSend) — avant ce correctif on laissait le hash du canal
                    # classique dans `channel`, donc aucun destinataire ne tentait jamais le
                    # déchiffrement PKI de nos paquets.
                    paquet.channel = 0
                    paquet.pki_encrypted = True
                    paquet.public_key = bytes.fromhex(crypto.cle_publique_depuis_privee_hex(cle_privee_hex))
                    paquet.encrypted = crypto.chiffrer_pkc(
                        cle_privee_hex, destinataire_pubkey_hex, packet_id, compagnon["node_num"], data.SerializeToString(),
                    )
                    canal_id_mqtt = "PKI"
                    mode = "PKI"
                else:
                    if canal_nom is None:
                        canal_nom = registre.nom_principal()
                    if canal_nom is None:
                        await django.marquer_dm(message["id"], "ECHEC", erreur="Aucun canal disponible pour ce DM.")
                        continue
                    canal = registre.get(canal_nom)
                    paquet.channel = crypto.hash_canal(canal_nom, canal["psk"])
                    chiffre = crypto.chiffrer(canal["psk"], packet_id, compagnon["node_num"], data.SerializeToString())
                    if chiffre is None:
                        paquet.decoded.CopyFrom(data)
                    else:
                        paquet.encrypted = chiffre
                    canal_id_mqtt = canal_nom
                    mode = "PSK canal"

                enveloppe = mqtt_pb2.ServiceEnvelope(
                    packet=paquet, channel_id=canal_id_mqtt, gateway_id=f"!{compagnon['node_num']:08x}",
                )
                topic = f"{compagnon['topic_racine']}/2/e/{canal_id_mqtt}/!{compagnon['node_num']:08x}"
                info = mqtt_client.publish(topic, enveloppe.SerializeToString())
                info.wait_for_publish(timeout=10)

                await django.marquer_dm(message["id"], "ENVOYE")
                logger.info("DM Meshtastic (%s) publié vers %08x sur '%s'.", mode, message["contact_node_num"], canal_id_mqtt)
        except Exception:
            logger.exception("Échec du cycle d'envoi des DM.")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def boucle_envoi_canaux(mqtt_client, compagnon, registre, django):
    chiffrement_supporte = bool(compagnon.get("chiffrement_supporte"))
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
                    paquet.hop_limit = 7
                    paquet.hop_start = 7

                    # chiffrement_supporte décoché : on ne tente même pas crypto.chiffrer, même
                    # logique de fail-closed que boucle_envoi_dm (voir modèle Django).
                    chiffre = (
                        crypto.chiffrer(canal["psk"], packet_id, compagnon["node_num"], data.SerializeToString())
                        if chiffrement_supporte else None
                    )
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


def _publier_paquet(mqtt_client, compagnon, canal_nom, canal, paquet):
    enveloppe = mqtt_pb2.ServiceEnvelope(
        packet=paquet, channel_id=canal_nom, gateway_id=f"!{compagnon['node_num']:08x}",
    )
    topic = f"{compagnon['topic_racine']}/2/e/{canal_nom}/!{compagnon['node_num']:08x}"
    info = mqtt_client.publish(topic, enveloppe.SerializeToString())
    info.wait_for_publish(timeout=10)


async def boucle_annonce_position(mqtt_client, compagnon, registre):
    """Annonce périodiquement notre position sur POSITION_ANNONCE_CANAL — voir le commentaire
    de POSITION_ANNONCE_INTERVAL_SECONDS : hypothèse que Gaulix a besoin de nous savoir
    localisés pour router correctement nos BROADCASTS vers la bonne bulle locale (les messages
    adressés à un node_num précis, eux, sont déjà arrivés sans cette annonce)."""
    if POSITION_ANNONCE_LATITUDE is None or POSITION_ANNONCE_LONGITUDE is None:
        logger.info("Annonce de position désactivée (POSITION_ANNONCE_LATITUDE/LONGITUDE non renseignées).")
        return
    while True:
        try:
            canal = registre.get(POSITION_ANNONCE_CANAL)
            if canal is None:
                logger.warning("Canal d'annonce de position '%s' inconnu, annonce ignorée.", POSITION_ANNONCE_CANAL)
            else:
                packet_id = random.randint(1, 0xFFFFFFFF)
                position = mesh_pb2.Position(
                    latitude_i=int(POSITION_ANNONCE_LATITUDE * 1e7),
                    longitude_i=int(POSITION_ANNONCE_LONGITUDE * 1e7),
                )
                data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.POSITION_APP, payload=position.SerializeToString())
                paquet = mesh_pb2.MeshPacket()
                setattr(paquet, "from", compagnon["node_num"])
                paquet.to = BROADCAST_NUM
                paquet.id = packet_id
                paquet.channel = crypto.hash_canal(POSITION_ANNONCE_CANAL, canal["psk"])
                paquet.hop_limit = 7
                paquet.hop_start = 7

                chiffre = crypto.chiffrer(canal["psk"], packet_id, compagnon["node_num"], data.SerializeToString())
                if chiffre is None:
                    paquet.decoded.CopyFrom(data)
                else:
                    paquet.encrypted = chiffre

                _publier_paquet(mqtt_client, compagnon, POSITION_ANNONCE_CANAL, canal, paquet)
                logger.info(
                    "Position annoncée (%.4f, %.4f) sur '%s'.",
                    POSITION_ANNONCE_LATITUDE, POSITION_ANNONCE_LONGITUDE, POSITION_ANNONCE_CANAL,
                )
        except Exception:
            logger.exception("Échec de l'annonce de position.")
        await asyncio.sleep(POSITION_ANNONCE_INTERVAL_SECONDS)


async def boucle_annonce_identite(mqtt_client, compagnon, registre, cle_publique_hex):
    """Diffuse notre NodeInfo (long_name/short_name/clé publique) sur TOUS les canaux connus,
    périodiquement — voir le commentaire de NODEINFO_ANNONCE_INTERVAL_SECONDS."""
    while True:
        try:
            for canal_nom, canal in registre.tous().items():
                packet_id = random.randint(1, 0xFFFFFFFF)
                user = mesh_pb2.User(
                    id=f"!{compagnon['node_num']:08x}",
                    long_name=compagnon.get("long_name") or compagnon["nom"],
                    short_name=(compagnon.get("short_name") or compagnon["nom"])[:4],
                    hw_model=mesh_pb2.HardwareModel.PRIVATE_HW,
                    public_key=bytes.fromhex(cle_publique_hex),
                )
                data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.NODEINFO_APP, payload=user.SerializeToString())
                paquet = mesh_pb2.MeshPacket()
                setattr(paquet, "from", compagnon["node_num"])
                paquet.to = BROADCAST_NUM
                paquet.id = packet_id
                paquet.channel = crypto.hash_canal(canal_nom, canal["psk"])
                paquet.hop_limit = 7
                paquet.hop_start = 7

                chiffre = crypto.chiffrer(canal["psk"], packet_id, compagnon["node_num"], data.SerializeToString())
                if chiffre is None:
                    paquet.decoded.CopyFrom(data)
                else:
                    paquet.encrypted = chiffre

                _publier_paquet(mqtt_client, compagnon, canal_nom, canal, paquet)
                logger.info("NodeInfo annoncé sur '%s'.", canal_nom)
        except Exception:
            logger.exception("Échec de l'annonce NodeInfo.")
        await asyncio.sleep(NODEINFO_ANNONCE_INTERVAL_SECONDS)


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
            boucle_annonce_position(mqtt_client, compagnon, registre),
            boucle_annonce_identite(mqtt_client, compagnon, registre, cle_privee["x25519_public_key_hex"]),
        )
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
