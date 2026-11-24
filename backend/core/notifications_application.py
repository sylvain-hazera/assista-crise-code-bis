"""Les notifications de l'application mobile, et ce qu'on sait de leur sort.

Demande de Sylvain du 14/11/2026 : mobiliser par l'application, « avec un feedback de qui a eu
la notif, vu, lu, répondu (une réponse négative est une réponse) ».

**Pourquoi le téléphone vient chercher, et pas l'inverse.** Pousser un message vers un
téléphone endormi passe par le service du fabricant (Google, Apple), donc par un compte chez
lui et par ses serveurs. L'application interroge ici à intervalle régulier : c'est plus lent
(jusqu'à un quart d'heure, application fermée) mais ne dépend de personne, et rien du contenu
ne sort de nos serveurs. Le jour où un service de réveil est branché, il n'aura qu'à dire
« viens lire » — ce module ne change pas.

**L'accusé est une affirmation du téléphone**, pas une mesure : « remise » veut dire que
l'application a reçu le message et demandé au système de l'afficher. Si la personne a coupé
les notifications, elle ne l'a pas vu pour autant — d'où `AppareilMobile.notifications_
autorisees`, que le suivi affiche à côté.
"""
import datetime
import json
import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Au-delà, on considère que l'application n'est plus sur ce téléphone. Une application
#: ouverte une fois il y a six mois ne joint personne, et l'annoncer comme un canal ferait
#: économiser un SMS qui, lui, serait arrivé.
APPAREIL_ACTIF_JOURS = 45

#: Ce que l'application garde sous les yeux. Plus ancien, c'est de l'archive.
FENETRE_JOURS = 60

ETAPE_REMISE = "REMISE"
ETAPE_VUE = "VUE"
ETAPE_LUE = "LUE"
#: Chaque étape entraîne les précédentes : on ne lit pas un message qu'on n'a pas reçu, et
#: un accusé perdu en route ne doit pas laisser un « lu, jamais remis » dans le suivi.
_ENTRAINE = {
    ETAPE_REMISE: ["date_remise"],
    ETAPE_VUE: ["date_remise", "date_vue"],
    ETAPE_LUE: ["date_remise", "date_vue", "date_lue"],
}


def joignables_par_application(utilisateur_ids):
    """Parmi ces personnes, celles dont un téléphone a parlé au serveur récemment."""
    from .models import AppareilMobile

    limite = timezone.now() - datetime.timedelta(days=APPAREIL_ACTIF_JOURS)
    return set(
        AppareilMobile.objects.filter(
            utilisateur_id__in=list(utilisateur_ids), dernier_contact__gte=limite,
        ).values_list("utilisateur_id", flat=True)
    )


def enregistrer_appareil(utilisateur, installation, plateforme="", version="",
                         notifications_autorisees=True, abonnement_push=None):
    """Le téléphone se présente. Idempotent : appelé à chaque ouverture de l'application.

    Un téléphone qui change de compte (déconnexion, puis connexion d'une autre personne) suit
    le dernier connecté : sinon l'ancien titulaire resterait « joignable » sur un appareil
    qu'il n'a plus en main."""
    from .models import AppareilMobile, PlateformeMobile
    from .web_push import valider_abonnement

    plateforme = plateforme if plateforme in PlateformeMobile.values else PlateformeMobile.ANDROID
    valeurs = {
        "utilisateur": utilisateur,
        "plateforme": plateforme,
        "version": (version or "")[:20],
        "notifications_autorisees": bool(notifications_autorisees),
        "dernier_contact": timezone.now(),
    }
    # Application web : l'abonnement aux notifications poussées (vérifié, lève
    # AbonnementRefuse). Absent : on garde celui qu'on a ; vide : on l'oublie.
    if abonnement_push is not None:
        valeurs["abonnement_push"] = json.dumps(valider_abonnement(abonnement_push)) if abonnement_push else ""
    appareil, _ = AppareilMobile.objects.update_or_create(installation=installation[:64], defaults=valeurs)
    return appareil


def oublier_appareil(utilisateur, installation):
    """À la déconnexion : ce téléphone ne joint plus cette personne."""
    from .models import AppareilMobile

    return AppareilMobile.objects.filter(
        utilisateur=utilisateur, installation=installation,
    ).delete()[0]


def notifier(utilisateur, genre, titre, corps="", *, urgent=False, institution=None,
             campagne=None, environment=None):
    """Dépose une notification pour une personne, si l'application peut la lui porter.

    Renvoie `None` quand elle n'a pas de téléphone actif : écrire quand même ferait apparaître
    dans le suivi un message « envoyé » que personne ne recevra jamais."""
    from .models import Environment, NotificationApplication

    if not joignables_par_application([utilisateur.id]):
        return None
    notification = NotificationApplication.objects.create(
        utilisateur=utilisateur, genre=genre, titre=titre, corps=corps or "",
        urgent=urgent, institution=institution, campagne=campagne,
        environment=environment or getattr(campagne, "environment", None) or Environment.PROD,
    )
    programmer_la_poussee(notification)
    return notification


