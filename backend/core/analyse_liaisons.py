"""Analyse des liaisons radio Meshtastic : liaisons à sens unique, déséquilibrées, relais sourds.

Porté de `carte-live/src/asymetrie.js` de `sauveteur71/carte-live-meshtastic` (GPL-3.0, repris
avec son autorisation). Le code est réécrit en Python sur les modèles d'Assista-Crise, mais le
RAISONNEMENT est le sien, et c'est lui qui a de la valeur — il tient à quelques précautions qu'on
ne devine pas :

1. **Une liaison est orientée.** `a → b` veut dire « b a entendu a directement ». « B entend A »
   n'implique rien sur « A entend B ».

2. **On ne peut conclure « à sens unique » que pour un nœud qui RAPPORTE ce qu'il entend** : une
   passerelle MQTT (source RF) ou un nœud qui publie son voisinage (NeighborInfo). Un saut de
   traceroute ne suffit pas : un relais qui ne rapporte rien ferait passer pour « à sens unique »
   tout ce qu'il entend sans le dire.

3. **Un rapport de voisinage Meshtastic est plafonné à 10 voisins.** Si un nœud en déclare 10,
   l'absence d'un voisin n'est PAS une preuve : la liste était pleine.

4. **Il faut de la régularité**, pas une observation isolée : au moins 3 observations.

5. **Relais sourd** : sur une liaison réciproque,
   `SNR(P entend X) − SNR(X entend P) = (Ptx X − Ptx P) + (bruit X − bruit P)`.
   L'écart de puissance retiré, il reste le bruit propre à X, ou sa désensibilisation. On prend la
   MÉDIANE sur ses voisins — une seule mesure ne prouve rien — et il faut au moins deux mesures
   concordantes dont une réciproque.
   Une liaison que X ne rapporte jamais alors que P l'entend fort donne une borne basse : X l'a
   reçue sous son seuil de démodulation.

Limite propre à Assista-Crise : la puissance d'émission des nœuds n'est pas connue (aucun champ ne
la porte, elle viendrait d'une lecture de configuration à distance qui n'existe pas encore). La
correction de puissance est donc nulle, ce qui rend la détection de relais sourd plus bruyante que
la sienne : un nœud qui émet simplement plus fort que ses voisins peut passer pour sourd. Le
champ `puissance_connue` du résultat le signale, et l'interface doit le dire.
"""
import datetime
import math
import statistics
from collections import defaultdict

from django.utils import timezone

from .models import ContactMeshtastic, LiaisonMeshtastic, SourceLiaisonMeshtastic

# Écart de SNR au-delà duquel un nœud est jugé sourd, en dB. Valeur de son implémentation.
SEUIL_SOURD_DB = 8.0
# Écart au-delà duquel une liaison réciproque est jugée déséquilibrée.
SEUIL_DESEQUILIBRE_DB = 10.0
# Un rapport de voisinage Meshtastic ne porte que 10 voisins : au-delà, une absence ne prouve rien.
PLAFOND_VOISINAGE = 10
# SNR minimal démodulable du preset LONG_FAST. Les autres presets diffèrent, mais le projet n'a
# aucun champ qui porte le preset d'un réseau : valeur par défaut, comme chez lui.
SEUIL_DEMODULATION_DB = -17.5
# Au-delà, une « liaison directe » est impossible : erreur de position ou de relais.
DISTANCE_MAX_KM = 120.0
# Fenêtre « récent » de l'analyse.
HEURES_RECENT = 24
# Nombre d'observations minimal pour conclure.
OBSERVATIONS_MIN = 3


