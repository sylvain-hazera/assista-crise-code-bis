"""Le circuit réflexe « feu de forêt → points d'eau → binômes RCSC → cellule → CODIS »
(24/11/2026). Demande de Sylvain : « type FDF => activation des points d'eau => équipe RCSC =>
tel binôme une pompe là => point d'eau X actif, les pompiers peuvent venir remplir leur camion
=> prévenance cellule de crise => prévenance CODIS ».

Le déroulé :
1. À l'ouverture d'une crise feu (type INCENDIE), le pilotage PROPOSE d'activer les points
   d'eau ; rien ne part sans un clic de la cellule (une fausse alerte n'appelle personne).
2. La cellule choisit à chaud les points (parmi les points d'eau connus autour de la crise) et
   l'équipe envoyée sur chacun : une mission « Pompe au point d'eau X » part à l'équipe, ses
   membres sont notifiés en urgence.
3. Le binôme déclare depuis l'application : en route, pompe en place (point ACTIF), fermé.
4. Au passage ACTIF : le point passe en vert « remplissage possible » sur les cartes ; la
   cellule le lit dans sa conversation et sa chronologie ; le CODIS reçoit un email (avec accusé
   de réception et le lien de la carte en direct) et la cellule a une tâche « appeler le
   CODIS », cochée d'elle-même quand le CODIS accuse réception.

La carte du CODIS (lien sans compte, jeton chiffré et retrouvé par son empreinte) ne montre
aucun nom de personne : des points, leur état, l'indicatif de l'équipe.
"""
import datetime
import logging
import secrets

from django.conf import settings
from django.contrib.gis.measure import D
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

MARGE_KM = 5
CANDIDATS_MAX = 300
TRANSITIONS = {
    "DEMANDE": {"EN_ROUTE", "ACTIF", "ANNULE"},
    "EN_ROUTE": {"ACTIF", "ANNULE"},
    "ACTIF": {"FERME"},
    "FERME": {"ACTIF"},
    "ANNULE": set(),
}
LIBELLES_ETAT = {"EN_ROUTE": "binôme en route", "ACTIF": "actif, remplissage possible", "FERME": "fermé",
                 "ANNULE": "annulé"}


# ── Droits ───────────────────────────────────────────────────────────────────

def peut_piloter(user, crise):
    """La cellule : régulation de la crise (autorité locale impliquée, régulateurs, admin)."""
    from .conversations import est_regulation

    return bool(user and user.is_authenticated and est_regulation(user, crise))


def peut_declarer(user, activation):
    """Le binôme (membre, chef ou encadrement de l'équipe envoyée) ou la cellule."""
    from .conversations import dans_equipe

    if not (user and user.is_authenticated):
        return False
    if activation.equipe_id and dans_equipe(user, activation.equipe):
        return True
    return peut_piloter(user, activation.crise)


def institution_de(user, crise):
    from .models import ImplicationInstitution, StatutImplication

    if getattr(user, "institution_id", None):
        return user.institution
    implication = ImplicationInstitution.objects.filter(crise=crise, actif=True, statut=StatutImplication.VALIDEE) \
        .select_related("institution").first()
    return implication.institution if implication else None


# ── Lecture ──────────────────────────────────────────────────────────────────

def propose(crise):
    from .models import TypeCrise

    return (crise.type == TypeCrise.INCENDIE and crise.end_date is None
            and not crise.activations_point_eau.exclude(statut="ANNULE").exists())


def _lambert93(location):
    from .points_eau import lambert93
    return lambert93(location)


def activation_en_dict(a, avec_noms=True):
    return {
        "id": str(a.id), "nom": a.nom, "type_pei": a.type_pei, "debit": a.debit, "volume": a.volume,
        "latitude": a.location.y, "longitude": a.location.x, "gps": f"{a.location.y:.5f}, {a.location.x:.5f}",
        "lambert93": dict(zip(("x", "y"), _lambert93(a.location))), "pei": a.pei_id, "statut": a.statut,
        "statut_libelle": a.get_statut_display(),
        "equipe": (a.equipe.name if avec_noms else None) if a.equipe_id else None,
        "indicatif": (a.equipe.indicatif or None) if a.equipe_id else None,
        "equipe_id": str(a.equipe_id) if a.equipe_id and avec_noms else None,
        "mission": str(a.mission_id) if a.mission_id and avec_noms else None,
        "demande_le": a.demande_le.isoformat(), "en_route_le": a.en_route_le.isoformat() if a.en_route_le else None,
        "actif_le": a.actif_le.isoformat() if a.actif_le else None, "ferme_le": a.ferme_le.isoformat() if a.ferme_le else None,
        "codis_prevenu_le": a.codis_prevenu_le.isoformat() if a.codis_prevenu_le else None,
    }


