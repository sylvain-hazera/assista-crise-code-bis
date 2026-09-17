"""Proxy TCP pour companion MeshCore partagé entre plusieurs consommateurs (ex: Home Assistant
+ assista-crise) — le companion n'accepte qu'UNE seule connexion TCP longue à la fois (constaté
en pratique, pas juste documenté). Ce proxy garde l'unique connexion réelle vers le companion, et
expose un port local sur lequel plusieurs clients peuvent se connecter en même temps.

Format de trame — lu directement dans le code source de la lib `meshcore` (tcp_cx.py), PAS
deviné depuis de la documentation :
  - trame envoyée par un client   : 0x3C + longueur (2 octets, little-endian) + payload
  - trame envoyée par le companion : 0x3E + longueur (2 octets, little-endian) + payload
  - le premier octet du payload est un code (`PacketType` dans meshcore/packets.py) :
    < 0x80  = réponse directe à une commande (ex: SELF_INFO, MSG_SENT, CONTACT_MSG_RECV...)
    >= 0x80 = notification push, non sollicitée (ADVERTISEMENT, MESSAGES_WAITING, ACK...)

Routage :
  - trame d'un client -> companion : sérialisée via un verrou global — une seule commande en
    vol vers le companion réel à la fois, tout client confondu. Envoyer la commande d'un 2e
    client avant la réponse au 1er déroute un appareil embarqué qui ne traite qu'une commande
    à la fois (constaté : ça cassait la connexion réelle en pratique, pas juste en théorie).
  - trame du companion -> clients :
      - code < 0x80  : livrée uniquement au client dont la commande est actuellement en vol —
        SAUF CONTACT_MSG_RECV/CHANNEL_MSG_RECV (0x07/0x08, voir CODES_MESSAGE_RECU) : un message
        reçu n'est délivré par le companion qu'UNE fois, au premier qui le demande après un
        MESSAGES_WAITING ; sans diffusion à tous, seul le client "gagnant" de la course
        (ex: Home Assistant) le verrait, jamais l'autre (ex: assista-crise).
      - code >= 0x80 : diffusée à TOUS les clients connectés (personne n'a demandé, tout le
        monde doit voir).

IMPORTANT : Home Assistant doit être reconfiguré pour se connecter à CE proxy (host/port de ce
service) plutôt que directement au companion — sinon il continue de prendre la seconde connexion
directe que le companion n'accepte pas, et rien n'est résolu.
"""

import asyncio
import logging
import os
import socket

from meshcore.packets import CommandType, BinaryReqType

try:
    from zeroconf import ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf
except ImportError:
    ServiceInfo = None
    AsyncZeroconf = None

try:
    import serial_asyncio_fast
except ImportError:
    serial_asyncio_fast = None

logger = logging.getLogger("meshcore-proxy")

_NOMS_COMMANDES = {c.value: c.name for c in CommandType}
_NOMS_REQ_BINAIRES = {r.value: r.name for r in BinaryReqType}


def _decrire_commande(payload: bytes) -> str:
    """Résumé lisible d'une commande cliente pour le log — code CommandType, et pour un
    BINARY_REQ (50, ex: req_status_sync/req_telemetry_sync — voir meshcore/commands/base.py
    send_binary_req) la pubkey destinataire complète (payload[1:33]) et le type de requête
    binaire (payload[33]), seule façon de savoir QUI un client interroge sans dupliquer tout
    le parsing de la lib meshcore ici."""
    if not payload:
        return "(payload vide)"
    code = payload[0]
    nom = _NOMS_COMMANDES.get(code, f"code={code}")
    if code == CommandType.BINARY_REQ.value and len(payload) >= 34:
        dst_pubkey = payload[1:33].hex()
        type_req = _NOMS_REQ_BINAIRES.get(payload[33], f"type={payload[33]}")
        return f"{nom} dst={dst_pubkey} req_type={type_req}"
    return f"{nom} ({len(payload)} octet(s))"

