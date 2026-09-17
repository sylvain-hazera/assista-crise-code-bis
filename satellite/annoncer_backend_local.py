"""Annonce mDNS de l'assista-crise LOCAL (profil Full) sur le LAN — permet à un satellite GW
SÉPARÉ, sur le même site (voir le modèle à 2 Pi du cadrage "Chantier B"), de trouver ce backend
sans IP configurée à la main. Même technique que meshcore-bridge/proxy.py (ServiceInfo +
AsyncZeroconf) — voir sa docstring pour le détail déjà validé en conditions réelles sur .113.

Ne fait qu'annoncer : le backend Django lui-même tourne dans un autre conteneur (`backend`,
voir docker-compose.yml) et écoute déjà sur son port — ce script n'a aucune donnée à faire
transiter, contrairement à un vrai proxy."""
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
PORT_BACKEND = int(os.environ.get("BACKEND_PORT", "8000"))
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


async def annoncer():
    if AsyncZeroconf is None:
        logger.warning("zeroconf non installé — annonce mDNS désactivée, le backend local reste joignable en IP manuelle uniquement.")
        while True:
            await asyncio.sleep(3600)

    ip = _ip_locale_annoncable()
    if ip is None:
        logger.warning("Impossible de déterminer une IP locale à annoncer.")
        while True:
            await asyncio.sleep(3600)

    nom_service = f"{NOM_INSTANCE}.{SERVICE_TYPE}"
    info = ServiceInfo(
        SERVICE_TYPE, nom_service,
        addresses=[socket.inet_aton(ip)], port=PORT_BACKEND,
        server=f"{NOM_INSTANCE}.local.",
        properties={"role": "backend-local"},
    )
    zc = AsyncZeroconf()
    await zc.async_register_service(info)
    logger.info("Annoncé en mDNS : %s (%s:%s)", nom_service, ip, PORT_BACKEND)
    try:
        while True:
            await asyncio.sleep(INTERVALLE_VERIFICATION_SECONDES)
    finally:
        await zc.async_unregister_service(info)
        await zc.async_close()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(annoncer())