def candidats(crise):
    """Points d'eau connus autour de la crise (rayon de la crise + 5 km), du plus proche au
    plus loin, sans ceux déjà activés."""
    from . import points_eau

    rayon = (crise.radius or 10) + MARGE_KM
    deja = set(crise.activations_point_eau.exclude(statut="ANNULE").values_list("pei_id", flat=True))
    qs = (points_eau.visibles(crise.environment).filter(location__distance_lte=(crise.location, D(km=rayon)))
          .exclude(pk__in=[d for d in deja if d]))
    from .views_veille import _distance_km
    points = sorted(((round(_distance_km(crise.location.y, crise.location.x, p.location.y, p.location.x), 2), p)
                     for p in qs[:CANDIDATS_MAX * 3]), key=lambda c: c[0])[:CANDIDATS_MAX]
    # Adresse, GPS et Lambert 93 : de quoi trouver le point sur le terrain (24/11/2026).
    return [points_eau.en_dict(p, d, avec_localisation=True) for d, p in points]


def equipes_mobilisables(crise, user):
    from django.db.models import Q

    from .conversations import equipes_de_la_crise
    from .models import Team

    institution = getattr(user, "institution_id", None)
    qs = Team.objects.filter(Q(pk__in=equipes_de_la_crise(crise).values("pk")) | (Q(institution_id=institution) if institution else Q(pk__in=[])))
    return [{"id": str(e.id), "nom": e.name, "indicatif": e.indicatif or None, "effectif": e.members.count()}
            for e in qs.distinct().order_by("name")]


def lien_actif(crise):
    return crise.liens_codis.filter(revoque_le__isnull=True).first()


def url_codis(lien):
    return f"{settings.SERVER_URL.rstrip('/')}/codis/{lien.jeton}"


def etat(crise, user):
    from .models import NotificationAlertePCS, StatutNotificationPCS

    activations = list(crise.activations_point_eau.select_related("equipe").order_by("demande_le"))
    lien = lien_actif(crise)
    prevenances = [{
        "id": str(n.id), "organisme": n.organisme_snapshot, "point": n.point_nom_snapshot, "statut": n.statut,
        "statut_libelle": n.get_statut_display(), "envoye_le": n.date_envoi_auto.isoformat() if n.date_envoi_auto else None,
        "accuse_le": n.date_confirmation.isoformat() if n.date_confirmation else None,
    } for n in NotificationAlertePCS.objects.filter(crise=crise, motif="POINT_EAU").order_by("-date_creation")[:50]]
    sans_accuse = sum(1 for p in prevenances if p["statut"] in (StatutNotificationPCS.ENVOYE_AUTO, StatutNotificationPCS.EN_ATTENTE,
                                                                StatutNotificationPCS.ECHEC_AUTO))
    return {
        "crise": str(crise.id), "type": crise.type, "propose": propose(crise), "peut_piloter": peut_piloter(user, crise),
        "activations": [activation_en_dict(a) for a in activations],
        "actifs": sum(1 for a in activations if a.statut == "ACTIF"),
        "lien_codis": url_codis(lien) if lien and peut_piloter(user, crise) else None,
        "prevenances_codis": prevenances, "codis_sans_accuse": sans_accuse,
        "interlocuteurs_codis": len(_interlocuteurs_codis(institution_de(user, crise))),
    }


# ── Activation ───────────────────────────────────────────────────────────────

def nom_du_point(point):
    """« Poteau d'incendie n° 12 — à 40 m du 12 rue de la Gare, 43000 Le Puy-en-Velay » : le nom
    porté par l'activation, la mission et la carte du CODIS."""
    from . import points_eau

    adresse = points_eau.localisation(point.location, point.insee)["adresse"]
    nom = points_eau.nom_du_point(point)
    return f"{nom} — {adresse}" if adresse else nom


