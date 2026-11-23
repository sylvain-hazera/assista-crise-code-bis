"""Messagerie interne (23/11/2026) : remplace les salons Matrix.

Décision de Sylvain : « on arrête Matrix ; tous les circuits qui l'utilisaient passent par notre
application ». Le serveur est la seule messagerie ; l'application, le site et les passerelles
radio y écrivent, et chaque message garde sa provenance (`source`, `recu_par`).

- **Quelle conversation** : `conversation_equipe` (celle de la crise en cours de l'équipe,
  sinon celle de tous les jours : règle du 16/11, `salons_de_crise.crise_du_contexte`),
  `conversation_crise` (CRISE, CELLULE, A_TRIER : une par crise), `conversation_communautaire`
  (Fr_EMCOM…), `conversation_directe`.
- **Écrire** : `ecrire()` — jamais de doublon : même `origine` (import, renvoi d'un téléphone)
  ou même empreinte dans la même conversation à moins de 10 minutes (le même message entendu
  par deux passerelles, deux protocoles ou un téléphone) → un seul message, plusieurs
  « reçu par ». Dans le doute on garde les deux : un doublon vaut mieux qu'une perte.
- **Droits** : `peut_lire` / `peut_ecrire`.
- **Vers la radio** : `diffuser_radio()` met le message EN_ATTENTE sur le canal de crise
  (préfixé `@INDICATIF`) et, pendant la transition, sur l'ancien canal de l'équipe.
"""
import datetime
import re
import unicodedata

from django.db.models import Q
from django.utils import timezone

from .models import (
    Conversation, GenreConversation, LectureConversation, MessageConversation, SourceMessage, UserRole,
)

FENETRE_DOUBLON = datetime.timedelta(minutes=10)
GENRES_DE_CRISE = (GenreConversation.CRISE, GenreConversation.CELLULE, GenreConversation.A_TRIER)


# ══ Trouver (ou créer) la conversation ════════════════════════════════════════

def _obtenir(environment, **filtre):
    conversation = Conversation.objects.filter(**filtre).order_by("cree_le").first()
    if conversation is None:
        conversation = Conversation.objects.create(environment=environment, **filtre)
    return conversation


def conversation_equipe(equipe, crise=None, genre=GenreConversation.EQUIPE, environment=None):
    """La conversation de l'équipe pour `crise` (None = celle de tous les jours)."""
    return _obtenir(environment or equipe.environment, genre=genre, equipe=equipe,
                    crise=crise if genre == GenreConversation.EQUIPE else None)


def conversation_du_contexte(equipe, crise_id=None, environment=None):
    """Celle où l'on parle à l'équipe en ce moment (crise ouverte de l'équipe, sinon le quotidien)."""
    from .salons_de_crise import crise_du_contexte

    return conversation_equipe(equipe, crise_du_contexte(equipe, crise_id), environment=environment)


def conversation_crise(crise, genre=GenreConversation.CRISE, environment=None):
    assert genre in GENRES_DE_CRISE
    return _obtenir(environment or crise.environment, genre=genre, crise=crise, equipe=None)


def conversation_communautaire(nom, environment):
    return _obtenir(environment, genre=GenreConversation.COMMUNAUTAIRE, canal_nom=nom[:40])


def conversation_directe(a, b, environment):
    for c in Conversation.objects.filter(genre=GenreConversation.DIRECT, participants=a).filter(participants=b):
        if c.participants.count() == 2:
            return c
    c = Conversation.objects.create(genre=GenreConversation.DIRECT, environment=environment)
    c.participants.add(a, b)
    return c


# ══ Écrire ════════════════════════════════════════════════════════════════════

_PREFIXE_NOM = re.compile(r"^\s*([^:\n]{1,32}):\s+(.*)$", re.DOTALL)


def normaliser(texte):
    t = unicodedata.normalize("NFKC", texte or "").strip().lower()
    return re.sub(r"\s+", " ", t)


def empreinte(texte, auteur=""):
    from .crypto_fields import empreinte_jeton

    return empreinte_jeton(f"{normaliser(auteur)}|{normaliser(texte)}")


