"""Réglages de nœud Meshtastic modifiables à distance : table déclarative et validation.

Repris de `CHAMPS` dans `carte-live/src/administration.js` de `sauveteur71/carte-live-meshtastic`
(GPL-3.0, avec son autorisation). Son idée, et c'est la bonne : **une liste blanche de champs avec
leur validateur**, plutôt qu'une opération par réglage. Un réglage inconnu est refusé, une valeur
hors bornes est refusée, et rien ne part sur la radio avant ces deux contrôles.

**Pourquoi la validation vit ici et pas seulement dans le pont.** Le pont est le seul à connaître
les protobufs, mais Django est le seul point par lequel une demande peut entrer. Valider ici,
c'est refuser tout de suite avec un message lisible, au lieu de laisser l'exploitant attendre
trente secondes un échec. Le pont revalide néanmoins les deux minima imposés par le firmware
(voir `meshtastic-bridge/admin_meshtastic.py`) : un pont peut tourner contre un Django plus
ancien, et ces deux-là ne sont pas des préférences mais des contraintes de temps d'antenne.

**Ce qui n'est volontairement PAS exposé**, et pourquoi :

- `override_frequency` et `channel_num` : ils font émettre hors de la bande prévue. Une erreur
  est une infraction réglementaire, et sur un relais inaccessible elle n'est pas rattrapable.
  Son module les accepte (400-1000 MHz) ; nous non.
- `packet_signature_policy` (section sécurité) : touche à l'authentification des paquets, à
  traiter avec le propriétaire du réseau, pas depuis une page d'administration.
- la quasi-totalité du module Télémétrie (capteurs d'environnement, qualité d'air, santé) :
  rien de tout cela n'est utilisé par Assista-Crise ; exposer trente champs qui ne servent à rien
  ajoute de la surface d'erreur sans rien apporter.
- les GPIO de la section position : un mauvais numéro de broche rend le GPS muet, et seul
  quelqu'un qui a l'appareil en main peut le corriger.
"""


class ChampReglage:
    """Un réglage modifiable : son type, ses bornes, et à quoi il sert."""

    def __init__(self, libelle, aide=""):
        self.libelle = libelle
        self.aide = aide

    def valider(self, valeur):
        raise NotImplementedError

    def decrire(self):
        return {"type": "inconnu", "libelle": self.libelle, "aide": self.aide}


class Entier(ChampReglage):
    def __init__(self, mini, maxi, libelle, aide="", valeurs_speciales=()):
        super().__init__(libelle, aide)
        self.mini, self.maxi = mini, maxi
        # Valeurs acceptées hors de l'intervalle, avec leur sens propre (ex. 0 = « défaut du
        # firmware » pour un intervalle de télémétrie).
        self.valeurs_speciales = set(valeurs_speciales)

    def valider(self, valeur):
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            raise ValueError(f"{self.libelle} : un entier est attendu.")
        if valeur in self.valeurs_speciales:
            return valeur
        if not self.mini <= valeur <= self.maxi:
            speciales = (" ou " + ", ".join(str(v) for v in sorted(self.valeurs_speciales))
                         if self.valeurs_speciales else "")
            raise ValueError(
                f"{self.libelle} : {valeur} est hors bornes ({self.mini} à {self.maxi}{speciales})."
            )
        return valeur

    def decrire(self):
        return {"type": "entier", "libelle": self.libelle, "aide": self.aide,
                "mini": self.mini, "maxi": self.maxi,
                "valeurs_speciales": sorted(self.valeurs_speciales)}


class Booleen(ChampReglage):
    def valider(self, valeur):
        if not isinstance(valeur, bool):
            raise ValueError(f"{self.libelle} : vrai ou faux est attendu.")
        return valeur

    def decrire(self):
        return {"type": "booleen", "libelle": self.libelle, "aide": self.aide}


class Enumeration(ChampReglage):
    """Nom d'une valeur d'énumération du firmware.

    La liste est recopiée du firmware (vérifiée le 07/11/2026 contre les protobufs de la lib
    officielle 2.7.11). Si une version ajoute une valeur, cette liste est seulement incomplète,
    jamais fausse : le pont revalide contre le protobuf réel, qui fait foi."""

    def __init__(self, valeurs, libelle, aide="", refusees=()):
        super().__init__(libelle, aide)
        self.valeurs = list(valeurs)
        self.refusees = set(refusees)

    def valider(self, valeur):
        if not isinstance(valeur, str):
            raise ValueError(f"{self.libelle} : un nom de valeur est attendu.")
        if valeur in self.refusees:
            raise ValueError(f"{self.libelle} : « {valeur} » n'est pas acceptée ici.")
        if valeur not in self.valeurs:
            raise ValueError(
                f"{self.libelle} : « {valeur} » inconnue. Attendu l'une de : "
                f"{', '.join(self.valeurs)}."
            )
        return valeur

    def decrire(self):
        return {"type": "enumeration", "libelle": self.libelle, "aide": self.aide,
                "valeurs": [v for v in self.valeurs if v not in self.refusees]}