@transaction.atomic
def activer(crise, affectations, request):
    """Ouvre les points choisis, chacun avec son équipe. Idempotent par (crise, point) : un
    point déjà ouvert garde son activation (son équipe peut changer)."""
    from . import points_eau
    from .models import ActivationPointEau, JalonCrise, Mission, Team

    institution = institution_de(request.user, crise)
    crees = []
    for affectation in affectations:
        point = points_eau.visibles(crise.environment, True).filter(pk=affectation.get("pei")).first()
        equipe = Team.objects.filter(pk=affectation.get("equipe")).first() if affectation.get("equipe") else None
        if point is None:
            raise ValueError("Point d'eau introuvable.")
        if equipe is None:
            raise ValueError(f"Choisissez l'équipe envoyée au point « {nom_du_point(point)} ».")
        existante = crise.activations_point_eau.filter(pei=point).first()
        if existante is not None and existante.statut != "ANNULE":
            if existante.equipe_id != equipe.id:
                existante.equipe = equipe
                existante.save(update_fields=["equipe"])
                if existante.mission_id:
                    existante.mission.equipes.set([equipe])
                _appeler_equipe(existante, request)
            crees.append(existante)
            continue
        nom = nom_du_point(point)
        mission = Mission.objects.create(
            titre=f"Pompe au point d'eau {nom}"[:200],
            description=(f"Mettre une pompe en place au point d'eau « {nom} » (GPS {point.location.y:.5f}, {point.location.x:.5f} ; "
                         f"Lambert 93 X {_lambert93(point.location)[0]} Y {_lambert93(point.location)[1]}) "
                         "et le déclarer actif dans l'application : les pompiers pourront venir y remplir leurs camions."),
            crise=crise, statut=Mission.Statut.EN_COURS, environment=crise.environment, institution=institution,
        )
        mission.equipes.add(equipe)
        if existante is not None:   # annulée auparavant : on la rouvre
            activation = existante
            activation.equipe, activation.mission, activation.statut = equipe, mission, "DEMANDE"
            activation.en_route_le = activation.actif_le = activation.ferme_le = None
            activation.save()
        else:
            activation = ActivationPointEau.objects.create(
                crise=crise, institution=institution, pei=point, nom=nom[:120], type_pei=point.type_pei,
                debit=point.debit, volume=point.volume, location=point.location, equipe=equipe, mission=mission,
                demande_par=request.user, environment=crise.environment,
            )
        _appeler_equipe(activation, request)
        crees.append(activation)
    if crees and institution is not None:
        JalonCrise.objects.create(crise=crise, institution=institution, auteur=request.user, environment=crise.environment,
                                  libelle=f"Points d'eau activés : {', '.join(a.nom for a in crees)}"[:500])
    return crees


def _appeler_equipe(activation, request):
    """Les membres de l'équipe envoyée : notification urgente (application et site)."""
    from .models import GenreNotification, Notification
    from .notifications_application import notifier

    if activation.equipe is None:
        return
    titre = f"Point d'eau à ouvrir : {activation.nom}"
    corps = (f"Crise « {activation.crise.name} » : mettez une pompe au point d'eau {activation.nom}, puis déclarez-le "
             "actif dans la mission.")
    membres = set(activation.equipe.members.all())
    if activation.equipe.leader:
        membres.add(activation.equipe.leader)
    for membre in membres:
        Notification.objects.create(utilisateur=membre, titre=titre, message=corps, crise=activation.crise,
                                    environment=activation.environment)
        try:
            notifier(membre, GenreNotification.INFORMATION, titre, corps, urgent=True, environment=activation.environment)
        except Exception:   # noqa: BLE001 - la notification du site suffit
            logger.exception("Notification d'application d'un point d'eau à ouvrir")


# ── États déclarés ───────────────────────────────────────────────────────────

def changer_etat(activation, nouvel_etat, request, observe_le=None):
    """Applique un état ; rejouable (un état déjà atteint ne refait rien). Rend True si l'état
    a changé."""
    if nouvel_etat == activation.statut:
        return False
    if nouvel_etat not in TRANSITIONS.get(activation.statut, set()):
        raise ValueError(f"Passage impossible de « {activation.get_statut_display()} » à « {nouvel_etat} ».")
    maintenant = timezone.now()
    observe_le = min(observe_le or maintenant, maintenant)
    activation.statut = nouvel_etat
    activation.declare_par = request.user
    champ = {"EN_ROUTE": "en_route_le", "ACTIF": "actif_le", "FERME": "ferme_le"}.get(nouvel_etat)
    if champ:
        setattr(activation, champ, observe_le)
    activation.save()
    if nouvel_etat in ("ACTIF", "FERME"):
        prevenir(activation, request)
    elif nouvel_etat == "EN_ROUTE":
        _dire_a_la_cellule(activation, f"Point d'eau {activation.nom} : {LIBELLES_ETAT['EN_ROUTE']} ({_equipe(activation)}).")
    if nouvel_etat in ("FERME", "ANNULE") and activation.mission_id:
        activation.mission.statut = "TERMINEE"
        activation.mission.date_cloture = maintenant
        activation.mission.save(update_fields=["statut", "date_cloture"])
    return True


