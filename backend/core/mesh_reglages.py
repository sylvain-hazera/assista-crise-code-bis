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

**Les réglages réglementés sont exposés, avec leur avertissement** (décision du 09/11/2026, à
sa demande). Fréquence, numéro de canal, décalage de fréquence, rapport cyclique, puissance et
région sont modifiables : la bande de 868 MHz n'est pas la même partout, et un outil qui décide à
la place de l'exploitant l'empêche de faire ce que sa situation autorise. Ils portent
`reglementaire=True`, un `avertissement` affiché à côté du champ, et leur écriture exige une
confirmation explicite (voir `valider_reglages`), tracée dans le journal d'audit avec la tâche.

Ce n'est pas un garde-fou technique : rien n'empêche techniquement un exploitant de poser une
valeur illégale. C'est une chaîne de responsabilité — la demande est nominative, horodatée et
conservée.

**Ce qui n'est volontairement PAS exposé**, et pourquoi :

- `bandwidth`, `spread_factor`, `coding_rate` (réglages radio manuels, actifs seulement avec
  `use_preset=False`). Ce n'est pas un refus de principe mais un refus de deviner : vérifié le
  09/11/2026 dans `applyModemConfig()` (`src/mesh/RadioInterface.cpp`), `bandwidth` ne stocke
  PAS des kHz mais un **code** converti par `bwCodeToKHz()`, dont la table est dans un autre
  fichier que je n'ai pas lu ; et dans la branche sans preset, `spread_factor` et `coding_rate`
  sont recopiés **sans aucun contrôle de bornes**. Une valeur fausse ne rend pas le nœud
  illégal, elle le rend invisible pour tout le réseau — et personne ne saura pourquoi. À exposer
  le jour où la table des codes aura été lue, pas avant.
- `packet_signature_policy` (section sécurité) : touche à l'authentification des paquets, à
  traiter avec le propriétaire du réseau, pas depuis une page d'administration.
- la quasi-totalité du module Télémétrie (capteurs d'environnement, qualité d'air, santé) :
  rien de tout cela n'est utilisé par Assista-Crise ; exposer trente champs qui ne servent à rien
  ajoute de la surface d'erreur sans rien apporter.
- les GPIO de la section position : un mauvais numéro de broche rend le GPS muet, et seul
  quelqu'un qui a l'appareil en main peut le corriger.
"""


class ChampReglage:
    """Un réglage modifiable : son type, ses bornes, et à quoi il sert.

    `reglementaire` : ce réglage décide de ce qui part dans l'air (bande, puissance, occupation).
    L'écriture exige alors une confirmation explicite, et `avertissement` est affiché à côté du
    champ — pas enfoui dans une documentation que personne n'ouvre au moment d'agir."""

    def __init__(self, libelle, aide="", avertissement="", reglementaire=False):
        self.libelle = libelle
        self.aide = aide
        self.avertissement = avertissement
        self.reglementaire = reglementaire

    def valider(self, valeur):
        raise NotImplementedError

    def _commun(self, type_champ):
        return {"type": type_champ, "libelle": self.libelle, "aide": self.aide,
                "avertissement": self.avertissement, "reglementaire": self.reglementaire}

    def decrire(self):
        return self._commun("inconnu")


class Entier(ChampReglage):
    def __init__(self, mini, maxi, libelle, aide="", valeurs_speciales=(),
                 avertissement="", reglementaire=False):
        super().__init__(libelle, aide, avertissement, reglementaire)
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
        return {**self._commun("entier"), "mini": self.mini, "maxi": self.maxi,
                "valeurs_speciales": sorted(self.valeurs_speciales)}


class Reel(ChampReglage):
    """Nombre à virgule. Nécessaire pour les fréquences : `override_frequency` et
    `frequency_offset` sont des `float` dans le protobuf, et un décalage de crystal se compte en
    fractions de MHz — l'arrondir à l'entier n'aurait aucun sens."""

    def __init__(self, mini, maxi, libelle, aide="", valeurs_speciales=(),
                 avertissement="", reglementaire=False):
        super().__init__(libelle, aide, avertissement, reglementaire)
        self.mini, self.maxi = mini, maxi
        self.valeurs_speciales = set(valeurs_speciales)

    def valider(self, valeur):
        # `isinstance(True, int)` est vrai en Python : sans ce garde, `tx=True` passerait pour 1.
        if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
            raise ValueError(f"{self.libelle} : un nombre est attendu.")
        valeur = float(valeur)
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
        return {**self._commun("reel"), "mini": self.mini, "maxi": self.maxi,
                "valeurs_speciales": sorted(self.valeurs_speciales)}


