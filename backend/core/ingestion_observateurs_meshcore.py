"""Ingestion des messages publiés par les observateurs MeshCore sur MQTT.

Un **observateur** est un répéteur ou un room server dont le firmware a été complété d'un client
MQTT : il republie ce qu'il entend sur l'air. Ce n'est pas MeshCore lui-même — le firmware
officiel ne contient aucun `mqtt` (vérifié sur `meshcore-dev/MeshCore` : ni dans `src/`, ni dans
ses six exemples). Les binaires `heltec_v4_repeater_observer_mqtt` et
`heltec_v4_room_server_observer_mqtt` sont des forks du répéteur, avec les clés de
configuration `mqtt.server`, `mqtt.port`, `mqtt.username`, `mqtt.password`, `mqtt.iata`,
`mqtt.origin`, `mqtt.owner`, `mqtt.raw`, `mqtt.packets`, `mqtt.status`, `mqtt.tx`,
`mqtt.interval` (relevées dans les chaînes du binaire v1.16).

**Le contrat**, établi des deux côtés — les gabarits de topic dans le firmware observateur, et
la lecture qu'en fait CoreScope (`cmd/ingestor/main.go`, `db.go:2546`) :

```
meshcore/<iata>/<cle_observateur>/packets   {"raw": "<trame hex>", "SNR": .., "RSSI": ..,
                                             "origin": "..", "timestamp": "..", ...}
meshcore/<iata>/<cle_observateur>/raw       trame brute
meshcore/<iata>/<cle_observateur>/status    {"battery_mv":.., "uptime_secs":.., "noise_floor":..,
                                             "last_rssi":.., "last_snr":.., "recv":.., ...}
meshcore/<iata>/<cle_observateur>/neighbors  voisinage rapporté
```

C'est le champ `raw` qui ferme la boucle : il porte la trame hexadécimale, c'est-à-dire
exactement l'entrée de `core/decodeur_meshcore.decoder_paquet`.

**Deux précautions reprises de leur expérience, et elles coûtent cher à réapprendre** :

1. **L'horodatage de l'observateur n'est pas digne de confiance.** CoreScope l'a constaté
   (leur ticket #1370 : des observateurs à l'horloge fausse estampillaient 18 h 42 une réception
   réelle de 1 h 42) et a basculé sur l'heure d'ingestion. On fait pareil : `timestamp` est
   conservé pour information, jamais utilisé comme date de réception.
2. **Le SNR de l'enveloppe est celui de l'observateur**, pas celui d'une liaison de bout en
   bout. Il mesure ce que CET observateur a entendu de l'émetteur — ce qui est précisément une
   liaison orientée, et rien de plus.
"""
import json
import logging

from django.utils import timezone

from .decodeur_meshcore import TrameInvalide, decoder_paquet
from .models import Environment, LiaisonMeshCore, SourceLiaisonMeshtastic

logger = logging.getLogger(__name__)

# Types de sous-topic qu'on sait traiter. Les autres sont ignorés sans bruit : l'écosystème en
# ajoute (client/rf, client/regions…) et un observateur n'a pas à être compatible avec nous.
SOUS_TOPICS_CONNUS = {"packets", "raw", "status", "neighbors"}


class MessageObservateur:
    """Un message d'observateur, décomposé — ou refusé, avec la raison."""

    __slots__ = ("iata", "observateur", "sorte", "donnees")

    def __init__(self, iata, observateur, sorte, donnees):
        self.iata = iata
        self.observateur = observateur
        self.sorte = sorte
        self.donnees = donnees


def lire_topic(topic):
    """`meshcore/<iata>/<cle>/<sorte>` → (iata, clé, sorte), ou None si ce n'en est pas un.

    Renvoie None plutôt que de deviner : le même broker porte des topics de service
    (`meshcore/status`, `meshcore/events/connection`) et des topics de clients mobiles
    (`meshcore/client/<cle>/…`) qui ne sont pas des observations."""
    morceaux = (topic or "").split("/")
    if len(morceaux) != 4 or morceaux[0] != "meshcore":
        return None
    iata, observateur, sorte = morceaux[1], morceaux[2], morceaux[3]
    if iata == "client" or sorte not in SOUS_TOPICS_CONNUS:
        return None
    return iata, observateur.lower(), sorte


