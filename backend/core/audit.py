import logging

from .models import AuditAction, AuditLog
from .permissions import get_active_environment

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Adresse IP réelle du client, en tenant compte du proxy nginx (X-Forwarded-For/X-Real-IP)."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.META.get("HTTP_X_REAL_IP")
    if real_ip:
        return real_ip
    return request.META.get("REMOTE_ADDR")


def audit_log(
    request,
    action_code,
    objet_type,
    objet_id=None,
    crise=None,
    ancien_etat=None,
    nouvel_etat=None,
    commentaire=None,
    succes=True
):
    """Écrit une ligne de main courante (AuditLog). Ne doit jamais faire échouer l'action métier appelante."""
    try:

        action = AuditAction.objects.get(
            code=action_code
        )

        is_authenticated = (
            hasattr(request, "user")
            and request.user.is_authenticated
        )

        AuditLog.objects.create(
            utilisateur=request.user if is_authenticated else None,
            institution=getattr(request.user, "institution", None) if is_authenticated else None,
            adresse_ip=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT"),
            action=action,
            objet_type=objet_type,
            objet_id=objet_id,
            crise=crise,
            ancien_etat=ancien_etat,
            nouvel_etat=nouvel_etat,
            commentaire=commentaire,
            succes=succes,
            environment=get_active_environment(request),
        )
        # Marque la requête comme déjà journalisée : voir AuditTraceMiddleware, qui n'écrit sa
        # propre ligne générique (LECTURE/CREATION/MODIFICATION/SUPPRESSION par méthode HTTP)
        # que si aucun appel explicite (plus riche, avec un vrai commentaire métier) ne l'a
        # déjà fait pendant cette même requête — évite un doublon. `request` ici est souvent le
        # Request DRF (self.request dans une vue), qui enveloppe le HttpRequest brut que reçoit
        # le middleware Django : il faut poser le marqueur sur ce dernier (._request), sinon le
        # middleware ne le voit jamais.
        try:
            getattr(request, "_request", request)._audit_log_written = True
        except Exception:
            pass

    except Exception:
        logger.exception("Échec de l'écriture de la main courante (action_code=%s, objet_type=%s)", action_code, objet_type)


def send_mail_logged(request, subject, message, from_email, recipient_list, **kwargs):
    """Enveloppe django.core.mail.send_mail : journalise systématiquement l'envoi (ou l'échec)
    dans la main courante — une vraie main courante ne doit pas laisser passer les emails
    envoyés sans trace, au même titre que les actions qu'ils accompagnent. Utilisée directement
    pour les emails de cycle de vie de compte (hors périmètre de send_mail_env_aware, voir son
    docstring) ; send_mail_env_aware route aussi par ici pour que TOUT email journalise, quel
    que soit le chemin emprunté."""
    from django.core.mail import send_mail as django_send_mail

    succes = True
    try:
        return django_send_mail(subject, message, from_email, recipient_list, **kwargs)
    except Exception:
        succes = False
        raise
    finally:
        audit_log(
            request=request,
            action_code="ENVOI_EMAIL",
            objet_type="Email",
            commentaire=f'Envoi "{subject}" à {", ".join(recipient_list)}',
            succes=succes,
        )