class Booleen(ChampReglage):
    def valider(self, valeur):
        if not isinstance(valeur, bool):
            raise ValueError(f"{self.libelle} : vrai ou faux est attendu.")
        return valeur

    def decrire(self):
        return self._commun("booleen")


class Enumeration(ChampReglage):
    """Nom d'une valeur d'énumération du firmware.

    La liste est recopiée du firmware (vérifiée le 07/11/2026 contre les protobufs de la lib
    officielle 2.7.11). Si une version ajoute une valeur, cette liste est seulement incomplète,
    jamais fausse : le pont revalide contre le protobuf réel, qui fait foi."""

    def __init__(self, valeurs, libelle, aide="", refusees=(), avertissements_par_valeur=None,
                 avertissement="", reglementaire=False):
        super().__init__(libelle, aide, avertissement, reglementaire)
        self.valeurs = list(valeurs)
        self.refusees = set(refusees)
        # Avertissement propre à CHAQUE valeur : c'est ce qui rend l'alerte adaptée à la zone
        # géographique plutôt que générique. L'interface affiche celui de la valeur choisie.
        self.avertissements_par_valeur = dict(avertissements_par_valeur or {})

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
        valeurs = [v for v in self.valeurs if v not in self.refusees]
        return {**self._commun("enumeration"), "valeurs": valeurs,
                "avertissements_par_valeur": {
                    v: self.avertissements_par_valeur[v]
                    for v in valeurs if v in self.avertissements_par_valeur
                }}


# --- Énumérations du firmware ------------------------------------------------------------------
ROLES = ['CLIENT', 'CLIENT_MUTE', 'ROUTER', 'ROUTER_CLIENT', 'REPEATER', 'TRACKER', 'SENSOR',
         'TAK', 'CLIENT_HIDDEN', 'LOST_AND_FOUND', 'TAK_TRACKER', 'ROUTER_LATE', 'CLIENT_BASE']
MODES_REDIFFUSION = ['ALL', 'ALL_SKIP_DECODING', 'LOCAL_ONLY', 'KNOWN_ONLY', 'NONE',
                     'CORE_PORTNUMS_ONLY']
PRESETS = ['LONG_FAST', 'LONG_SLOW', 'VERY_LONG_SLOW', 'MEDIUM_SLOW', 'MEDIUM_FAST', 'SHORT_SLOW',
           'SHORT_FAST', 'LONG_MODERATE', 'SHORT_TURBO', 'LONG_TURBO', 'LITE_FAST', 'LITE_SLOW',
           'NARROW_FAST', 'NARROW_SLOW']
# --- Régions et réglementation -----------------------------------------------------------------
# Table des régions du FIRMWARE, recopiée des macros RDEF de `src/mesh/RadioInterface.cpp`
# (branche master, lue le 09/11/2026) : (début MHz, fin MHz, rapport cyclique %, puissance max
# dBm). C'est elle qui fait foi sur ce que l'appareil va réellement faire — la documentation
# publique ne donne pas ces valeurs.
TABLE_REGIONS_FIRMWARE = {
    'US': (902.0, 928.0, 100, 30),
    'EU_433': (433.0, 434.0, 10, 10),
    'EU_868': (869.4, 869.65, 10, 27),
    'CN': (470.0, 510.0, 100, 19),
    'JP': (920.5, 923.5, 100, 13),
    'ANZ': (915.0, 928.0, 100, 30),
    'KR': (920.0, 923.0, 100, 23),
    'TW': (920.0, 925.0, 100, 27),
    'RU': (868.7, 869.2, 100, 20),
    'IN': (865.0, 867.0, 100, 30),
    'NZ_865': (864.0, 868.0, 100, 36),
    'TH': (920.0, 925.0, 10, 27),
    'LORA_24': (2400.0, 2483.5, 100, 10),
    'UA_433': (433.0, 434.7, 10, 10),
    'UA_868': (868.0, 868.6, 1, 14),
    'MY_433': (433.0, 435.0, 100, 20),
    'MY_919': (919.0, 924.0, 100, 27),
    'SG_923': (917.0, 925.0, 100, 20),
    'PH_433': (433.0, 434.7, 100, 10),
    'PH_868': (868.0, 869.4, 100, 14),
    'PH_915': (915.0, 918.0, 100, 24),
    'ANZ_433': (433.05, 434.79, 100, 14),
    'KZ_433': (433.075, 434.775, 100, 10),
    'KZ_863': (863.0, 868.0, 100, 30),
    'NP_865': (865.0, 868.0, 100, 30),
    'BR_902': (902.0, 907.5, 100, 30),
}

