"""Par où passer pour joindre un nœud Meshtastic.

Deux questions qu'il ne faut surtout pas confondre, et c'est tout l'objet de ce module :

1. **Quelle passerelle a entendu ce nœud ?** C'est une OBSERVATION, lue dans `LiaisonMeshtastic`
   de source `RF` : une passerelle MQTT a reçu un paquet de ce nœud sans relais intermédiaire
   (`hop_start == hop_limit`, voir `_observer_liaison_rf` dans `meshtastic-bridge/bridge.py`).
   Elle dit par où le trafic du nœud ARRIVE jusqu'à nous.

2. **Par où faut-il émettre pour l'atteindre ?** Ce n'est pas la même chose, pour trois raisons
   qu'on ne devine pas :

   a. **Le broker cloisonne.** Un nœud entendu via le broker d'un réseau n'est joignable qu'en
      publiant sur CE broker : nos autres companions publient dans un autre réseau, qui ne
      communique pas avec celui-là. Le companion à employer est donc celui qui a vu le nœud
      (`ContactMeshtastic.compagnon`, le plus récent quand plusieurs l'ont vu), jamais un
      companion choisi au hasard.

   b. **La passerelle qui entend n'est pas forcément la nôtre.** Sur un broker partagé
      (ex. Gaulix) la plupart des passerelles appartiennent à d'autres. On voit alors le nœud
      sans rien maîtriser du dernier saut : la descente dépend du `downlink_enabled` de cette
      passerelle, réglage qu'on ne peut pas lire chez quelqu'un d'autre. Le résultat distingue
      donc explicitement les passerelles « à nous » des autres.

   c. **Une liaison est orientée.** « La passerelle a entendu le nœud » n'implique PAS « le nœud
      entend la passerelle » — l'asymétrie est le cas courant, c'est même l'objet de
      `core/analyse_liaisons.py`. Chaque saut du chemin porte donc `retour_prouve` : vrai
      seulement si le sens inverse a été observé lui aussi. Un chemin dont le retour n'est pas
      prouvé est un chemin pour ÉCOUTER, pas forcément pour PARLER.

Le nombre de sauts compte aussi, et il est actionnable : Meshtastic décrémente `hop_limit` à
chaque relais, et sa valeur par défaut est 3 (maximum 7). Un nœud à 4 sauts d'une passerelle est
hors d'atteinte avec le réglage par défaut, sans que rien ne le signale à l'émetteur — le paquet
est simplement abandonné en route.

Ce module ne CHOISIT pas un chemin : Meshtastic inonde, personne ne route explicitement. Il dit
par quel companion émettre, et ce que le réseau observé permet d'affirmer sur l'atteignabilité —
y compris le relais qui est un point de passage obligé, donc une panne unique.

Équivalent Meshtastic de `core/routage_mesh.py` (MeshCore), dont il reprend le principe : jamais
un choix opaque, le résultat porte toujours une `raison` lisible.
"""
import datetime
from collections import defaultdict, deque

from django.utils import timezone

from .models import (
    CompagnonMeshtastic, ContactMeshtastic, LiaisonMeshtastic, SourceLiaisonMeshtastic,
)

# Fenêtre d'observation des liaisons. Sept jours : une semaine lisse les nœuds qui n'émettent
# qu'épisodiquement, sans remonter à une topologie périmée.
FENETRE_JOURS = 7
# Au-delà, un nœud n'est plus considéré comme actif (même convention que core/analyse_liaisons.py).
HEURES_RECENT = 24
# Valeur par défaut de `hop_limit` dans le firmware Meshtastic, et son maximum protocolaire.
HOP_LIMIT_DEFAUT = 3
HOP_LIMIT_MAX = 7


def _rang(contact, plancher):
    """Clé de préférence entre deux contacts du même nœud vus par des companions différents."""
    return contact.dernier_advert or plancher


def _nom_noeud(contact, num):
    if contact is not None and (contact.long_name or contact.short_name):
        return contact.long_name or contact.short_name
    return f"!{num:08x}"


class _Sens:
    """Agrégat d'une liaison orientée toutes sources confondues : « recepteur a entendu emetteur ».

    Plusieurs lignes `LiaisonMeshtastic` peuvent décrire le même sens (une par source) ; on garde
    le meilleur SNR, la somme des observations et la date la plus récente."""

    def __init__(self):
        self.snr = None
        self.rssi = None
        self.nombre = 0
        self.dernier_vu = None
        self.sources = set()

    def ajouter(self, liaison):
        if liaison.snr is not None and (self.snr is None or liaison.snr > self.snr):
            self.snr = liaison.snr
            self.rssi = liaison.rssi
        self.nombre += liaison.nombre
        if self.dernier_vu is None or liaison.dernier_vu > self.dernier_vu:
            self.dernier_vu = liaison.dernier_vu
        self.sources.add(liaison.source)


