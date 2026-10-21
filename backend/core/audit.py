import logging

from .models import AuditAction, AuditLog, Environment
from .permissions import get_active_environment

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Adresse IP réelle du client, en tenant compte du proxy nginx (X-Forwarded-For/X-Real-IP).
    None hors requête HTTP (signal, commande, shell -- voir audit_log)."""
    if request is None:
        return None
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
    succes=True,
    objets_ids=None,
    exposition=None,
    perimetre=None,
    recherche=None,
):
    """Écrit une ligne de main courante (AuditLog) et la renvoie (None en cas d'échec). Ne doit
    jamais faire échouer l'action métier appelante.

    objets_ids / exposition / perimetre / recherche : voir core/tracabilite.py. Une vue qui
    journalise elle-même n'a pas à les fournir : AuditTraceMiddleware complète la ligne d'après
    la réponse (voir _enrichir_ligne_explicite). `crise` fournie sans périmètre vaut CRISE."""
    try:
        from .tracabilite import est_compte_systeme

        action = AuditAction.objects.get(
            code=action_code
        )

        is_authenticated = (
            hasattr(request, "user")
            and request.user.is_authenticated
        )

        if crise is not None and perimetre is None:
            perimetre = AuditLog.Perimetre.CRISE

        ligne = AuditLog.objects.create(
            utilisateur=request.user if is_authenticated else None,
            institution=getattr(request.user, "institution", None) if is_authenticated else None,
            adresse_ip=get_client_ip(request),
            # request=None : appel hors requête HTTP (signal post_save, commande, shell) --
            # journalisé quand même plutôt que d'échouer (constaté le 16/10 avec un email
            # envoyé depuis le shell : la ligne de main courante était silencieusement perdue).
            user_agent=request.META.get("HTTP_USER_AGENT") if request is not None else None,
            action=action,
            objet_type=objet_type,
            objet_id=objet_id,
            # crise : instance (appels explicites des vues) ou identifiant (middleware)
            crise_id=getattr(crise, "pk", crise),
            ancien_etat=ancien_etat,
            nouvel_etat=nouvel_etat,
            commentaire=commentaire,
            succes=succes,
            environment=get_active_environment(request) if request is not None else Environment.PROD,
            objets_ids=objets_ids or None,
            exposition=exposition,
            perimetre=perimetre,
            compte_systeme=est_compte_systeme(request.user) if is_authenticated else False,
            recherche=recherche,
        )
        # Marque la requête comme déjà journalisée : voir AuditTraceMiddleware, qui n'écrit sa
        # propre ligne générique (LECTURE/CREATION/MODIFICATION/SUPPRESSION par méthode HTTP)
        # que si aucun appel explicite (plus riche, avec un vrai commentaire métier) ne l'a
        # déjà fait pendant cette même requête — évite un doublon. `request` ici est souvent le
        # Request DRF (self.request dans une vue), qui enveloppe le HttpRequest brut que reçoit
        # le middleware Django : il faut poser le marqueur sur ce dernier (._request), sinon le
        # middleware ne le voit jamais.
        # La ligne elle-même est gardée (_audit_log_ligne) : le middleware y ajoute les fiches
        # exposées par la réponse, que la vue n'a pas forcément pensé à noter.
        try:
            requete_brute = getattr(request, "_request", request)
            requete_brute._audit_log_written = True
            if getattr(requete_brute, "_audit_log_ligne", None) is None:
                requete_brute._audit_log_ligne = ligne
        except Exception:
            pass
        return ligne

    except Exception:
        logger.exception("Échec de l'écriture de la main courante (action_code=%s, objet_type=%s)", action_code, objet_type)
        return None


def send_mail_logged(request, subject, message, from_email, recipient_list, reply_to=None, **kwargs):
    """Enveloppe django.core.mail.send_mail : journalise systématiquement l'envoi (ou l'échec)
    dans la main courante — une vraie main courante ne doit pas laisser passer les emails
    envoyés sans trace, au même titre que les actions qu'ils accompagnent. Utilisée directement
    pour les emails de cycle de vie de compte (hors périmètre de send_mail_env_aware, voir son
    docstring) ; send_mail_env_aware route aussi par ici pour que TOUT email journalise, quel
    que soit le chemin emprunté.

    `reply_to` (voir core/branding.py::send_branded_mail) : django.core.mail.send_mail ne
    supporte aucun header custom -- bascule sur EmailMessage (même mécanisme que
    send_mail_with_attachment_logged) uniquement quand reply_to est fourni, pour ne rien changer
    au comportement des ~40 appelants existants qui ne le passent pas."""
    from django.core.mail import EmailMessage
    from django.core.mail import send_mail as django_send_mail

    succes = True
    try:
        if reply_to:
            fail_silently = kwargs.pop("fail_silently", False)
            email = EmailMessage(subject, message, from_email, recipient_list, reply_to=reply_to, **kwargs)
            resultat = email.send(fail_silently=fail_silently)
        else:
            resultat = django_send_mail(subject, message, from_email, recipient_list, **kwargs)
        if not resultat:
            # fail_silently=True (une vingtaine d'appelants) : django.core.mail.send_mail
            # avale l'exception SMTP en interne et renvoie 0 plutôt que de lever -- sans ce
            # test, ni l'except ci-dessous ni l'alerte ne se déclenchaient jamais pour ces
            # appels, malgré un envoi réellement en échec.
            succes = False
            logger.error('Échec silencieux d\'envoi email ("%s" à %s) : send_mail a renvoyé 0', subject, ", ".join(recipient_list))
        return resultat
    except Exception:
        succes = False
        # logger.exception (pas seulement l'audit_log juste en dessous) : c'est ce qui
        # déclenche l'alerte mail_admins/Matrix (voir LOGGING dans config/settings.py) --
        # avant son ajout, un échec d'envoi ici ne laissait selon les cas AUCUNE trace
        # exploitable nulle part (voir l'incident du 07/10).
        logger.exception('Échec d\'envoi email ("%s" à %s)', subject, ", ".join(recipient_list))
        raise
    finally:
        audit_log(
            request=request,
            action_code="ENVOI_EMAIL",
            objet_type="Email",
            commentaire=f'Envoi "{subject}" à {", ".join(recipient_list)}',
            succes=succes,
        )


def send_mail_with_attachment_logged(
    request, subject, message, from_email, recipient_list,
    attachment_filename, attachment_content, attachment_mimetype, **kwargs,
):
    """Variante de send_mail_logged avec pièce jointe — django.core.mail.send_mail ne le permet
    pas, EmailMessage.attach() si. Même journalisation systématique dans la main courante que
    send_mail_logged, avec le nom du fichier joint en plus dans le commentaire."""
    from django.core.mail import EmailMessage

    succes = True
    try:
        email = EmailMessage(subject, message, from_email, recipient_list, **kwargs)
        email.attach(attachment_filename, attachment_content, attachment_mimetype)
        return email.send()
    except Exception:
        succes = False
        logger.exception(
            'Échec d\'envoi email ("%s", pièce jointe %s, à %s)',
            subject, attachment_filename, ", ".join(recipient_list),
        )
        raise
    finally:
        audit_log(
            request=request,
            action_code="ENVOI_EMAIL",
            objet_type="Email",
            commentaire=f'Envoi "{subject}" (pièce jointe : {attachment_filename}) à {", ".join(recipient_list)}',
            succes=succes,
        )
