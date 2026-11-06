"""Administration à distance de nœuds Meshtastic (portnum ADMIN_APP).

Ce module exécute les `TacheAdminMeshtastic` mises en file par Django. Il ne tourne que sur un
companion relié à un VRAI appareil (TCP ou série) : c'est le firmware de cet appareil qui chiffre
et signe le message d'administration, exactement comme le fait l'application officielle. Le mode
MQTT ne peut pas administrer -- voir `executer()` pour la raison, qui n'est pas une paresse
d'implémentation.

Ce qui gouverne tout, lu dans le firmware (`AdminModule::handleReceivedProtobuf`, le 06/11/2026 ;
la documentation ne le dit pas) :

1. Un message d'administration venant d'un autre nœud n'est accepté que s'il est
   `pki_encrypted` ET que la clé publique de l'émetteur figure dans l'une des TROIS fentes
   `config.security.admin_key` du nœud cible (comparaison sur 32 octets). Sinon le nœud répond
   `ADMIN_PUBLIC_KEY_UNAUTHORIZED`.
2. Il existe une voie historique : un canal nommé « admin » avec `admin_channel_enabled`, SANS
   aucune vérification de clé. **On ne l'utilise jamais** : elle donne l'administration de tous
   les nœuds à quiconque possède la PSK de ce canal, qui est partagée par construction. D'où
   `channelIndex=0` forcé ici, au lieu du `localNode._getAdminChannelIndex()` que la lib
   officielle utilise -- lui basculerait sur cette voie faible dès qu'un canal « admin » existe
   sur la passerelle.
3. Les LECTURES (`get_*_request`) sont dispensées de clé de session ; les ÉCRITURES l'exigent
   (`checkPassKey`). La clé est un jeton de 8 octets qu'un nœud glisse dans toute réponse de
   lecture, valable 300 s, et **regénéré dès qu'une réponse est construite plus de 150 s après
   la précédente**. Une écriture doit donc suivre de près la lecture qui a fourni la clé, et un
   `ADMIN_BAD_SESSION_KEY` n'est pas une erreur définitive : c'est une clé périmée, on en
   redemande une (voir `_ecrire`).

Un détail à ne pas rater : la clé qu'il faut autoriser sur les nœuds cibles est celle de
l'APPAREIL passerelle (`iface.getPublicKey()`), pas l'identité logicielle X25519 du companion
Django -- c'est l'appareil qui émet sur la radio, et c'est sa clé que le nœud cible compare.
"""
import logging
import threading

from meshtastic.protobuf import admin_pb2, config_pb2, mesh_pb2, portnums_pb2

logger = logging.getLogger(__name__)

# Une lecture traverse le mesh et attend que le nœud cible veuille bien parler. Large à dessein :
# plusieurs sauts, un relais occupé, et le firmware réessaie lui-même (want_ack).
TIMEOUT_REPONSE_S = 90

# Même bornes que côté Django (core/models.py:PUISSANCE_MAX_DBM) : 27 dBm est le plafond de la
# bande 869,4-869,65 MHz du preset EU_868. Revérifié ici parce qu'un pont peut servir une base
# plus ancienne que lui.
PUISSANCE_MIN_DBM = 1
PUISSANCE_MAX_DBM = 27

LECTURES = {"LIRE_METADATA", "LIRE_CONFIG_LORA", "LIRE_CONFIG_APPAREIL", "LIRE_PROPRIETAIRE"}
ECRITURES = {"DEFINIR_PUISSANCE", "REDEMARRER"}


class ErreurAdmin(Exception):
    """Échec d'une opération d'administration, avec un message destiné à l'exploitant."""