def _distance_km(a, b):
    """Distance orthodromique entre deux points (lat, lon), ou None si l'un manque."""
    if not a or not b:
        return None
    r = math.pi / 180
    s = (math.sin(((b[0] - a[0]) * r) / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(((b[1] - a[1]) * r) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(min(1.0, s)))


class _Sens:
    """Meilleure observation d'un sens (a → b), toutes sources confondues."""

    __slots__ = ("a", "b", "nombre", "snr", "dernier_vu", "sources")

    def __init__(self, a, b):
        self.a, self.b = a, b
        self.nombre, self.snr, self.dernier_vu = 0, None, None
        self.sources = set()

    def ajouter(self, liaison):
        self.nombre += liaison.nombre or 1
        if self.dernier_vu is None or liaison.dernier_vu > self.dernier_vu:
            self.dernier_vu = liaison.dernier_vu
        if liaison.snr is not None and (self.snr is None or liaison.snr > self.snr):
            self.snr = liaison.snr
        self.sources.add(liaison.source)


def analyser(environment, maintenant=None):
    """Renvoie {sens_unique, desequilibrees, inaudibles, sourds} pour une zone."""
    maintenant = maintenant or timezone.now()
    recent = maintenant - datetime.timedelta(hours=HEURES_RECENT)

    noeuds = {}
    for contact in ContactMeshtastic.objects.filter(environment=environment):
        # Un même node_num peut être vu par plusieurs companions : on garde le plus récent.
        connu = noeuds.get(contact.node_num)
        if connu is None or (contact.dernier_advert and contact.dernier_advert > (connu.dernier_advert or contact.dernier_advert)):
            noeuds[contact.node_num] = contact

    sens = {}
    # Nœuds qui RAPPORTENT ce qu'ils entendent (RF ou voisinage) depuis 24 h -> émetteurs entendus.
    rapporteurs = defaultdict(set)
    passerelles = set()
    for liaison in LiaisonMeshtastic.objects.filter(
        environment=environment, dernier_vu__gte=maintenant - datetime.timedelta(days=7),
    ):
        if liaison.emetteur == liaison.recepteur:
            continue
        cle = (liaison.emetteur, liaison.recepteur)
        sens.setdefault(cle, _Sens(*cle)).ajouter(liaison)
        if liaison.dernier_vu >= recent and liaison.source in (
            SourceLiaisonMeshtastic.RF, SourceLiaisonMeshtastic.VOISINAGE,
        ):
            rapporteurs[liaison.recepteur].add(liaison.emetteur)
        if liaison.dernier_vu >= recent and liaison.source == SourceLiaisonMeshtastic.RF:
            passerelles.add(liaison.recepteur)

    def actif(num):
        contact = noeuds.get(num)
        return bool(contact and contact.dernier_advert and contact.dernier_advert >= recent)

    def nom(num):
        contact = noeuds.get(num)
        if contact and (contact.long_name or contact.short_name):
            return contact.long_name or contact.short_name
        return f"!{num:08x}"

    def position(num):
        contact = noeuds.get(num)
        if contact and contact.location:
            return (contact.location.y, contact.location.x)
        return None

    def trop_loin(a, b):
        d = _distance_km(position(a), position(b))
        return (d is not None and d > DISTANCE_MAX_KM), d

    sens_unique, desequilibrees = [], []
    paires_vues = set()

    for obs in sens.values():
        if obs.dernier_vu < recent or obs.nombre < OBSERVATIONS_MIN:
            continue
        a, b = obs.a, obs.b
        loin, distance = trop_loin(a, b)
        if loin:
            continue
        inverse = sens.get((b, a))

        if inverse is None:
            # A rapporte ce qu'il entend et B émet : A devrait l'entendre.
            if a not in rapporteurs or not actif(b):
                continue
            # Voisinage plein : l'absence de B n'est pas une preuve.
            if a not in passerelles and len(rapporteurs[a]) >= PLAFOND_VOISINAGE:
                continue
            sens_unique.append({
                "preuve": "passerelle" if a in passerelles else "voisinage",
                "entend": b, "entendu": a,
                "nom_entend": nom(b), "nom_entendu": nom(a),
                "snr": obs.snr, "nombre": obs.nombre, "sources": sorted(obs.sources),
                "distance_km": round(distance, 1) if distance is not None else None,
            })
        else:
            paire = (min(a, b), max(a, b))
            if (paire not in paires_vues and obs.snr is not None and inverse.snr is not None
                    and abs(obs.snr - inverse.snr) >= SEUIL_DESEQUILIBRE_DB
                    and inverse.dernier_vu >= recent):
                paires_vues.add(paire)
                fort, faible = (obs, inverse) if obs.snr > inverse.snr else (inverse, obs)
                desequilibrees.append({
                    "a": fort.a, "b": fort.b, "nom_a": nom(fort.a), "nom_b": nom(fort.b),
                    "snr_fort": fort.snr, "snr_faible": faible.snr,
                    "ecart_db": round(fort.snr - faible.snr, 1),
                    "distance_km": round(distance, 1) if distance is not None else None,
                })

    # Nœuds qui entendent leurs voisins mais que personne n'entend : souvent une antenne en
    # réception seulement, ou une émission en panne.
    entendus = {obs.a for obs in sens.values()}
    inaudibles = [
        {"node_num": num, "nom": nom(num), "entend": len(emetteurs),
         "voisins": [nom(x) for x in sorted(emetteurs)[:8]]}
        for num, emetteurs in rapporteurs.items()
        if len(emetteurs) >= 2 and num not in entendus and actif(num)
    ]

    return {
        "sens_unique": sorted(sens_unique, key=lambda x: -x["nombre"])[:100],
        "desequilibrees": sorted(desequilibrees, key=lambda x: -x["ecart_db"])[:100],
        "inaudibles": inaudibles,
        "sourds": _sourds(sens, rapporteurs, passerelles, recent, actif, nom, trop_loin),
        "puissance_connue": False,
        "calcule_le": maintenant.isoformat(),
    }


def _sourds(sens, rapporteurs, passerelles, recent, actif, nom, trop_loin):
    """Relais sourds : écart médian de SNR anormal entre ce qu'un nœud entend et ce qu'on entend
    de lui. Voir la docstring du module pour l'équation."""
    mesures = defaultdict(list)

    for obs in sens.values():
        # obs : obs.b a entendu obs.a, SNR mesuré CHEZ obs.b.
        x, p = obs.a, obs.b
        if obs.snr is None or obs.dernier_vu < recent:
            continue
        loin, _ = trop_loin(x, p)
        if loin:
            continue
        inverse = sens.get((p, x))
        # Correction de puissance impossible : aucun champ ne porte la puissance d'émission.
        correction = 0.0

        if inverse is not None and inverse.snr is not None and inverse.dernier_vu >= recent:
            mesures[x].append({
                "partenaire": p, "nom_partenaire": nom(p),
                "entendu_chez_partenaire": obs.snr, "entendu_chez_lui": inverse.snr,
                "ecart_db": round(obs.snr - inverse.snr - correction, 1), "borne": False,
            })
        elif (x in rapporteurs and actif(p) and obs.nombre >= OBSERVATIONS_MIN
              and (x in passerelles or len(rapporteurs[x]) < PLAFOND_VOISINAGE)):
            # X rapporte ce qu'il entend mais jamais P, alors que P l'entend : X l'a reçu sous son
            # seuil de démodulation. Ça ne donne qu'une BORNE BASSE de son écart.
            borne = obs.snr - SEUIL_DEMODULATION_DB - correction
            if borne >= SEUIL_SOURD_DB:
                mesures[x].append({
                    "partenaire": p, "nom_partenaire": nom(p),
                    "entendu_chez_partenaire": obs.snr, "entendu_chez_lui": None,
                    "ecart_db": round(borne, 1), "borne": True,
                })

    sourds = []
    for x, liste in mesures.items():
        reciproques = [m for m in liste if not m["borne"]]
        # Au moins deux voisins, et au moins une mesure réciproque : une borne basse seule ne
        # prouve rien (le partenaire peut simplement émettre très fort).
        if not actif(x) or len(liste) < 2 or not reciproques:
            continue
        mediane = statistics.median(m["ecart_db"] for m in liste)
        concordantes = sum(1 for m in liste if m["ecart_db"] >= SEUIL_SOURD_DB)
        if mediane < SEUIL_SOURD_DB or concordantes < 2:
            continue
        sourds.append({
            "node_num": x, "nom": nom(x), "ecart_db": round(mediane, 1),
            "nb_voisins": len(liste), "nb_concordantes": concordantes,
            "puissance_connue": False,
            "mesures": sorted(liste, key=lambda m: -m["ecart_db"])[:8],
        })
    return sorted(sourds, key=lambda s: -s["ecart_db"])
