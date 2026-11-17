"""Prévenir les bonnes personnes quand un appel aux dons avance (core/appels_dons.py).

Demande de Sylvain du 17/11/2026 : « fais le nécessaire pour les envois de courrier, avec la
personnalisation si nécessaire ; branche aussi les notifications via l'application ou Matrix ».

Quatre canaux, chacun pour ce qu'il sait faire :

- la **notification du site** (`Notification`), pour la personne concernée ;
- l'**application mobile** (`notifications_application.notifier`), si elle l'a sur son téléphone ;
- le **courriel**, par `send_branded_mail` : signature et adresse de l'institution qui écrit ;
- le **salon Matrix des permanents** de l'institution destinataire, pour que l'équipe le voie.

On prévient des PERSONNES PRÉCISES (qui a lancé l'appel, qui s'est engagé), jamais tout un
annuaire : un appel qui écrit à cent personnes à chaque engagement, plus personne ne le lit.
Aucun canal ne fait échouer le geste qui l'a déclenché.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

LIEN = "/admin/appels-dons"


def _adresse() -> str:
    return f"{settings.SERVER_URL.rstrip('/')}{LIEN}"


def prevenir(*, de, vers, titre, corps, personnes=(), courriels=(), request=None, crise=None, environment=None) -> dict:
    """`de` : l'institution qui écrit (sa signature) ; `vers` : celle qu'on prévient (son salon).
    `personnes` : les comptes à notifier ; `courriels` : adresses en plus (le contact de l'appel).
    Rend ce qui est parti, canal par canal."""
    from .branding import send_branded_mail, send_branded_mail_env_aware
    from .models import Environment, GenreNotification, Notification, SalonMatrixInstitution, TypeSalonInstitution
    from .notifications_application import notifier

    environment = environment or Environment.PROD
    personnes = [p for p in {p.pk: p for p in personnes if p is not None}.values()]
    bilan = {"site": 0, "application": 0, "courriels": 0, "matrix": False}

    for personne in personnes:
        try:
            Notification.objects.create(utilisateur=personne, titre=titre[:200], message=corps, crise=crise, environment=environment)
            bilan["site"] += 1
            if notifier(personne, GenreNotification.INFORMATION, titre[:200], corps, institution=vers, environment=environment):
                bilan["application"] += 1
        except Exception as exc:
            logger.warning("Notification d'appel aux dons non déposée (%s).", type(exc).__name__)

    adresses = sorted({a.strip() for a in [*courriels, *(p.email for p in personnes)] if a and "@" in a})
    if adresses:
        message = f"{corps}\n\nPour suivre cet appel : {_adresse()}\n\n{{signature}}"
        try:
            if request is not None:
                send_branded_mail_env_aware(request, de, titre, message, adresses)
            elif environment == Environment.PROD:
                # Hors requête (rappel planifié) : jamais d'envoi réel depuis la zone de démonstration.
                send_branded_mail(None, de, titre, message, adresses)
            else:
                adresses = []
            bilan["courriels"] = len(adresses)
        except Exception as exc:
            logger.warning("Courriel d'appel aux dons non parti (%s).", type(exc).__name__)

    if vers is not None:
        try:
            salon = SalonMatrixInstitution.objects.filter(institution=vers, type=TypeSalonInstitution.PERMANENTS,
                                                          room_id__isnull=False).exclude(room_id="").first()
            if salon is not None:
                _dire_au_salon(salon.room_id, f"Appel aux dons — {titre}\n{corps}")
                bilan["matrix"] = True
        except Exception as exc:
            logger.warning("Message Matrix d'appel aux dons non parti (%s).", type(exc).__name__)
    return bilan


def _dire_au_salon(room_id: str, texte: str) -> None:
    """Message du robot dans un salon. Pas `matrix.envoyer_message_salon`, qui signe au nom d'une
    personne : ici c'est l'application qui parle, y compris depuis une tâche planifiée."""
    import uuid

    import requests

    from .matrix import SYNAPSE_URL, _bot_headers
    requests.put(f"{SYNAPSE_URL}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{uuid.uuid4().hex}",
                 headers=_bot_headers(), json={"msgtype": "m.text", "body": texte}, timeout=10).raise_for_status()


def contacts_de(appel) -> tuple[list, list]:
    """Qui prévenir chez l'institution qui a lancé l'appel : la personne qui l'a créé, et le
    courriel de contact qu'elle a publié."""
    return [appel.cree_par] if appel.cree_par_id else [], [appel.contact_email] if appel.contact_email else []
