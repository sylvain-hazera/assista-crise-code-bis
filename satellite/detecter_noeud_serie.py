"""Détection et différenciation des nœuds MeshCore/Meshtastic branchés en USB sur un satellite,
à l'installation — voir le cadrage "Chantier B" et la précision du 2026-09-17 : chaque nœud a
un identifiant unique (clé publique MeshCore, node_num Meshtastic assigné par le firmware), qui
sert de clé d'idempotence pour l'auto-enregistrement côté central (voir
CompagnonMeshCoreViewSet.enregistrer_depuis_satellite / CompagnonMeshtasticViewSet.<idem>).

Une fois un device confirmé, la configuration (device, protocole, id central) est PERSISTÉE
dans un fichier local et réutilisée telle quelle tant que le device répond — pas de re-sondage
à chaque démarrage, seulement si la connexion échoue (voir main()).

Sondage : réutilise exactement les mêmes techniques que MeshLocalDetecterView côté Django
(backend/core/views.py, _detecter_meshcore_local/_detecter_meshtastic_local), déjà vérifiées en
conditions réelles pour le cas TCP — seule la construction de la connexion diffère (série au
lieu de TCP)."""
import asyncio
import glob
import json
import logging
import os
import threading

logger = logging.getLogger("detecter-noeud-serie")

FICHIER_ETAT = os.environ.get("FICHIER_ETAT_NOEUD_SERIE", "/var/run/satellite/noeud_serie.json")
MOTIFS_DEVICES = ["/dev/ttyUSB*", "/dev/ttyACM*"]
# Noms stables créés par udev : by-id (modèle + numéro de série de la radio), à défaut by-path
# (port USB physique). /dev/ttyACM0 et /dev/ttyACM1 sont attribués dans l'ordre d'apparition et
# s'inversent d'un démarrage à l'autre quand deux radios sont branchées (constaté sur le
# satellite de la Loire, 22/10/2026) : chaque bridge ouvrait alors la radio de l'autre protocole.
DOSSIERS_CHEMINS_STABLES = ["/dev/serial/by-id", "/dev/serial/by-path"]
TIMEOUT_SONDAGE_SECONDES = float(os.environ.get("TIMEOUT_SONDAGE_SECONDES", "5"))
INTERVALLE_DETECTION_SECONDES = int(os.environ.get("INTERVALLE_DETECTION_SECONDES", "30"))


def lister_devices_candidats():
    devices = []
    for motif in MOTIFS_DEVICES:
        devices.extend(glob.glob(motif))
    return sorted(devices)


def chemin_stable(device):
    """Nom stable (voir DOSSIERS_CHEMINS_STABLES) du port série `device`, ou `device` lui-même
    s'il n'en a pas. C'est ce nom qui part dans .env et au central : Docker le résout vers le bon
    /dev/ttyACMx à chaque démarrage du conteneur."""
    reel = os.path.realpath(device)
    for dossier in DOSSIERS_CHEMINS_STABLES:
        for lien in sorted(glob.glob(os.path.join(dossier, "*"))):
            if os.path.realpath(lien) == reel:
                return lien
    return device


def lire_config_persistee(fichier=None):
    fichier = fichier or FICHIER_ETAT
    if not os.path.exists(fichier):
        return None
    with open(fichier, encoding="utf-8") as f:
        return json.load(f)


def ecrire_config_persistee(config, fichier=None):
    fichier = fichier or FICHIER_ETAT
    os.makedirs(os.path.dirname(fichier), exist_ok=True)
    tmp = fichier + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f)
    os.replace(tmp, fichier)


async def sonder_meshcore(device, timeout=None, baudrate=115200):
    """Renvoie {"pubkey_hex": ...} si `device` répond en MeshCore dans le délai, None sinon —
    même séquence que _detecter_meshcore_local (send_appstart -> EventType.SELF_INFO)."""
    timeout = timeout or TIMEOUT_SONDAGE_SECONDES
    from meshcore import MeshCore, EventType

    async def _essai():
        mc = await MeshCore.create_serial(device, baudrate, default_timeout=timeout)
        try:
            resultat = await mc.commands.send_appstart()
            if resultat and resultat.type == EventType.SELF_INFO:
                payload = resultat.payload or {}
                pubkey = payload.get('public_key') or payload.get('pubkey')
                if pubkey:
                    return {"pubkey_hex": pubkey}
        finally:
            await mc.disconnect()
        return None

    try:
        return await asyncio.wait_for(_essai(), timeout=timeout + 2)
    except Exception:
        return None