# --- Énumérations du firmware ------------------------------------------------------------------
ROLES = ['CLIENT', 'CLIENT_MUTE', 'ROUTER', 'ROUTER_CLIENT', 'REPEATER', 'TRACKER', 'SENSOR',
         'TAK', 'CLIENT_HIDDEN', 'LOST_AND_FOUND', 'TAK_TRACKER', 'ROUTER_LATE', 'CLIENT_BASE']
MODES_REDIFFUSION = ['ALL', 'ALL_SKIP_DECODING', 'LOCAL_ONLY', 'KNOWN_ONLY', 'NONE',
                     'CORE_PORTNUMS_ONLY']
PRESETS = ['LONG_FAST', 'LONG_SLOW', 'VERY_LONG_SLOW', 'MEDIUM_SLOW', 'MEDIUM_FAST', 'SHORT_SLOW',
           'SHORT_FAST', 'LONG_MODERATE', 'SHORT_TURBO', 'LONG_TURBO', 'LITE_FAST', 'LITE_SLOW',
           'NARROW_FAST', 'NARROW_SLOW']
# Seules les régions utiles au périmètre du projet (France métropolitaine et outre-mer). Exposer
# les trente-quatre régions du firmware inviterait à poser par erreur une région d'un autre
# continent sur un relais, ce qui le rend muet jusqu'à une intervention sur place.
REGIONS = ['EU_868', 'EU_433']

# Minimum imposé par le FIRMWARE entre deux rapports de voisinage sur LoRa : 4 h. Ce n'est pas une
# préférence mais une limite de temps d'antenne — un rapport de voisinage est volumineux, et le
# diffuser souvent sature le réseau pour tout le monde.
VOISINAGE_INTERVALLE_MIN_S = 14400
# Intervalle de télémétrie : 0 = valeur par défaut du firmware, sinon au moins 15 min.
TELEMETRIE_INTERVALLE_MIN_S = 900
SEPT_JOURS_S = 7 * 86400