def router(environment, maintenant=None, node_num=None):
    """Routage de tous les nœuds connus d'une zone, ou d'un seul si `node_num` est donné.

    Une seule passe sur les contacts et sur la fenêtre de liaisons : le graphe est construit en
    mémoire puis parcouru, parce que la question « par où le joindre ? » se pose pour toutes les
    lignes d'un tableau à la fois, et qu'une requête par nœud serait un N+1 à l'échelle d'un
    réseau départemental."""
    maintenant = maintenant or timezone.now()
    depuis = maintenant - datetime.timedelta(days=FENETRE_JOURS)
    recent = maintenant - datetime.timedelta(hours=HEURES_RECENT)
    plancher = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    contacts = {}
    for contact in ContactMeshtastic.objects.filter(environment=environment).select_related('compagnon'):
        connu = contacts.get(contact.node_num)
        if connu is None or _rang(contact, plancher) > _rang(connu, plancher):
            contacts[contact.node_num] = contact

    # `entendu_par[emetteur][recepteur]` : qui a entendu qui, agrégé. Les sauts de traceroute sont
    # retenus ici — ils prouvent bien un saut radio direct — mais leur récepteur n'est PAS compté
    # comme passerelle : un relais traversé ne publie pas forcément sur MQTT.
    entendu_par = defaultdict(dict)
    passerelles = set()
    for liaison in LiaisonMeshtastic.objects.filter(environment=environment, dernier_vu__gte=depuis):
        if liaison.emetteur == liaison.recepteur:
            continue
        sens = entendu_par[liaison.emetteur].setdefault(liaison.recepteur, _Sens())
        sens.ajouter(liaison)
        if liaison.source == SourceLiaisonMeshtastic.RF:
            passerelles.add(liaison.recepteur)

    # Arêtes inversées, pour un parcours en largeur qui part des passerelles.
    entend = defaultdict(set)
    for emetteur, recepteurs in entendu_par.items():
        for recepteur in recepteurs:
            entend[recepteur].add(emetteur)

    sauts = {num: 0 for num in passerelles}
    file = deque(passerelles)
    while file:
        courant = file.popleft()
        distance = sauts[courant]
        if distance >= HOP_LIMIT_MAX:
            continue
        for emetteur in entend.get(courant, ()):
            if emetteur not in sauts:
                sauts[emetteur] = distance + 1
                file.append(emetteur)

    nos_passerelles = set(
        CompagnonMeshtastic.objects.filter(environment=environment)
        .values_list('node_num', flat=True)
    )

    def nom(num):
        return _nom_noeud(contacts.get(num), num)

    def retour_prouve(emetteur, recepteur):
        """Le sens inverse (« emetteur a entendu recepteur ») a-t-il été observé ?"""
        return recepteur in entendu_par and emetteur in entendu_par[recepteur]

    def prochains_sauts(num):
        """Voisins qui rapprochent d'une passerelle — plusieurs = pas de point de passage unique."""
        distance = sauts.get(num)
        if not distance:
            return []
        return [r for r in entendu_par.get(num, {}) if sauts.get(r, HOP_LIMIT_MAX + 1) == distance - 1]

    def chemin_de(num):
        """Un chemin de longueur minimale du nœud vers une passerelle, le meilleur SNR d'abord.

        « Un » et pas « le » : plusieurs chemins de même longueur peuvent exister, et Meshtastic
        n'en emprunte aucun en particulier puisqu'il inonde. Celui-ci sert à nommer les relais
        traversés, pas à prédire la route réelle."""
        chemin, courant = [num], num
        while sauts.get(courant):
            candidats = prochains_sauts(courant)
            if not candidats:
                break
            suivant = max(
                candidats,
                key=lambda r: (entendu_par[courant][r].snr if entendu_par[courant][r].snr is not None else -999),
            )
            chemin.append(suivant)
            courant = suivant
            if len(chemin) > HOP_LIMIT_MAX + 1:
                break
        return chemin

    numeros = [node_num] if node_num is not None else sorted(contacts)
    routes = []
    for num in numeros:
        contact = contacts.get(num)
        distance = sauts.get(num)
        directes = [
            {
                "node_num": recepteur,
                "nom": nom(recepteur),
                "snr": sens.snr,
                "rssi": sens.rssi,
                "nombre": sens.nombre,
                "dernier_vu": sens.dernier_vu.isoformat() if sens.dernier_vu else None,
                "nous": recepteur in nos_passerelles,
                "retour_prouve": retour_prouve(num, recepteur),
            }
            for recepteur, sens in sorted(entendu_par.get(num, {}).items())
            if recepteur in passerelles
        ]
        directes.sort(key=lambda p: (p["snr"] is None, -(p["snr"] or 0)))

        chemin = chemin_de(num) if distance else [num]
        etapes = []
        for position in range(len(chemin) - 1):
            emetteur, recepteur = chemin[position], chemin[position + 1]
            sens = entendu_par[emetteur][recepteur]
            etapes.append({
                "de": emetteur, "nom_de": nom(emetteur),
                "vers": recepteur, "nom_vers": nom(recepteur),
                "snr": sens.snr,
                "sources": sorted(sens.sources),
                "retour_prouve": retour_prouve(emetteur, recepteur),
            })

        candidats = prochains_sauts(num)
        relais_obligatoire = None
        if distance is not None and distance >= 2 and len(candidats) == 1:
            relais_obligatoire = {"node_num": candidats[0], "nom": nom(candidats[0])}

        routes.append({
            "node_num": num,
            "nom": nom(num),
            "actif": bool(contact and contact.dernier_advert and contact.dernier_advert >= recent),
            "dernier_advert": contact.dernier_advert.isoformat() if contact and contact.dernier_advert else None,
            "compagnon_id": str(contact.compagnon_id) if contact else None,
            "compagnon_nom": contact.compagnon.nom if contact else None,
            "broker": f"{contact.compagnon.broker_host}:{contact.compagnon.broker_port}" if contact else None,
            "passerelles": directes,
            "passerelles_a_nous": sum(1 for p in directes if p["nous"]),
            "sauts": distance,
            "chemin": etapes,
            "relais_obligatoire": relais_obligatoire,
            "retour_prouve": bool(etapes) and all(etape["retour_prouve"] for etape in etapes),
            "hop_limit_suffisant": None if distance is None else distance <= HOP_LIMIT_DEFAUT,
            "raison": _raison(num, contact, distance, directes, relais_obligatoire, etapes),
        })

    return {
        "routes": routes,
        "fenetre_jours": FENETRE_JOURS,
        "hop_limit_defaut": HOP_LIMIT_DEFAUT,
        "hop_limit_max": HOP_LIMIT_MAX,
        "calcule_le": maintenant.isoformat(),
    }