# CONNEXION_TYPE : TCP (compagnon distant sur le LAN, historique) ou SERIE (compagnon branché
# en USB directement sur l'hôte du proxy — cas d'un satellite Raspberry Pi, voir satellite/
# docker-compose.yml). Pas de BLE ici : contrairement à bridge.py, ce proxy tourne sans
# interaction humaine pour l'appairage, et BLE n'apporte rien qu'USB ne fasse déjà en local.
CONNEXION_TYPE = os.environ.get("MESHCORE_CONNEXION_TYPE", "TCP").upper()
UPSTREAM_HOST = os.environ.get("MESHCORE_TCP_HOST")
UPSTREAM_PORT = int(os.environ.get("MESHCORE_TCP_PORT", "5000"))
SERIE_DEVICE = os.environ.get("MESHCORE_SERIE_DEVICE")
SERIE_BAUDRATE = int(os.environ.get("MESHCORE_SERIE_BAUDRATE", "115200"))

if CONNEXION_TYPE == "TCP" and not UPSTREAM_HOST:
    raise RuntimeError("MESHCORE_TCP_HOST est requis pour une connexion TCP (MESHCORE_CONNEXION_TYPE=TCP).")
if CONNEXION_TYPE == "SERIE" and not SERIE_DEVICE:
    raise RuntimeError("MESHCORE_SERIE_DEVICE est requis pour une connexion série (ex: /dev/ttyUSB0).")
if CONNEXION_TYPE not in ("TCP", "SERIE"):
    raise RuntimeError(f"MESHCORE_CONNEXION_TYPE inconnu : {CONNEXION_TYPE!r} (attendu TCP ou SERIE).")