def prevenir(utilisateur, titre, corps="", *, urgent=False, lien="", institution=None, crise=None,
             environment=None):
    """Prévenir une personne : la notification du site (cloche, et poussée vers le site installé
    sur son téléphone) ET l'application Android si elle l'a.

    Remplace les messages privés Matrix depuis l'arrêt de Matrix (demande de Sylvain du
    24/11/2026 : « tout ce qui passe par Matrix doit passer par l'application »). Ne lève
    jamais : une alerte qui n'a pas pu être déposée ne doit pas faire perdre le geste qui l'a
    déclenchée. Rend vrai si l'application Android porte le message."""
    from .models import Environment, GenreNotification, Notification

    environment = environment or getattr(crise, "environment", None) or Environment.PROD
    titre = (titre or "Notification").strip()[:200]
    try:
        Notification.objects.create(utilisateur=utilisateur, titre=titre, message=corps or "", crise=crise,
                                    lien=lien_relatif(lien, defaut="") if lien else "", environment=environment)
    except Exception:
        logger.exception("Notification du site non déposée (destinataire %s).", getattr(utilisateur, "id", None))
    try:
        return notifier(utilisateur, GenreNotification.INFORMATION, titre, corps, urgent=urgent,
                        institution=institution, environment=environment) is not None
    except Exception:
        logger.exception("Notification d'application non déposée (destinataire %s).", getattr(utilisateur, "id", None))
        return False


def prevenir_administrateurs(titre, corps="", *, urgent=False, lien=""):
    """Les administrateurs de la plateforme, chacun par `prevenir`. Rend le nombre atteint par
    l'application."""
    from .models import User, UserRole

    return sum(1 for admin in User.objects.filter(type=UserRole.ADMINISTRATOR, is_active=True)
               if prevenir(admin, titre, corps, urgent=urgent, lien=lien))


# ── Notifications poussées vers les applications web (DOSSIER-PWA-INTERVENANTS.md, lot 4) ──
#
# Seule exception au « le téléphone vient chercher » : sur iPhone, une application web fermée ne
# peut rien aller chercher. Le message est chiffré de bout en bout et ne porte que le titre et la
# page à ouvrir (voir core/web_push.py) ; le détail se lit dans l'application.

#: Ce que porte une notification poussée, au plus : un titre court.
TITRE_POUSSE_MAX = 120


def programmer_la_poussee(notification):
    """Après l'enregistrement : pousse vers les applications web de la personne, s'il y en a."""
    from .models import AppareilMobile, PlateformeMobile

    if not AppareilMobile.objects.filter(utilisateur_id=notification.utilisateur_id,
                                         plateforme=PlateformeMobile.WEB).exists():
        return
    from .tasks import pousser_notification_task

    identifiant = str(notification.id)
    transaction.on_commit(lambda: pousser_notification_task.delay(identifiant))


def pousser(notification_id, envoyer=None):
    """Envoie une notification à chaque application web abonnée de son destinataire. Rend le
    nombre d'envois acceptés. Un abonnement que le service dit expiré est oublié."""
    from . import web_push
    from .models import AppareilMobile, NotificationApplication, PlateformeMobile

    notification = NotificationApplication.objects.filter(id=notification_id).first()
    if notification is None:
        return 0
    envoyer = envoyer or web_push.envoyer
    message = {"titre": (notification.titre or "Nouvelle notification")[:TITRE_POUSSE_MAX],
               "lien": "/terrain/alertes", "id": str(notification.id), "urgent": notification.urgent}
    acceptes = 0
    # Le filtre sur l'abonnement se fait ici, en Python : la colonne est chiffrée.
    for appareil in AppareilMobile.objects.filter(utilisateur_id=notification.utilisateur_id,
                                                  plateforme=PlateformeMobile.WEB,
                                                  notifications_autorisees=True):
        if not appareil.abonnement_push:
            continue
        try:
            statut = envoyer(json.loads(appareil.abonnement_push), message, urgent=notification.urgent)
            acceptes += 1 if statut < 400 else 0
        except web_push.AbonnementExpire:
            appareil.abonnement_push = ""
            appareil.save(update_fields=["abonnement_push"])
        except Exception:
            logger.exception("Notification poussée non envoyée (appareil %s).", appareil.id)
    return acceptes


def accuser(utilisateur, identifiants, etape):
    """Le téléphone dit où en sont ces notifications. Renvoie combien ont avancé.

    Chaque date n'est écrite qu'une fois : la première remise est la vraie."""
    from .models import NotificationApplication

    champs = _ENTRAINE.get(etape)
    if not champs:
        return 0
    maintenant = timezone.now()
    avancees = 0
    for notification in NotificationApplication.objects.filter(
        utilisateur=utilisateur, id__in=list(identifiants),
    ):
        a_ecrire = [c for c in champs if getattr(notification, c) is None]
        if not a_ecrire:
            continue
        for champ in a_ecrire:
            setattr(notification, champ, maintenant)
        notification.save(update_fields=a_ecrire)
        avancees += 1
    return avancees