def ecrire(conversation, texte, *, auteur=None, auteur_libre=None, source=SourceMessage.SITE, urgent=False,
           recu_par=None, emis_le=None, origine="", message_meshtastic=None, message_meshcore=None,
           dedupliquer=True):
    """Enregistre un message (voir le module). Rend `(message, cree)`. `dedupliquer=False` : seule
    l'origine compte (import d'un historique, où deux « ok » identiques sont deux messages)."""
    texte = (texte or "").strip()
    emis_le = emis_le or timezone.now()
    nom_auteur = auteur_libre or (str(auteur.id) if auteur else "")
    signature = empreinte(texte, nom_auteur)
    existant = None
    if origine:
        existant = MessageConversation.objects.filter(conversation=conversation, origine=origine).first()
    if existant is None and dedupliquer and source not in (SourceMessage.SITE, SourceMessage.APPLICATION):
        existant = MessageConversation.objects.filter(
            conversation=conversation, empreinte=signature,
            emis_le__gte=emis_le - FENETRE_DOUBLON, emis_le__lte=emis_le + FENETRE_DOUBLON,
        ).first()
    if existant is not None:
        nouveaux = [r for r in (recu_par or []) if r and r not in (existant.recu_par or [])]
        champs = []
        if nouveaux:
            existant.recu_par = list(existant.recu_par or []) + nouveaux
            champs.append("recu_par")
        if message_meshtastic is not None and existant.message_meshtastic_id is None:
            existant.message_meshtastic = message_meshtastic
            champs.append("message_meshtastic")
        if message_meshcore is not None and existant.message_meshcore_id is None:
            existant.message_meshcore = message_meshcore
            champs.append("message_meshcore")
        if champs:
            existant.save(update_fields=champs)
        return existant, False
    message = MessageConversation.objects.create(
        conversation=conversation, texte=texte, auteur=auteur, auteur_libre=auteur_libre or None, source=source,
        urgent=urgent, recu_par=list(recu_par or []), emis_le=emis_le, empreinte=signature, origine=origine[:120],
        message_meshtastic=message_meshtastic, message_meshcore=message_meshcore,
        environment=conversation.environment,
    )
    if conversation.dernier_message_le is None or emis_le > conversation.dernier_message_le:
        Conversation.objects.filter(pk=conversation.pk).update(dernier_message_le=emis_le)
    return message, True


def deja_entendu(conversation, texte, auteur, fenetre=datetime.timedelta(hours=24)):
    """Le téléphone remet un message qu'il a déjà émis par sa radio : une passerelle l'a peut-être
    entendu et rangé, sans auteur connu. On le rattache à son auteur au lieu de le doubler."""
    cible = normaliser(texte)
    for m in conversation.messages.filter(auteur__isnull=True, emis_le__gte=timezone.now() - fenetre,
                                          source__in=[SourceMessage.MESHTASTIC, SourceMessage.MESHCORE,
                                                      SourceMessage.TELEPHONE_RADIO]).order_by("-emis_le")[:50]:
        if normaliser(m.texte).endswith(cible):
            m.auteur = auteur
            m.save(update_fields=["auteur"])
            return m
    return None


def nom_auteur(message, request=None):
    if message.auteur_id:
        from .permissions import nom_affichable
        return nom_affichable(message.auteur, request) or message.auteur.email
    return message.auteur_libre or "Par radio"


# ══ Droits ════════════════════════════════════════════════════════════════════

def _est_admin(user):
    return getattr(user, "type", None) == UserRole.ADMINISTRATOR


def dans_equipe(user, equipe):
    """Membre, chef, régulateur ou encadrant de l'équipe, ou compte institutionnel de son
    institution (ou de l'institution délégataire)."""
    if equipe is None or not user.is_authenticated:
        return False
    if _est_admin(user) or user.id in (equipe.leader_id, equipe.regulateur_id):
        return True
    if equipe.members.filter(pk=user.pk).exists() or equipe.membres_encadrement.filter(pk=user.pk).exists():
        return True
    from .permissions import INSTITUTIONAL_TYPES
    return (user.type in INSTITUTIONAL_TYPES and user.institution_id is not None
            and user.institution_id in (equipe.institution_id, equipe.institution_delegataire_id))


def equipes_de_la_crise(crise):
    from .models import PointOperationnel, Team

    ids = set(crise.assigned_teams.values_list("id", flat=True))
    ids |= set(PointOperationnel.objects.filter(crise=crise, equipe__isnull=False).values_list("equipe_id", flat=True))
    return Team.objects.filter(pk__in=ids, actif=True)


def dans_la_crise(user, crise):
    """Compte d'une institution impliquée sur la crise, ou membre d'une équipe engagée."""
    from .models import ImplicationInstitution, StatutImplication
    from .permissions import INSTITUTIONAL_TYPES

    if _est_admin(user):
        return True
    if user.type in INSTITUTIONAL_TYPES and user.institution_id and ImplicationInstitution.objects.filter(
            crise=crise, institution_id=user.institution_id, actif=True, statut=StatutImplication.VALIDEE).exists():
        return True
    return any(dans_equipe(user, e) for e in equipes_de_la_crise(crise).filter(
        Q(members=user) | Q(leader=user) | Q(regulateur=user) | Q(membres_encadrement=user)).distinct())