# Motifs d'erreur du routage Meshtastic, traduits en quelque chose d'actionnable. Le message
# compte : « ADMIN_PUBLIC_KEY_UNAUTHORIZED » ne dit pas à l'exploitant quoi faire, et c'est
# pourtant l'erreur qu'il rencontrera le plus souvent au premier essai.
MESSAGES_ROUTAGE = {
    "ADMIN_PUBLIC_KEY_UNAUTHORIZED": (
        "Le nœud refuse : la clé publique de la passerelle n'est pas dans sa liste "
        "security.admin_key. Il faut l'y ajouter une fois, avec l'application Meshtastic, en "
        "ayant l'appareil en main."
    ),
    "ADMIN_BAD_SESSION_KEY": (
        "Clé de session refusée (elle n'est valable que 300 s et le nœud la renouvelle). "
        "Relancer l'opération suffit en général."
    ),
    "NOT_AUTHORIZED": "Le nœud refuse l'administration à distance (voie non autorisée).",
    "NO_RESPONSE": "Le nœud a reçu la demande mais n'a pas répondu.",
    "NO_CHANNEL": "Aucun canal commun avec ce nœud pour lui parler.",
    "MAX_RETRANSMIT": "Pas d'accusé de réception après plusieurs tentatives : nœud injoignable.",
    "TIMEOUT": "Délai dépassé côté firmware.",
    "PKI_FAILED": "Le chiffrement par clé publique a échoué (clé publique du nœud inconnue ?).",
    "PKI_UNKNOWN_PUBKEY": "La passerelle ne connaît pas la clé publique de ce nœud (pas encore annoncée).",
}


def _nom_enum(enum, valeur):
    """Nom lisible d'une valeur d'énumération protobuf, ou le nombre si le firmware en annonce
    une plus récente que nos protos."""
    try:
        return enum.Name(valeur)
    except (ValueError, KeyError):
        return str(valeur)


def _passkey(iface, node_num):
    """Clé de session mémorisée par la lib pour ce nœud (elle la récolte toute seule dans les
    réponses d'administration, meshtastic/__init__.py)."""
    try:
        return iface._getOrCreateByNum(node_num).get("adminSessionPassKey")
    except Exception:       # nœud encore inconnu de la base locale
        return None


def _oublier_passkey(iface, node_num):
    try:
        iface._getOrCreateByNum(node_num).pop("adminSessionPassKey", None)
    except Exception:
        pass


def _verifier(paquet):
    """Lève si le paquet reçu est un refus de routage ; renvoie le message d'administration."""
    decode = paquet.get("decoded") or {}
    routage = decode.get("routing")
    if routage:
        motif = routage.get("errorReason", "NONE")
        if motif != "NONE":
            raise ErreurAdmin(MESSAGES_ROUTAGE.get(motif, f"Refus du nœud : {motif}."))
    return decode


def _envoyer(iface, node_num, local, message, attend_reponse, timeout=None):
    """Envoie un AdminMessage et attend soit la réponse, soit l'accusé, soit le refus.

    `onResponseAckPermitted=True` est indispensable pour une écriture : la lib n'appelle le
    rappel sur un simple ACK que si on le demande (mesh_interface, « not isAck or ... or
    handler.ackPermitted »), et une écriture ne produit pas de réponse applicative -- sans ça on
    attendrait 90 s pour rien une opération qui a réussi."""
    # Lu à l'appel et non figé en valeur par défaut : une valeur par défaut est évaluée à la
    # définition du module, ce qui rendrait TIMEOUT_REPONSE_S impossible à ajuster.
    timeout = timeout or TIMEOUT_REPONSE_S
    recu = {}
    pret = threading.Event()

    def sur_reponse(paquet):
        recu["paquet"] = paquet
        pret.set()

    cle = _passkey(iface, node_num)
    if cle:
        message.session_passkey = cle

    iface.sendData(
        message,
        destinationId=node_num,
        portNum=portnums_pb2.PortNum.ADMIN_APP,
        wantAck=True,
        wantResponse=attend_reponse,
        onResponse=sur_reponse,
        onResponseAckPermitted=True,
        # Jamais l'index du canal « admin » : voir le point 2 de la docstring du module.
        channelIndex=0,
        # Un message local (`to` == nous) passe par l'API filaire, le firmware le traite comme
        # venant du téléphone : ni PKI, ni clé d'administration, ni clé de session.
        pkiEncrypted=not local,
    )

    if not pret.wait(timeout):
        raise ErreurAdmin(
            f"Aucune réponse du nœud après {timeout} s. Nœud éteint, hors de portée, ou clé "
            "publique de la passerelle non autorisée chez lui."
        )
    return _verifier(recu["paquet"])


def _brut(decode):
    """Le protobuf AdminMessage derrière le dictionnaire de la lib."""
    admin = decode.get("admin") or {}
    message = admin.get("raw")
    if message is None:
        raise ErreurAdmin("Le nœud a répondu, mais pas par un message d'administration.")
    return message


def _lire(iface, node_num, local, message):
    return _brut(_envoyer(iface, node_num, local, message, attend_reponse=True))