def lire_message(topic, charge):
    """Décompose un message reçu. Renvoie None si ce n'est pas pour nous."""
    decompose = lire_topic(topic)
    if decompose is None:
        return None
    iata, observateur, sorte = decompose

    if isinstance(charge, (bytes, bytearray)):
        try:
            charge = charge.decode("utf-8")
        except UnicodeDecodeError:
            # Le sous-topic `raw` peut porter des octets bruts : on les rend en hexadécimal
            # plutôt que de les perdre.
            return MessageObservateur(iata, observateur, sorte, {"raw": bytes(charge).hex()})

    if isinstance(charge, str):
        texte = charge.strip()
        if texte.startswith("{"):
            try:
                charge = json.loads(texte)
            except json.JSONDecodeError:
                return None
        else:
            charge = {"raw": texte}

    if not isinstance(charge, dict):
        return None
    return MessageObservateur(iata, observateur, sorte, charge)


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def ingerer_paquet(message, environment=Environment.PROD, maintenant=None):
    """Décode la trame d'un message `packets` et en tire une liaison orientée.

    Renvoie `(decode, liaison)` — `decode` est le résultat du décodeur (utile à l'appelant pour
    les adverts et les messages), `liaison` la ligne créée ou mise à jour, ou None.

    **Le sens** : l'observateur a ENTENDU l'émetteur de la trame. Il est donc le récepteur de la
    liaison. L'émetteur, lui, n'est pas dans l'en-tête MeshCore — il n'y a pas de champ
    « expéditeur » hors des charges chiffrées. On n'en déduit donc une liaison que pour un
    **ADVERT**, seul type qui porte la clé publique de son émetteur en clair et signée."""
    maintenant = maintenant or timezone.now()
    brut = message.donnees.get("raw")
    if not brut:
        return None, None

    try:
        decode = decoder_paquet(brut)
    except TrameInvalide as erreur:
        # Pas une erreur de chez nous : une trame malformée ou hostile sur un broker public est
        # attendue. On la compte en debug, on ne remplit pas le journal d'une trace par trame.
        logger.debug("Trame illisible de l'observateur %s : %s", message.observateur[:8], erreur)
        return None, None

    charge = decode.get("charge") or {}
    emetteur = charge.get("cle_publique") if charge.get("type") == "ADVERT" else None
    if not emetteur:
        # Tout le reste est chiffré ou anonyme : en tirer une liaison supposerait de savoir qui
        # a émis, ce qu'on ne sait pas. Le paquet reste exploitable par l'appelant.
        return decode, None

    # Une signature invalide disqualifie l'advert : n'importe qui peut en fabriquer un portant
    # la clé d'autrui, et la liaison serait attribuée au mauvais nœud.
    if charge.get("signature_valide") is False:
        logger.debug("Advert à signature invalide ignoré (observateur %s).", message.observateur[:8])
        return decode, None

    snr = _nombre(message.donnees.get("SNR"))
    liaison, cree = LiaisonMeshCore.objects.get_or_create(
        emetteur_prefixe_hex=emetteur.lower(),
        recepteur_pubkey_hex=message.observateur,
        source=SourceLiaisonMeshtastic.RF,
        environment=environment,
        defaults={"snr": snr, "prefixe_octets": 32, "dernier_vu": maintenant},
    )
    if not cree:
        if snr is not None and (liaison.snr is None or snr > liaison.snr):
            liaison.snr = snr
        liaison.nombre += 1
        liaison.dernier_vu = maintenant
        liaison.save(update_fields=["snr", "nombre", "dernier_vu"])
    return decode, liaison
