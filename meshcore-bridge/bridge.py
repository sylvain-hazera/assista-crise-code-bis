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
import hashlib
import json
import logging
import os
import random
import socket
import sys

import httpx
from meshcore import EventType, MeshCore

logger = logging.getLogger("meshcore-bridge")

DJANGO_API_URL = os.environ["DJANGO_API_URL"]
DJANGO_EMAIL = os.environ["DJANGO_BRIDGE_EMAIL"]
DJANGO_PASSWORD = os.environ["DJANGO_BRIDGE_PASSWORD"]
COMPAGNON_ID = os.environ["COMPAGNON_ID"]

# Bascule vers l'assista-crise LOCAL (profil Full colocalisé, voir satellite/docker-compose.yml)
# quand le central devient injoignable — tous optionnels : absents = comportement historique
# (central uniquement), rien ne change pour .113/.114 ni pour un satellite GW seul sans Full
# local. Voir DjangoClient._cible_actuelle.
LOCAL_API_URL = os.environ.get("LOCAL_API_URL")
# Port publié du backend local du satellite : 8010 (8000 est très souvent déjà pris sur un
# PC), décalé par installer.sh si lui aussi est occupé
PORT_BACKEND_LOCAL = int(os.environ.get("BACKEND_PORT") or 8010)
LOCAL_BRIDGE_EMAIL = os.environ.get("LOCAL_BRIDGE_EMAIL")
LOCAL_BRIDGE_PASSWORD = os.environ.get("LOCAL_BRIDGE_PASSWORD")
FICHIER_ETAT_CONNECTIVITE = os.environ.get("FICHIER_ETAT_CONNECTIVITE", "/var/run/satellite/etat_connectivite.json")

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
# index libre (0 réservé, "Public Channel" par défaut sur le firmware). Vérifié sur matériel
# réel (FR33BORD_SH1, 12/09) : le firmware accepte les index 0 à 39 (40 refuse avec
# ERR_CODE_NOT_FOUND) — soit 39 slots utilisables au-delà du public, chiffrés ou non (un canal
# "#nom" non chiffré occupe un slot exactement comme un canal privé, seule la dérivation de la
# clé diffère). 8 était une valeur bridée arbitrairement, jamais la vraie limite matérielle.
CANAUX_POLL_INTERVAL_SECONDS = int(os.environ.get("CANAUX_POLL_INTERVAL_SECONDS", "60"))
CANAL_IDX_MAX = int(os.environ.get("CANAL_IDX_MAX", "39"))
# Canaux "fantômes" (trafic radio capté sans connaître le canal localement, voir
# enregistrer_ecouteurs/_sur_log_rx et boucle_signalement_canaux_detectes) : accumulés en
# mémoire et envoyés groupés à cet intervalle plutôt qu'un appel API par paquet reçu, le trafic
# radio pouvant être nettement plus fréquent que les autres cycles de ce pont.
CANAUX_DETECTES_FLUSH_INTERVAL_SECONDS = int(os.environ.get("CANAUX_DETECTES_FLUSH_INTERVAL_SECONDS", "120"))
# Libération des anciens slots de canal (rotation de clé, délai de grâce de 48h -- voir
# CanalMeshCoreObsolete) : pas urgent, cycle peu fréquent.
NETTOYAGE_CANAUX_POLL_INTERVAL_SECONDS = int(os.environ.get("NETTOYAGE_CANAUX_POLL_INTERVAL_SECONDS", "3600"))
# Batterie du COMPANION lui-même (get_bat(), commande locale sans coût d'antenne mesh, voir
# docstring de CompagnonMeshCore.derniere_batterie_niveau) : un autre client la sonde déjà
# toutes les 5s via le même proxy (voir meshcore-bridge/proxy.py) sans problème constaté, mais
# rien ne justifie une telle fréquence pour notre propre usage -- pas une donnée urgente.
BATTERIE_COMPAGNON_POLL_INTERVAL_SECONDS = int(os.environ.get("BATTERIE_COMPAGNON_POLL_INTERVAL_SECONDS", "600"))
# Traceroute (voir docstring de TracerouteMeshCore côté Django, demande utilisateur du 10/10) :
# demandé explicitement par un acteur institutionnel (bouton), donc vérifié assez souvent pour
# rester réactif -- contrairement aux boucles passives ci-dessus. TIMEOUT large : un flood
# traceroute peut traverser plusieurs sauts avant de revenir, bien plus lent qu'un message
# direct.
TRACEROUTE_POLL_INTERVAL_SECONDS = int(os.environ.get("TRACEROUTE_POLL_INTERVAL_SECONDS", "15"))
TRACEROUTE_TIMEOUT_SECONDS = int(os.environ.get("TRACEROUTE_TIMEOUT_SECONDS", "25"))
POSITIONS_MISSIONS_REQ_TIMEOUT_SECONDS = int(os.environ.get("POSITIONS_MISSIONS_REQ_TIMEOUT_SECONDS", "20"))

# Miroir de AdvType (meshcore/packets.py) -> TypeContactMeshCore côté Django (voir models.py).
TYPE_CONTACT_PAR_ADV_TYPE = {
    0: "INCONNU",
    1: "COMPANION",
    2: "REPEATER",
    3: "ROOM",
    4: "SENSOR",
}