def _equipe(activation):
    if activation.equipe is None:
        return "équipe non précisée"
    return f"équipe {activation.equipe.indicatif or activation.equipe.name}"


def _dire_a_la_cellule(activation, texte, urgent=False):
    from . import conversations as conv
    from .models import GenreConversation, SourceMessage

    try:
        conversation = conv.conversation_crise(activation.crise, GenreConversation.CELLULE, environment=activation.environment)
        conv.ecrire(conversation, texte, auteur_libre="Circuit points d'eau", source=SourceMessage.SYSTEME, urgent=urgent,
                    dedupliquer=False)
    except Exception:   # noqa: BLE001 - la chronologie et le CODIS ne doivent pas en dépendre
        logger.exception("Message de cellule du circuit points d'eau")


def prevenir(activation, request):
    """Au passage ACTIF ou FERME : la cellule (conversation, chronologie) puis le CODIS (email
    avec accusé, lien de la carte, tâche d'appel)."""
    from .models import ActionCellule, JalonCrise

    heure = timezone.localtime(activation.actif_le if activation.statut == "ACTIF" else activation.ferme_le or timezone.now())
    if activation.statut == "ACTIF":
        texte = (f"Point d'eau {activation.nom} ACTIF depuis {heure:%H h %M} ({_equipe(activation)}) : "
                 "les pompiers peuvent venir remplir.")
    else:
        texte = f"Point d'eau {activation.nom} FERMÉ à {heure:%H h %M} ({_equipe(activation)})."
    _dire_a_la_cellule(activation, texte, urgent=activation.statut == "ACTIF")
    institution = activation.institution or institution_de(request.user, activation.crise)
    if institution is not None:
        JalonCrise.objects.create(crise=activation.crise, institution=institution, auteur=request.user, libelle=texte[:500],
                                  environment=activation.environment)
    lien = lien_actif(activation.crise) or creer_lien(activation.crise, request.user)
    envoyes = envoyer_codis(activation, institution, lien, request)
    if activation.statut == "ACTIF" and institution is not None:
        telephones = ", ".join(t for t in (i.telephone for i in _interlocuteurs_codis(institution)) if t) or "numéro à trouver dans l'annuaire"
        activation.action_codis = ActionCellule.objects.create(
            crise=activation.crise, institution=institution, intitule=f"Appeler le CODIS : point d'eau {activation.nom} actif",
            responsable_libre="CODIS", commentaire=f"Téléphone : {telephones}. Email envoyé à {envoyes} contact(s) SDIS.",
            echeance=timezone.now() + datetime.timedelta(minutes=10), cree_par=request.user, environment=activation.environment,
        )
    activation.codis_prevenu_le = timezone.now()
    activation.save(update_fields=["codis_prevenu_le", "action_codis"])


def _interlocuteurs_codis(institution):
    from .models import CategorieInterlocuteurPCS, InterlocuteurAlertePCS

    if institution is None:
        return []
    return list(InterlocuteurAlertePCS.objects.filter(institutions=institution, actif=True,
                                                      categorie=CategorieInterlocuteurPCS.SDIS))