def est_regulation(user, crise):
    """La régulation d'une crise : régulateurs, régulateur d'une équipe engagée, cellule."""
    from .permissions import INSTITUTIONAL_TYPES

    if _est_admin(user) or user.type == UserRole.REGULATEUR:
        return dans_la_crise(user, crise) or _est_admin(user)
    if equipes_de_la_crise(crise).filter(regulateur=user).exists():
        return True
    return user.type in INSTITUTIONAL_TYPES and dans_la_crise(user, crise)


def trieurs_de(crise):
    """Qui trie le pot commun : l'équipe transmissions engagée, à défaut la régulation
    (décision de Sylvain du 23/11/2026)."""
    transmissions = equipes_de_la_crise(crise).filter(transmissions=True)
    if transmissions.exists():
        return ("TRANSMISSIONS", transmissions)
    return ("REGULATION", None)


def peut_trier(user, crise):
    if _est_admin(user):
        return True
    mode, equipes = trieurs_de(crise)
    if mode == "TRANSMISSIONS":
        return any(dans_equipe(user, e) for e in equipes) or est_regulation(user, crise)
    return est_regulation(user, crise)


def peut_lire(user, conversation):
    if not user.is_authenticated:
        return False
    g = conversation.genre
    if g in (GenreConversation.EQUIPE, GenreConversation.ENCADREMENT):
        return dans_equipe(user, conversation.equipe)
    if g == GenreConversation.CRISE:
        return dans_la_crise(user, conversation.crise)
    if g == GenreConversation.CELLULE:
        return est_regulation(user, conversation.crise)
    if g == GenreConversation.A_TRIER:
        return peut_trier(user, conversation.crise)
    if g == GenreConversation.DIRECT:
        return conversation.participants.filter(pk=user.pk).exists()
    if g == GenreConversation.COMMUNAUTAIRE:
        from .permissions import INSTITUTIONAL_TYPES
        return user.type in INSTITUTIONAL_TYPES or user.type == UserRole.REGULATEUR or user.teams.exists()
    if g == GenreConversation.SUPERVISION:
        return _est_admin(user)
    if g == GenreConversation.MISSION and conversation.mission_id:
        return any(dans_equipe(user, e) for e in conversation.mission.equipes.all())
    if g == GenreConversation.INSTITUTION:
        return _est_admin(user) or user.institution_id == conversation.institution_id
    return False


def peut_ecrire(user, conversation):
    # On n'écrit pas dans le pot commun : on le trie.
    return conversation.genre != GenreConversation.A_TRIER and peut_lire(user, conversation)


# ══ Lecture, non-lus ══════════════════════════════════════════════════════════

def marquer_lu(user, conversation, jusqua=None):
    jusqua = jusqua or timezone.now()
    LectureConversation.objects.update_or_create(conversation=conversation, utilisateur=user,
                                                 defaults={"lu_jusqua": jusqua})


def non_lus(user, conversation):
    lecture = LectureConversation.objects.filter(conversation=conversation, utilisateur=user).first()
    qs = conversation.messages.exclude(auteur=user)
    if conversation.genre == GenreConversation.A_TRIER:
        qs = qs.filter(range_le__isnull=True)
        return qs.count()
    if lecture is not None:
        qs = qs.filter(emis_le__gt=lecture.lu_jusqua)
    return qs.count()


def mes_conversations(user, environment):
    """Les conversations d'une personne, de la plus récente à la plus ancienne."""
    from .models import Team
    from .salons_de_crise import crise_du_contexte, crises_ouvertes_de

    trouvees = {}
    equipes = Team.objects.filter(actif=True).filter(
        Q(members=user) | Q(leader=user) | Q(regulateur=user) | Q(membres_encadrement=user)).distinct()
    crises = {}
    for equipe in equipes:
        c = conversation_equipe(equipe, crise_du_contexte(equipe), environment=environment)
        trouvees[c.id] = c
        for crise in crises_ouvertes_de(equipe):
            crises[crise.id] = crise
    from .models import Crisis, ImplicationInstitution, StatutImplication
    if user.institution_id and user.type != UserRole.SIMPLE_USER:
        for crise in Crisis.objects.filter(end_date__isnull=True, pk__in=ImplicationInstitution.objects.filter(
                institution_id=user.institution_id, actif=True, statut=StatutImplication.VALIDEE).values("crise_id")):
            crises[crise.id] = crise
    for crise in crises.values():
        if crise.environment != environment:
            continue
        c = conversation_crise(crise, environment=environment)
        trouvees[c.id] = c
        if est_regulation(user, crise):
            c = conversation_crise(crise, GenreConversation.CELLULE, environment=environment)
            trouvees[c.id] = c
        if peut_trier(user, crise):
            c = conversation_crise(crise, GenreConversation.A_TRIER, environment=environment)
            trouvees[c.id] = c
    for c in Conversation.objects.filter(genre=GenreConversation.DIRECT, participants=user, environment=environment):
        trouvees[c.id] = c
    for c in Conversation.objects.filter(genre=GenreConversation.COMMUNAUTAIRE, environment=environment):
        if peut_lire(user, c):
            trouvees[c.id] = c
    epoque = timezone.make_aware(datetime.datetime(2000, 1, 1))
    return sorted(trouvees.values(), key=lambda c: c.dernier_message_le or epoque, reverse=True)


