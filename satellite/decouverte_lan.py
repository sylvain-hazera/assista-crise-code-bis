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

Ne fait PAS le handshake protocolaire de confirmation (MeshCore vs Meshtastic vs rien du
tout) — seulement une liste de candidats "quelque chose écoute ici". La confirmation
réutilise la même logique que MeshLocalDetecterView côté Django (backend/core/views.py :
_detecter_meshcore_local/_detecter_meshtastic_local), pas dupliquée ici."""
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


async def decouvrir_noeuds_lan(cidr=None, duree_mdns_s=5.0):
    """Combine mDNS + scan de port, dédoublonné par IP — un candidat trouvé par les deux
    méthodes n'apparaît qu'une fois, avec `source` valant "mdns", "scan" ou "mdns+scan"."""
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
    return sorted(par_ip.values(), key=lambda e: e["ip"])


if __name__ == "__main__":
    resultats = asyncio.run(decouvrir_noeuds_lan())
    if not resultats:
        print("Aucun candidat trouvé sur le réseau local.")
    for candidat in resultats:
        etiquette = f" ({candidat['nom_mdns']})" if candidat["nom_mdns"] else ""
        print(f"{candidat['ip']}:{candidat['port']}{etiquette} — {candidat['source']}")