# Les trente-quatre régions de l'énumération du protobuf (vérifiées contre la lib 2.7.11 embarquée
# dans le pont). Elles sont toutes exposées : décider à la place de l'exploitant quelle région sa
# situation autorise, c'est l'empêcher de faire ce qui est légal chez lui.
REGIONS = [
    'EU_868', 'EU_433', 'US', 'CN', 'JP', 'ANZ', 'ANZ_433', 'KR', 'TW', 'RU', 'IN', 'NZ_865',
    'TH', 'UA_433', 'UA_868', 'MY_433', 'MY_919', 'SG_923', 'PH_433', 'PH_868', 'PH_915',
    'KZ_433', 'KZ_863', 'NP_865', 'BR_902', 'LORA_24',
    'EU_866', 'EU_874', 'EU_917', 'EU_N_868', 'ITU1_2M', 'ITU2_2M', 'ITU3_2M', 'UNSET',
]

# Présentes dans le protobuf mais SANS entrée dans la table des régions du firmware lue le
# 09/11/2026. Poser l'une d'elles peut laisser le nœud sans plan de fréquences utilisable, donc
# muet — et il faudra l'appareil en main pour le rattraper.
REGIONS_SANS_TABLE_FIRMWARE = {
    'EU_866', 'EU_874', 'EU_917', 'EU_N_868', 'ITU1_2M', 'ITU2_2M', 'ITU3_2M',
}

# Régions du service AMATEUR (bande 2 m). Elles ne relèvent pas des dispositifs de faible portée :
# il faut une licence radioamateur, et le service amateur interdit le trafic pour le compte de
# tiers — ce qui exclut l'usage opérationnel visé par Assista-Crise.
REGIONS_RADIOAMATEUR = {'ITU1_2M', 'ITU2_2M', 'ITU3_2M'}

# Le fond réglementaire français, rappelé sur chaque réglage qui décide de ce qui part dans l'air.
# Vérifié le 09/11/2026 : le tableau national de répartition des bandes de fréquences (TNRBF) de
# l'ANFR s'applique à l'outre-mer « sous réserve de dispositions particulières », regroupées dans
# son chapitre 7. Aucune condition propre à La Réunion pour 863-870 MHz n'a été trouvée dans cette
# recherche — ce qui ne veut pas dire qu'il n'y en a pas : cela veut dire qu'il faut la vérifier.
AVERTISSEMENT_FRANCE = (
    "Réglementation française : la bande et la puissance autorisées ne sont PAS les mêmes partout. "
    "Le TNRBF de l'ANFR s'applique en outre-mer « sous réserve de dispositions particulières » "
    "(chapitre 7) : ce qui est permis en métropole ne l'est pas automatiquement à La Réunion, "
    "Mayotte, aux Antilles ou en Guyane. Référence : chapitre 7 du TNRBF en vigueur et la table "
    "SRD de l'ANFR, à défaut le délégué régional de l'ANFR. La responsabilité est celle de "
    "l'exploitant de la station, pas celle de l'outil."
)


def _avertissement_region(code):
    """Avertissement propre à une région : ce que le FIRMWARE va faire, puis le cadre français.

    Dire d'abord le fait technique vérifiable (bande, puissance, rapport cyclique tels qu'ils
    sont écrits dans le firmware), ensuite le cadre juridique à vérifier. L'inverse donnerait un
    avertissement que personne ne lit parce qu'il est le même partout."""
    morceaux = []
    if code == 'UNSET':
        return "Aucune région : le nœud n'émet pas du tout."
    if code in REGIONS_SANS_TABLE_FIRMWARE:
        morceaux.append(
            "Cette région existe dans le protobuf mais n'a AUCUNE entrée dans la table des "
            "régions du firmware lue le 09/11/2026 : le nœud risque de rester muet, et il faudra "
            "l'appareil en main pour le rattraper."
        )
    if code in REGIONS_RADIOAMATEUR:
        morceaux.append(
            "Bande du service AMATEUR (2 m) : licence radioamateur obligatoire, et le service "
            "amateur interdit le trafic pour le compte de tiers — donc l'usage opérationnel."
        )
    table = TABLE_REGIONS_FIRMWARE.get(code)
    if table:
        debut, fin, cycle, puissance = table
        morceaux.append(
            f"Le firmware émettra entre {debut} et {fin} MHz, plafonné à {puissance} dBm, "
            f"rapport cyclique {cycle} %."
        )
    if code in ('EU_868', 'EU_433'):
        morceaux.append(AVERTISSEMENT_FRANCE)
    else:
        morceaux.append(
            "Région hors France : à n'employer que si le nœud est réellement exploité dans ce "
            "pays. " + AVERTISSEMENT_FRANCE
        )
    return " ".join(morceaux)


