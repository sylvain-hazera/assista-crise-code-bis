"""Un message radio entendu plusieurs fois n'est enregistré qu'une fois (24/11/2026).

Signalé par Sylvain : « si je reçois un message plusieurs fois, entendu par plusieurs relais, il
apparaît plusieurs fois ! Sur les vrais clients, ce dédoublement est traité. »

Un message de canal arrive autant de fois qu'il est entendu : une copie par relais pour le
décodage logiciel (qui lit chaque paquet reçu, voir meshcore-bridge), une par radio quand
plusieurs radios (locale, satellite, relais navigateur, passerelle MQTT) écoutent le même canal.

**L'identité radio** : les clients MeshCore reconnaissent un message à l'horodatage posé par
l'émetteur et à l'empreinte de son texte — les relais ne changent ni l'un ni l'autre. Le pont la
transmet (`cle_radio`) ; elle est gardée en HMAC. Deux messages identiques d'une même personne,
à deux instants, restent deux messages.

**À défaut** (pont plus ancien, satellite pas encore à jour, Meshtastic) : même canal, même
texte (et même nœud pour Meshtastic) dans les deux minutes. Le jour où toutes les radios
donnent l'identité, cette tolérance ne sert plus qu'aux messages qui n'en ont pas.
"""
import datetime

from django.utils import timezone

#: Une copie relayée arrive en quelques secondes ; une passerelle MQTT parfois en une minute.
FENETRE_IDENTITE = datetime.timedelta(minutes=30)
FENETRE_TEXTE = datetime.timedelta(minutes=2)
#: Au-delà, on ne remonte pas plus loin dans les messages récents du canal.
PLAFOND = 200


def empreinte_radio(protocole, canal_id, cle):
    """HMAC de l'identité radio, propre au canal ; None sans identité."""
    from .crypto_fields import empreinte_jeton

    cle = (cle or "").strip()
    return empreinte_jeton(f"{protocole}|{canal_id}|{cle}") if cle else None


def doublon(modele, canal, contenu, empreinte=None, maintenant=None, **memes):
    """Le message déjà enregistré dont celui-ci est une copie, ou None.

    Le texte est chiffré en base : la comparaison se fait en Python, sur les messages entrants
    récents du canal seulement."""
    from .models import DirectionMessageMesh

    if canal is None:
        return None
    maintenant = maintenant or timezone.now()
    texte = (contenu or "").strip()
    recents = (modele.objects.filter(canal=canal, direction=DirectionMessageMesh.ENTRANT,
                                     date_creation__gte=maintenant - FENETRE_IDENTITE, **memes)
               .order_by("-date_creation")[:PLAFOND])
    for message in recents:
        connue = getattr(message, "empreinte_radio", None)
        if empreinte and connue:
            if connue == empreinte:
                return message
            continue              # deux identités différentes : deux messages, même texte
        if message.date_creation >= maintenant - FENETRE_TEXTE and (message.contenu or "").strip() == texte:
            return message
    return None