def _raison(num, contact, distance, directes, relais_obligatoire, etapes):
    """Phrase lisible, affichée telle quelle : l'opérateur doit pouvoir contester la conclusion."""
    if contact is None:
        return "Nœud inconnu dans cette zone."
    broker = contact.compagnon.nom
    if distance is None:
        return (
            f"Aucune passerelle ne l'a entendu depuis {FENETRE_JOURS} jours : rien ne permet "
            f"d'affirmer qu'on peut l'atteindre. Son identité nous vient de « {broker} »."
        )

    if distance == 0:
        # Le nœud est lui-même une passerelle : il publie sur MQTT, on l'atteint sans relais.
        return (
            f"Ce nœud est lui-même une passerelle MQTT : il publie sur « {broker} », "
            "aucun relais radio n'est nécessaire pour l'atteindre."
        )

    if distance == 1 and directes:
        premiere = directes[0]
        qui = "notre passerelle" if premiere["nous"] else "une passerelle qui n'est pas à nous"
        marge = f", SNR {premiere['snr']:+.1f} dB" if premiere["snr"] is not None else ""
        phrase = f"Entendu directement par {qui} « {premiere['nom']} »{marge}. Émettre par « {broker} »."
        if len(directes) == 1:
            phrase += " Une seule passerelle l'entend : si elle tombe, le nœud disparaît."
        else:
            phrase += f" {len(directes)} passerelles l'entendent."
        if not premiere["retour_prouve"]:
            phrase += " Le sens retour n'a jamais été observé : on l'entend, rien ne prouve qu'il nous entende."
        if not premiere["nous"]:
            phrase += " Son `downlink_enabled` nous est inconnu : la descente n'est pas garantie."
        return phrase

    arrivee = etapes[-1]["nom_vers"] if etapes else "une passerelle"
    phrase = f"À {distance} sauts de la passerelle « {arrivee} ». Émettre par « {broker} »."
    if relais_obligatoire:
        phrase += f" Tout passe par « {relais_obligatoire['nom']} » : point de panne unique."
    if distance > HOP_LIMIT_DEFAUT:
        phrase += (
            f" {distance} sauts dépassent le hop_limit par défaut ({HOP_LIMIT_DEFAUT}) :"
            " un message émis sans augmenter cette limite est abandonné en route, sans erreur."
        )
    if etapes and not all(etape["retour_prouve"] for etape in etapes):
        manquants = [e["nom_de"] + " → " + e["nom_vers"] for e in etapes if not e["retour_prouve"]]
        phrase += f" Sens retour jamais observé sur : {', '.join(manquants)}."
    return phrase
