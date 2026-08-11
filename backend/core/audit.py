import logging

from .models import AuditAction, AuditLog

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
            succes=succes
        )

    except Exception:
        logger.exception("Échec de l'écriture de la main courante (action_code=%s, objet_type=%s)", action_code, objet_type)
