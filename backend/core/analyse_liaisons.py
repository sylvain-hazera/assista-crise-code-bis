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

6. **La correction de puissance n'est appliquée que si elle est connue des DEUX côtés.** La
   puissance d'émission d'un nœud vient d'une lecture de configuration à distance
   (`TacheAdminMeshtastic`, type LIRE_CONFIG_LORA) : elle n'existe que pour les nœuds qu'on a
   effectivement interrogés. Sans elle, l'écart mesuré mélange le bruit du nœud et sa puissance,
   et un nœud qui émet simplement plus fort que ses voisins peut passer pour sourd. Le résultat
   porte donc `puissance_connue` globalement, par relais sourd ET par mesure : une conclusion
   corrigée et une conclusion non corrigée ne valent pas la même chose, et l'interface doit les
   distinguer.

   Piège à ne pas rater : `tx_power = 0` ne veut PAS dire 0 dBm. Le firmware l'interprète comme
   « applique le maximum autorisé pour la région » : c'est une puissance inconnue, traitée ici
   comme absente.

**Deux protocoles, un seul raisonnement** (10/11/2026). Le cœur (`_analyser`) ne connaît que des
identités opaques et des liaisons ; ce qui dépend du protocole est rassemblé dans une *source*
(`_SourceMeshtastic`, `_SourceMeshCore`). Ce n'est pas de l'abstraction gratuite : les six
précautions ci-dessus sont l'actif du module, et les dupliquer pour MeshCore aurait garanti
qu'une des deux copies finisse par en perdre une.

Ce que les deux protocoles ne partagent PAS, et que la source porte :

- **la preuve d'une absence.** Meshtastic plafonne son rapport de voisinage à 10 **sans le
  dire** : une absence n'y prouve jamais rien au-delà. MeshCore annonce son total
  (`neighbours_count`), donc l'absence PEUT être une preuve — voir
  `ReleveVoisinageMeshCore.complet` ;
- **l'identité.** Meshtastic désigne un nœud par un entier 32 bits ; MeshCore par une clé
  publique Ed25519, dont un rapport de voisinage ne donne qu'un **préfixe de 4 octets**. La
  source MeshCore résout ces préfixes et **écarte** ce qu'elle ne peut pas résoudre de façon
  certaine : conclure « à sens unique » sur un préfixe ambigu reviendrait à inventer une
  liaison, et une liaison fausse envoie quelqu'un sur un point haut.
"""
import datetime
import math
import statistics
from collections import defaultdict

from django.utils import timezone

from .models import (
    ConfigurationNoeudMeshtastic, ContactMeshCore, ContactMeshtastic, LiaisonMeshCore,
    LiaisonMeshtastic, ReleveVoisinageMeshCore, SourceLiaisonMeshtastic,
)

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


def _correction_db(puissances, a, b):
    """Écart de puissance d'émission entre `a` et `b`, et si on le connaît vraiment.

    `SNR(b entend a) - SNR(a entend b) = (Ptx a - Ptx b) + (bruit a - bruit b)`. Retirer le
    premier terme isole le second, qui est ce qu'on cherche. Si l'une des deux puissances
    manque, on ne corrige pas -- une demi-correction serait pire que pas de correction."""
    pa, pb = puissances.get(a), puissances.get(b)
    if pa is None or pb is None:
        return 0.0, False
    return float(pa - pb), True


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


class _Source:
    """Ce que le cœur de l'analyse a besoin de savoir, et rien de plus.

    Une sous-classe par protocole. Tout ce qui est ici dépend du protocole ; tout ce qui est
    dans `_analyser` n'en dépend pas."""

    #: Nom de la clé d'identité dans le résultat : le frontend Meshtastic lit `node_num`.
    cle_identite = "node_num"

    def __init__(self, environment):
        self.environment = environment

    def noeuds(self):
        """{identité: objet} des nœuds connus."""
        raise NotImplementedError

    def liaisons(self, depuis):
        """Liaisons observées depuis `depuis`, avec `.emetteur .recepteur .source .snr
        .nombre .dernier_vu`."""
        raise NotImplementedError

    def puissances(self):
        """{identité: dBm} pour les nœuds dont la puissance d'émission est connue."""
        return {}

    def nom(self, identite, noeud):
        raise NotImplementedError

    def actif(self, noeud, recent):
        raise NotImplementedError

    def position(self, noeud):
        return None

    def absence_est_preuve(self, identite, nombre_rapporte, est_passerelle):
        """« Si ce nœud ne rapporte pas X, est-ce une preuve qu'il ne l'entend pas ? »"""
        raise NotImplementedError