def _ecrire(iface, node_num, local, construire):
    """Envoie une écriture, en garantissant d'abord une clé de session.

    `construire` est appelé à chaque tentative (et non une fois) : une écriture qui recopie une
    configuration doit repartir de la configuration FRAÎCHE, pas de celle lue avant la
    péremption de la clé.

    Une écriture locale n'a pas besoin de clé du tout, le firmware la traite comme venant du
    téléphone."""
    if local:
        return _envoyer(iface, node_num, True, construire(), attend_reponse=False)

    for tentative in (1, 2):
        # On construit d'abord : une écriture qui recopie une configuration la relit, et cette
        # lecture rapporte déjà une clé de session. Demander une lecture AVANT coûterait un
        # aller-retour radio pour rien -- et deux lectures signifient deux clés, dont la
        # première est aussitôt remplacée.
        message = construire()
        if _passkey(iface, node_num) is None:
            # Aucune lecture dans le chemin (ex. redémarrage) : on prend la moins coûteuse.
            demande = admin_pb2.AdminMessage()
            demande.get_device_metadata_request = True
            _lire(iface, node_num, local, demande)
            if _passkey(iface, node_num) is None:
                raise ErreurAdmin(
                    "Le nœud a répondu sans fournir de clé de session : écriture impossible."
                )
        try:
            return _envoyer(iface, node_num, local, message, attend_reponse=False)
        except ErreurAdmin as erreur:
            # Clé périmée entre notre lecture et notre écriture (le firmware la renouvelle dès
            # qu'une réponse est construite plus de 150 s après la précédente) : on en reprend
            # une et on réessaie UNE fois. Au-delà, c'est autre chose.
            if tentative == 1 and "session" in str(erreur).lower():
                logger.info("Clé de session périmée, nouvelle demande puis seconde tentative.")
                _oublier_passkey(iface, node_num)
                continue
            raise


# ---------------------------------------------------------------- lectures

def _metadata(message):
    rep = message.get_device_metadata_response
    return {
        "firmware_version": rep.firmware_version,
        "device_state_version": rep.device_state_version,
        "role": _nom_enum(config_pb2.Config.DeviceConfig.Role, rep.role),
        "hardware_model": _nom_enum(mesh_pb2.HardwareModel, rep.hw_model),
        "a_pkc": bool(rep.hasPKC),
    }


def _config_lora(message):
    lora = message.get_config_response.lora
    return {
        "region": _nom_enum(config_pb2.Config.LoRaConfig.RegionCode, lora.region),
        "modem_preset": _nom_enum(config_pb2.Config.LoRaConfig.ModemPreset, lora.modem_preset),
        "utilise_preset": bool(lora.use_preset),
        "puissance_emission_dbm": lora.tx_power,
        "hop_limit": lora.hop_limit,
        "emission_activee": bool(lora.tx_enabled),
        "gain_rx_boost": bool(lora.sx126x_rx_boosted_gain),
        "rapport_cyclique_outrepasse": bool(lora.override_duty_cycle),
    }


def _config_appareil(message):
    appareil = message.get_config_response.device
    return {
        "role": _nom_enum(config_pb2.Config.DeviceConfig.Role, appareil.role),
        "rediffusion": _nom_enum(config_pb2.Config.DeviceConfig.RebroadcastMode, appareil.rebroadcast_mode),
        "annonce_nodeinfo_s": appareil.node_info_broadcast_secs,
    }


def _proprietaire(message):
    user = message.get_owner_response
    return {
        "long_name": user.long_name,
        "short_name": user.short_name,
        "identifiant": user.id,
        "sous_licence": bool(user.is_licensed),
    }


def _demande_config(type_config):
    message = admin_pb2.AdminMessage()
    message.get_config_request = type_config
    return message


# ---------------------------------------------------------------- point d'entrée

