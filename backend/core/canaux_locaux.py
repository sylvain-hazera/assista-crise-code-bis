"""Plan de canaux d'une passerelle locale, et la règle de diffusion qui va avec.

**Règle fixée par Sylvain le 14/11/2026**, pour une passerelle Meshtastic locale (radio branchée
en USB sur une machine de la commune : relais navigateur ou satellite) :

1. **Isolée par défaut.** Ce que sa radio entend est enregistré dans Assista-Crise — la cellule
   de crise de la commune le voit — mais n'est réémis par aucune autre passerelle. Dans l'autre
   sens, elle **ne réémet que ce qui concerne sa crise et sa commune**. Un réglage
   (`CompagnonMeshtastic.relais_reseau`) lui rend le comportement de réseau.
2. **Deux canaux communautaires d'office : `Fr_Balise` et `Fr_EMCOM`.**
3. **Deux canaux créés par Assista-Crise : un pour la crise, un pour la commune**, dont le nom
   est annoncé sur `Fr_EMCOM` par la seule passerelle locale.
4. **Clé publique par défaut** pour ces deux canaux — « tant pis », avec un avertissement : ils
   ne sont pas chiffrés, tout le monde peut les lire.
5. **Mutualisation** : le canal de crise est celui de la CRISE, pas de la commune. Toutes les
   communes impliquées dans la même crise partagent donc le même canal, et chaque passerelle
   locale l'émet de son côté — c'est ce qui donne le contact avec le voisin.
6. **Le plan se décide au branchement** : on lit les emplacements de la radio, on propose
   d'ajouter `Fr_Balise` et `Fr_EMCOM` s'ils manquent, puis, selon la place restante, d'ajouter
   les canaux de crise et de commune — en proposant, s'il le faut, d'en supprimer d'autres.
   Rien n'est écrit sur la radio sans l'accord de la personne.

Ce module décide QUOI proposer et QUOI diffuser. Écrire sur la radio est le travail du
navigateur (`frontend/src/app/shared/mesh/pilotes.ts`), et l'API est dans `RelaisSerieView`.
"""
import re

from django.db.models import Q
from django.utils import timezone

#: Canaux communautaires d'office, par ordre de priorité. Leurs clés sont celles de la
#: communauté (publiques par convention) : on les lit dans les canaux DÉCLARÉS dans Assista-Crise,
#: on ne les invente jamais.
CANAUX_COMMUNAUTAIRES = ("Fr_Balise", "Fr_EMCOM")

#: La clé publique par défaut de Meshtastic, sous sa forme courte : `01` désigne la clé connue
#: de tous (`d4f1bb3a…`, voir meshtastic-bridge/crypto.py). « Public par défaut, tant pis ».
PSK_PUBLIQUE = "01"

#: Une radio Meshtastic a 8 emplacements de canaux, l'emplacement 0 étant le canal primaire.
EMPLACEMENTS_MESHTASTIC = 8

#: Une passerelle isolée ne rattrape pas l'historique en se branchant : au-delà, un message de
#: canal n'est plus d'actualité, et le réémettre d'un coup inonderait le réseau.
MINUTES_DE_RATTRAPAGE = 15

#: Délai minimal entre deux annonces des canaux sur Fr_EMCOM par la même passerelle : EMCOM est
#: un canal d'urgence partagé, on ne le remplit pas à chaque reconnexion USB.
MINUTES_ENTRE_ANNONCES = 30

#: Préfixes retirés d'un nom d'institution pour nommer le canal de la commune : 11 octets ne
#: laissent pas la place à « Mairiede ».
_PREFIXES_COMMUNE = re.compile(
    r"^\s*(mairie|commune|ville|cit[ée]|communaut[ée] de communes)\s+(de|du|des|d'|de la|de l')\s*",
    re.IGNORECASE,
)

AVERTISSEMENT_NON_CHIFFRE = (
    "Canaux de crise et de commune non chiffrés : ils utilisent la clé publique par défaut, tout "
    "le monde peut les lire. N'y faites passer aucune donnée personnelle (nom, adresse, état de "
    "santé)."
)


