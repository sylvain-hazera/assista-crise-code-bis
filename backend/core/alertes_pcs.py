"""Diffusion de l'annuaire PCS/PICS lors d'une déclaration de crise -- voir le plan de
conception "Annuaire d'alerte PCS/PICS" et les docstrings de InterlocuteurAlertePCS/
NotificationAlertePCS (core/models.py).

Déroulé en deux temps, demande utilisateur du 11/10 :
1. `preparer_checklist_pcs` -- appelé automatiquement par CrisisViewSet.perform_create. Crée
   UNE ligne NotificationAlertePCS par interlocuteur actif rattaché à l'institution, mais
   N'ENVOIE RIEN : juste la checklist, prête à être relue.
2. `envoyer_notifications` -- appelé explicitement par NotificationAlertePCSViewSet.envoyer_lot
   quand l'utilisateur qui a déclenché le PCS a choisi ses destinataires et (ré)écrit le
   message, "pour cette fois uniquement" (jamais persisté comme nouveau modèle par défaut).

Même esprit que core/matrix.py/verifier_alertes_sismiques.py : un petit registre {canal:
fonction} pour que SMS/Intramuros/Facebook s'ajoutent plus tard par une fonction + une entrée,
sans toucher au reste -- un canal absent du registre (TELEPHONE/SMS/API_TIERCE/AUCUN) retombe
automatiquement sur la checklist manuelle (NotificationAlertePCSViewSet.confirmer)."""
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .matrix import envoyer_dm
from .models import InterlocuteurAlertePCS, ModeAlertePCS, NotificationAlertePCS, StatutNotificationPCS
from .permissions import send_mail_env_aware

logger = logging.getLogger(__name__)


def preparer_checklist_pcs(crise, institution):
    """Crée une ligne de checklist pour chaque interlocuteur actif rattaché à `institution` --
    sans rien envoyer (voir docstring du module). Chaque ligne isolée dans son propre
    try/except : un interlocuteur mal configuré ne doit jamais empêcher la création des
    suivants, ni (via l'appelant) la déclaration de la crise elle-même."""
    interlocuteurs = InterlocuteurAlertePCS.objects.filter(institutions=institution, actif=True)

    for interlocuteur in interlocuteurs:
        try:
            NotificationAlertePCS.objects.create(
                crise=crise,
                interlocuteur=interlocuteur,
                nom_snapshot=interlocuteur.nom,
                organisme_snapshot=interlocuteur.organisme,
                categorie_snapshot=interlocuteur.categorie,
                institution_nom_snapshot=institution.nom,
                canal_tente=interlocuteur.mode_alerte,
                token_confirmation=secrets.token_urlsafe(32),
                environment=crise.environment,
                # Tous figurent dans la liste ; ceux que l'annuaire dit de prévenir à
                # l'ouverture sont cochés d'avance. Rien ne part sans le clic de quelqu'un.
                preselectionne=interlocuteur.prevenir_ouverture_crise,
            )
        except Exception:
            logger.exception(
                "Impossible de créer la ligne de checklist PCS pour l'interlocuteur %s (crise %s).",
                interlocuteur.id, crise.id,
            )


def preparer_checklist_centre(point, institution) -> int:
    """À l'ouverture d'un centre d'accueil : prépare la liste des interlocuteurs que l'annuaire
    dit de prévenir à ce moment-là (18/11/2026). Rien n'est envoyé — même principe que
    `preparer_checklist_pcs` : la liste attend d'être relue et confirmée d'un clic.

    Rejouable : un même centre ne prépare pas deux fois la même ligne."""
    if point.crise_id is None or institution is None:
        return 0
    faites = 0
    for interlocuteur in InterlocuteurAlertePCS.objects.filter(institutions=institution, actif=True, prevenir_ouverture_centre=True):
        try:
            if NotificationAlertePCS.objects.filter(crise_id=point.crise_id, interlocuteur=interlocuteur, motif="CENTRE", point=point).exists():
                continue
            with transaction.atomic():
              NotificationAlertePCS.objects.create(
                crise_id=point.crise_id, interlocuteur=interlocuteur, nom_snapshot=interlocuteur.nom,
                organisme_snapshot=interlocuteur.organisme, categorie_snapshot=interlocuteur.categorie,
                institution_nom_snapshot=institution.nom, canal_tente=interlocuteur.mode_alerte,
                token_confirmation=secrets.token_urlsafe(32), environment=point.environment,
                motif="CENTRE", point=point, point_nom_snapshot=point.nom[:255], preselectionne=True,
            )
            faites += 1
        except Exception:
            logger.exception("Impossible de préparer la prévenance de l'interlocuteur %s pour le centre %s.", interlocuteur.id, point.id)
    return faites


