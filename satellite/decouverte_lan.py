"""Découverte des nœuds MeshCore/Meshtastic sur le réseau local d'un satellite, à
l'installation — voir le cadrage "Chantier B" (plan) et sa note du 2026-09-17. Combine deux
méthodes complémentaires, ni l'une ni l'autre fiable seule :
  - mDNS (zeroconf) : un vrai nœud MeshCore/Meshtastic peut s'annoncer sur le réseau — le nom
    de service exact dépend du firmware, PAS confirmé sur du vrai matériel à ce stade (voir
    SERVICE_TYPES_MDNS ci-dessous, à ajuster une fois testé en conditions réelles). En
    revanche, `_meshcore._tcp.local.` EST déjà garanti trouvable pour un ac_meshcore_proxy
    (meshcore-bridge/proxy.py, qui s'annonce désormais lui-même sous ce type de service,
    `properties={"role": "proxy", ...}` pour le distinguer d'un vrai nœud) — pas de
    handshake protocolaire nécessaire pour reconnaître CE cas précis.
  - Scan TCP du port 5000 (port MeshCore par défaut) sur le sous-réseau local : protocole-
    agnostique, plus lent mais ne dépend d'aucune annonce.

Handshake protocolaire de confirmation disponible (voir confirmer_protocole_tcp,
decouvrir_noeuds_lan(confirmer=True)) — désactivé par défaut dans decouvrir_noeuds_lan (coûte
plusieurs secondes réelles par candidat), mais utilisé par défaut par le CLI (__main__) où
l'attente est acceptable. Réutilise la même logique que MeshLocalDetecterView côté Django
(backend/core/views.py : _detecter_meshcore_local/_detecter_meshtastic_local, déjà validées en
conditions réelles), réécrite ici (pas un import direct : ce module tourne côté satellite,
hors du process Django)."""
import asyncio
import ipaddress
import logging
import socket
import time

logger = logging.getLogger(__name__)

PORT_MESHCORE_DEFAUT = 5000

# Noms de service mDNS plausibles pour un nœud MeshCore/Meshtastic en mode TCP — à confirmer
# sur du vrai matériel, aucune garantie qu'un firmware donné les annonce tel quel.
SERVICE_TYPES_MDNS = ["_meshcore._tcp.local.", "_meshtastic._tcp.local."]


def reseau_local_cidr():
    """Devine le CIDR /24 du réseau local à partir de l'IP locale par défaut (connexion UDP
    factice, aucun paquet réellement envoyé). Suffisant pour un sous-réseau domestique/
    associatif typique ; None si l'interface réseau n'est pas résolvable (pas de lien actif)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip_locale = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return str(ipaddress.ip_network(f"{ip_locale}/24", strict=False))


async def _tester_hote(ip, port, timeout):
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return ip


async def scanner_port_tcp(cidr=None, port=PORT_MESHCORE_DEFAUT, timeout=0.5, concurrence=64):
    """Scan TCP connect (pas de paquet brut, fonctionne sans privilèges élevés) de toutes les
    IP d'un `cidr` sur `port` — renvoie les IP qui répondent, triées. `concurrence` borne le
    nombre de connexions simultanées pour ne pas saturer une interface WiFi modeste (Pi Zero
    2 W). `cidr` par défaut : reseau_local_cidr()."""
    cidr = cidr or reseau_local_cidr()
    if not cidr:
        return []
    reseau = ipaddress.ip_network(cidr, strict=False)
    semaphore = asyncio.Semaphore(concurrence)

    async def _borne(ip):
        async with semaphore:
            return await _tester_hote(str(ip), port, timeout)

    hotes = list(reseau.hosts()) or [reseau.network_address]
    resultats = await asyncio.gather(*[_borne(ip) for ip in hotes])
    return sorted({ip for ip in resultats if ip})


def decouvrir_mdns(duree_s=5.0):
    """Navigue les types de service mDNS plausibles (SERVICE_TYPES_MDNS) pendant `duree_s`
    secondes — renvoie une liste de {"nom", "ip", "port"}. Dépendance zeroconf optionnelle :
    renvoie une liste vide (avec un avertissement) si elle n'est pas installée — scanner_port_tcp
    fonctionne indépendamment."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        logger.warning("zeroconf non installé — découverte mDNS indisponible, scan de port seul.")
        return []

    trouves = []

    class _Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                # properties : {b"role": b"proxy", ...} pour un ac_meshcore_proxy (voir
                # meshcore-bridge/proxy.py) — absent ou différent pour un vrai nœud, dont le
                # firmware ne connaît rien de cette convention propre à assista-crise.
                proprietes = {
                    k.decode(errors="replace"): v.decode(errors="replace") if isinstance(v, bytes) else v
                    for k, v in (info.properties or {}).items()
                }
                trouves.append({
                    "nom": name, "ip": socket.inet_ntoa(info.addresses[0]), "port": info.port,
                    "role": proprietes.get("role"),
                })

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    try:
        _browsers = [ServiceBrowser(zc, service_type, _Listener()) for service_type in SERVICE_TYPES_MDNS]
        time.sleep(duree_s)
    finally:
        zc.close()
    return trouves


