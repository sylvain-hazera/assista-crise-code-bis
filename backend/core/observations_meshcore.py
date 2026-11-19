"""Ce qu'une trame MeshCore entendue dit du réseau (19/11/2026).

Jumeau, côté MeshCore, de ce que le pont Meshtastic tire de chaque paquet. Trois sources
alimentent ce module, et c'est voulu qu'elles passent par le même code :

- les trames que NOTRE companion entend (événement RX_LOG_DATA, rapportées par le pont) ;
- les trames publiées par les observateurs MQTT (`ingestion_observateurs_meshcore`) ;
- les traceroutes lancés depuis l'interface (`liaisons_d_un_traceroute`).

**Ce qu'une trame prouve, et rien de plus :**

1. Le SNR mesuré est celui du DERNIER émetteur : le dernier relais du chemin d'un paquet en
   inondation, ou l'auteur lui-même si le chemin est vide. Son identité n'est connue que si le
   chemin la donne (préfixe du relais) ou si la charge la porte en clair et signée (ADVERT).
   Tout autre paquet sans chemin est anonyme : on n'en tire aucune liaison.
2. Deux relais consécutifs d'un chemin d'inondation se sont entendus (source CHEMIN), sans SNR.
   Seulement en inondation : un chemin DIRECT est la route prévue, pas celle parcourue.
3. Une trame TRACE porte des SNR dans son champ de chemin, pas des préfixes : elle est exclue
   ici et traitée par `liaisons_d_un_traceroute`.

**Préfixes.** L'émetteur d'une liaison peut rester un préfixe (c'est ce que stocke
`LiaisonMeshCore`). Le récepteur doit être une clé complète : on ne le résout que si le préfixe
fait au moins deux octets ET ne correspond qu'à un seul nœud connu. À un octet, 256 valeurs : un
nœud « unique aujourd'hui » est un faux positif demain (voir `decodeur_meshcore.prefixe_fiable`).
"""
import logging

from django.utils import timezone

from .decodeur_meshcore import TrameInvalide, decoder_paquet

logger = logging.getLogger(__name__)

#: Octets minimum pour qu'un préfixe désigne un nœud sur la carte ou serve de récepteur.
OCTETS_MIN_RESOLUTION = 2

ROUTES_INONDATION = {"FLOOD", "TRANSPORT_FLOOD"}


class IndexCles:
    """Les clés publiques complètes connues (nos contacts, le réseau public importé, nos
    companions), pour résoudre un préfixe en un nœud. Construit une fois par lot de trames."""

    _partages = {}

    @classmethod
    def partage(cls, environment, duree_s=300):
        """Un index réutilisé quelques minutes : l'ingestion MQTT traite les trames une à une, et
        relire des milliers de clés à chaque trame serait absurde."""
        import time
        entree = cls._partages.get(environment)
        if entree is None or time.monotonic() - entree[0] > duree_s:
            entree = (time.monotonic(), cls(environment))
            cls._partages[environment] = entree
        return entree[1]

    def __init__(self, environment):
        from .models import CompagnonMeshCore, ContactMeshCore, NoeudPublicMeshCore
        cles = set()
        for modele in (ContactMeshCore, NoeudPublicMeshCore):
            filtre = {"environment": environment} if modele is ContactMeshCore else {}
            cles.update(k.lower() for k in modele.objects.filter(**filtre).values_list("pubkey_hex", flat=True) if k)
        cles.update(k.lower() for k in CompagnonMeshCore.objects.exclude(pubkey_hex__isnull=True)
                    .exclude(pubkey_hex="").values_list("pubkey_hex", flat=True))
        self.cles = cles
        self._cache = {}

    def resoudre(self, prefixe):
        """Clé complète si le préfixe est assez long et désigne un seul nœud connu, sinon None."""
        prefixe = (prefixe or "").lower()
        if len(prefixe) == 64:
            return prefixe
        if len(prefixe) < 2 * OCTETS_MIN_RESOLUTION:
            return None
        if prefixe not in self._cache:
            candidats = [k for k in self.cles if k.startswith(prefixe)]
            self._cache[prefixe] = candidats[0] if len(candidats) == 1 else None
        return self._cache[prefixe]


def _ecrire_liaison(emetteur, recepteur, source, snr, environment, maintenant, prefixe_octets, nombre=1):
    from django.db.models import F
    from .models import LiaisonMeshCore

    liaison, cree = LiaisonMeshCore.objects.get_or_create(
        emetteur_prefixe_hex=emetteur, recepteur_pubkey_hex=recepteur, source=source,
        environment=environment,
        defaults={"snr": snr, "prefixe_octets": prefixe_octets, "dernier_vu": maintenant, "nombre": nombre},
    )
    if not cree:
        champs = {"nombre": F("nombre") + nombre, "dernier_vu": maintenant}
        if snr is not None and (liaison.snr is None or snr > liaison.snr):
            champs["snr"] = snr
        LiaisonMeshCore.objects.filter(pk=liaison.pk).update(**champs)
    return liaison


