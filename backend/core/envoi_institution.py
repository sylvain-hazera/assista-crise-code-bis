"""Routage de l'envoi d'un email : API de l'institution si elle en a une, SMTP sinon.

Une institution en marque blanche qui fournit sa clé Brevo (voir
`ConfigurationEnvoiInstitution`) envoie depuis SA propre adresse. Assista-Crise n'apparaît alors
nulle part dans le message.

**Le repli est volontaire et il est partiel** (arbitrage du 11/11/2026). Si l'API échoue — clé
révoquée, quota, panne, expéditeur non vérifié — le message part quand même par le SMTP
Assista-Crise, **en gardant le texte de l'institution** : sa signature, son Reply-To, son nom
dans le corps. Seule l'enveloppe technique (l'adresse `From`) retombe sur Assista-Crise. Un
destinataire reçoit donc un message qui lui parle au nom de son association, expédié par une
adresse qui n'est pas la sienne — c'est une fuite de marque assumée, préférée à un message qui
ne part pas.

Ce repli **n'est pas silencieux** : il est journalisé en main courante avec le message d'erreur
du fournisseur, et horodaté sur la configuration de l'institution pour que l'écran de
configuration le montre. Une clé révoquée se verrait sinon seulement au moment où quelqu'un
signale n'avoir rien reçu.
"""
import logging

from django.utils import timezone

from .envoi_brevo import EchecBrevo, envoyer_email_brevo

logger = logging.getLogger(__name__)


def configuration_envoi(institution):
    """La configuration d'envoi de cette institution, ou None.

    Tolère l'absence de ligne : la très grande majorité des institutions n'en ont pas, et une
    exception ici ferait échouer l'envoi au lieu de retomber sur le SMTP."""
    if institution is None:
        return None
    return getattr(institution, 'configuration_envoi', None)


def envoyer_email_pour_institution(request, institution, sujet, message, destinataires,
                                   reply_to=None):
    """Tente l'envoi par l'API de l'institution.

    Renvoie `(True, messageId)` si l'API a pris le message, `(False, motif)` si elle a échoué
    ou n'est pas configurée. Ne lève jamais : l'appelant doit pouvoir retomber sur le SMTP, et
    une exception qui traverse ferait perdre le message au lieu de le dégrader.
    """
    config = configuration_envoi(institution)
    if config is None or not config.email_configure:
        return False, "non configuré"

    nom_expediteur = config.brevo_expediteur_nom or institution.nom_affichage or institution.nom
    try:
        identifiant = envoyer_email_brevo(
            cle_api=config.brevo_cle_api,
            expediteur_email=config.brevo_expediteur_email,
            expediteur_nom=nom_expediteur,
            sujet=sujet,
            message=message,
            destinataires=destinataires,
            reply_to=reply_to or institution.email_reply_to or None,
        )
    except EchecBrevo as echec:
        _noter_echec_email(config, echec.detail)
        logger.warning(
            "Envoi Brevo refusé pour « %s » (sujet « %s ») : %s — repli sur le SMTP.",
            institution.nom, sujet, echec.detail,
        )
        return False, echec.detail
    except Exception as erreur:
        # Garde-fou : un bug chez nous ne doit pas empêcher le message de partir par le SMTP.
        _noter_echec_email(config, f"Erreur inattendue : {erreur}")
        logger.exception("Erreur inattendue à l'envoi Brevo pour « %s ».", institution.nom)
        return False, str(erreur)

    _noter_succes_email(config)
    # Les crédits baissent à chaque envoi : on les relit, au plus une fois par demi-heure
    # (voir credits_brevo.INTERVALLE_RELEVE). C'est ce qui permet d'alerter AVANT la panne
    # plutôt que de la constater.
    try:
        from .credits_brevo import relever

        relever(config, request=request)
    except Exception:  # noqa: BLE001 - un suivi de consommation ne fait pas échouer un envoi
        logger.exception("Relevé des crédits Brevo impossible pour « %s ».", institution.nom)
    return True, identifiant


def _noter_succes_email(config):
    """Efface la dernière erreur : la garder après un envoi réussi ferait lire un problème
    résolu comme un problème courant."""
    config.dernier_envoi_email_le = timezone.now()
    config.derniere_erreur_email = ""
    config.save(update_fields=['dernier_envoi_email_le', 'derniere_erreur_email',
                               'date_modification'])


def _noter_echec_email(config, detail):
    # Tronqué : un corps de réponse HTTP peut être long, et seule la cause nous intéresse.
    config.derniere_erreur_email = (detail or "")[:500]
    config.save(update_fields=['derniere_erreur_email', 'date_modification'])