def noter_la_reponse(campagne, utilisateur):
    """La personne a répondu à la campagne — par l'application OU par le site.

    Appelée depuis `enregistrer_la_reponse` : quelqu'un qui reçoit la notification puis répond
    depuis son ordinateur a bien répondu, et le suivi de l'application doit le dire."""
    from .models import NotificationApplication

    maintenant = timezone.now()
    for notification in NotificationApplication.objects.filter(
        campagne=campagne, utilisateur=utilisateur, date_reponse__isnull=True,
    ):
        notification.date_reponse = maintenant
        notification.save(update_fields=["date_reponse"])


def suivi_par_personne(campagne):
    """Pour chaque personne notifiée : les étapes franchies par AU MOINS une notification.

    Une relance crée une seconde notification ; ce qui compte pour l'encadrement, c'est la
    personne, pas le message — on garde donc la date la plus ancienne de chaque étape."""
    from .models import AppareilMobile, NotificationApplication

    suivi = {}
    for n in NotificationApplication.objects.filter(campagne=campagne).order_by("date_creation"):
        ligne = suivi.setdefault(n.utilisateur_id, {
            "envoyee": n.date_creation, "remise": None, "vue": None, "lue": None,
            "notifications_autorisees": True,
        })
        for cle, champ in (("remise", "date_remise"), ("vue", "date_vue"), ("lue", "date_lue")):
            valeur = getattr(n, champ)
            if valeur and (ligne[cle] is None or valeur < ligne[cle]):
                ligne[cle] = valeur
    if suivi:
        sonnent = set(
            AppareilMobile.objects.filter(
                utilisateur_id__in=list(suivi), notifications_autorisees=True,
            ).values_list("utilisateur_id", flat=True)
        )
        for utilisateur_id, ligne in suivi.items():
            # Faux seulement si elles sont coupées sur TOUS ses téléphones : un seul qui
            # sonne suffit à prévenir.
            ligne["notifications_autorisees"] = utilisateur_id in sonnent
    return suivi


def bilan(campagne):
    """Les quatre chiffres demandés, sur les personnes — jamais sur les messages."""
    from .models import CibleCampagne, EtatCible

    suivi = suivi_par_personne(campagne)
    repondu = set(
        CibleCampagne.objects.filter(
            campagne=campagne, etat=EtatCible.A_REPONDU, utilisateur_id__in=list(suivi),
        ).values_list("utilisateur_id", "creneaux_declares")
    )
    return {
        "notifiees": len(suivi),
        "remises": sum(1 for s in suivi.values() if s["remise"]),
        "vues": sum(1 for s in suivi.values() if s["vue"]),
        "lues": sum(1 for s in suivi.values() if s["lue"]),
        "repondu": len(repondu),
        # Un « non » est une réponse, et c'est aussi une information : la garde ne sera pas
        # armée par ces personnes-là.
        "repondu_non": sum(1 for _u, creneaux in repondu if creneaux == 0),
    }


# ── Les notifications de l'administration (poste de pilotage sur iPad, lot 6) ─────────────

def lien_relatif(lien, defaut="/pilotage/alertes"):
    """Une page du site, jamais une adresse extérieure (« //exemple.fr » non plus). Sans page
    précise, la liste des alertes de l'espace Pilotage."""
    lien = (lien or "").strip()
    return lien if lien.startswith("/") and not lien.startswith("//") else defaut


def notification_site_creee(sender, instance, created, **kwargs):
    """Signal : une notification de l'administration vient d'être déposée pour quelqu'un."""
    from .models import AppareilMobile, PlateformeMobile

    if not created or not AppareilMobile.objects.filter(utilisateur_id=instance.utilisateur_id,
                                                        plateforme=PlateformeMobile.WEB).exists():
        return
    from .tasks import pousser_notification_site_task

    identifiant = str(instance.id)
    transaction.on_commit(lambda: pousser_notification_site_task.delay(identifiant))


def pousser_notification_site(notification_id, envoyer=None):
    """Comme `pousser`, pour une notification de l'administration : son titre et sa page. En
    zone de démonstration, le titre le dit (« Formation — »), pour ne jamais être pris pour du réel."""
    from . import web_push
    from .models import AppareilMobile, Notification, PlateformeMobile

    notification = Notification.objects.filter(id=notification_id).first()
    if notification is None:
        return 0
    envoyer = envoyer or web_push.envoyer
    titre = notification.titre or "Nouvelle notification"
    if notification.environment == "DEMO":
        titre = f"Formation — {titre}"
    message = {"titre": titre[:TITRE_POUSSE_MAX], "lien": lien_relatif(notification.lien), "id": str(notification.id)}
    acceptes = 0
    for appareil in AppareilMobile.objects.filter(utilisateur_id=notification.utilisateur_id,
                                                  plateforme=PlateformeMobile.WEB, notifications_autorisees=True):
        if not appareil.abonnement_push:
            continue
        try:
            acceptes += 1 if envoyer(json.loads(appareil.abonnement_push), message) < 400 else 0
        except web_push.AbonnementExpire:
            appareil.abonnement_push = ""
            appareil.save(update_fields=["abonnement_push"])
        except Exception:
            logger.exception("Notification poussée non envoyée (appareil %s).", appareil.id)
    return acceptes