def enregistrer_liaison_meshcore(emetteur, recepteur, source, snr, environment, maintenant, prefixe_octets=32,
                                 tampon=None):
    """Agrège une observation : compteur, dernière vue, MEILLEUR SNR conservé (même choix que
    côté Meshtastic : une moyenne serait tirée vers le bas par les paquets en limite de portée).

    Avec un `tampon` (flux continus, 19/11/2026), l'observation est seulement notée : le tampon
    l'écrira avec les autres au prochain vidage."""
    emetteur, recepteur = emetteur.lower(), recepteur.lower()
    if not emetteur or not recepteur or recepteur.startswith(emetteur) or emetteur.startswith(recepteur):
        return None
    if tampon is not None:
        tampon.noter(emetteur, recepteur, source, snr, environment, prefixe_octets)
        return True
    return _ecrire_liaison(emetteur, recepteur, source, snr, environment, maintenant, prefixe_octets)


class TamponLiaisons:
    """Observations de liaisons notées en mémoire et écrites par lots (19/11/2026).

    Un broker national publie une dizaine de trames par seconde : une écriture en base par trame
    ferait des dizaines de requêtes par seconde pour un résultat agrégé. Ici, une ligne par
    liaison et par vidage, avec le nombre d'observations et le meilleur SNR de la période.
    Utilisable depuis plusieurs fils (un par source)."""

    def __init__(self):
        import threading
        self._verrou = threading.Lock()
        self._lignes = {}
        self.notees = 0

    def noter(self, emetteur, recepteur, source, snr, environment, prefixe_octets):
        cle = (emetteur, recepteur, source, environment, prefixe_octets)
        with self._verrou:
            nombre, meilleur = self._lignes.get(cle, (0, None))
            if snr is not None and (meilleur is None or snr > meilleur):
                meilleur = snr
            self._lignes[cle] = (nombre + 1, meilleur)
            self.notees += 1

    def vider(self, maintenant=None):
        """Écrit ce qui a été noté. Rend le nombre de lignes écrites."""
        maintenant = maintenant or timezone.now()
        with self._verrou:
            lignes, self._lignes = self._lignes, {}
        for (emetteur, recepteur, source, environment, octets), (nombre, snr) in lignes.items():
            _ecrire_liaison(emetteur, recepteur, source, snr, environment, maintenant, octets, nombre)
        return len(lignes)


class DejaVus:
    """Les (observateur, trame) déjà traités depuis quelques minutes : la même observation peut
    arriver par deux sources (un broker et le flux d'une instance CoreScope qu'il alimente).
    Sans cela, chaque observation compterait deux fois."""

    def __init__(self, duree_s=600, maximum=200000):
        import threading
        self._verrou = threading.Lock()
        self._vus = {}
        self.duree_s, self.maximum = duree_s, maximum

    def deja_vu(self, observateur, trame):
        import hashlib
        import time
        cle = (observateur.lower(), hashlib.sha1((trame or "").lower().encode()).digest()[:12])
        maintenant = time.monotonic()
        with self._verrou:
            vu = self._vus.get(cle)
            if vu is not None and maintenant - vu < self.duree_s:
                return True
            self._vus[cle] = maintenant
            if len(self._vus) > self.maximum:
                limite = maintenant - self.duree_s
                self._vus = {k: v for k, v in self._vus.items() if v >= limite}
        return False


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def tirer_liaisons(decode, snr, recepteur, index, environment, maintenant, tampon=None, resolus=None):
    """Les liaisons qu'une trame décodée prouve (voir la docstring du module). Renvoie leur nombre.

    `resolus` : les relais du chemin déjà résolus en clés complètes par la source (une instance
    CoreScope le fait), alignés sur les sauts. Utilisés pour les RÉCEPTEURS des maillons du
    chemin, et seulement quand le préfixe fait au moins deux octets : même règle que notre propre
    résolution, pour ne pas importer une conclusion qu'on refuserait de tirer soi-même."""
    from .models import SourceLiaisonMeshtastic as Source

    entete, chemin, charge = decode["entete"], decode["chemin"] or {}, decode.get("charge") or {}
    if entete.get("nom_charge") == "TRACE":
        return 0
    sauts = chemin.get("sauts") or []
    taille = chemin.get("taille_hash") or 1
    inondation = entete.get("nom_route") in ROUTES_INONDATION
    auteur = None
    if charge.get("type") == "ADVERT" and charge.get("signature_valide") is not False:
        auteur = (charge.get("cle_publique") or "").lower() or None

    n = 0
    # 1. Le dernier émetteur, entendu par le récepteur, avec le SNR mesuré.
    if sauts and inondation:
        if enregistrer_liaison_meshcore(sauts[-1], recepteur, Source.RF, snr, environment, maintenant, taille, tampon):
            n += 1
    elif not sauts and auteur:
        if enregistrer_liaison_meshcore(auteur, recepteur, Source.RF, snr, environment, maintenant, 32, tampon):
            n += 1
    # 2. Les relais consécutifs d'une inondation, et l'auteur d'un advert vers son premier relais.
    if inondation and sauts:
        maillons = ([auteur] if auteur else []) + sauts
        decalage = 1 if auteur else 0
        resolus = resolus if isinstance(resolus, list) and len(resolus) == len(sauts) else None
        for i, (precedent, suivant) in enumerate(zip(maillons, maillons[1:])):
            recepteur_saut = None
            if taille >= OCTETS_MIN_RESOLUTION:
                donne = resolus[i + 1 - decalage] if resolus else None
                if isinstance(donne, str) and len(donne) == 64 and donne.lower().startswith(suivant.lower()):
                    recepteur_saut = donne.lower()
                else:
                    recepteur_saut = index.resoudre(suivant)
            if recepteur_saut is None:
                continue
            octets = 32 if precedent == auteur else taille
            if enregistrer_liaison_meshcore(precedent, recepteur_saut, Source.CHEMIN, None,
                                            environment, maintenant, octets, tampon):
                n += 1
    return n