def _lien_accuse_reception(notification) -> str:
    base_url = settings.SERVER_URL.rstrip('/')
    return f"{base_url}/confirmation-pcs/{notification.token_confirmation}"


def _envoyer_email(interlocuteur, crise, notification, message, request):
    if not interlocuteur.email:
        raise ValueError("Aucune adresse email renseignée pour ce contact.")
    sujet = f"[PCS] Activation du plan communal de sauvegarde — {crise.name}"
    corps = (
        f"{message}\n\n"
        "---\n"
        "Pour accuser réception de cette alerte (et éviter un appel téléphonique de "
        f"relance si ce n'est pas nécessaire) : {_lien_accuse_reception(notification)}"
    )
    send_mail_env_aware(
        request, subject=sujet, message=corps, from_email=None,
        recipient_list=[interlocuteur.email], fail_silently=False,
    )


def _envoyer_matrix(interlocuteur, crise, notification, message, request):
    if not interlocuteur.utilisateur:
        raise ValueError("Aucun compte utilisateur lié -- envoi Matrix impossible.")
    texte = f"{message}\n\nAccuser réception : {_lien_accuse_reception(notification)}"
    envoyer_dm(interlocuteur.utilisateur, texte)


# Un canal absent de ce registre (TELEPHONE/SMS/API_TIERCE/AUCUN) n'est jamais sélectionnable
# depuis envoyer_notifications -- reste EN_ATTENTE, à traiter via la checklist manuelle
# (NotificationAlertePCSViewSet.confirmer). Ajouter un canal plus tard (SMS, Intramuros,
# Facebook...) : une fonction + une entrée ici, rien d'autre à changer.
_REGISTRE_ENVOI = {
    ModeAlertePCS.EMAIL: _envoyer_email,
    ModeAlertePCS.MATRIX: _envoyer_matrix,
}

STATUTS_TERMINAUX = {
    StatutNotificationPCS.ENVOYE_AUTO,
    StatutNotificationPCS.CONFIRME_PAR_CONTACT,
    StatutNotificationPCS.CONFIRME_MANUEL,
}


def envoyer_notifications(request, notifications, message):
    """Tente l'envoi (email/Matrix) pour chaque notification fournie, avec le texte `message`
    choisi/modifié par l'utilisateur pour cette fois uniquement. Ignore silencieusement les
    lignes déjà dans un statut terminal (permet de rappeler cette action sans spammer) et
    celles dont le canal n'a pas d'envoi automatique. Retourne le nombre de lignes effectivement
    traitées (envoyées ou en échec, pour affichage)."""
    traitees = 0
    for notification in notifications:
        if notification.statut in STATUTS_TERMINAUX:
            continue
        envoyer = _REGISTRE_ENVOI.get(notification.canal_tente)
        if envoyer is None:
            continue

        interlocuteur = notification.interlocuteur
        if interlocuteur is None:
            notification.statut = StatutNotificationPCS.ECHEC_AUTO
            notification.detail_erreur = "Interlocuteur retiré de l'annuaire depuis la création de la checklist."
        else:
            try:
                envoyer(interlocuteur, notification.crise, notification, message, request)
                notification.statut = StatutNotificationPCS.ENVOYE_AUTO
                notification.detail_erreur = None
            except Exception as exc:
                logger.exception(
                    "Échec envoi alerte PCS (%s) pour la notification %s.",
                    notification.canal_tente, notification.id,
                )
                notification.statut = StatutNotificationPCS.ECHEC_AUTO
                notification.detail_erreur = str(exc)

        notification.message_envoye = message
        notification.date_envoi_auto = timezone.now()
        notification.save(update_fields=["statut", "detail_erreur", "message_envoye", "date_envoi_auto"])
        traitees += 1

    return traitees