class _SourceMeshtastic(_Source):
    """Meshtastic : identités entières, puissance relevée par administration à distance."""

    cle_identite = "node_num"

    def noeuds(self):
        connus = {}
        for contact in ContactMeshtastic.objects.filter(environment=self.environment):
            # Un même node_num peut être vu par plusieurs companions : on garde le plus récent.
            connu = connus.get(contact.node_num)
            if connu is None or (contact.dernier_advert
                                 and contact.dernier_advert > (connu.dernier_advert or contact.dernier_advert)):
                connus[contact.node_num] = contact
        return connus

    def liaisons(self, depuis):
        return LiaisonMeshtastic.objects.filter(
            environment=self.environment, dernier_vu__gte=depuis,
        )

    def puissances(self):
        """0 est écarté : le firmware l'interprète comme « maximum de la région », c'est une
        puissance inconnue et non une puissance nulle."""
        return {
            config.node_num: config.puissance_emission_dbm
            for config in ConfigurationNoeudMeshtastic.objects.filter(
                environment=self.environment, puissance_emission_dbm__isnull=False,
            ).exclude(puissance_emission_dbm=0).only('node_num', 'puissance_emission_dbm')
        }

    def nom(self, identite, noeud):
        if noeud and (noeud.long_name or noeud.short_name):
            return noeud.long_name or noeud.short_name
        return f"!{identite:08x}"

    def actif(self, noeud, recent):
        return bool(noeud and noeud.dernier_advert and noeud.dernier_advert >= recent)

    def position(self, noeud):
        if noeud and noeud.location:
            return (noeud.location.y, noeud.location.x)
        return None

    def absence_est_preuve(self, identite, nombre_rapporte, est_passerelle):
        # Un rapport de voisinage Meshtastic ne porte que 10 voisins, et rien ne dit qu'il
        # était plein : au-delà, une absence ne prouve rien.
        return est_passerelle or nombre_rapporte < PLAFOND_VOISINAGE


class _SourceMeshCore(_Source):
    """MeshCore : identités par clé publique, et des voisins connus par PRÉFIXE.

    Deux différences portées ici, et nulle part ailleurs :

    1. **La résolution des préfixes.** `LiaisonMeshCore.emetteur_prefixe_hex` fait 4 octets par
       défaut. On ne garde une liaison que si son préfixe désigne **un seul** nœud connu. Les
       autres sont comptées dans `ecartees` et n'entrent pas dans l'analyse : conclure « à sens
       unique » sur un préfixe ambigu, c'est affirmer qu'un retour n'existe pas alors qu'on ne
       sait même pas de qui on parle.
    2. **L'absence peut être une preuve**, quand le relevé de voisinage était complet.
    """

    cle_identite = "pubkey"

    def __init__(self, environment):
        super().__init__(environment)
        self.ecartees_ambigues = 0
        self.ecartees_inconnues = 0
        self._par_prefixe = defaultdict(list)
        self._releves = {}

    def noeuds(self):
        connus = {}
        for contact in ContactMeshCore.objects.filter(environment=self.environment):
            cle = (contact.pubkey_hex or '').lower()
            if not cle:
                continue
            connu = connus.get(cle)
            if connu is None or (contact.dernier_advert
                                 and contact.dernier_advert > (connu.dernier_advert or contact.dernier_advert)):
                connus[cle] = contact
        self._par_prefixe.clear()
        for cle in connus:
            # Indexé par toutes les longueurs de préfixe utiles : un relevé peut en rendre 4,
            # un autre 8, et ils ne se comparent pas entre eux.
            for octets in range(1, 17):
                self._par_prefixe[cle[:octets * 2]].append(cle)
        self._releves = {
            releve.pubkey_hex.lower(): releve.complet
            for releve in ReleveVoisinageMeshCore.objects.filter(environment=self.environment)
        }
        return connus

    def _resoudre(self, prefixe):
        """Un préfixe vers UNE clé complète, ou None s'il est ambigu ou inconnu."""
        candidats = self._par_prefixe.get((prefixe or '').lower())
        if not candidats:
            self.ecartees_inconnues += 1
            return None
        if len(candidats) > 1:
            self.ecartees_ambigues += 1
            return None
        return candidats[0]

    def liaisons(self, depuis):
        resolues = []
        for liaison in LiaisonMeshCore.objects.filter(
            environment=self.environment, dernier_vu__gte=depuis,
        ):
            emetteur = self._resoudre(liaison.emetteur_prefixe_hex)
            if emetteur is None:
                continue
            liaison.emetteur = emetteur
            liaison.recepteur = (liaison.recepteur_pubkey_hex or '').lower()
            resolues.append(liaison)
        return resolues

    def nom(self, identite, noeud):
        if noeud and noeud.nom:
            return noeud.nom
        return identite[:12]

    def actif(self, noeud, recent):
        return bool(noeud and noeud.dernier_advert and noeud.dernier_advert >= recent)

    def position(self, noeud):
        if noeud and noeud.location:
            return (noeud.location.y, noeud.location.x)
        return None

    def absence_est_preuve(self, identite, nombre_rapporte, est_passerelle):
        # MeshCore annonce son total de voisins : on SAIT si la liste était complète, au lieu
        # de supposer comme côté Meshtastic.
        return est_passerelle or self._releves.get(identite, False)


