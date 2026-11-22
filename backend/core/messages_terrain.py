"""Messages de terrain en un geste (22/11/2026) : enregistrement, effets, et format radio.

Demande de Sylvain : « il faut pouvoir remonter facilement, par data classique, Meshtastic ou
MeshCore, des fonctions aussi simples que : arrivé sur les lieux, message de situation,
intervention terminée, on se rend à l'intervention suivante, disponible en retour, non
disponible en retour… », plus demande de renfort, danger, pause, et demande de premiers
secours avec son motif.

**Format radio** : lisible par un humain sur n'importe quelle radio, et reconnu par le serveur
quand le message arrive par un pont :

    ⚑ARR 3f2a9c.9c1e0b.a1b2c3 Arrivé sur les lieux
     │   │      │      └ identifiant du message (6 hex) : dédoublonnage radio/données
     │   │      └ début de l'identifiant de l'intervenant (6 hex)
     │   └ début de l'identifiant de la mission (6 hex), ou « ------ » sans mission
     └ code du type

Le serveur retrouve l'intervenant parmi les membres des équipes de la mission : le préfixe
suffit, la liste est courte. Un message dont l'intervenant n'est pas retrouvé est ignoré
(il reste dans le fil radio, lisible par tous).
"""
import logging
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

CODES = {
    "ARR": "ARRIVE", "SIT": "SITUATION", "FIN": "TERMINEE", "SUIV": "EN_ROUTE_SUIVANTE",
    "DISPO": "DISPONIBLE", "INDISPO": "INDISPONIBLE", "RENF": "RENFORT", "DANG": "DANGER",
    "PAUSE": "PAUSE", "PS": "PREMIERS_SECOURS",
}
CODE_DU_TYPE = {v: k for k, v in CODES.items()}
PRIORITAIRES = {"DANGER", "PREMIERS_SECOURS"}
#: Le statut courant de l'intervenant que chaque message établit (le PC le lit).
STATUT_DU_TYPE = {
    "ARRIVE": "Sur place", "TERMINEE": "Intervention terminée", "EN_ROUTE_SUIVANTE": "En route",
    "DISPONIBLE": "Disponible", "INDISPONIBLE": "Non disponible", "PAUSE": "En pause",
    "RENFORT": "Demande de renfort", "DANGER": "Danger signalé", "PREMIERS_SECOURS": "Demande de secours",
}

_ETIQUETTE = re.compile(r"⚑([A-Z]{2,7}) ([0-9a-f-]{6})\.([0-9a-f]{6})\.([0-9a-f]{6})(?: (.*))?$", re.S)


def lire_etiquette(texte):
    """Rend {type, mission6, auteur6, ident, texte} si le texte porte une étiquette, sinon None.
    L'étiquette peut suivre un préfixe ajouté par la radio ou le pont (« Nom: »)."""
    if not texte or "⚑" not in texte:
        return None
    m = _ETIQUETTE.search(texte[texte.index("⚑"):].strip())
    if not m or m.group(1) not in CODES:
        return None
    return {"type": CODES[m.group(1)], "mission6": None if m.group(2) == "------" else m.group(2),
            "auteur6": m.group(3), "ident": m.group(4), "texte": (m.group(5) or "").strip()}


def peut_ecrire(user, mission) -> bool:
    """Tout membre, chef ou régulateur d'une équipe de la mission."""
    from django.db.models import Q
    return mission.equipes.filter(Q(members=user) | Q(leader=user) | Q(regulateur=user)).exists()


def enregistrer(auteur, mission, type_, texte="", nombre=None, latitude=None, longitude=None,
                canal="DONNEES", emis_le=None, identifiant_client="", request=None):
    """Enregistre le message (une seule fois par identifiant client), et ses effets. Rend
    (message, cree)."""
    from .models import MessageTerrain

    if type_ == "PREMIERS_SECOURS" and not (texte or "").strip():
        raise ValueError("Pour quel motif demander des secours ?")
    existant = MessageTerrain.objects.filter(auteur=auteur, identifiant_client=identifiant_client).first() if identifiant_client else None
    if existant is not None:
        if canal not in (existant.canaux_recus or []):
            existant.canaux_recus = list(existant.canaux_recus or []) + [canal]
            existant.save(update_fields=["canaux_recus"])
        return existant, False
    equipe = None
    if mission is not None:
        from django.db.models import Q
        equipe = mission.equipes.filter(Q(members=auteur) | Q(leader=auteur) | Q(regulateur=auteur)).first()
    try:
        with transaction.atomic():
            message = MessageTerrain.objects.create(
                auteur=auteur, mission=mission, equipe=equipe, crise=mission.crise if mission else None, type=type_,
                texte=(texte or "")[:2000], nombre=nombre, latitude="" if latitude is None else str(latitude),
                longitude="" if longitude is None else str(longitude), canal=canal, canaux_recus=[canal],
                emis_le=emis_le or timezone.now(), identifiant_client=(identifiant_client or "")[:16],
                environment=mission.environment if mission else _environnement(request))
    except IntegrityError:
        return MessageTerrain.objects.get(auteur=auteur, identifiant_client=identifiant_client), False
    _effets(message, request)
    return message, True