def ingerer_trames(trames, recepteur, environment, maintenant=None, compteurs=None):
    """Traite un lot de trames entendues par `recepteur` (clé complète).

    `trames` : [{"raw": hex, "snr": .., "rssi": ..}]. `compteurs` (dict type -> nombre), s'il
    est fourni, reçoit la répartition par type de charge. Renvoie un résumé chiffré."""
    maintenant = maintenant or timezone.now()
    index = IndexCles(environment)
    resume = {"recues": 0, "decodees": 0, "illisibles": 0, "liaisons": 0}
    for trame in trames:
        resume["recues"] += 1
        brut = (trame or {}).get("raw")
        if not isinstance(brut, str) or not brut:
            resume["illisibles"] += 1
            continue
        try:
            decode = decoder_paquet(brut)
        except TrameInvalide:
            resume["illisibles"] += 1
            continue
        resume["decodees"] += 1
        if compteurs is not None:
            nom = decode["entete"].get("nom_charge") or "INCONNU"
            compteurs[nom] = compteurs.get(nom, 0) + 1
        resume["liaisons"] += tirer_liaisons(decode, _nombre(trame.get("snr")), recepteur.lower(),
                                             index, environment, maintenant)
    return resume


def liaisons_d_un_traceroute(chemin, recepteur, environment, maintenant=None):
    """Un traceroute MeshCore terminé, en liaisons de source TRACEROUTE.

    `chemin` tel que la bibliothèque meshcore le rend : `[{hash, snr}, …, {snr}]`. `snr[i]` est
    le SNR auquel le saut i a reçu le précédent (nous pour le premier) ; le dernier élément, sans
    hash, est le SNR auquel NOUS avons reçu le dernier saut."""
    from .models import SourceLiaisonMeshtastic as Source

    maintenant = maintenant or timezone.now()
    if not isinstance(chemin, list) or not chemin:
        return 0
    index = IndexCles(environment)
    nous = recepteur.lower()
    sauts = [e for e in chemin if isinstance(e, dict) and e.get("hash")]
    final = chemin[-1] if isinstance(chemin[-1], dict) and not chemin[-1].get("hash") else None
    n = 0
    precedent = nous
    for saut in sauts:
        prefixe = str(saut["hash"]).lower()
        recepteur_saut = index.resoudre(prefixe)
        if recepteur_saut and enregistrer_liaison_meshcore(precedent, recepteur_saut, Source.TRACEROUTE,
                                                           _nombre(saut.get("snr")), environment, maintenant,
                                                           32 if precedent == nous else len(precedent) // 2):
            n += 1
        precedent = prefixe
    if sauts and final is not None:
        if enregistrer_liaison_meshcore(precedent, nous, Source.TRACEROUTE, _nombre(final.get("snr")),
                                        environment, maintenant, len(precedent) // 2):
            n += 1
    return n
