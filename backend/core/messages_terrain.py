"""Messages de terrain en un geste (22/11/2026) : enregistrement, effets, et format radio.

Demande de Sylvain : « il faut pouvoir remonter facilement, par data classique, Meshtastic ou
MeshCore, des fonctions aussi simples que : arrivé sur les lieux, message de situation,
intervention terminée, on se rend à l'intervention suivante, disponible en retour, non
disponible en retour… », plus demande de renfort, danger, pause, et demande de premiers
secours avec son motif.

**Format radio** : lisible par un humain sur n'importe quelle radio, et reconnu par le serveur
quand le message arrive par un pont :

    ⚑ARR 3f2a9c.9c1e0b.a1b2c3.7d41e0 Arrivé sur les lieux
     │   │      │      │      └ début de l'identifiant du dossier (facultatif)
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
    "PAUSE": "PAUSE", "PS": "PREMIERS_SECOURS", "BES": "BESOIN",
}
CODE_DU_TYPE = {v: k for k, v in CODES.items()}
PRIORITAIRES = {"DANGER", "PREMIERS_SECOURS"}
#: Le statut courant de l'intervenant que chaque message établit (le PC le lit).
STATUT_DU_TYPE = {
    "ARRIVE": "Sur place", "TERMINEE": "Intervention terminée", "EN_ROUTE_SUIVANTE": "En route",
    "DISPONIBLE": "Disponible", "INDISPONIBLE": "Non disponible", "PAUSE": "En pause",
    "RENFORT": "Demande de renfort", "DANGER": "Danger signalé", "PREMIERS_SECOURS": "Demande de secours",
}

_ETIQUETTE = re.compile(r"⚑([A-Z]{2,7}) ([0-9a-f-]{6})\.([0-9a-f]{6})\.([0-9a-f]{6})(?:\.([0-9a-f]{6}))?(?: (.*))?$", re.S)


def lire_etiquette(texte):
    """Rend {type, mission6, auteur6, ident, texte} si le texte porte une étiquette, sinon None.
    L'étiquette peut suivre un préfixe ajouté par la radio ou le pont (« Nom: »)."""
    if not texte or "⚑" not in texte:
        return None
    m = _ETIQUETTE.search(texte[texte.index("⚑"):].strip())
    if not m or m.group(1) not in CODES:
        return None
    return {"type": CODES[m.group(1)], "mission6": None if m.group(2) == "------" else m.group(2),
            "auteur6": m.group(3), "ident": m.group(4), "dossier6": m.group(5), "texte": (m.group(6) or "").strip()}


def peut_ecrire(user, mission) -> bool:
    """Tout membre, chef ou régulateur d'une équipe de la mission."""
    from django.db.models import Q
    return mission.equipes.filter(Q(members=user) | Q(leader=user) | Q(regulateur=user)).exists()


def enregistrer(auteur, mission, type_, texte="", nombre=None, latitude=None, longitude=None,
                canal="DONNEES", emis_le=None, identifiant_client="", request=None, dossier=None):
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
                auteur=auteur, mission=mission, dossier=dossier, equipe=equipe,
                crise=mission.crise if mission else (dossier.crise if dossier is not None else None), type=type_,
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
    sur = f" — dossier {message.dossier.numero}" if message.dossier_id and message.dossier.numero else ""
    audit_log(request=request, action_code="MODIFICATION", objet_type="MessageTerrain", objet_id=message.id,
              crise=message.crise,
              commentaire=f"{_nom(message.auteur)} — {libelle}{nombre}{sur}{detail}"
                          f"{' (par radio ' + message.get_canal_display() + ')' if message.canal != 'DONNEES' else ''}")
    if message.type in PRIORITAIRES:
        try:
            alerter(message, request)
        except Exception:
            logger.exception("Alerte prioritaire non envoyée pour le message de terrain %s.", message.id)
    if message.type == "BESOIN":
        try:
            demande_du_besoin(message)
        except Exception:
            logger.exception("Besoin de terrain %s non transformé en demande.", message.id)


# --- Besoin relevé sur le terrain (27/11/2026) ---------------------------------------------
#
# « ⚑BES 3f2a9c.9c1e0b.a1b2c3 EVAC·A·EQ 44.80000,-0.59000 3 chevaux » : famille, pour qui,
# catégorie d'animaux (facultative), position (facultative), et quelques mots. Rien sur
# l'habitant : la demande créée porte le nom de l'intervenant qui l'a relevée.

_BESOIN = re.compile(
    r"^\s*([A-Z]{2,6})(?:[·.]([PAB]))?(?:[·.]([A-Z]{2}))?(?:\s+(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+))?(?:\s+(.*))?$", re.S)


def ecrire_besoin(code, beneficiaire=None, categorie=None, latitude=None, longitude=None, note=""):
    """Le corps d'un message BES (le pendant de l'application : domaine/MessageTerrain.kt)."""
    from .models import CODE_BENEFICIAIRE, CODE_CATEGORIE_ANIMAUX

    etiquette = code
    if beneficiaire:
        etiquette += "·" + CODE_BENEFICIAIRE[beneficiaire]
        if beneficiaire == "ANIMAUX" and categorie:
            etiquette += "·" + CODE_CATEGORIE_ANIMAUX[categorie]
    morceaux = [etiquette]
    if latitude is not None and longitude is not None:
        morceaux.append(f"{latitude:.5f},{longitude:.5f}")
    if note:
        morceaux.append(note.strip()[:30].rstrip())
    return " ".join(morceaux)


