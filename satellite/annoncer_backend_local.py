"""Annonce mDNS de l'assista-crise LOCAL (profil Full) sur le LAN — permet à un satellite GW
SÉPARÉ, sur le même site (voir le modèle à 2 Pi du cadrage "Chantier B"), de trouver ce backend
sans IP configurée à la main. Même technique que meshcore-bridge/proxy.py (ServiceInfo +
AsyncZeroconf) — voir sa docstring pour le détail déjà validé en conditions réelles sur .113.

Ne fait qu'annoncer : le backend Django lui-même tourne dans un autre conteneur (`backend`,
voir docker-compose.yml) et écoute déjà sur son port — ce script n'a aucune donnée à faire
transiter, contrairement à un vrai proxy.

23/11/2026 — **le site local, pour les téléphones et PC du site** : « les satellites
s'annoncent en mDNS, et l'application, si elle ne joint pas le central, bascule sur le
satellite ». Deux ajouts :
- le **site** (port web, 80 par défaut) est annoncé en `_http._tcp` sous le nom d'hôte
  générique `assista-crise.local` (en plus de `<nom>.local`) : un téléphone tape ou reçoit
  `http://assista-crise.local/` sans connaître l'IP ;
- les **adresses locales** sont écrites dans le volume d'état partagé
  (`adresses_locales.json`) : le signal de vie (`etat_connectivite.py`) les transmet au
  central, qui les donne à la PWA et à l'application pour proposer le satellite quand le
  central ne répond plus. L'adresse est relue à chaque tour : un bail DHCP qui change est
  réannoncé."""
import asyncio
import logging
import os
import socket

try:
    from zeroconf import ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf
except ImportError:
    ServiceInfo = None
    AsyncZeroconf = None

logger = logging.getLogger("annoncer-backend-local")

# Le label de service mDNS (avant "._tcp.local.") est limité à 15 octets (RFC 6763) —
# "_assista-crise-local" (20) dépasse, d'où "_ac-local" ; découvert en le testant pour de vrai
# le 2026-09-17 (zeroconf lève BadTypeInNameException, pas une erreur silencieuse).
SERVICE_TYPE = "_ac-local._tcp.local."
NOM_INSTANCE = os.environ.get("SATELLITE_NOM", socket.gethostname())
PORT_BACKEND = int(os.environ.get("BACKEND_PORT", "8010"))
PORT_WEB = int(os.environ.get("WEB_PORT", "80"))
NOM_HOTE_GENERIQUE = os.environ.get("NOM_HOTE_GENERIQUE", "assista-crise")
TYPE_SITE = "_http._tcp.local."
FICHIER_ADRESSES = os.environ.get("FICHIER_ADRESSES_LOCALES", "/var/run/satellite/adresses_locales.json")
INTERVALLE_VERIFICATION_SECONDES = int(os.environ.get("INTERVALLE_VERIFICATION_SECONDES", "60"))


def _ip_locale_annoncable():
    """Même technique que meshcore-bridge/proxy.py:_ip_locale_annoncable — connexion UDP
    factice, aucun paquet réellement envoyé."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def services(ip):
    """Les deux annonces : le backend (pour un satellite GW voisin) et le site (pour les
    téléphones), ce dernier sous le nom générique `assista-crise.local`."""
    adresse = [socket.inet_aton(ip)]
    backend = ServiceInfo(
        SERVICE_TYPE, f"{NOM_INSTANCE}.{SERVICE_TYPE}", addresses=adresse, port=PORT_BACKEND,
        server=f"{NOM_INSTANCE}.local.", properties={"role": "backend-local", "web_port": str(PORT_WEB)},
    )
    site = ServiceInfo(
        TYPE_SITE, f"Assista-Crise {NOM_INSTANCE}.{TYPE_SITE}", addresses=adresse, port=PORT_WEB,
        server=f"{NOM_HOTE_GENERIQUE}.local.", properties={"role": "site-local", "path": "/", "nom": NOM_INSTANCE},
    )
    return [backend, site]


def ecrire_adresses(ip, fichier=FICHIER_ADRESSES):
    """Pour le signal de vie au central. Jamais d'exception : sans volume, on annonce quand même."""
    import json
    contenu = {"ips": [ip], "port_web": PORT_WEB, "noms": [f"{NOM_HOTE_GENERIQUE}.local", f"{NOM_INSTANCE}.local"]}
    try:
        os.makedirs(os.path.dirname(fichier), exist_ok=True)
        with open(fichier + ".tmp", "w", encoding="utf-8") as f:
            json.dump(contenu, f)
        os.replace(fichier + ".tmp", fichier)
    except OSError as exc:
        logger.warning("Adresses locales non écrites (%s) : %s", fichier, exc)
    return contenu


async def annoncer():
    if AsyncZeroconf is None:
        logger.warning("zeroconf non installé — annonce mDNS désactivée, le backend local reste joignable en IP manuelle uniquement.")
        while True:
            await asyncio.sleep(3600)

    zc = AsyncZeroconf()
    annonces, ip_annoncee = [], None
    try:
        while True:
            ip = _ip_locale_annoncable()
            if ip is None:
                logger.warning("Impossible de déterminer une IP locale à annoncer.")
            elif ip != ip_annoncee:
                for info in annonces:
                    await zc.async_unregister_service(info)
                annonces = services(ip)
                for info in annonces:
                    await zc.async_register_service(info)
                ip_annoncee = ip
                ecrire_adresses(ip)
                logger.info("Annoncé en mDNS : %s.local et %s.local (%s, site :%s, backend :%s)",
                            NOM_INSTANCE, NOM_HOTE_GENERIQUE, ip, PORT_WEB, PORT_BACKEND)
            await asyncio.sleep(INTERVALLE_VERIFICATION_SECONDES)
    finally:
        for info in annonces:
            await zc.async_unregister_service(info)
        await zc.async_close()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(annoncer())