# --- Sections ----------------------------------------------------------------------------------
# `module` : la section est un module (AdminMessage.set_module_config) et non une section de
# configuration (set_config). `redemarre` : le firmware redémarre le nœud de lui-même après un
# changement dans cette section — à dire à l'exploitant, pas à découvrir.
SECTIONS = {
    "device": {
        "libelle": "Appareil",
        "module": False,
        "redemarre": False,
        "champs": {
            "role": Enumeration(
                ROLES, "Rôle",
                "Décide si le nœud relaie le trafic des autres. ROUTER et REPEATER relaient, "
                "CLIENT_MUTE ne relaie rien. Un relais au mauvais rôle est un relais mort.",
            ),
            "rebroadcast_mode": Enumeration(
                MODES_REDIFFUSION, "Mode de rediffusion",
                "ALL rediffuse tout. LOCAL_ONLY et KNOWN_ONLY limitent, NONE coupe la "
                "rediffusion sans changer le rôle.",
            ),
            "node_info_broadcast_secs": Entier(
                3600, SEPT_JOURS_S, "Annonce d'identité (s)",
                "Fréquence à laquelle le nœud s'annonce. Trop court, il sature le réseau ; trop "
                "long, il disparaît des répertoires.",
            ),
        },
    },
    "lora": {
        "libelle": "Radio LoRa",
        "module": False,
        # Le firmware redémarre dès que region, preset, bande, puissance ou fréquence changent.
        "redemarre": True,
        "champs": {
            "region": Enumeration(
                REGIONS, "Région",
                "Détermine la bande et la puissance autorisées. Un nœud sans région ne transmet "
                "pas du tout.", refusees=("UNSET",),
            ),
            "modem_preset": Enumeration(
                PRESETS, "Preset",
                "Compromis portée/débit. Tous les nœuds d'un même réseau doivent avoir le même : "
                "un preset différent rend le nœud invisible pour les autres.",
            ),
            "use_preset": Booleen(
                "Utiliser le preset",
                "Faux = réglages radio manuels (bande, étalement) : réservé aux essais.",
            ),
            "hop_limit": Entier(
                1, 7, "Nombre de sauts",
                "Combien de relais un message peut traverser. Plus haut = plus de portée mais "
                "plus de trafic pour tout le monde.",
            ),
            "tx_power": Entier(
                1, 27, "Puissance d'émission (dBm)",
                "27 dBm est le plafond de la bande 869,4-869,65 MHz (500 mW, 10 % de rapport "
                "cyclique). Alimente aussi la correction du diagnostic des liaisons.",
            ),
            "tx_enabled": Booleen(
                "Émission activée",
                "Faux = le nœud écoute sans jamais émettre. À ne pas poser à distance sur un "
                "nœud qu'on ne peut pas aller rallumer.",
            ),
            "sx126x_rx_boosted_gain": Booleen(
                "Gain de réception renforcé",
                "Améliore la sensibilité sur les modules SX126x, au prix d'un peu de "
                "consommation.",
            ),
            "config_ok_to_mqtt": Booleen(
                "Autoriser la remontée MQTT",
                "Le nœud accepte que ses paquets soient relayés vers MQTT par une passerelle.",
            ),
            "ignore_mqtt": Booleen(
                "Ignorer le trafic venu de MQTT",
                "Vrai = le nœud ne réémet pas sur la radio ce qui arrive par MQTT. Utile pour "
                "éviter qu'un pont ne réinjecte du trafic distant.",
            ),
        },
    },
    "position": {
        "libelle": "Position",
        "module": False,
        "redemarre": False,
        "champs": {
            "position_broadcast_secs": Entier(
                300, SEPT_JOURS_S, "Diffusion de position (s)",
                "Sans diffusion de position, le nœud n'apparaît pas sur la carte et le "
                "diagnostic des liaisons ne peut pas calculer de distance.",
            ),
            "position_broadcast_smart_enabled": Booleen(
                "Diffusion intelligente",
                "Ne diffuse que si le nœud a bougé : économise le temps d'antenne.",
            ),
            "fixed_position": Booleen(
                "Position fixe",
                "Pour un relais qui ne bouge pas : il garde sa position même sans GPS.",
            ),
            "gps_enabled": Booleen(
                "GPS activé",
                "Couper le GPS d'un relais à position fixe économise sa batterie.",
            ),
        },
    },
    "voisinage": {
        "libelle": "Module Voisinage (NeighborInfo)",
        "module": True,
        "redemarre": False,
        "champs": {
            "enabled": Booleen(
                "Module activé",
                "C'est ce module qui fait dire au nœud QUI il entend et à quel SNR. Sans lui, le "
                "diagnostic des liaisons est aveugle partout sauf aux passerelles : il ne voit "
                "que ce que les passerelles reçoivent, jamais ce que les relais entendent.",
            ),
            "transmit_over_lora": Booleen(
                "Diffuser sur la radio",
                "Faux = le rapport ne part que par MQTT, sans coûter de temps d'antenne. "
                "Préférable quand le nœud est une passerelle.",
            ),
            "update_interval": Entier(
                VOISINAGE_INTERVALLE_MIN_S, SEPT_JOURS_S, "Intervalle (s)",
                "Au moins 4 h : c'est le firmware qui l'impose, un rapport de voisinage étant "
                "volumineux. Une valeur plus courte est refusée.",
            ),
        },
    },
    "telemetrie": {
        "libelle": "Module Télémétrie",
        "module": True,
        "redemarre": False,
        "champs": {
            "device_telemetry_enabled": Booleen(
                "Télémétrie de l'appareil",
                "Batterie, tension, charge. C'est la source de l'alerte « batterie faible » "
                "sur les relais.",
            ),
            "device_update_interval": Entier(
                TELEMETRIE_INTERVALLE_MIN_S, SEPT_JOURS_S, "Intervalle (s)",
                "0 = valeur par défaut du firmware. Sinon au moins 15 min.",
                valeurs_speciales=(0,),
            ),
        },
    },
}


class ReglageInvalide(ValueError):
    """Section inconnue, champ non modifiable, ou valeur hors bornes."""


def valider_reglages(section, valeurs):
    """Valide `{champ: valeur}` pour une section, et renvoie les valeurs normalisées.

    Refuse une section inconnue, un champ hors liste blanche, une valeur du mauvais type ou hors
    bornes, et un ensemble vide — « aucune modification » est une erreur d'appel, pas une
    opération réussie."""
    description = SECTIONS.get(section)
    if description is None:
        raise ReglageInvalide(
            f"Section « {section} » inconnue. Attendu l'une de : {', '.join(sorted(SECTIONS))}."
        )
    if not isinstance(valeurs, dict) or not valeurs:
        raise ReglageInvalide("Aucun réglage à modifier.")

    champs = description["champs"]
    inconnus = [nom for nom in valeurs if nom not in champs]
    if inconnus:
        raise ReglageInvalide(
            f"Réglage(s) non modifiable(s) dans « {section} » : {', '.join(sorted(inconnus))}. "
            f"Modifiables : {', '.join(sorted(champs))}."
        )

    normalisees = {}
    for nom, valeur in valeurs.items():
        try:
            normalisees[nom] = champs[nom].valider(valeur)
        except ValueError as erreur:
            raise ReglageInvalide(str(erreur)) from erreur
    return normalisees


def catalogue():
    """Description des sections et de leurs champs, pour que l'interface construise son
    formulaire sans dupliquer ni les bornes ni les libellés."""
    return {
        nom: {
            "libelle": section["libelle"],
            "module": section["module"],
            "redemarre": section["redemarre"],
            "champs": {cle: champ.decrire() for cle, champ in section["champs"].items()},
        }
        for nom, section in SECTIONS.items()
    }
