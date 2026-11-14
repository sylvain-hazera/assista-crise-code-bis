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

from django.utils import timezone

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
                         notifications_autorisees=True):
    """Le téléphone se présente. Idempotent : appelé à chaque ouverture de l'application.

    Un téléphone qui change de compte (déconnexion, puis connexion d'une autre personne) suit
    le dernier connecté : sinon l'ancien titulaire resterait « joignable » sur un appareil
    qu'il n'a plus en main."""
    from .models import AppareilMobile, PlateformeMobile

    plateforme = plateforme if plateforme in PlateformeMobile.values else PlateformeMobile.ANDROID
    appareil, _ = AppareilMobile.objects.update_or_create(
        installation=installation[:64],
        defaults={
            "utilisateur": utilisateur,
            "plateforme": plateforme,
            "version": (version or "")[:20],
            "notifications_autorisees": bool(notifications_autorisees),
            "dernier_contact": timezone.now(),
        },
    )
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
    return NotificationApplication.objects.create(
        utilisateur=utilisateur, genre=genre, titre=titre, corps=corps or "",
        urgent=urgent, institution=institution, campagne=campagne,
        environment=environment or getattr(campagne, "environment", None) or Environment.PROD,
    )


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