def titre(conversation, user=None, request=None):
    g = conversation.genre
    if g in (GenreConversation.EQUIPE, GenreConversation.ENCADREMENT):
        nom = conversation.equipe.name if conversation.equipe_id else "Équipe"
        return f"{nom} — encadrement" if g == GenreConversation.ENCADREMENT else nom
    if g in GENRES_DE_CRISE:
        nom = conversation.crise.name if conversation.crise_id else "Crise"
        return {GenreConversation.CRISE: nom, GenreConversation.CELLULE: f"Cellule — {nom}",
                GenreConversation.A_TRIER: f"À trier — {nom}"}[g]
    if g == GenreConversation.COMMUNAUTAIRE:
        return conversation.canal_nom
    if g == GenreConversation.DIRECT and user is not None:
        autre = conversation.participants.exclude(pk=user.pk).first()
        if autre is not None:
            from .permissions import nom_affichable
            return nom_affichable(autre, request) or autre.email
    if g == GenreConversation.MISSION and conversation.mission_id:
        return f"Mission — {conversation.mission}"
    return conversation.get_genre_display()


# ══ Vers la radio ═════════════════════════════════════════════════════════════

def diffuser_radio(message, equipe=None, crise=None, deja_emis=(), auteur=None):
    """Met le message EN_ATTENTE d'émission par les passerelles :
    - sur le canal de crise (Meshtastic et MeshCore), préfixé `@INDICATIF` de l'équipe
      (`@PC` pour la cellule), une seule fois par protocole ;
    - pendant la transition, sur l'ancien canal de l'équipe s'il existe (les téléphones encore
      réglés sur lui l'entendent).
    `deja_emis` : protocoles que le téléphone a déjà émis lui-même (enregistrés ENVOYE).
    Rien de personnel ne doit passer par là : le canal de crise est public."""
    from .models import (
        CanalMeshCore, CanalMeshtastic, DirectionMessageMesh, MessageCanalMeshCore, MessageCanalMeshtastic,
        StatutMessageMesh,
    )

    texte = message.texte
    env = message.environment
    deja = {p.upper() for p in deja_emis}
    lies = {}

    def statut(protocole):
        return StatutMessageMesh.ENVOYE if protocole in deja else StatutMessageMesh.EN_ATTENTE

    prefixe = ""
    if equipe is not None and equipe.indicatif:
        prefixe = f"@{equipe.indicatif} "
    elif message.conversation.genre == GenreConversation.CELLULE:
        prefixe = "@PC "
    if crise is not None:
        from .canaux_locaux import canaux_de_crise
        canaux_de_crise(crise, env)
        for modele_canal, modele_msg, proto in ((CanalMeshtastic, MessageCanalMeshtastic, "MESHTASTIC"),
                                               (CanalMeshCore, MessageCanalMeshCore, "MESHCORE")):
            canal = modele_canal.objects.filter(crise=crise, equipe__isnull=True, actif=True).first()
            if canal is not None:
                lies[proto] = modele_msg.objects.create(
                    canal=canal, direction=DirectionMessageMesh.SORTANT, expediteur=auteur,
                    contenu=prefixe + texte, statut=statut(proto), environment=env)
    if equipe is not None:
        for modele_canal, modele_msg, proto in ((CanalMeshtastic, MessageCanalMeshtastic, "MESHTASTIC"),
                                               (CanalMeshCore, MessageCanalMeshCore, "MESHCORE")):
            canal = modele_canal.objects.filter(equipe=equipe).first()
            if canal is not None:
                m = modele_msg.objects.create(canal=canal, direction=DirectionMessageMesh.SORTANT, expediteur=auteur,
                                              contenu=texte, statut=statut(proto), environment=env)
                lies.setdefault(proto, m)
    champs = []
    if "MESHTASTIC" in lies:
        message.message_meshtastic = lies["MESHTASTIC"]
        champs.append("message_meshtastic")
    if "MESHCORE" in lies:
        message.message_meshcore = lies["MESHCORE"]
        champs.append("message_meshcore")
    if champs:
        message.save(update_fields=champs)
    return lies