def sonder_meshtastic(device, timeout=None):
    """Renvoie {"node_num": ...} si `device` répond en Meshtastic dans le délai, None sinon —
    même séquence que _detecter_meshtastic_local (thread + join, la lib officielle bloque
    potentiellement très longtemps si l'appareil en face ne parle pas ce protocole)."""
    timeout = timeout or TIMEOUT_SONDAGE_SECONDES
    from meshtastic.serial_interface import SerialInterface

    resultat = {}

    def _essai():
        iface = None
        try:
            iface = SerialInterface(devPath=device)
            info = iface.myInfo
            if info is not None and getattr(info, 'my_node_num', None):
                resultat["node_num"] = info.my_node_num
        except Exception:
            pass
        finally:
            if iface is not None:
                try:
                    iface.close()
                except Exception:
                    pass

    thread = threading.Thread(target=_essai, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    return resultat if resultat.get("node_num") else None


async def identifier_device(device):
    """MeshCore d'abord (rapide à écarter, async natif), Meshtastic ensuite (thread bloquant,
    plus lent) — renvoie {"protocole": "meshcore"|"meshtastic", ...identité...} ou None si rien
    ne répond sur ce device."""
    meshcore_info = await sonder_meshcore(device)
    if meshcore_info:
        return {"protocole": "meshcore", **meshcore_info}
    meshtastic_info = await asyncio.get_running_loop().run_in_executor(None, sonder_meshtastic, device)
    if meshtastic_info:
        return {"protocole": "meshtastic", **meshtastic_info}
    return None


async def decouvrir_et_identifier():
    """Sonde tous les devices candidats, renvoie la première identification réussie (un
    satellite n'a normalement qu'un seul nœud branché à la fois) ou None."""
    for device in lister_devices_candidats():
        identite = await identifier_device(device)
        if identite:
            return {"device": chemin_stable(device), **identite}
    return None


async def config_verifiee_ou_redecouverte(fichier_etat=None):
    """Cœur de "garder la config tant qu'elle marche" : si une config persistée existe, revérifie
    juste que SON device répond encore au protocole attendu (rapide) avant de la réutiliser —
    ne relance un sondage complet de tous les devices que si elle a disparu ou ne répond plus."""
    config = lire_config_persistee(fichier_etat)
    if config:
        sondeur = sonder_meshcore if config["protocole"] == "meshcore" else None
        if sondeur:
            reponse = await sondeur(config["device"])
        else:
            reponse = await asyncio.get_running_loop().run_in_executor(None, sonder_meshtastic, config["device"])
        if reponse:
            logger.info("Config persistée toujours valide : %s (%s).", config["device"], config["protocole"])
            stable = chemin_stable(config["device"])
            if stable != config["device"]:
                config["device"] = stable
                ecrire_config_persistee(config, fichier_etat)
            return config
        logger.warning("Le device persisté %s ne répond plus (%s attendu) — nouvelle découverte.", config["device"], config["protocole"])

    nouvelle = await decouvrir_et_identifier()
    if nouvelle:
        ecrire_config_persistee(nouvelle, fichier_etat)
        logger.info("Nouveau nœud identifié : %s (%s).", nouvelle["device"], nouvelle["protocole"])
    else:
        logger.warning("Aucun nœud MeshCore/Meshtastic détecté sur les devices candidats : %s", lister_devices_candidats())
    return nouvelle


async def enregistrer_aupres_du_central(identite, central_url, email, password, client=None):
    """Appelle l'action d'auto-enregistrement idempotente correspondant au protocole détecté
    (voir CompagnonMeshCoreViewSet.enregistrer_depuis_satellite / CompagnonMeshtasticViewSet.
    <idem>) — authentifié avec le compte de service du satellite (JWT, même flux que
    meshcore-bridge/bridge.py:DjangoClient). Renvoie l'UUID du companion central, réutilisé tel
    quel aux appels suivants (idempotent côté serveur par pubkey_hex/node_num). `client`
    injectable pour les tests (httpx.MockTransport, aucun vrai réseau)."""
    import httpx

    central_url = central_url.rstrip("/")
    ferme_client = client is None
    client = client or httpx.AsyncClient()
    try:
        token_resp = await client.post(f"{central_url}/token/", json={"email": email, "password": password})
        token_resp.raise_for_status()
        headers = {"Authorization": f"Bearer {token_resp.json()['access']}"}

        if identite["protocole"] == "meshcore":
            url = f"{central_url}/compagnons-meshcore/enregistrer-depuis-satellite/"
            payload = {"pubkey_hex": identite["pubkey_hex"], "connexion_type": "SERIE", "serie_device": identite["device"]}
        else:
            url = f"{central_url}/compagnons-meshtastic/enregistrer-depuis-satellite/"
            payload = {"node_num": identite["node_num"], "connexion_type": "SERIE", "serie_device": identite["device"]}

        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["id"]
    finally:
        if ferme_client:
            await client.aclose()


async def decouvrir_identifier_et_enregistrer(central_url, email, password, fichier_etat=None, client=None):
    """Enchaîne la détection/persistance locale (config_verifiee_ou_redecouverte) et
    l'auto-enregistrement central — best-effort sur la partie centrale : si le central est
    injoignable, la détection locale reste valable et utilisable (voir la bascule vers le local
    prévue côté bridge.py), seul compagnon_id manquera tant que le central n'est pas revenu."""
    identite = await config_verifiee_ou_redecouverte(fichier_etat)
    if identite is None:
        return None
    if identite.get("compagnon_id"):
        return identite
    try:
        compagnon_id = await enregistrer_aupres_du_central(identite, central_url, email, password, client=client)
    except Exception:
        logger.exception("Nœud détecté (%s) mais central injoignable — pas encore enregistré.", identite["device"])
        return identite
    identite["compagnon_id"] = compagnon_id
    ecrire_config_persistee(identite, fichier_etat)
    logger.info("Companion central : %s", compagnon_id)
    return identite


async def detecter_et_enregistrer_toutes(central_url=None, email=None, password=None, client=None):
    """Toutes les radios branchées (MeshCore ET Meshtastic, contrairement à
    decouvrir_et_identifier qui s'arrête à la première) -- utilisé par `installer.sh installer`
    pour configurer chaque radio sans question (20/10/2026). Chacune est enregistrée au central
    si possible (best-effort, comme decouvrir_identifier_et_enregistrer)."""
    radios = []
    for device in lister_devices_candidats():
        identite = await identifier_device(device)
        if not identite:
            continue
        identite = {"device": chemin_stable(device), **identite}
        if central_url and email and password:
            try:
                identite["compagnon_id"] = await enregistrer_aupres_du_central(identite, central_url, email, password, client=client)
            except Exception:
                logger.exception("Radio détectée (%s) mais central injoignable — pas encore enregistrée.", device)
        radios.append(identite)
    return radios


async def boucle(central_url=None, email=None, password=None, fichier_etat=None, client=None, une_seule_iteration=False):
    """Surveillance continue (service "surveiller-noeuds", profils gw/full) : ré-exécute le
    même enchaînement que l'exécution ponctuelle (profil "outillage", conservée telle quelle
    pour un sondage manuel à la demande) à intervalle régulier — AUCUNE action humaine requise
    après le branchement d'un nouveau nœud. La découverte reste bon marché quand une config
    est déjà persistée (config_verifiee_ou_redecouverte ne re-sonde TOUS les devices candidats
    que si le device persisté a disparu/ne répond plus, voir sa docstring) : cette boucle ne
    fait donc pas un sondage complet à chaque itération dans le cas courant."""
    while True:
        if central_url and email and password:
            resultat = await decouvrir_identifier_et_enregistrer(
                central_url, email, password, fichier_etat=fichier_etat, client=client,
            )
        else:
            resultat = await config_verifiee_ou_redecouverte(fichier_etat)
        if une_seule_iteration:
            return resultat
        await asyncio.sleep(INTERVALLE_DETECTION_SECONDES)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    central_url = os.environ.get("CENTRAL_URL")
    email = os.environ.get("SATELLITE_EMAIL")
    password = os.environ.get("SATELLITE_PASSWORD")
    central_api = f"{central_url}/api" if central_url else None
    if not (central_api and email and password):
        logger.warning("CENTRAL_URL/SATELLITE_EMAIL/SATELLITE_PASSWORD absents — détection locale seule, pas d'enregistrement.")

    if os.environ.get("DETECTION_TOUTES", "false").lower() == "true":
        # Installation automatique : liste JSON de toutes les radios, une ligne.
        print(json.dumps(asyncio.run(detecter_et_enregistrer_toutes(central_api, email, password))))
    elif os.environ.get("DETECTION_CONTINUE", "false").lower() == "true":
        # Service continu (surveiller-noeuds) : ne s'arrête jamais, pas de sortie JSON unique à
        # produire — voir boucle() pour le détail de ce qui est journalisé à chaque passage.
        asyncio.run(boucle(central_api, email, password))
    else:
        # Comportement historique, un seul passage (profil "outillage", sondage manuel ponctuel).
        if central_api and email and password:
            resultat = asyncio.run(decouvrir_identifier_et_enregistrer(central_api, email, password))
        else:
            resultat = asyncio.run(config_verifiee_ou_redecouverte())
        print(json.dumps(resultat) if resultat else "null")