def est_local(compagnon):
    """Passerelle locale : radio branchée sur une machine de la commune (USB du satellite, ou
    navigateur). Les companions MQTT et TCP sont des passerelles de réseau, non concernées."""
    from .models import MeshtasticConnexionType

    # BLE : radio tenue en Bluetooth par la machine du pont (passerelle Windows) — aussi locale
    # qu'une radio en USB.
    return compagnon.connexion_type in (MeshtasticConnexionType.SERIE,
                                        MeshtasticConnexionType.BLE,
                                        MeshtasticConnexionType.NAVIGATEUR)


def est_isolee(compagnon):
    return est_local(compagnon) and not compagnon.relais_reseau


def crises_de(institution):
    """Les crises EN COURS où l'institution est impliquée (implication validée et active)."""
    from .models import Crisis, ImplicationInstitution, StatutImplication

    if institution is None:
        return Crisis.objects.none()
    ids = ImplicationInstitution.objects.filter(
        institution=institution, actif=True, statut=StatutImplication.VALIDEE,
        crise__end_date__isnull=True,
    ).values_list("crise_id", flat=True)
    # Les plus récentes d'abord : quand la radio manque de place, ce sont elles qu'on garde
    # (revue du 19/11/2026).
    return Crisis.objects.filter(pk__in=list(ids), end_date__isnull=True).order_by("-start_date")


def canaux_du_perimetre(compagnon):
    """Les canaux qui concernent la crise et la commune de cette passerelle.

    Commune : canaux de l'institution, et ceux de ses équipes. Crise : canaux des crises en cours
    où l'institution est impliquée — y compris quand c'est une commune voisine qui les a fait
    naître, c'est la mutualisation."""
    from .models import CanalMeshtastic

    institution_id = compagnon.institution_id
    if not institution_id:
        return CanalMeshtastic.objects.none()
    return CanalMeshtastic.objects.filter(actif=True).filter(
        Q(institution_id=institution_id) | Q(equipe__institution_id=institution_id)
        | Q(crise__in=crises_de(compagnon.institution))
    )


# ══ Noms courts ═══════════════════════════════════════════════════════════════

def _nom_valide(nom):
    from .views import nom_canal_meshtastic_valide
    return nom_canal_meshtastic_valide(nom)


def nom_canal_commune(institution):
    """« Mairie de Moissac » → « Moissac ». 11 octets au plus, sans accents ni espaces."""
    nom = _PREFIXES_COMMUNE.sub("", institution.nom or "").strip() or institution.nom or "Commune"
    return _nom_valide(nom) or "Commune"


def nom_canal_crise(crise, deja_pris=()):
    """« Crise » + le début du nom de la crise, rendu unique parmi les canaux de crise actifs.

    Deux crises différentes ne doivent pas porter le même nom de canal : avec la même clé
    publique, elles tomberaient sur le MÊME canal radio."""
    base = _nom_valide("Crise" + _nom_valide(crise.name or ""))[:11] or "Crise"
    if base not in deja_pris:
        return base
    for n in range(2, 100):
        candidat = base[:11 - len(str(n))] + str(n)
        if candidat not in deja_pris:
            return candidat
    return base


# ══ Création à la demande ═════════════════════════════════════════════════════

def canal_commune(institution, environnement):
    """Le canal de la commune, créé au premier besoin. Clé publique par défaut."""
    from .models import CanalMeshtastic

    # La clé est chiffrée au repos (Fernet, non déterministe) : impossible de filtrer dessus en
    # SQL, on compare en Python. Peu de canaux par institution, le coût est négligeable.
    existant = None
    for canal in CanalMeshtastic.objects.filter(
            institution=institution, crise__isnull=True, equipe__isnull=True,
            compagnon__isnull=True, actif=True):
        if (canal.psk_hex or "") == PSK_PUBLIQUE:
            existant = canal
            break
    if existant is not None:
        return existant, False
    return CanalMeshtastic.objects.create(
        institution=institution, nom=nom_canal_commune(institution), psk_hex=PSK_PUBLIQUE,
        environment=environnement,
    ), True