AVERTISSEMENTS_REGION = {code: _avertissement_region(code) for code in REGIONS}

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
                "pas du tout. Les trente-quatre régions du firmware sont proposées : chacune "
                "porte son propre avertissement, parce que 868 MHz ne désigne pas la même bande "
                "ni les mêmes conditions selon le territoire.",
                refusees=("UNSET",),
                avertissements_par_valeur=AVERTISSEMENTS_REGION,
                reglementaire=True,
                avertissement=AVERTISSEMENT_FRANCE,
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
                1, 36, "Puissance d'émission (dBm)",
                "27 dBm correspond à 500 mW, le plafond que le firmware applique à la région "
                "EU_868 (bande 869,4-869,65 MHz). Alimente aussi la correction du diagnostic "
                "des liaisons. Le maximum accepté ici (36 dBm) est celui de la région la plus "
                "permissive du firmware, pas une autorisation.",
                reglementaire=True,
                avertissement=(
                    "Le firmware ramène normalement la puissance au plafond de la région — MAIS "
                    "il ne le fait PAS si le propriétaire du nœud est marqué « licencié » "
                    "(`is_licensed`, vérifié le 09/11/2026 dans applyModemConfig() et "
                    "limitPower()). Ce garde-fou n'est donc pas une garantie : une valeur "
                    "au-dessus du plafond peut réellement partir dans l'air. " + AVERTISSEMENT_FRANCE
                ),
            ),
            "override_duty_cycle": Booleen(
                "Désactiver le limiteur de rapport cyclique",
                "Vrai = le nœud n'applique plus de limite d'occupation du temps d'antenne.",
                reglementaire=True,
                avertissement=(
                    "Vérifié le 09/11/2026 dans `AirTime::isTxAllowedAirUtil()` : cette case "
                    "fait sauter entièrement le contrôle d'occupation. Sans elle, le firmware "
                    "mesure le temps d'émission sur une fenêtre glissante d'une heure et "
                    "s'arrête à la MOITIÉ du rapport cyclique de la région — soit 5 % effectifs "
                    "en EU_868, donc deux fois plus strict que la condition réglementaire de "
                    "10 %. La désactiver supprime la seule chose qui fasse respecter ces 10 % "
                    "côté appareil : le respect redevient entièrement votre affaire. Sur une "
                    "bande partagée, un nœud qui émet sans limite dégrade le réseau de tous les "
                    "autres, secours compris. " + AVERTISSEMENT_FRANCE
                ),
            ),
            "override_frequency": Reel(
                400.0, 1000.0, "Fréquence imposée (MHz)",
                "0 = désactivé, le nœud suit le plan de canaux de sa région. Toute autre valeur "
                "est employée telle quelle, en MHz.",
                valeurs_speciales=(0,),
                reglementaire=True,
                avertissement=(
                    "Vérifié le 09/11/2026 dans `applyModemConfig()` : la valeur est prise "
                    "directement comme fréquence en MHz, elle court-circuite le calcul de canal "
                    "et met le numéro de canal à -1. Le plafond de puissance de la région reste "
                    "appliqué, mais plus rien ne garantit que la fréquence soit dans une bande "
                    "autorisée. Sur un relais en point haut inaccessible, l'erreur n'est pas "
                    "rattrapable à distance : le nœud n'écoute plus sur la fréquence du réseau. "
                    + AVERTISSEMENT_FRANCE
                ),
            ),
            "frequency_offset": Reel(
                -10.0, 10.0, "Décalage de fréquence (MHz)",
                "Corrige l'erreur du quartz de l'appareil. Se compte en fractions de MHz : "
                "0,001 MHz = 1 kHz.",
                reglementaire=True,
                avertissement=(
                    "Vérifié le 09/11/2026 : la valeur est ADDITIONNÉE EN MHz à la fréquence "
                    "calculée (`saveFreq(freq + loraConfig.frequency_offset)`). Un chiffre entier "
                    "saisi en croyant écrire des kHz déplace donc le nœud de plusieurs MHz, hors "
                    "de la bande et hors du réseau. " + AVERTISSEMENT_FRANCE
                ),
            ),
            "channel_num": Entier(
                0, 104, "Numéro de canal",
                "0 = calculé à partir du nom du canal principal, ce qui est le comportement "
                "normal. Sinon, index du créneau de fréquence dans la bande de la région.",
                reglementaire=True,
                avertissement=(
                    "Index à partir de 1, et le firmware le prend MODULO le nombre de créneaux "
                    "de la région (vérifié le 09/11/2026) : une valeur trop grande ne provoque "
                    "aucune erreur, elle fait simplement atterrir le nœud sur une autre "
                    "fréquence, en silence. Le nombre de créneaux dépend de la région ET de la "
                    "largeur de bande — la bande EU_868 du firmware ne fait que 250 kHz de large, "
                    "donc un seul créneau à 250 kHz de largeur de bande. "
                    + AVERTISSEMENT_FRANCE
                ),
            ),
            "tx_enabled": Booleen(
                "Émission activée",
                "Faux = le nœud écoute sans jamais émettre.",
                avertissement=(
                    "Sur un nœud administré à distance, le mettre à faux coupe le seul chemin "
                    "par lequel on pourrait le rallumer : il faudra l'appareil en main. C'est le "
                    "réglage le plus irréversible de cette page."
                ),
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
    """Section inconnue, champ non modifiable, valeur hors bornes, ou confirmation manquante."""


def champs_reglementaires(section, valeurs):
    """Les réglages demandés qui décident de ce qui part dans l'air."""
    description = SECTIONS.get(section) or {}
    champs = description.get("champs", {})
    return sorted(nom for nom in (valeurs or {})
                  if nom in champs and champs[nom].reglementaire)


def valider_reglages(section, valeurs, confirmation_reglementaire=False):
    """Valide `{champ: valeur}` pour une section, et renvoie les valeurs normalisées.

    Refuse une section inconnue, un champ hors liste blanche, une valeur du mauvais type ou hors
    bornes, et un ensemble vide — « aucune modification » est une erreur d'appel, pas une
    opération réussie.

    Refuse aussi un réglage `reglementaire` sans `confirmation_reglementaire`. Ce n'est pas une
    protection technique — l'exploitant peut confirmer et poser la valeur qu'il veut, c'est le
    but. C'est une case qu'on ne coche pas par inadvertance, et une trace nominative : la
    confirmation reste dans les paramètres de la tâche et dans le journal d'audit."""
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

    reglementaires = [nom for nom in sorted(valeurs) if champs[nom].reglementaire]
    if reglementaires and not confirmation_reglementaire:
        raise ReglageInvalide(
            "Réglage(s) sous contrainte réglementaire : "
            + ", ".join(f"{nom} ({champs[nom].libelle})" for nom in reglementaires)
            + ". Ils décident de la bande, de la puissance ou de l'occupation du temps "
              "d'antenne. Pour les écrire, confirmer explicitement "
              "(`confirmation_reglementaire: true`) : la demande est alors nominative et "
              "conservée au journal d'audit. " + AVERTISSEMENT_FRANCE
        )
    return normalisees


def catalogue():
    """Description des sections et de leurs champs, pour que l'interface construise son
    formulaire sans dupliquer ni les bornes, ni les libellés, ni les avertissements.

    Forme : `{"sections": {...}, "avertissement_france": "...", "regions_firmware": {...}}`.
    L'enveloppe existe pour que le texte réglementaire et la table des régions du firmware ne
    soient écrits qu'une fois, ici, et pas recopiés dans le frontend où ils divergeraient."""
    return {
        "sections": {
            nom: {
                "libelle": section["libelle"],
                "module": section["module"],
                "redemarre": section["redemarre"],
                # Vrai dès qu'un champ de la section est sous contrainte réglementaire : permet à
                # l'interface de marquer la section sans réinspecter chaque champ.
                "reglementaire": any(c.reglementaire for c in section["champs"].values()),
                "champs": {cle: champ.decrire() for cle, champ in section["champs"].items()},
            }
            for nom, section in SECTIONS.items()
        },
        "avertissement_france": AVERTISSEMENT_FRANCE,
        "regions_firmware": {
            code: {"debut_mhz": debut, "fin_mhz": fin, "rapport_cyclique_pct": cycle,
                   "puissance_max_dbm": puissance}
            for code, (debut, fin, cycle, puissance) in TABLE_REGIONS_FIRMWARE.items()
        },
        "regions_sans_table_firmware": sorted(REGIONS_SANS_TABLE_FIRMWARE),
        "regions_radioamateur": sorted(REGIONS_RADIOAMATEUR),
    }