def lire_besoin(texte):
    """{code, beneficiaire, categorie, latitude, longitude, note} ou None."""
    from .models import CODE_BENEFICIAIRE, CODE_CATEGORIE_ANIMAUX

    texte = texte or ""
    # Par radio, l'étiquette ajoute le libellé : « Besoin relevé sur le terrain : EVAC·A … ».
    if " : " in texte:
        texte = texte.split(" : ", 1)[1]
    m = _BESOIN.match(texte)
    if not m:
        return None
    par_lettre = {v: k for k, v in CODE_BENEFICIAIRE.items()}
    par_code = {v: k for k, v in CODE_CATEGORIE_ANIMAUX.items()}
    lat = float(m.group(4)) if m.group(4) else None
    lon = float(m.group(5)) if m.group(5) else None
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = lon = None
    return {"code": m.group(1), "beneficiaire": par_lettre.get(m.group(2) or ""),
            "categorie": par_code.get(m.group(3) or ""), "latitude": lat, "longitude": lon,
            "note": (m.group(6) or "").strip()}


def demande_du_besoin(message):
    """Le besoin relevé devient une demande de la crise, puis un dossier rapproché comme les
    autres (du plus précis au plus général). Rend la demande, ou None."""
    from django.contrib.gis.geos import Point

    from .classement import beneficiaires_admis, choisir, competences_pour_demande, libelle_radio
    from .models import Dossier, Request, RequestType
    from .views import populate_dossier_participants_and_notify, resolve_besoin_for_request

    crise = message.crise
    lu = lire_besoin(message.texte)
    if crise is None or lu is None:
        return None
    type_ = (RequestType.objects.filter(code=lu["code"], parent__isnull=True, actif=True).first()
             or RequestType.objects.filter(code="AUTRE", parent__isnull=True).first())
    if type_ is None:
        return None
    admis = beneficiaires_admis(type_, "demande")
    beneficiaire = lu["beneficiaire"] if lu["beneficiaire"] in admis else (admis[0] if len(admis) == 1 else None)
    if beneficiaire is None and admis:
        beneficiaire = "PERSONNES" if "PERSONNES" in admis else admis[0]
    categorie = lu["categorie"] if beneficiaire == "ANIMAUX" else None
    lat, lon = lu["latitude"], lu["longitude"]
    if lat is None and message.latitude:
        lat, lon = float(message.latitude), float(message.longitude)
    nombre = None
    if beneficiaire == "ANIMAUX" and lu["note"][:1].isdigit():
        chiffres = re.match(r"\d+", lu["note"])
        nombre = int(chiffres.group(0)) if chiffres else None
    libelle = libelle_radio(type_, beneficiaire)
    auteur = message.auteur
    demande = Request.objects.create(
        title=f"Relevé terrain : {libelle}"[:150], description=lu["note"] or None,
        first_name_request=auteur.first_name or "Intervenant", last_name_request=auteur.last_name or "",
        email_request=auteur.email or "", phone_request="",
        request_type=type_, crisis=crise, author=auteur,
        location=Point(lon, lat, srid=4326) if lat is not None else None,
        beneficiaire=beneficiaire, categorie_animaux=categorie, nombre_animaux=nombre,
        environment=message.environment,
    )
    competence, equipe = choisir(crise, competences_pour_demande(demande), demande)
    import uuid as _uuid
    dossier = Dossier.objects.create(
        numero=f"DOS-{_uuid.uuid4().hex[:8].upper()}", crise=crise, competence=competence,
        besoin=resolve_besoin_for_request(demande), equipe=equipe, demande=demande,
        titre=demande.title, description=f"Besoin relevé par {_nom(auteur)} ({message.get_canal_display()})",
        statut=Dossier.Statut.EN_ATTENTE_AFFECTATION, environment=message.environment,
    )
    populate_dossier_participants_and_notify(dossier, equipe=equipe)
    return demande


def _nom(user):
    return (f"{user.first_name} {user.last_name}".strip() or user.username) if user else "Intervenant"


def alerter(message, request=None):
    """Danger ou demande de secours : le régulateur et le chef de l'équipe, l'institution de la
    mission, par courriel et par l'application (et le site), tout de suite."""
    from django.conf import settings

    from .audit import send_mail_logged
    from .models import User
    from .notifications_application import prevenir
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
             f"{'Dossier : ' + str(message.dossier.numero or '') + ' ' + str(message.dossier.titre or '') + chr(10) if message.dossier_id else ''}"
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
        prevenir(u, titre, corps, urgent=True, lien="/pilotage/terrain", crise=message.crise,
                 environment=message.environment)


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
        dossier = None
        if lu.get("dossier6"):
            dossier = next((d for d in mission.dossiers.all() if d.id.hex.startswith(lu["dossier6"])), None)
        message, _cree = enregistrer(auteur, mission, lu["type"], texte=lu["texte"], canal=canal,
                                     identifiant_client=lu["ident"], dossier=dossier)
        return message
    except Exception:
        logger.exception("Étiquette de terrain reçue par radio non traitée.")
        return None