LISTEN_HOST = os.environ.get("PROXY_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("PROXY_LISTEN_PORT", "5050"))
RECONNECT_DELAY_SECONDS = int(os.environ.get("RECONNECT_DELAY_SECONDS", "5"))

PUSH_THRESHOLD = 0x80
# CONTACT_MSG_RECV, CHANNEL_MSG_RECV (meshcore/packets.py) : un message reçu par le companion
# n'est délivré qu'UNE fois, au premier client qui appelle get_msg() après le push
# MESSAGES_WAITING — sans ce traitement spécial, seul le client "gagnant" de la course voit le
# contenu (constaté : avec Home Assistant ET assista-crise connectés, l'autre ne reçoit jamais
# rien). On diffuse donc ces deux codes à tous les clients, pas seulement au demandeur.
CODES_MESSAGE_RECU = {0x07, 0x08}
# 0.3s à l'origine : trop court sous charge réelle (plusieurs clients partageant la même
# connexion companion, dont un qui sonde la batterie toutes les 5s) — une rafale multi-trames
# (ex: CHANNEL_INFO, une par canal) qui dépasse ce délai de silence se fait couper en cours de
# route : le proxy livre ce qu'il a déjà reçu et referme la fenêtre, puis les trames arrivant
# après sont journalisées "reçue sans commande en attente, ignorée" et jetées — jamais
# transmises à personne. Constaté en direct le 2026-09-16 (CHANNEL_INFO perdu 20s après la
# connexion d'un client, pendant qu'un autre pollait GET_BATT_AND_STORAGE toutes les 5s).
SILENCE_FIN_REPONSE = 0.9  # secondes de silence avant de considérer une réponse (mono ou multi-trames) terminée
TIMEOUT_MAX_REPONSE = 8.0  # garde-fou si le companion ne répond jamais du tout

# Annonce mDNS : ce proxy expose un port TCP local partagé, exactement comme le ferait un vrai
# nœud MeshCore sur le LAN — utile pour que satellite/decouverte_lan.py (ou tout autre outil de
# découverte) le trouve automatiquement sans IP codée en dur. Nom de service choisi ici même
# (pas deviné depuis un firmware réel, contrairement aux nœuds physiques — voir la note du
# cadrage "Chantier B" sur SERVICE_TYPES_MDNS) : "role"=proxy dans les properties permet de le
# distinguer d'un vrai nœud si jamais les deux finissaient par partager le même type de service.
MDNS_SERVICE_TYPE = "_meshcore._tcp.local."
MDNS_ACTIF = os.environ.get("PROXY_MDNS_ANNONCE", "true").strip().lower() not in ("0", "false", "non")
MDNS_NOM_INSTANCE = os.environ.get("PROXY_MDNS_NOM", socket.gethostname())


def _lire_trames(tampon: bytearray, marqueur: int):
    """Extrait toutes les trames complètes disponibles dans `tampon` (mutable, vidé au fur et à
    mesure), selon le format marqueur + longueur (2 octets LE) + payload. Ignore tout octet
    parasite avant un marqueur, comme le fait tcp_cx.py côté lib officielle."""
    trames = []
    while True:
        idx = tampon.find(bytes([marqueur]))
        if idx < 0:
            tampon.clear()
            break
        if idx > 0:
            del tampon[:idx]
        if len(tampon) < 3:
            break
        taille = int.from_bytes(tampon[1:3], "little", signed=False)
        if taille > 300:
            del tampon[:1]  # marqueur invalide, on avance d'un octet et on réessaie
            continue
        if len(tampon) < 3 + taille:
            break
        payload = bytes(tampon[3:3 + taille])
        del tampon[:3 + taille]
        trames.append(payload)
    return trames


def _ip_locale_annoncable() -> str | None:
    """IP à annoncer en mDNS : celle configurée explicitement si PROXY_LISTEN_HOST n'est pas un
    joker, sinon devinée via une connexion UDP factice (aucun paquet réellement envoyé) — même
    technique que satellite/decouverte_lan.reseau_local_cidr."""
    if LISTEN_HOST not in ("0.0.0.0", "::", ""):
        return LISTEN_HOST
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


class ProxyMeshCore:
    def __init__(self):
        self.upstream_writer: asyncio.StreamWriter | None = None
        self._mdns_zeroconf: "AsyncZeroconf | None" = None
        self._mdns_info: "ServiceInfo | None" = None
        self.clients: set[asyncio.StreamWriter] = set()
        # Un companion embarqué ne traite qu'une commande à la fois — envoyer la commande d'un
        # 2e client avant d'avoir reçu la réponse de la 1re (ce que faisait la version
        # précédente, purement FIFO sans attente) déroute l'appareil réel et casse la
        # connexion. Ce verrou sérialise : une seule commande en vol à la fois, tout le
        # système confondu, quel que soit le client d'origine.
        self.verrou_commande = asyncio.Lock()
        # Certaines commandes (ex: GET_CONTACTS) ne renvoient pas une seule trame de réponse
        # mais une rafale (CONTACT_START, puis N x CONTACT, puis CONTACT_END) — constaté en
        # pratique : livrer seulement la 1re trame et relâcher le verrou en jette des dizaines
        # d'autres, cassant la synchro côté client (ex: Home Assistant). On collecte donc
        # toutes les trames de réponse jusqu'à un silence de `SILENCE_FIN_REPONSE`, plutôt que
        # de supposer une seule trame.
        self.collecte_active = False
        self.frames_reponse: list[bytes] = []
        self.evenement_fin_reponse: asyncio.Event | None = None
        self.minuteur_silence: asyncio.TimerHandle | None = None
        # Client dont la commande est actuellement en vol — voir CODES_MESSAGE_RECU ci-dessous.
        self.client_en_vol: asyncio.StreamWriter | None = None

    async def demarrer(self):
        asyncio.create_task(self._boucle_upstream())
        await self._annoncer_mdns()
        serveur = await asyncio.start_server(self._gerer_client, LISTEN_HOST, LISTEN_PORT)
        libelle_upstream = SERIE_DEVICE if CONNEXION_TYPE == "SERIE" else f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"
        logger.info("Proxy en écoute sur %s:%s (companion réel, %s : %s)", LISTEN_HOST, LISTEN_PORT, CONNEXION_TYPE, libelle_upstream)
        try:
            async with serveur:
                await serveur.serve_forever()
        finally:
            await self._retirer_annonce_mdns()

    async def _annoncer_mdns(self):
        """Annonce ce proxy en mDNS, comme le ferait un vrai nœud MeshCore sur le LAN —
        best-effort : zeroconf absent, réseau sans multicast, ou IP non déterminable ->
        le proxy continue de fonctionner normalement, juste non découvrable automatiquement
        (PROXY_MDNS_ANNONCE=false pour désactiver explicitement)."""
        if AsyncZeroconf is None:
            logger.warning("zeroconf non installé — annonce mDNS désactivée.")
            return
        if not MDNS_ACTIF:
            logger.info("Annonce mDNS désactivée (PROXY_MDNS_ANNONCE=false).")
            return
        ip = _ip_locale_annoncable()
        if ip is None:
            logger.warning("Impossible de déterminer une IP locale à annoncer — mDNS désactivé.")
            return
        nom_service = f"{MDNS_NOM_INSTANCE}.{MDNS_SERVICE_TYPE}"
        info = ServiceInfo(
            MDNS_SERVICE_TYPE, nom_service,
            addresses=[socket.inet_aton(ip)], port=LISTEN_PORT,
            server=f"{MDNS_NOM_INSTANCE}.local.",
            properties={"role": "proxy", "protocole": "meshcore"},
        )
        zc = AsyncZeroconf()
        try:
            await zc.async_register_service(info)
        except Exception:
            logger.exception("Échec de l'annonce mDNS — le proxy continue sans.")
            await zc.async_close()
            return
        self._mdns_zeroconf = zc
        self._mdns_info = info
        logger.info("Annoncé en mDNS : %s (%s:%s)", nom_service, ip, LISTEN_PORT)

    async def _retirer_annonce_mdns(self):
        if self._mdns_zeroconf is None:
            return
        try:
            await self._mdns_zeroconf.async_unregister_service(self._mdns_info)
        except Exception:
            logger.exception("Échec du retrait de l'annonce mDNS.")
        finally:
            await self._mdns_zeroconf.async_close()
            self._mdns_zeroconf = None

    async def _ouvrir_connexion_upstream(self):
        if CONNEXION_TYPE == "SERIE":
            if serial_asyncio_fast is None:
                raise RuntimeError("pyserial-asyncio-fast non installé — requis pour MESHCORE_CONNEXION_TYPE=SERIE.")
            return await serial_asyncio_fast.open_serial_connection(url=SERIE_DEVICE, baudrate=SERIE_BAUDRATE)
        return await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)

    async def _boucle_upstream(self):
        libelle = SERIE_DEVICE if CONNEXION_TYPE == "SERIE" else f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"
        while True:
            try:
                logger.info("Connexion au companion réel (%s) : %s...", CONNEXION_TYPE, libelle)
                reader, writer = await self._ouvrir_connexion_upstream()
                self.upstream_writer = writer
                logger.info("Connecté au companion réel.")
                tampon = bytearray()
                while True:
                    data = await reader.read(4096)
                    if not data:
                        raise ConnectionError("companion réel déconnecté")
                    tampon.extend(data)
                    for payload in _lire_trames(tampon, 0x3E):
                        await self._router_depuis_upstream(payload)
            except Exception:
                logger.exception("Connexion au companion réel perdue, nouvelle tentative dans %ds.", RECONNECT_DELAY_SECONDS)
                self.upstream_writer = None
                if self.evenement_fin_reponse is not None and not self.evenement_fin_reponse.is_set():
                    self.evenement_fin_reponse.set()
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _router_depuis_upstream(self, payload: bytes):
        code = payload[0] if payload else 0
        trame = b"\x3e" + len(payload).to_bytes(2, "little") + payload
        if code < PUSH_THRESHOLD:
            if code in CODES_MESSAGE_RECU:
                for client in list(self.clients):
                    if client is not self.client_en_vol:
                        await self._envoyer(client, trame)
            if self.collecte_active:
                self.frames_reponse.append(trame)
                self._reprogrammer_silence()
            else:
                logger.debug("Réponse (code=%d) reçue sans commande en attente, ignorée.", code)
        else:
            logger.debug("Push (code=0x%02x) diffusé à %d client(s).", code, len(self.clients))
            for client in list(self.clients):
                await self._envoyer(client, trame)

    async def _gerer_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        pair = writer.get_extra_info("peername")
        logger.info("Client connecté : %s", pair)
        self.clients.add(writer)
        tampon = bytearray()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                tampon.extend(data)
                for payload in _lire_trames(tampon, 0x3C):
                    await self._envoyer_commande(writer, payload)
        except Exception:
            logger.exception("Erreur avec le client %s.", pair)
        finally:
            logger.info("Client déconnecté : %s", pair)
            self.clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    def _reprogrammer_silence(self):
        """Repousse la fin de collecte tant que de nouvelles trames de réponse arrivent —
        c'est ce qui permet de capturer une rafale complète (ex: liste de contacts) plutôt
        qu'une seule trame."""
        if self.minuteur_silence is not None:
            self.minuteur_silence.cancel()
        loop = asyncio.get_event_loop()

        def _fin():
            if self.evenement_fin_reponse is not None:
                self.evenement_fin_reponse.set()

        self.minuteur_silence = loop.call_later(SILENCE_FIN_REPONSE, _fin)

    async def _envoyer_commande(self, writer: asyncio.StreamWriter, payload: bytes):
        """Sérialise l'envoi : une seule commande en vol vers le companion réel à la fois,
        quel que soit le client d'origine — voir le commentaire sur `verrou_commande`. Collecte
        TOUTES les trames de réponse jusqu'à un silence, pas juste la première (voir
        `_reprogrammer_silence` — une commande comme GET_CONTACTS répond en rafale)."""
        if self.upstream_writer is None:
            logger.warning("Trame cliente reçue mais companion réel non connecté, ignorée.")
            return
        async with self.verrou_commande:
            if self.upstream_writer is None:
                logger.warning("Companion réel déconnecté juste avant l'envoi, commande abandonnée.")
                return
            trame = b"\x3c" + len(payload).to_bytes(2, "little") + payload
            logger.info("Commande de %s : %s", writer.get_extra_info("peername"), _decrire_commande(payload))
            self.frames_reponse = []
            self.evenement_fin_reponse = asyncio.Event()
            self.collecte_active = True
            self.client_en_vol = writer
            self._reprogrammer_silence()
            self.upstream_writer.write(trame)
            await self.upstream_writer.drain()
            try:
                await asyncio.wait_for(self.evenement_fin_reponse.wait(), timeout=TIMEOUT_MAX_REPONSE)
            except asyncio.TimeoutError:
                logger.warning("Pas de réponse du companion réel dans le délai — %d trame(s) tout de même livrée(s).", len(self.frames_reponse))
            finally:
                self.collecte_active = False
                self.client_en_vol = None
                if self.minuteur_silence is not None:
                    self.minuteur_silence.cancel()
                    self.minuteur_silence = None
                self.evenement_fin_reponse = None
            logger.debug("Réponse complète : %d trame(s) pour ce client.", len(self.frames_reponse))
            for reponse in self.frames_reponse:
                await self._envoyer(writer, reponse)

    async def _envoyer(self, writer: asyncio.StreamWriter, trame: bytes):
        try:
            writer.write(trame)
            await writer.drain()
        except Exception:
            logger.exception("Échec d'envoi vers un client, retiré.")
            self.clients.discard(writer)


async def main():
    proxy = ProxyMeshCore()
    await proxy.demarrer()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
