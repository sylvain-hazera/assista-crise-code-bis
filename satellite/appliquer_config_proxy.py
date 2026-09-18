"""Applique côté satellite, SANS action locale/SSH, un changement de configuration MeshCore
décidé depuis le site central — referme le manque signalé le 2026-09-18 ("comment configurer un
satellite depuis le site central pour lui ajouter un nœud dans son LAN").

Poll périodique de `GET /api/compagnons-meshcore/<MESHCORE_COMPAGNON_ID>/` (authentifié avec le
compte de service du satellite, comme tous les autres scripts de ce dossier) : si
`connexion_type`/`tcp_host`/`tcp_port`/`serie_device` diffèrent de ce que porte déjà `.env`,
réécrit `.env` (atomique) puis force la RECRÉATION de `meshcore-proxy` — `docker compose up -d
--no-deps meshcore-proxy`, PAS `docker restart` : un conteneur déjà démarré a figé son
environnement à sa création, `restart` ne relit jamais de nouvelles variables, seule une
recréation le fait.

Nécessite le socket Docker monté (voir docker-compose.yml, service `appliquer-config-proxy`) —
même compromis de sécurité déjà accepté pour `detecter-noeud` (`--privileged` pour `/dev`) :
donne en pratique un accès root au conteneur hôte. Acceptable pour un service tournant sur le
propre Pi du satellite, jamais exposé au-delà de sa propre machine.

**Non testé sur du vrai matériel à ce jour** — la recréation via `docker compose up -d
--no-deps` est la partie la plus fragile (dépend du plugin compose v2, normalement inclus par
`get.docker.com` utilisé dans `installer.sh`, mais jamais vérifié en conditions réelles)."""
import logging
import os
import subprocess
import time

import requests

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("appliquer_config_proxy")

CENTRAL_URL = os.environ.get("CENTRAL_URL", "https://assista-crise.fr").rstrip("/")
SATELLITE_EMAIL = os.environ.get("SATELLITE_EMAIL", "")
SATELLITE_PASSWORD = os.environ.get("SATELLITE_PASSWORD", "")
MESHCORE_COMPAGNON_ID = os.environ.get("MESHCORE_COMPAGNON_ID", "")
FICHIER_ENV = os.environ.get("FICHIER_ENV", "/satellite/.env")
POLL_INTERVAL_S = int(os.environ.get("CONFIG_POLL_INTERVAL_S", 60))

# Champ renvoyé par l'API -> variable d'environnement lue par meshcore-proxy (voir
# meshcore-bridge/proxy.py et satellite/docker-compose.yml, service meshcore-proxy).
CHAMPS_SURVEILLES = {
    "connexion_type": "MESHCORE_CONNEXION_TYPE",
    "tcp_host": "MESHCORE_TCP_HOST",
    "tcp_port": "MESHCORE_TCP_PORT",
    "serie_device": "MESHCORE_SERIE_DEVICE",
}


def lire_env():
    valeurs = {}
    try:
        with open(FICHIER_ENV, encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne or ligne.startswith("#") or "=" not in ligne:
                    continue
                cle, _, valeur = ligne.partition("=")
                valeurs[cle.strip()] = valeur.strip()
    except FileNotFoundError:
        logger.warning("%s introuvable — aucune configuration existante à comparer.", FICHIER_ENV)
    return valeurs


def ecrire_env(valeurs_completes):
    """Écriture atomique (fichier temporaire puis renommage) — jamais un .env à moitié écrit lu
    par un autre processus pendant que celui-ci le réécrit."""
    fichier_tmp = FICHIER_ENV + ".tmp"
    with open(fichier_tmp, "w", encoding="utf-8") as f:
        for cle, valeur in valeurs_completes.items():
            f.write(f"{cle}={valeur}\n")
    os.replace(fichier_tmp, FICHIER_ENV)


def authentifier():
    reponse = requests.post(
        f"{CENTRAL_URL}/api/token/", json={"email": SATELLITE_EMAIL, "password": SATELLITE_PASSWORD}, timeout=15,
    )
    reponse.raise_for_status()
    return reponse.json()["access"]


def config_attendue(jeton):
    reponse = requests.get(
        f"{CENTRAL_URL}/api/compagnons-meshcore/{MESHCORE_COMPAGNON_ID}/",
        headers={"Authorization": f"Bearer {jeton}"}, timeout=15,
    )
    reponse.raise_for_status()
    return reponse.json()


def config_a_change(config_centrale, env_actuel):
    for champ_api, cle_env in CHAMPS_SURVEILLES.items():
        valeur_centrale = config_centrale.get(champ_api)
        valeur_centrale = "" if valeur_centrale is None else str(valeur_centrale)
        if valeur_centrale and valeur_centrale != env_actuel.get(cle_env, ""):
            return True
    return False


def recreer_proxy():
    logger.info("Configuration changée côté central — recréation de meshcore-proxy...")
    resultat = subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", "meshcore-proxy"],
        cwd=os.path.dirname(os.path.abspath(FICHIER_ENV)) or ".", capture_output=True, text=True,
    )
    if resultat.returncode != 0:
        logger.error("Échec de la recréation de meshcore-proxy : %s", resultat.stderr)
    else:
        logger.info("meshcore-proxy recréé avec la nouvelle configuration.")


def verifier_une_fois():
    if not all([SATELLITE_EMAIL, SATELLITE_PASSWORD, MESHCORE_COMPAGNON_ID]):
        logger.warning(
            "SATELLITE_EMAIL/SATELLITE_PASSWORD/MESHCORE_COMPAGNON_ID non configurés — inactif "
            "(comportement historique, ce satellite n'a pas encore de companion déclaré)."
        )
        return
    try:
        jeton = authentifier()
        config_centrale = config_attendue(jeton)
    except requests.RequestException as exc:
        logger.warning("Central injoignable (%s) — retenté au prochain passage.", exc)
        return

    env_actuel = lire_env()
    if not config_a_change(config_centrale, env_actuel):
        return

    nouvel_env = dict(env_actuel)
    for champ_api, cle_env in CHAMPS_SURVEILLES.items():
        valeur = config_centrale.get(champ_api)
        if valeur is not None:
            nouvel_env[cle_env] = str(valeur)
    ecrire_env(nouvel_env)
    recreer_proxy()


def boucle():
    while True:
        verifier_une_fois()
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    boucle()