def executer(iface, tache):
    """Exécute une tâche et renvoie `(reponse, configuration)`.

    `reponse` est le détail lisible, journalisé chiffré côté Django. `configuration` est le
    sous-ensemble normalisé que Django range dans `ConfigurationNoeudMeshtastic` (ou None).

    Lève `ErreurAdmin` avec un message destiné à l'exploitant. Appelé depuis un thread
    (asyncio.to_thread) : tout ici est bloquant."""
    type_tache = tache["type_tache"]
    cible = tache.get("node_num_cible")
    parametres = tache.get("parametres") or {}

    notre_num = iface.myInfo.my_node_num if iface.myInfo is not None else None
    local = cible is None or (notre_num is not None and int(cible) == notre_num)
    node_num = notre_num if local else int(cible)
    if node_num is None:
        raise ErreurAdmin("Numéro de nœud de la passerelle encore inconnu (connexion en cours).")

    if type_tache == "LIRE_METADATA":
        donnees = _metadata(_lire(iface, node_num, local, _message_metadata()))
        return donnees, {
            "firmware_version": donnees["firmware_version"],
            "hardware_model": donnees["hardware_model"],
            "role": donnees["role"],
        }

    if type_tache == "LIRE_CONFIG_LORA":
        donnees = _config_lora(_lire(
            iface, node_num, local,
            _demande_config(admin_pb2.AdminMessage.ConfigType.LORA_CONFIG),
        ))
        return donnees, {
            "puissance_emission_dbm": donnees["puissance_emission_dbm"],
            "region": donnees["region"],
            "modem_preset": donnees["modem_preset"],
            "hop_limit": donnees["hop_limit"],
        }

    if type_tache == "LIRE_CONFIG_APPAREIL":
        donnees = _config_appareil(_lire(
            iface, node_num, local,
            _demande_config(admin_pb2.AdminMessage.ConfigType.DEVICE_CONFIG),
        ))
        return donnees, {"role": donnees["role"]}

    if type_tache == "LIRE_PROPRIETAIRE":
        message = admin_pb2.AdminMessage()
        message.get_owner_request = True
        # Pas de `configuration` : un nom de nœud est une donnée nominative, elle reste dans la
        # réponse chiffrée et n'alimente pas une table en clair.
        return _proprietaire(_lire(iface, node_num, local, message)), None

    if type_tache == "DEFINIR_PUISSANCE":
        return _definir_puissance(iface, node_num, local, parametres)

    if type_tache == "REDEMARRER":
        delai = int(parametres.get("delai_s") or 10)
        def construire():
            message = admin_pb2.AdminMessage()
            message.reboot_seconds = delai
            return message
        _ecrire(iface, node_num, local, construire)
        return {"redemarrage_dans_s": delai}, None

    raise ErreurAdmin(f"Opération inconnue de ce pont : {type_tache}.")


def _message_metadata():
    message = admin_pb2.AdminMessage()
    message.get_device_metadata_request = True
    return message


def _definir_puissance(iface, node_num, local, parametres):
    """Change la puissance d'émission.

    On relit la configuration LoRa et on la renvoie ENTIÈRE avec le seul champ modifié :
    `set_config.lora` remplace tout le bloc côté firmware (`config.lora = validatedLora`), donc
    envoyer un bloc vide avec juste tx_power effacerait région, preset et hop_limit -- un nœud
    sans région ne transmet plus du tout.

    Le firmware redémarre de lui-même après ce changement (`requiresReboot` est vrai dès que
    tx_power diffère), il n'y a donc pas à enchaîner un REDEMARRER."""
    try:
        puissance = int(parametres["puissance_dbm"])
    except (KeyError, TypeError, ValueError):
        raise ErreurAdmin("Paramètre puissance_dbm manquant ou non entier.")
    if not PUISSANCE_MIN_DBM <= puissance <= PUISSANCE_MAX_DBM:
        raise ErreurAdmin(
            f"Puissance hors bornes : {puissance} dBm (autorisé {PUISSANCE_MIN_DBM}-{PUISSANCE_MAX_DBM})."
        )

    def construire():
        lora = _config_lora_protobuf(iface, node_num, local)
        if lora.tx_power == puissance:
            logger.info("Nœud %08x déjà à %d dBm : on envoie quand même (idempotent).", node_num, puissance)
        message = admin_pb2.AdminMessage()
        message.set_config.lora.CopyFrom(lora)
        message.set_config.lora.tx_power = puissance
        return message

    _ecrire(iface, node_num, local, construire)
    return {"puissance_emission_dbm": puissance, "redemarrage_declenche": True}, {
        "puissance_emission_dbm": puissance,
    }


def _config_lora_protobuf(iface, node_num, local):
    message = _lire(iface, node_num, local, _demande_config(admin_pb2.AdminMessage.ConfigType.LORA_CONFIG))
    lora = message.get_config_response.lora
    if not lora.ByteSize() and lora.region == 0:
        raise ErreurAdmin("Configuration LoRa lue vide : on ne réécrit pas à l'aveugle.")
    return lora