def canal_crise(crise, environnement):
    """Le canal de la crise — UN par crise, partagé par toutes les communes impliquées. Le
    premier qui en a besoin le crée, les suivants le retrouvent : c'est la mutualisation."""
    from .models import CanalMeshtastic

    existant = CanalMeshtastic.objects.filter(crise=crise, equipe__isnull=True, actif=True).first()
    if existant is not None:
        return existant, False
    pris = set(CanalMeshtastic.objects.filter(crise__isnull=False, actif=True)
               .values_list("nom", flat=True))
    return CanalMeshtastic.objects.create(
        crise=crise, nom=nom_canal_crise(crise, pris), psk_hex=PSK_PUBLIQUE,
        environment=environnement,
    ), True


def canal_communautaire(nom):
    """Le canal communautaire déclaré sous ce nom, ou None. Sa clé vient de la déclaration —
    jamais inventée : sans déclaration, on ne peut pas le pousser sur une radio."""
    from .models import CanalMeshtastic

    return CanalMeshtastic.objects.filter(nom__iexact=nom, actif=True).order_by(
        "equipe", "crise", "institution").first()


# ══ Le plan proposé au branchement ════════════════════════════════════════════

def plan_canaux(compagnon, environnement):
    """Les canaux qu'Assista-Crise propose pour cette radio, par ordre de priorité.

    Chaque entrée : `nom`, `psk_hex`, `role` (`communautaire`, `commune`, `crise`), `libelle`,
    `canal` (identifiant, pour faire correspondre les messages), `public` (clé connue de tous),
    et `disponible` à False quand on ne connaît pas la clé (canal communautaire non déclaré).

    Les clés renvoyées sont **publiques** : clé par défaut pour la crise et la commune, clés de
    convention pour Fr_Balise et Fr_EMCOM. Aucun secret ne quitte le serveur par ici.
    """
    entrees = []
    for nom in CANAUX_COMMUNAUTAIRES:
        canal = canal_communautaire(nom)
        entrees.append({
            "nom": canal.nom if canal else nom,
            "psk_hex": (canal.psk_hex or "") if canal else "",
            "role": "communautaire",
            "libelle": "Canal communautaire " + nom,
            "canal": str(canal.id) if canal else None,
            "public": True,
            "disponible": canal is not None and bool(canal.psk_hex),
        })

    institution = compagnon.institution
    if institution is not None:
        for crise in crises_de(institution):
            canal, _ = canal_crise(crise, environnement)
            entrees.append({
                "nom": canal.nom, "psk_hex": canal.psk_hex or PSK_PUBLIQUE, "role": "crise",
                "libelle": f"Crise « {crise.name} »", "canal": str(canal.id),
                "public": (canal.psk_hex or "") == PSK_PUBLIQUE, "disponible": True,
            })
        canal, _ = canal_commune(institution, environnement)
        entrees.append({
            "nom": canal.nom, "psk_hex": canal.psk_hex or PSK_PUBLIQUE, "role": "commune",
            "libelle": institution.nom, "canal": str(canal.id),
            "public": (canal.psk_hex or "") == PSK_PUBLIQUE, "disponible": True,
        })
    return entrees


# ══ Annonce sur Fr_EMCOM, en local seulement ══════════════════════════════════

def texte_annonce(compagnon, environnement):
    """Le texte annoncé sur Fr_EMCOM : les noms des canaux de crise et de commune, et le fait
    qu'ils sont en clair. Court : un message LoRa long échoue nettement plus souvent."""
    morceaux = []
    for entree in plan_canaux(compagnon, environnement):
        if entree["role"] == "crise":
            morceaux.append(f"crise {entree['nom']}")
        elif entree["role"] == "commune":
            morceaux.append(f"commune {entree['nom']}")
    if not morceaux:
        return ""
    return "Canaux " + ", ".join(morceaux) + " - cle publique, non chiffre"