def analyser(environment, maintenant=None):
    """Analyse du réseau Meshtastic. Signature inchangée : c'est l'entrée de l'API."""
    return _analyser(_SourceMeshtastic(environment), maintenant)


def analyser_meshcore(environment, maintenant=None):
    """Analyse du réseau MeshCore.

    Le résultat porte en plus `liaisons_ecartees`, parce qu'un diagnostic calculé sur une partie
    des liaisons seulement doit le dire : un réseau où la moitié des préfixes sont ambigus ne
    donne pas des conclusions de même valeur."""
    source = _SourceMeshCore(environment)
    resultat = _analyser(source, maintenant)
    resultat["liaisons_ecartees"] = {
        "prefixe_ambigu": source.ecartees_ambigues,
        "prefixe_inconnu": source.ecartees_inconnues,
    }
    return resultat


def _analyser(source, maintenant=None):
    """Renvoie {sens_unique, desequilibrees, inaudibles, sourds} pour une zone.

    Ne connaît aucun protocole : les identités sont opaques, et tout ce qui en dépend est
    demandé à `source`."""
    maintenant = maintenant or timezone.now()
    recent = maintenant - datetime.timedelta(hours=HEURES_RECENT)
    puissances = source.puissances()
    noeuds = source.noeuds()

    sens = {}
    # Nœuds qui RAPPORTENT ce qu'ils entendent (RF ou voisinage) depuis 24 h -> émetteurs entendus.
    rapporteurs = defaultdict(set)
    passerelles = set()
    for liaison in source.liaisons(maintenant - datetime.timedelta(days=7)):
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
        return source.actif(noeuds.get(num), recent)

    def nom(num):
        return source.nom(num, noeuds.get(num))

    def position(num):
        return source.position(noeuds.get(num))

    def absence_prouve(num):
        """« Si ce nœud ne rapporte pas X, est-ce une preuve qu'il ne l'entend pas ? »"""
        return source.absence_est_preuve(num, len(rapporteurs[num]), num in passerelles)

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
            # L'absence de B dans ce que A rapporte doit être une PREUVE, pas un effet de
            # bord d'une liste tronquée (voir _Source.absence_est_preuve).
            if not absence_prouve(a):
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
            # Correction de puissance (ajout d'Assista-Crise à son algorithme) : un écart qui
            # s'explique entièrement par une différence de puissance d'émission connue n'est pas
            # un déséquilibre à signaler. `correction_db` est renvoyée pour que la conclusion
            # reste vérifiable.
            correction, connue = _correction_db(puissances, obs.a, obs.b)
            if (paire not in paires_vues and obs.snr is not None and inverse.snr is not None
                    and abs(obs.snr - inverse.snr - correction) >= SEUIL_DESEQUILIBRE_DB
                    and inverse.dernier_vu >= recent):
                paires_vues.add(paire)
                corrige = obs.snr - inverse.snr - correction
                fort, faible = (obs, inverse) if corrige > 0 else (inverse, obs)
                desequilibrees.append({
                    "a": fort.a, "b": fort.b, "nom_a": nom(fort.a), "nom_b": nom(fort.b),
                    "snr_fort": fort.snr, "snr_faible": faible.snr,
                    "ecart_db": round(abs(corrige), 1),
                    "correction_db": round(correction, 1),
                    "puissance_connue": connue,
                    "distance_km": round(distance, 1) if distance is not None else None,
                })

    # Nœuds qui entendent leurs voisins mais que personne n'entend : souvent une antenne en
    # réception seulement, ou une émission en panne.
    entendus = {obs.a for obs in sens.values()}
    inaudibles = [
        {source.cle_identite: num, "nom": nom(num), "entend": len(emetteurs),
         "voisins": [nom(x) for x in sorted(emetteurs)[:8]]}
        for num, emetteurs in rapporteurs.items()
        if len(emetteurs) >= 2 and num not in entendus and actif(num)
    ]

    return {
        "sens_unique": sorted(sens_unique, key=lambda x: -x["nombre"])[:100],
        "desequilibrees": sorted(desequilibrees, key=lambda x: -x["ecart_db"])[:100],
        "inaudibles": inaudibles,
        "sourds": _sourds(sens, recent, actif, nom, trop_loin, puissances, absence_prouve,
                          source.cle_identite),
        # Vrai dès qu'au moins un nœud a une puissance relevée : chaque conclusion porte en plus
        # son propre `puissance_connue`, parce qu'une correction peut s'appliquer à une paire et
        # pas à la suivante.
        "puissance_connue": bool(puissances),
        "noeuds_puissance_connue": len(puissances),
        "calcule_le": maintenant.isoformat(),
    }