async def _tester_localhost_backend(port=None, timeout=2.0):
    port = port or PORT_BACKEND_LOCAL
    """Cas le plus courant : ce pont et le backend local tournent sur le MÊME Pi (profil Full,
    voir satellite/docker-compose.yml) — pas besoin de mDNS, un simple test de port suffit."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def _decouvrir_backend_local_mdns(duree_s=5.0):
    """Satellite à 2 Pi (GW séparé du Pi Full sur le même site, voir le cadrage "Chantier B") :
    le backend local s'annonce lui-même (satellite/annoncer_backend_local.py, service
    _ac-local._tcp.local.) — renvoie son URL API si trouvé dans le délai, None sinon.
    Best-effort : zeroconf absent -> None, jamais une exception qui remonte."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        return None

    trouve = {}

    class _Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                trouve["ip"] = socket.inet_ntoa(info.addresses[0])
                trouve["port"] = info.port

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, "_ac-local._tcp.local.", _Listener())
        await asyncio.sleep(duree_s)
    finally:
        zc.close()

    if trouve:
        return f"http://{trouve['ip']}:{trouve['port']}/api"
    return None


async def resoudre_url_locale():
    """Ordre de résolution, une seule fois au démarrage (pas re-sondé en boucle — voir
    DjangoClient, qui bascule ensuite central/local via etat_connectivite.py sans jamais
    revérifier CETTE résolution) :
      1. LOCAL_API_URL renseignée à la main -> utilisée telle quelle, AUCUNE détection (voir
         satellite/README.md : c'est la voie "je sais déjà, ne cherche pas", prioritaire sur
         tout le reste par construction).
      2. localhost:8010 répond -> même machine (profil Full colocalisé), cas le plus courant.
      3. mDNS -> satellite à 2 Pi, GW et Full séparés sur le même site.
      4. Rien -> pas de repli local, comportement historique (central uniquement)."""
    if LOCAL_API_URL:
        logger.info("URL locale configurée manuellement : %s", LOCAL_API_URL)
        return LOCAL_API_URL
    if await _tester_localhost_backend():
        logger.info("Backend local détecté sur localhost:%s (même machine).", PORT_BACKEND_LOCAL)
        return f"http://localhost:{PORT_BACKEND_LOCAL}/api"
    url_mdns = await _decouvrir_backend_local_mdns()
    if url_mdns:
        logger.info("Backend local découvert en mDNS : %s", url_mdns)
        return url_mdns
    logger.info("Aucun assista-crise local détecté au démarrage — central uniquement.")
    return None


class _CibleAuth:
    """Une cible (central OU local) avec son propre token — deux bases distinctes, deux comptes
    de service distincts, un JWT obtenu sur l'une n'est jamais valide sur l'autre."""

    def __init__(self, base_url, email, password):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.access_token = None