def annoncer(compagnon, utilisateur, environnement):
    """Annonce les canaux sur Fr_EMCOM par CETTE passerelle seulement. Renvoie `(message, raison)`.

    Le message est **ciblé** sur la passerelle (`MessageCanalMeshtastic.compagnon`) : aucune
    autre passerelle ne le reçoit dans sa file — c'est le « qu'en local » de la règle."""
    from .models import DirectionMessageMesh, MessageCanalMeshtastic, StatutMessageMesh

    emcom = canal_communautaire("Fr_EMCOM")
    if emcom is None:
        return None, "Le canal Fr_EMCOM n'est pas déclaré dans Assista-Crise : rien à annoncer."
    texte = texte_annonce(compagnon, environnement)
    if not texte:
        return None, "Aucun canal de crise ou de commune à annoncer."
    recente = MessageCanalMeshtastic.objects.filter(
        canal=emcom, compagnon=compagnon, direction=DirectionMessageMesh.SORTANT,
        date_creation__gte=timezone.now() - timezone.timedelta(minutes=MINUTES_ENTRE_ANNONCES),
    ).exists()
    if recente:
        return None, "Canaux déjà annoncés il y a moins de 30 minutes."
    message = MessageCanalMeshtastic.objects.create(
        canal=emcom, compagnon=compagnon, direction=DirectionMessageMesh.SORTANT,
        contenu=texte, statut=StatutMessageMesh.EN_ATTENTE, expediteur=utilisateur,
        environment=environnement,
    )
    return message, None


# ══ File de diffusion d'une passerelle isolée ═════════════════════════════════

def messages_a_diffuser(compagnon, canal_id=None):
    """Les messages de canal qu'une passerelle ISOLÉE doit émettre.

    Pas le statut global du message : il ne dit que « parti quelque part », et la première
    passerelle qui l'émettait privait toutes les autres de le faire. Pour un canal de crise
    partagé entre deux communes, une seule l'aurait émis. Ici chaque passerelle locale suit SA
    propre diffusion (`DiffusionCanalMeshtastic`).

    Retenus : les messages sortants récents (`MINUTES_DE_RATTRAPAGE`) des canaux du périmètre,
    plus ceux qui ciblent explicitement cette passerelle (l'annonce EMCOM), moins ceux qu'elle a
    déjà émis et ceux qui ciblent une AUTRE passerelle.
    """
    from .models import DirectionMessageMesh, MessageCanalMeshtastic, StatutMessageMesh

    limite = timezone.now() - timezone.timedelta(minutes=MINUTES_DE_RATTRAPAGE)
    qs = MessageCanalMeshtastic.objects.filter(
        direction=DirectionMessageMesh.SORTANT, date_creation__gte=limite,
    ).exclude(statut=StatutMessageMesh.ECHEC).filter(
        Q(compagnon=compagnon)
        | (Q(compagnon__isnull=True) & Q(canal__in=canaux_du_perimetre(compagnon)))
    ).exclude(diffusions__compagnon=compagnon)
    if canal_id:
        qs = qs.filter(canal_id=canal_id)
    return qs.select_related("canal__institution", "expediteur").order_by("date_creation")


def noter_diffusion(message, compagnon, environnement):
    """Note que CETTE passerelle a émis ce message. Le premier émetteur fait aussi passer le
    statut global à ENVOYE — l'interface doit pouvoir dire « parti sur la radio »."""
    from .models import DiffusionCanalMeshtastic, StatutMessageMesh

    _, cree = DiffusionCanalMeshtastic.objects.get_or_create(
        message=message, compagnon=compagnon, defaults={"environment": environnement},
    )
    if message.statut == StatutMessageMesh.EN_ATTENTE:
        message.statut = StatutMessageMesh.ENVOYE
        message.save(update_fields=["statut"])
    return cree