def envoyer_codis(activation, institution, lien, request):
    """Un email à chaque interlocuteur SDIS de l'annuaire de l'institution, avec le lien
    d'accusé de réception existant et celui de la carte en direct. Rend le nombre d'envois."""
    from .alertes_pcs import _lien_accuse_reception
    from .models import ModeAlertePCS, NotificationAlertePCS, StatutNotificationPCS
    from .permissions import send_mail_env_aware

    envoyes = 0
    ouvert = activation.statut == "ACTIF"
    for interlocuteur in _interlocuteurs_codis(institution):
        notification = NotificationAlertePCS.objects.create(
            crise=activation.crise, interlocuteur=interlocuteur, nom_snapshot=interlocuteur.nom,
            organisme_snapshot=interlocuteur.organisme, categorie_snapshot=interlocuteur.categorie,
            institution_nom_snapshot=institution.nom, canal_tente=ModeAlertePCS.EMAIL,
            token_confirmation=secrets.token_urlsafe(32), environment=activation.environment, motif="POINT_EAU",
            activation=activation, point_nom_snapshot=activation.nom[:255], preselectionne=True,
        )
        message = (
            f"{'OUVERT' if ouvert else 'FERMÉ'} — point d'eau {activation.nom}, crise « {activation.crise.name} ».\n"
            f"Position GPS : {activation.location.y:.5f}, {activation.location.x:.5f}"
            f" — Lambert 93 : X {_lambert93(activation.location)[0]} Y {_lambert93(activation.location)[1]}"
            f" (https://www.openstreetmap.org/?mlat={activation.location.y:.5f}&mlon={activation.location.x:.5f}#map=17/"
            f"{activation.location.y:.5f}/{activation.location.x:.5f})\n"
            + (f"Débit indiqué : {activation.debit:g} m3/h\n" if activation.debit else "")
            + (f"Volume indiqué : {activation.volume:g} m3\n" if activation.volume else "")
            + (f"Remplissage possible : une pompe est en place ({_equipe(activation)}).\n" if ouvert
               else "Le point n'est plus tenu.\n")
            + f"\nCarte en direct des points d'eau de la crise : {url_codis(lien)}\n"
        )
        if not interlocuteur.email:
            notification.statut = StatutNotificationPCS.ECHEC_AUTO
            notification.detail_erreur = "Aucune adresse email : à appeler."
        else:
            try:
                send_mail_env_aware(
                    request, subject=f"[Point d'eau {'OUVERT' if ouvert else 'FERMÉ'}] {activation.nom} — {activation.crise.name}",
                    message=message + f"\nAccuser réception : {_lien_accuse_reception(notification)}\n",
                    from_email=None, recipient_list=[interlocuteur.email], fail_silently=False,
                )
                notification.statut = StatutNotificationPCS.ENVOYE_AUTO
                envoyes += 1
            except Exception as erreur:   # noqa: BLE001 - l'appel par la cellule prend le relais
                logger.exception("Email CODIS du circuit points d'eau")
                notification.statut = StatutNotificationPCS.ECHEC_AUTO
                notification.detail_erreur = str(erreur)[:500]
        notification.message_envoye = message
        notification.date_envoi_auto = timezone.now()
        notification.save(update_fields=["statut", "detail_erreur", "message_envoye", "date_envoi_auto"])
    return envoyes


def accuse_codis(notification):
    """Le CODIS a accusé réception : la tâche d'appel de ce point est cochée d'elle-même."""
    activation = notification.activation
    if activation is None or activation.action_codis is None:
        return
    action = activation.action_codis
    if action.statut in (action.Statut.A_FAIRE, action.Statut.EN_COURS):
        action.statut = action.Statut.FAIT
        action.faite_le = timezone.now()
        action.commentaire = (action.commentaire + f" Accusé de réception de {notification.organisme_snapshot or 'du CODIS'}.").strip()
        action.save(update_fields=["statut", "faite_le", "commentaire"])


# ── Carte du CODIS ───────────────────────────────────────────────────────────

def creer_lien(crise, user):
    from .models import LienCodis

    crise.liens_codis.filter(revoque_le__isnull=True).update(revoque_le=timezone.now())
    return LienCodis.objects.create(crise=crise, jeton=secrets.token_urlsafe(32), cree_par=user, environment=crise.environment)


def carte_codis(jeton):
    """Ce que voit le CODIS : les points actifs et ceux fermés depuis moins de 12 h. None si le
    lien est inconnu, révoqué, ou la crise close."""
    from .crypto_fields import empreinte_jeton
    from .models import LienCodis

    lien = LienCodis.objects.filter(jeton_empreinte=empreinte_jeton(jeton), revoque_le__isnull=True).select_related("crise").first()
    if lien is None or lien.crise.end_date is not None:
        return None
    depuis = timezone.now() - datetime.timedelta(hours=12)
    activations = lien.crise.activations_point_eau.select_related("equipe").exclude(statut="ANNULE")
    points = [activation_en_dict(a, avec_noms=False) for a in activations
              if a.statut in ("ACTIF", "EN_ROUTE", "DEMANDE") or (a.ferme_le and a.ferme_le >= depuis)]
    return {"crise": lien.crise.name, "maj": timezone.now().isoformat(), "points": points,
            "actifs": sum(1 for p in points if p["statut"] == "ACTIF"),
            "centre": {"latitude": lien.crise.location.y, "longitude": lien.crise.location.x}}