async def decouvrir_noeuds_lan(cidr=None, duree_mdns_s=5.0, confirmer=False, delai_confirmation=6):
    """Combine mDNS + scan de port, dédoublonné par IP — un candidat trouvé par les deux
    méthodes n'apparaît qu'une fois, avec `source` valant "mdns", "scan" ou "mdns+scan".

    `confirmer=True` ajoute un vrai handshake protocolaire (voir confirmer_protocole_tcp) sur
    chaque candidat dont le protocole n'est pas déjà connu (un ac_meshcore_proxy, `role=proxy`,
    est déjà certain — pas la peine de le re-confirmer) : peuple `protocole` ("meshcore"/
    "meshtastic"/None) au lieu de laisser "quelque chose écoute sur ce port" sans réponse.
    Coûte du temps réel (`delai_confirmation` secondes par candidat par protocole essayé) —
    désactivé par défaut, à activer explicitement une fois la liste de candidats déjà réduite."""
    loop = asyncio.get_running_loop()
    mdns_task = loop.run_in_executor(None, decouvrir_mdns, duree_mdns_s)
    scan_task = scanner_port_tcp(cidr)
    mdns_resultats, scan_resultats = await asyncio.gather(mdns_task, scan_task)

    par_ip = {}
    for entree in mdns_resultats:
        par_ip[entree["ip"]] = {
            "ip": entree["ip"], "port": entree["port"], "nom_mdns": entree["nom"], "source": "mdns",
            "role": entree.get("role"),
        }
    for ip in scan_resultats:
        if ip in par_ip:
            par_ip[ip]["source"] = "mdns+scan"
        else:
            par_ip[ip] = {"ip": ip, "port": PORT_MESHCORE_DEFAUT, "nom_mdns": None, "source": "scan", "role": None}

    resultats = sorted(par_ip.values(), key=lambda e: e["ip"])
    if confirmer:
        for candidat in resultats:
            if candidat.get("role") == "proxy":
                candidat["protocole"] = "meshcore"  # déjà certain, voir docstring
                continue
            identite = await confirmer_protocole_tcp(candidat["ip"], candidat["port"], delai=delai_confirmation)
            candidat["protocole"] = identite["protocole"] if identite else None
            if identite:
                candidat.update({k: v for k, v in identite.items() if k != "protocole"})
    return resultats


async def confirmer_protocole_tcp(ip, port, delai=6):
    """Handshake réel pour savoir si `ip:port` parle MeshCore ou Meshtastic — même technique
    que MeshLocalDetecterView côté Django (backend/core/views.py :
    _detecter_meshcore_local/_detecter_meshtastic_local, déjà validées en conditions réelles),
    réécrite ici car ce module tourne côté satellite, hors du process Django. MeshCore d'abord
    (async natif, plus rapide à écarter), Meshtastic ensuite (thread bloquant, la lib peut
    attendre longtemps si l'appareil en face ne parle pas ce protocole)."""
    meshcore_info = await _confirmer_meshcore_tcp(ip, port, delai)
    if meshcore_info:
        return {"protocole": "meshcore", **meshcore_info}
    meshtastic_info = await loop_run_in_executor(_confirmer_meshtastic_tcp, ip, port, delai)
    if meshtastic_info:
        return {"protocole": "meshtastic", **meshtastic_info}
    return None


async def loop_run_in_executor(fonction, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fonction, *args)


async def _confirmer_meshcore_tcp(ip, port, delai):
    try:
        from meshcore import MeshCore, EventType
    except ImportError:
        logger.warning("Lib meshcore non installée — confirmation MeshCore impossible.")
        return None

    async def _essai():
        mc = await MeshCore.create_tcp(ip, port, default_timeout=delai)
        try:
            resultat = await mc.commands.send_appstart()
            if resultat and resultat.type == EventType.SELF_INFO:
                payload = resultat.payload or {}
                pubkey = payload.get("public_key") or payload.get("pubkey")
                if pubkey:
                    return {"pubkey_hex": pubkey}
        finally:
            await mc.disconnect()
        return None

    try:
        return await asyncio.wait_for(_essai(), timeout=delai + 2)
    except Exception:
        return None


def _confirmer_meshtastic_tcp(ip, port, delai):
    """Synchrone à dessein (la lib `meshtastic` bloque) — appelé via loop_run_in_executor pour
    ne pas geler la boucle asyncio pendant potentiellement plusieurs secondes."""
    try:
        from meshtastic.tcp_interface import TCPInterface
    except ImportError:
        logger.warning("Lib meshtastic non installée — confirmation Meshtastic impossible.")
        return None

    resultat = {}
    try:
        iface = TCPInterface(hostname=ip, portNumber=port, timeout=delai)
        try:
            info = iface.myInfo
            if info is not None and getattr(info, "my_node_num", None):
                resultat["node_num"] = info.my_node_num
        finally:
            iface.close()
    except Exception:
        pass
    return resultat if resultat.get("node_num") else None


if __name__ == "__main__":
    resultats = asyncio.run(decouvrir_noeuds_lan(confirmer=True))
    if not resultats:
        print("Aucun candidat trouvé sur le réseau local.")
    for candidat in resultats:
        etiquette = f" ({candidat['nom_mdns']})" if candidat["nom_mdns"] else ""
        protocole = candidat.get("protocole") or "non identifié"
        print(f"{candidat['ip']}:{candidat['port']}{etiquette} — {candidat['source']} — {protocole}")