class DjangoClient:
    """Client HTTP vers l'API assista-crise — authentification JWT avec ré-obtention
    automatique du token d'accès (durée de vie 1h côté serveur, voir SIMPLE_JWT dans
    backend/config/settings.py). Le compte utilisé doit être un compte de service dédié,
    authentifié (IsAuthenticated suffit pour les actions que ce pont appelle).

    Bascule vers une cible LOCALE (profil Full colocalisé, voir satellite/docker-compose.yml)
    quand le central est signalé hors-ligne — lit l'état déjà calculé par satellite/
    etat_connectivite.py (un seul processus vérifie, celui-ci ne refait jamais sa propre
    requête réseau, voir _cible_actuelle) plutôt que de dupliquer sa propre détection.
    `cible_locale=None` (aucun LOCAL_API_URL configuré) = comportement historique, toujours le
    central, satellite GW seul ou déploiement .113/.114 inchangés.

    ATTENTION (limite connue, 2026-09-17) : un CompagnonMeshCore/message n'a de sens des deux
    côtés que s'il existe avec le MÊME UUID dans les deux bases — pas garanti tant que la
    synchro locale -> centrale (cadrage "Chantier B") n'est pas construite. Cette bascule évite
    au pont de rester bloqué sur un central injoignable, elle ne résout pas encore la
    réconciliation des données écrites pendant la coupure."""

    def __init__(self, central_url, central_email, central_password,
                 local_url=None, local_email=None, local_password=None,
                 fichier_etat_connectivite=None):
        self._central = _CibleAuth(central_url, central_email, central_password)
        self._local = _CibleAuth(local_url, local_email, local_password) if local_url else None
        self._fichier_etat_connectivite = fichier_etat_connectivite or FICHIER_ETAT_CONNECTIVITE
        self._cible_precedente = None
        self._client = httpx.AsyncClient(timeout=15)

    def _cible_actuelle(self):
        """Fichier absent/illisible/corrompu, ou aucune cible locale configurée -> central par
        défaut (fail-safe : ne jamais basculer sur une supposition, seulement sur un signal
        explicite `en_ligne: false` déjà vérifié par etat_connectivite.py)."""
        cible = self._central
        if self._local is not None:
            try:
                with open(self._fichier_etat_connectivite, encoding="utf-8") as f:
                    etat = json.load(f)
                if etat.get("en_ligne") is False:
                    cible = self._local
            except (OSError, ValueError):
                pass
        if cible is not self._cible_precedente:
            logger.info("Cible API : %s (%s).", cible.base_url, "local" if cible is self._local else "central")
            self._cible_precedente = cible
        return cible

    async def _authenticate(self, cible):
        response = await self._client.post(
            f"{cible.base_url}/token/", json={"email": cible.email, "password": cible.password}
        )
        response.raise_for_status()
        cible.access_token = response.json()["access"]
        logger.info("Authentifié auprès de %s.", cible.base_url)

    async def _request(self, method, path, **kwargs):
        cible = self._cible_actuelle()
        if cible.access_token is None:
            await self._authenticate(cible)
        headers = {"Authorization": f"Bearer {cible.access_token}"}
        response = await self._client.request(method, f"{cible.base_url}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            # Token expiré entre-temps : une ré-authentification, puis on rejoue une fois.
            await self._authenticate(cible)
            headers = {"Authorization": f"Bearer {cible.access_token}"}
            response = await self._client.request(method, f"{cible.base_url}{path}", headers=headers, **kwargs)
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
        """Canaux (équipe ou publics `#nom`) pas encore configurés localement sur ce companion —
        voir CompagnonMeshCoreViewSet.canaux_a_provisionner."""
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/canaux-a-provisionner/")
        return response.json()

    async def canaux_provisionnes(self, compagnon_id):
        """Canaux déjà configurés sur ce companion (canal_idx connu, y compris le canal Public
        par défaut à l'idx 0) — voir CompagnonMeshCoreViewSet.canaux_provisionnes, appelé une
        fois au démarrage de session pour reconstruire canaux_idx_map."""
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/canaux-provisionnes/")
        return response.json()

    async def canaux_pour_decodage_logiciel(self, compagnon_id):
        """Tous les canaux actifs (équipe ou publics), provisionnés ou non -- voir
        CompagnonMeshCoreViewSet.canaux_pour_decodage_logiciel et
        boucle_decodage_logiciel_canaux ci-dessous."""
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/canaux-pour-decodage-logiciel/")
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

    async def rapporter_batterie(self, compagnon_id, niveau):
        await self._request(
            "POST", f"/compagnons-meshcore/{compagnon_id}/rapporter-batterie/",
            json={"niveau": niveau},
        )

    async def traceroutes_a_executer(self, compagnon_id):
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/traceroutes-a-executer/")
        return response.json()

    async def rapporter_traceroute(self, compagnon_id, traceroute_id, statut, tag=None, chemin=None, erreur=None):
        payload = {"id": traceroute_id, "statut": statut}
        if tag is not None:
            payload["tag"] = tag
        if chemin is not None:
            payload["chemin"] = chemin
        if erreur is not None:
            payload["erreur"] = erreur
        await self._request(
            "POST", f"/compagnons-meshcore/{compagnon_id}/rapporter-traceroute/", json=payload,
        )

    async def signaler_canaux_detectes(self, compagnon_id, hashes):
        """`hashes` : dict chan_hash (2 car. hex) -> nombre de paquets observés depuis le
        dernier envoi — voir CompagnonMeshCoreViewSet.signaler_canaux_detectes. Pas d'appel si
        rien de nouveau (voir boucle_signalement_canaux_detectes, qui vide le compteur local)."""
        if not hashes:
            return
        await self._request(
            "POST", f"/compagnons-meshcore/{compagnon_id}/signaler-canaux-detectes/",
            json={"hashes": hashes},
        )

    async def canaux_a_liberer(self, compagnon_id):
        """Anciens slots de canal mûrs pour être libérés sur ce companion (délai de grâce de
        48h après rotation de clé écoulé) — voir CompagnonMeshCoreViewSet.canaux_a_liberer."""
        response = await self._request("GET", f"/compagnons-meshcore/{compagnon_id}/canaux-a-liberer/")
        return response.json()

    async def rapporter_canal_libere(self, compagnon_id, obsolete_id):
        await self._request(
            "POST", f"/compagnons-meshcore/{compagnon_id}/rapporter-canal-libere/",
            json={"id": obsolete_id},
        )

    async def commandes_a_executer(self, compagnon_id):
        """Commandes ponctuelles en attente pour ce companion (advert/flood advert pour
        l'instant) — voir CommandeMeshCoreViewSet.a_executer."""
        response = await self._request("GET", "/commandes-meshcore/a-executer/", params={"compagnon": compagnon_id})
        return response.json()

    async def marquer_commande(self, commande_id, statut, erreur=None):
        payload = {"statut": statut}
        if erreur:
            payload["erreur"] = erreur
        await self._request("PATCH", f"/commandes-meshcore/{commande_id}/", json=payload)

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


def enregistrer_ecouteurs(meshcore, django, compagnon_id, sur_deconnexion, canaux_idx_map, canaux_detectes_compteur, canaux_virtuels_par_hash):
    """`canaux_idx_map` (dict canal_idx -> canal_id, partagé avec boucle_provisionnement_canaux)
    permet de rattacher un message de canal entrant au bon CanalMeshCore — un canal n'a pas
    d'identité serveur à ce niveau protocolaire, seulement un index local (voir
    PacketType.CHANNEL_MSG_RECV, aucun champ clé/id de canal dans la trame).

    `canaux_detectes_compteur` (dict chan_hash -> nombre de paquets, partagé avec
    boucle_signalement_canaux_detectes) : alimenté par _sur_log_rx ci-dessous, voir sa
    docstring.

    `canaux_virtuels_par_hash` (dict chan_hash -> canal_id, partagé avec
    boucle_decodage_logiciel_canaux) : canaux déchiffrés EN LOGICIEL (voir le plan de conception
    "Décodage logiciel des canaux MeshCore", 12/10) -- indépendant de canaux_idx_map, qui ne
    couvre que les canaux physiquement provisionnés (set_channel)."""

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

    async def _sur_log_rx(event):
        """RX_LOG_DATA est émis pour TOUT paquet radio journalisé (ADVERT, ACK, TRACE...), pas
        seulement les canaux — on ne garde que payload_type == 5 (GRP_TXT, message de canal en
        diffusion). `chan_hash` (1 octet, toujours présent sur l'air, voir doc de conception)
        est fourni même quand le companion ne connaît pas la clé.

        Décodage LOGICIEL (voir boucle_decodage_logiciel_canaux et le plan de conception
        "Décodage logiciel des canaux MeshCore", 12/10) : si `canaux_virtuels_par_hash` connaît
        ce chan_hash, le parseur meshcore_py a déjà déchiffré le message (decrypt_channels
        activé, voir executer_une_session) -- `message` est alors présent dans le payload. On le
        route directement, SANS passer par _sur_message_canal (qui ne voit que les canaux
        physiquement provisionnés) et sans le compter comme "détecté" ci-dessous.

        `chan_name` n'est renseigné que si la clé correspond à un slot déjà connu du parseur
        (physique OU virtuel) : c'est ce qui distingue un canal "fantôme" (jamais vu, ni
        physiquement ni virtuellement) d'un canal déjà reconnu (évite de le compter deux fois)."""
        if event.attributes.get("payload_type") != 5:
            return
        payload = event.payload or {}
        chan_hash = payload.get("chan_hash")
        message = payload.get("message")
        if chan_hash and message:
            canal_id = canaux_virtuels_par_hash.get(chan_hash)
            if canal_id:
                logger.info("Message décodé en logiciel sur le canal %s (%d caractères).", canal_id, len(message))
                try:
                    await django.logger_message_canal_entrant(canal_id, message)
                except Exception:
                    logger.exception("Échec de journalisation d'un message de canal décodé en logiciel.")
                return
        if not chan_hash or payload.get("chan_name"):
            return
        canaux_detectes_compteur[chan_hash] = canaux_detectes_compteur.get(chan_hash, 0) + 1

    meshcore.subscribe(EventType.CONTACT_MSG_RECV, _sur_message)
    meshcore.subscribe(EventType.CHANNEL_MSG_RECV, _sur_message_canal)
    meshcore.subscribe(EventType.DISCONNECTED, _sur_deconnexion)
    meshcore.subscribe(EventType.RX_LOG_DATA, _sur_log_rx)


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


async def boucle_commandes(meshcore, django, compagnon_id):
    """Interroge périodiquement l'API pour les commandes ponctuelles en attente (advert/flood
    advert pour l'instant) — même principe que boucle_envoi, voir
    CommandeMeshCoreViewSet.a_executer. N'agit que sur CE companion (l'appareil directement
    connecté) : piloter un relais distant est hors du périmètre de cette file, voir docstring
    du modèle CommandeMeshCore côté Django."""
    while True:
        try:
            en_attente = await django.commandes_a_executer(compagnon_id)
            for commande in en_attente:
                try:
                    if commande["type_commande"] == "FLOOD_ADVERT":
                        await meshcore.commands.send_advert(flood=True)
                    else:
                        await meshcore.commands.send_advert(flood=False)
                    await django.marquer_commande(commande["id"], "EXECUTEE")
                    logger.info("Commande %s (%s) exécutée.", commande["id"], commande["type_commande"])
                except Exception as exc:
                    logger.exception("Échec d'exécution de la commande %s.", commande["id"])
                    try:
                        await django.marquer_commande(commande["id"], "ECHEC", erreur=str(exc))
                    except Exception:
                        logger.exception("Échec de la mise à jour de statut après échec d'exécution.")
        except Exception:
            logger.exception("Échec de récupération des commandes en attente auprès de l'API.")
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
                    # out_path_len : nombre de sauts du chemin connu par CE companion vers ce
                    # contact. Le firmware transmet 255 comme sentinel ("direct/flood, aucun
                    # chemin confirmé"), PAS "255 sauts" -- mais la bibliothèque meshcore_py
                    # (reader.py, plen == 255) traduit déjà CE sentinel en -1 avant qu'on le
                    # voie ici, jamais en 255 : un test `== 255` ne correspond donc jamais, et
                    # -1 passait tel quel vers Django, qui le refuse (PositiveSmallIntegerField,
                    # contrainte >= 0 -- constaté en prod le 11/10, échec systématique de
                    # synchroniser_contacts). Transmis comme None dans les deux cas (-1 OU 255,
                    # au cas où une version future de la lib changerait de convention) pour ne
                    # jamais laisser croire à un chemin très long ni planter la synchro.
                    out_path_len = c.get("out_path_len")
                    if out_path_len is not None:
                        contact["nombre_sauts"] = None if out_path_len in (-1, 255) else out_path_len
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
    pas besoin de retrouver l'objet contact complet. La réponse est une liste de canaux LPP
    (channel/type/value) : la position est le canal "gps" (latitude/longitude/altitude), la
    batterie les canaux "voltage"/"percentage" (voir meshcore/lpp_json_encoder.py et la
    docstring de ContactMeshCore.tension_batterie_v côté Django, demande utilisateur du 10/10)
    — un nœud sans GPS actif en télémétrie peut quand même avoir une batterie à remonter, donc
    chaque canal est traité indépendamment plutôt que de tout ignorer faute de position."""
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
                maj = {"pubkey_hex": pubkey_hex}
                position = next((canal for canal in lpp if canal.get("type") == "gps"), None)
                if position and isinstance(position.get("value"), dict):
                    lat = position["value"].get("latitude")
                    lon = position["value"].get("longitude")
                    if lat and lon:
                        maj["latitude"], maj["longitude"] = lat, lon
                tension = next((canal for canal in lpp if canal.get("type") == "voltage"), None)
                if tension is not None and tension.get("value") is not None:
                    maj["tension_batterie_v"] = tension["value"]
                niveau = next((canal for canal in lpp if canal.get("type") == "percentage"), None)
                if niveau is not None and niveau.get("value") is not None:
                    maj["niveau_batterie_pct"] = niveau["value"]
                if len(maj) > 1:  # autre chose que pubkey_hex seul
                    contacts_rafraichis.append(maj)
                else:
                    logger.debug("Télémétrie reçue de %s sans canal GPS ni batterie exploitable.", pubkey_hex)

            if contacts_rafraichis:
                await django.synchroniser_contacts(compagnon_id, contacts_rafraichis)
                logger.info("Position/télémétrie rafraîchie pour %d nœud(s) en mission.", len(contacts_rafraichis))
        except Exception:
            logger.exception("Échec du cycle de suivi de position en mission.")
        await asyncio.sleep(POSITIONS_MISSIONS_POLL_INTERVAL_SECONDS)


async def _trouver_canal_existant_ou_libre(meshcore, secret):
    """Sonde les index de canal locaux (1..CANAL_IDX_MAX, 0 réservé au "Public Channel" par
    défaut du firmware). Cherche D'ABORD si `secret` est déjà configuré sur un slot — recovery
    nécessaire après un `rapporter_canal_provisionne` resté sans réponse (ex: backend
    redémarré au mauvais moment) : `set_channel` avait réussi localement mais Django ne l'a
    jamais su, donc le canal restait "à provisionner" indéfiniment et se faisait reconfigurer
    sur un NOUVEAU slot à chaque cycle — constaté en pratique (8 slots identiques gaspillés en
    une soirée avant que celui-ci ne les épuise tous). Retourne (idx, deja_configure)."""
    idx_libre = None
    for idx in range(1, CANAL_IDX_MAX + 1):
        try:
            resultat = await meshcore.commands.get_channel(idx)
        except Exception:
            logger.exception("Échec de lecture du canal local %s.", idx)
            continue
        if resultat is None or resultat.type == EventType.ERROR:
            if idx_libre is None:
                idx_libre = idx
            continue
        payload = resultat.payload or {}
        if payload.get("channel_secret") == secret:
            return idx, True
        if not payload.get("channel_name") and idx_libre is None:
            idx_libre = idx
    return idx_libre, False


async def boucle_provisionnement_canaux(meshcore, django, compagnon_id, canaux_idx_map):
    """Configure localement (set_channel) les canaux d'équipe et publics pas encore présents
    sur CE companion — voir docstring de CanalMeshCore : impossible de pousser cette
    configuration à distance sur le nœud d'un membre, mais le pont peut le faire pour son
    propre companion partagé, afin de pouvoir y envoyer/recevoir en son nom.

    Resynchronise aussi canaux_idx_map à chaque cycle (pas seulement au démarrage de session,
    voir executer_une_session) : couvre le canal "Public" par défaut (idx 0,
    SECRET_PUBLIC_PAR_DEFAUT), créé directement côté Django avec canal_idx déjà renseigné dès
    qu'un trafic radio le confirme (signaler_canaux_detectes) -- jamais via set_channel/cette
    boucle, donc jamais vu autrement par CE processus déjà en cours tant qu'il ne redémarre pas."""
    while True:
        try:
            for canal in await django.canaux_provisionnes(compagnon_id):
                canaux_idx_map.setdefault(canal["canal_idx"], canal["id"])
            a_provisionner = await django.canaux_a_provisionner(compagnon_id)
            for canal in a_provisionner:
                canal_id, nom, cle_hex = canal["id"], canal["nom"], canal.get("cle_partagee_hex")
                if not cle_hex:
                    logger.warning("Canal %s sans clé partagée, provisionnement ignoré.", canal_id)
                    continue
                secret = bytes.fromhex(cle_hex)
                idx, deja_configure = await _trouver_canal_existant_ou_libre(meshcore, secret)
                if idx is None:
                    logger.error("Aucun slot de canal local disponible (max %d) pour provisionner « %s ».", CANAL_IDX_MAX, nom)
                    continue
                if not deja_configure:
                    try:
                        resultat = await meshcore.commands.set_channel(idx, nom, secret)
                    except Exception:
                        logger.exception("Échec de configuration locale du canal « %s » (slot %s).", nom, idx)
                        continue
                    if resultat and resultat.type == EventType.ERROR:
                        logger.error("Échec de configuration locale du canal « %s » (slot %s) : %r", nom, idx, resultat.payload)
                        continue
                canaux_idx_map[idx] = canal_id
                try:
                    await django.rapporter_canal_provisionne(compagnon_id, canal_id, idx)
                except Exception:
                    # Le canal EST déjà configuré localement (slot idx) — le prochain cycle le
                    # retrouvera via `deja_configure` ci-dessus plutôt que d'en gaspiller un
                    # nouveau, contrairement à avant ce correctif.
                    logger.exception("Échec du rapport de provisionnement pour « %s » (slot %s déjà configuré, sera retrouvé au prochain cycle).", nom, idx)
                    continue
                logger.info(
                    "Canal « %s » %s sur le slot %s.", nom,
                    "déjà configuré, statut resynchronisé" if deja_configure else "configuré localement", idx,
                )
        except Exception:
            logger.exception("Échec du cycle de provisionnement des canaux.")
        await asyncio.sleep(CANAUX_POLL_INTERVAL_SECONDS)


async def boucle_decodage_logiciel_canaux(meshcore, django, compagnon_id, canaux_virtuels_par_hash, canaux_idx_map):
    """Déchiffrement LOGICIEL des canaux (voir le plan de conception "Décodage logiciel des
    canaux MeshCore", 12/10) : contrairement à boucle_provisionnement_canaux (qui configure un
    slot PHYSIQUE, requis pour ENVOYER), celle-ci se contente d'enregistrer chaque canal actif
    dans le registre 100% logiciel de la librairie meshcore_py (MeshcorePacketParser.channels,
    peuplé via newChannel -- voir meshcore_py/meshcore_parser.py) : dès que le secret y est
    connu, le trafic radio overheard (RX_LOG_DATA, toujours actif, voir _sur_log_rx) est
    déchiffré immédiatement -- AUCUN slot physique consommé, AUCUNE attente de
    boucle_provisionnement_canaux. C'est ce que l'utilisateur observe sur son propre matériel :
    configurer un canal `#public` suffit à en recevoir le trafic, sans rien demander à personne
    (la clé d'un canal `#nom` se dérive du nom, voir CanalMeshCore.derive_cle_publique).

    Les index utilisés ici (1000+i) sont purement des positions de LISTE PYTHON côté
    bibliothèque (self.channels dans meshcore_parser.py) -- jamais envoyés au matériel, jamais
    en concurrence avec les vrais slots 0-CANAL_IDX_MAX gérés par boucle_provisionnement_canaux.

    Ignore un canal déjà présent dans canaux_idx_map (déjà servi par le chemin FIRMWARE,
    CHANNEL_MSG_RECV) -- invariant à préserver : un canal n'est jamais traité par les deux
    chemins à la fois, pour ne jamais dupliquer un message entrant en base."""
    while True:
        try:
            canaux = await django.canaux_pour_decodage_logiciel(compagnon_id)
            for i, canal in enumerate(canaux):
                canal_id, nom, cle_hex = canal["id"], canal["nom"], canal.get("cle_partagee_hex")
                if not cle_hex:
                    continue
                if canal_id in canaux_idx_map.values():
                    continue  # déjà servi par le chemin firmware (CHANNEL_MSG_RECV)
                secret = bytes.fromhex(cle_hex)
                chan_hash = hashlib.sha256(secret).hexdigest()[0:2]
                await meshcore._reader.packet_parser.newChannel({
                    "channel_idx": 1000 + i,
                    "channel_name": nom,
                    "channel_secret": secret,
                    "channel_hash": chan_hash,
                })
                if chan_hash not in canaux_virtuels_par_hash:
                    logger.info("Canal « %s » enregistré pour décodage logiciel (chan_hash=%s, aucun slot physique requis).", nom, chan_hash)
                canaux_virtuels_par_hash[chan_hash] = canal_id
        except Exception:
            logger.exception("Échec du cycle de décodage logiciel des canaux.")
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


async def boucle_batterie_compagnon(meshcore, django, compagnon_id):
    """Batterie du companion lui-même (voir docstring de CompagnonMeshCore.
    derniere_batterie_niveau) -- commande locale (get_bat), aucun coût d'antenne mesh."""
    while True:
        await asyncio.sleep(BATTERIE_COMPAGNON_POLL_INTERVAL_SECONDS)
        try:
            resultat = await meshcore.commands.get_bat()
            if resultat is None or resultat.type == EventType.ERROR:
                logger.warning("Échec de lecture de la batterie du companion : %r", resultat.payload if resultat else None)
                continue
            niveau = (resultat.payload or {}).get("level")
            if niveau is None:
                continue
            await django.rapporter_batterie(compagnon_id, niveau)
            logger.debug("Batterie du companion rapportée : %s.", niveau)
        except Exception:
            logger.exception("Échec du cycle de lecture de la batterie du companion.")


async def boucle_traceroutes(meshcore, django, compagnon_id):
    """Exécute les diagnostics traceroute demandés depuis l'interface (voir
    CompagnonMeshCoreViewSet.lancer_traceroute) -- un paquet de trace en diffusion
    (send_trace, sans cible ni chemin forcé : voir docstring de TracerouteMeshCore côté
    Django) dont la réponse (EventType.TRACE_DATA) arrive de façon asynchrone, corrélée par
    `tag` -- meshcore.dispatcher.wait_for_event (même patron que req_telemetry_sync, qui
    utilise le même mécanisme en interne à la bibliothèque) permet d'attendre CETTE réponse
    précise sans intercepter celle d'un autre trace en cours."""
    while True:
        try:
            en_attente = await django.traceroutes_a_executer(compagnon_id)
            for tr in en_attente:
                tag = random.randint(1, 0xFFFFFFFF)
                try:
                    envoi = await meshcore.commands.send_trace(tag=tag)
                except Exception as exc:
                    logger.exception("Échec d'envoi du traceroute %s.", tr["id"])
                    await django.rapporter_traceroute(compagnon_id, tr["id"], "ECHEC", erreur=str(exc))
                    continue
                if envoi is None or envoi.type == EventType.ERROR:
                    logger.warning("Échec d'envoi du traceroute %s : %r", tr["id"], envoi.payload if envoi else None)
                    await django.rapporter_traceroute(
                        compagnon_id, tr["id"], "ECHEC", tag=tag,
                        erreur=str(envoi.payload if envoi else "Aucune réponse à l'envoi."),
                    )
                    continue
                trace_event = await meshcore.dispatcher.wait_for_event(
                    EventType.TRACE_DATA, attribute_filters={"tag": tag}, timeout=TRACEROUTE_TIMEOUT_SECONDS,
                )
                if trace_event is None:
                    logger.info("Traceroute %s : aucune réponse reçue dans le délai (tag=%s).", tr["id"], tag)
                    await django.rapporter_traceroute(
                        compagnon_id, tr["id"], "ECHEC", tag=tag,
                        erreur="Aucune réponse de trace reçue (chemin flood jamais revenu dans le délai).",
                    )
                else:
                    chemin = (trace_event.payload or {}).get("path")
                    logger.info("Traceroute %s terminé (tag=%s, %d saut(s)).", tr["id"], tag, len(chemin or []))
                    await django.rapporter_traceroute(compagnon_id, tr["id"], "TERMINE", tag=tag, chemin=chemin)
        except Exception:
            logger.exception("Échec du cycle de traceroute.")
        await asyncio.sleep(TRACEROUTE_POLL_INTERVAL_SECONDS)


async def boucle_signalement_canaux_detectes(django, compagnon_id, canaux_detectes_compteur):
    """Vide périodiquement `canaux_detectes_compteur` (alimenté par _sur_log_rx, voir
    enregistrer_ecouteurs) vers l'API — un lot groupé, pas un appel par paquet. Échange
    atomique (nouveau dict vide affecté avant l'appel réseau) pour ne perdre aucun comptage
    arrivé pendant l'envoi."""
    while True:
        await asyncio.sleep(CANAUX_DETECTES_FLUSH_INTERVAL_SECONDS)
        if not canaux_detectes_compteur:
            continue
        a_envoyer = dict(canaux_detectes_compteur)
        canaux_detectes_compteur.clear()
        try:
            await django.signaler_canaux_detectes(compagnon_id, a_envoyer)
            logger.info("Canaux détectés signalés : %r.", a_envoyer)
        except Exception:
            logger.exception("Échec de signalement des canaux détectés — comptages perdus pour ce cycle.")


async def boucle_nettoyage_canaux(meshcore, django, compagnon_id):
    """Libère localement (set_channel avec un nom vide, voir docstring de CanalMeshCoreObsolete
    côté Django — aucune commande firmware dédiée à la suppression d'un canal) les anciens
    slots dont le délai de grâce de 48h après rotation de clé est écoulé."""
    while True:
        try:
            a_liberer = await django.canaux_a_liberer(compagnon_id)
            for obsolete in a_liberer:
                idx = obsolete["canal_idx"]
                try:
                    resultat = await meshcore.commands.set_channel(idx, "")
                    if resultat and resultat.type == EventType.ERROR:
                        logger.error("Échec de libération du slot de canal %s : %r", idx, resultat.payload)
                        continue
                except Exception:
                    logger.exception("Échec de libération du slot de canal %s.", idx)
                    continue
                try:
                    await django.rapporter_canal_libere(compagnon_id, obsolete["id"])
                except Exception:
                    # Le slot EST déjà libéré localement — sans ce rapport, Django le
                    # resservira au prochain cycle, pour un second set_channel sans effet
                    # (slot déjà vide) plutôt qu'une perte d'information.
                    logger.exception("Échec du rapport de libération du slot %s (sera retenté au prochain cycle).", idx)
                    continue
                logger.info("Slot de canal %s libéré (ancien canal obsolète).", idx)
        except Exception:
            logger.exception("Échec du cycle de nettoyage des canaux obsolètes.")
        await asyncio.sleep(NETTOYAGE_CANAUX_POLL_INTERVAL_SECONDS)


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
    # canal_idx (local) -> canal_id (Django) : peuplé par boucle_provisionnement_canaux au fil
    # de l'eau, lu par le listener CHANNEL_MSG_RECV pour rattacher un message entrant à son
    # CanalMeshCore. Remis à zéro à chaque (re)démarrage de CE processus -- Django, lui, ne
    # renvoie plus un canal déjà provisionné via canaux_a_provisionner une fois le round-trip
    # terminé, donc un redémarrage du pont perdait silencieusement le rattachement de TOUS les
    # canaux déjà actifs jusqu'à une rotation de clé. Reconstruit ici une bonne fois avant de
    # démarrer les boucles, y compris pour le canal Public par défaut (idx 0, jamais passé par
    # set_channel/boucle_provisionnement_canaux puisque son slot est préconfiguré en usine).
    canaux_idx_map = {}
    try:
        for canal in await django.canaux_provisionnes(COMPAGNON_ID):
            canaux_idx_map[canal["canal_idx"]] = canal["id"]
        logger.info("%d canal(aux) déjà provisionné(s) retrouvé(s) au démarrage.", len(canaux_idx_map))
    except Exception:
        logger.exception("Échec de la reconstruction de canaux_idx_map au démarrage (recouvert au fil des cycles de provisionnement).")
    # chan_hash -> nombre de paquets observés depuis le dernier envoi (voir _sur_log_rx /
    # boucle_signalement_canaux_detectes).
    canaux_detectes_compteur = {}
    # chan_hash -> canal_id : canaux déchiffrés EN LOGICIEL (voir boucle_decodage_logiciel_canaux
    # et le plan de conception "Décodage logiciel des canaux MeshCore", 12/10) -- peuplé dès le
    # premier cycle de cette boucle, pas seulement au démarrage (contrairement à canaux_idx_map
    # ci-dessus, aucun round-trip "une seule fois" ici : canaux_a_provisionner n'exclut rien,
    # donc rien à perdre entre deux redémarrages).
    canaux_virtuels_par_hash = {}
    meshcore.set_decrypt_channel_logs(True)
    enregistrer_ecouteurs(meshcore, django, COMPAGNON_ID, deconnecte, canaux_idx_map, canaux_detectes_compteur, canaux_virtuels_par_hash)
    # Le firmware ne pousse jamais un message reçu de lui-même : il émet juste un événement
    # MESSAGES_WAITING, et CONTACT_MSG_RECV/CHANNEL_MSG_RECV ne sont émis qu'en réponse à une
    # commande explicite get_msg(). Sans cet appel, les écouteurs ci-dessus ne se déclenchent
    # jamais, quel que soit le nombre de messages réellement reçus par le companion.
    await meshcore.start_auto_message_fetching()

    tache_envoi = asyncio.create_task(boucle_envoi(meshcore, django, COMPAGNON_ID))
    tache_commandes = asyncio.create_task(boucle_commandes(meshcore, django, COMPAGNON_ID))
    tache_contacts = asyncio.create_task(boucle_contacts(meshcore, django, COMPAGNON_ID))
    tache_positions = asyncio.create_task(boucle_positions_missions(meshcore, django, COMPAGNON_ID))
    tache_canaux_provisionnement = asyncio.create_task(boucle_provisionnement_canaux(meshcore, django, COMPAGNON_ID, canaux_idx_map))
    tache_decodage_logiciel_canaux = asyncio.create_task(boucle_decodage_logiciel_canaux(meshcore, django, COMPAGNON_ID, canaux_virtuels_par_hash, canaux_idx_map))
    tache_canaux_envoi = asyncio.create_task(boucle_envoi_canaux(meshcore, django))
    tache_canaux_detectes = asyncio.create_task(boucle_signalement_canaux_detectes(django, COMPAGNON_ID, canaux_detectes_compteur))
    tache_nettoyage_canaux = asyncio.create_task(boucle_nettoyage_canaux(meshcore, django, COMPAGNON_ID))
    tache_batterie_compagnon = asyncio.create_task(boucle_batterie_compagnon(meshcore, django, COMPAGNON_ID))
    tache_traceroutes = asyncio.create_task(boucle_traceroutes(meshcore, django, COMPAGNON_ID))
    try:
        await deconnecte.wait()
    finally:
        tache_envoi.cancel()
        tache_commandes.cancel()
        tache_contacts.cancel()
        tache_positions.cancel()
        tache_canaux_provisionnement.cancel()
        tache_decodage_logiciel_canaux.cancel()
        tache_canaux_envoi.cancel()
        tache_canaux_detectes.cancel()
        tache_nettoyage_canaux.cancel()
        tache_batterie_compagnon.cancel()
        tache_traceroutes.cancel()
        try:
            await django.rapporter_etat(COMPAGNON_ID, "DECONNECTE")
        except Exception:
            logger.exception("Échec du rapport d'état DECONNECTE.")


async def main():
    url_locale = await resoudre_url_locale()
    django = DjangoClient(
        DJANGO_API_URL, DJANGO_EMAIL, DJANGO_PASSWORD,
        local_url=url_locale, local_email=LOCAL_BRIDGE_EMAIL, local_password=LOCAL_BRIDGE_PASSWORD,
    )
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