def _environnement(request):
    from .models import Environment
    from .permissions import get_active_environment
    return get_active_environment(request) if request is not None else Environment.PROD


def _effets(message, request):
    from .audit import audit_log

    libelle = message.get_type_display()
    detail = f" : {message.texte}" if message.texte else ""
    nombre = f" ({message.nombre} personne(s))" if message.nombre else ""
    audit_log(request=request, action_code="MODIFICATION", objet_type="MessageTerrain", objet_id=message.id,
              crise=message.crise,
              commentaire=f"{_nom(message.auteur)} — {libelle}{nombre}{detail}"
                          f"{' (par radio ' + message.get_canal_display() + ')' if message.canal != 'DONNEES' else ''}")
    if message.type in PRIORITAIRES:
        try:
            alerter(message, request)
        except Exception:
            logger.exception("Alerte prioritaire non envoyée pour le message de terrain %s.", message.id)


def _nom(user):
    return (f"{user.first_name} {user.last_name}".strip() or user.username) if user else "Intervenant"


def alerter(message, request=None):
    """Danger ou demande de secours : le régulateur et le chef de l'équipe, l'institution de la
    mission, par courriel et message Matrix, tout de suite."""
    from django.conf import settings

    from .audit import send_mail_logged
    from .matrix import envoyer_dm
    from .models import User
    from .permissions import INSTITUTIONAL_TYPES

    destinataires = set()
    if message.equipe is not None:
        for u in (message.equipe.regulateur, message.equipe.leader):
            if u is not None and u != message.auteur:
                destinataires.add(u)
    mission = message.mission
    if mission is not None and mission.institution_id:
        from django.db.models import Q

        from .models import ContactInstitution
        membres = ContactInstitution.objects.filter(institution_id=mission.institution_id, actif=True).values("utilisateur_id")
        destinataires |= set(User.objects.filter(Q(institution_id=mission.institution_id) | Q(id__in=membres),
                                                 type__in=INSTITUTIONAL_TYPES, is_active=True))
    titre = "🆘 Demande de premiers secours" if message.type == "PREMIERS_SECOURS" else "⚠ Danger signalé sur le terrain"
    corps = (f"{titre}\n\nPar : {_nom(message.auteur)}"
             f"{' — équipe ' + message.equipe.name if message.equipe else ''}\n"
             f"Mission : {mission.titre if mission else 'aucune'}\n"
             f"{'Motif' if message.type == 'PREMIERS_SECOURS' else 'Précision'} : {message.texte or 'non précisé'}\n"
             f"{'Position : ' + message.latitude + ', ' + message.longitude if message.latitude else 'Position non transmise'}\n"
             f"Reçu par : {message.get_canal_display()}")
    from .models import Environment
    if message.environment == Environment.DEMO:
        # Formation : jamais de vraie alerte à de vraies personnes. Comme send_mail_env_aware,
        # l'auteur seul reçoit ce que l'application aurait envoyé, marqué [DEMO] (22/11/2026).
        destinataires = {message.auteur}
        titre = f"[DEMO] {titre}"
        corps = f"[DEMO] {corps}"
    emails = [u.email for u in destinataires if u.email]
    if emails:
        send_mail_logged(request, f"[assista-crise] {titre}", corps, settings.DEFAULT_FROM_EMAIL, emails)
    for u in destinataires:
        try:
            envoyer_dm(u, corps)
        except Exception:
            logger.exception("Message Matrix non envoyé pour l'alerte de terrain %s.", message.id)


def depuis_radio(texte, canal):
    """Un message radio entré par un pont : s'il porte une étiquette, il devient un message de
    terrain (une fois). Ne lève jamais : le message radio lui-même est déjà enregistré."""
    from .models import Mission, User

    lu = lire_etiquette(texte)
    if lu is None:
        return None
    try:
        mission = None
        if lu["mission6"]:
            mission = next((m for m in Mission.objects.filter(statut__in=["EN_COURS", "EN_PREPARATION"]).only("id")
                            if str(m.id).replace("-", "").startswith(lu["mission6"])), None)
            if mission is not None:
                mission = Mission.objects.get(pk=mission.pk)
        candidats = []
        if mission is not None:
            for equipe in mission.equipes.all():
                candidats += list(equipe.members.all()) + [u for u in (equipe.leader, equipe.regulateur) if u]
        else:
            return None   # sans mission, on ne devine pas qui parle
        auteur = next((u for u in candidats if str(u.id).replace("-", "").startswith(lu["auteur6"])), None)
        if auteur is None:
            return None
        message, _cree = enregistrer(auteur, mission, lu["type"], texte=lu["texte"], canal=canal,
                                     identifiant_client=lu["ident"])
        return message
    except Exception:
        logger.exception("Étiquette de terrain reçue par radio non traitée.")
        return None