def _sourds(sens, recent, actif, nom, trop_loin, puissances, absence_prouve, cle_identite):
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
        # Écart de puissance d'émission entre X et son partenaire, s'il est connu des deux côtés.
        correction, connue = _correction_db(puissances, x, p)

        if inverse is not None and inverse.snr is not None and inverse.dernier_vu >= recent:
            mesures[x].append({
                "partenaire": p, "nom_partenaire": nom(p),
                "entendu_chez_partenaire": obs.snr, "entendu_chez_lui": inverse.snr,
                "ecart_db": round(obs.snr - inverse.snr - correction, 1), "borne": False,
                "correction_db": round(correction, 1), "puissance_connue": connue,
            })
        elif actif(p) and obs.nombre >= OBSERVATIONS_MIN and absence_prouve(x):
            # X rapporte ce qu'il entend mais jamais P, alors que P l'entend : X l'a reçu sous son
            # seuil de démodulation. Ça ne donne qu'une BORNE BASSE de son écart.
            borne = obs.snr - SEUIL_DEMODULATION_DB - correction
            if borne >= SEUIL_SOURD_DB:
                mesures[x].append({
                    "partenaire": p, "nom_partenaire": nom(p),
                    "entendu_chez_partenaire": obs.snr, "entendu_chez_lui": None,
                    "ecart_db": round(borne, 1), "borne": True,
                    "correction_db": round(correction, 1), "puissance_connue": connue,
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
            cle_identite: x, "nom": nom(x), "ecart_db": round(mediane, 1),
            "nb_voisins": len(liste), "nb_concordantes": concordantes,
            # Vrai seulement si TOUTES les mesures retenues ont pu être corrigées : il suffit
            # d'un voisin de puissance inconnue pour que la médiane redevienne discutable.
            "puissance_connue": all(m["puissance_connue"] for m in liste),
            "mesures": sorted(liste, key=lambda m: -m["ecart_db"])[:8],
        })
    return sorted(sourds, key=lambda s: -s["ecart_db"])
