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
      - code < 0x80  : livrée uniquement au client dont la commande est actuellement en vol.
      - code >= 0x80 : diffusée à TOUS les clients connectés (personne n'a demandé, tout le
        monde doit voir).

IMPORTANT : Home Assistant doit être reconfiguré pour se connecter à CE proxy (host/port de ce
service) plutôt que directement au companion — sinon il continue de prendre la seconde connexion
directe que le companion n'accepte pas, et rien n'est résolu.
"""

import asyncio
import logging
import os

logger = logging.getLogger("meshcore-proxy")

UPSTREAM_HOST = os.environ["MESHCORE_TCP_HOST"]
UPSTREAM_PORT = int(os.environ.get("MESHCORE_TCP_PORT", "5000"))
LISTEN_HOST = os.environ.get("PROXY_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("PROXY_LISTEN_PORT", "5050"))
RECONNECT_DELAY_SECONDS = int(os.environ.get("RECONNECT_DELAY_SECONDS", "5"))

PUSH_THRESHOLD = 0x80
SILENCE_FIN_REPONSE = 0.3  # secondes de silence avant de considérer une réponse (mono ou multi-trames) terminée
TIMEOUT_MAX_REPONSE = 8.0  # garde-fou si le companion ne répond jamais du tout


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


class ProxyMeshCore:
    def __init__(self):
        self.upstream_writer: asyncio.StreamWriter | None = None
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

    async def demarrer(self):
        asyncio.create_task(self._boucle_upstream())
        serveur = await asyncio.start_server(self._gerer_client, LISTEN_HOST, LISTEN_PORT)
        logger.info("Proxy en écoute sur %s:%s (companion réel : %s:%s)", LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT)
        async with serveur:
            await serveur.serve_forever()

    async def _boucle_upstream(self):
        while True:
            try:
                logger.info("Connexion au companion réel %s:%s...", UPSTREAM_HOST, UPSTREAM_PORT)
                reader, writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
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
            self.frames_reponse = []
            self.evenement_fin_reponse = asyncio.Event()
            self.collecte_active = True
            self._reprogrammer_silence()
            self.upstream_writer.write(trame)
            await self.upstream_writer.drain()
            try:
                await asyncio.wait_for(self.evenement_fin_reponse.wait(), timeout=TIMEOUT_MAX_REPONSE)
            except asyncio.TimeoutError:
                logger.warning("Pas de réponse du companion réel dans le délai — %d trame(s) tout de même livrée(s).", len(self.frames_reponse))
            finally:
                self.collecte_active = False
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
