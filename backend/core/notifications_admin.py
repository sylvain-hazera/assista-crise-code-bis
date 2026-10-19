"""Alertes email aux administrateurs de la plateforme (demande utilisateur du 19/10, préparation
du POC SDIS 40 : "être prévenu automatiquement quand une institution est créée, même en auto,
et quand un compte est en attente de validation").

Création d'institution : signal post_save sur Institution (voir CoreConfig.ready) plutôt qu'un
appel dans chaque chemin de création -- il y en a au moins six (annuaire à l'activation d'un
compte, creer_mon_institution, AASC à l'approbation, heuristique par nom, création manuelle,
import CSV), un signal n'en oublie aucun, y compris un futur. Envoyé APRÈS commit
(transaction.on_commit) : jamais pour une création finalement annulée par un rollback.
"""
import contextvars
import logging
from contextlib import contextmanager

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

# Import en masse : un seul email récapitulatif plutôt qu'un par ligne (voir
# imports.importer_institutions).
_notifications_institution_suspendues = contextvars.ContextVar("notifications_institution_suspendues", default=False)


def emails_administrateurs():
    """Emails des administrateurs actifs, hors adresses factices des comptes de démonstration
    (domaine *.demo, jamais délivrables)."""
    from .models import User, UserRole

    return sorted({
        u.email for u in User.objects.filter(type=UserRole.ADMINISTRATOR, is_active=True)
        if u.email and not u.email.lower().rstrip('.').endswith('.demo')
    })


def filtre_comptes_en_attente():
    """Comptes en attente de validation (UserViewSet.pending_validations, métrique
    assista_accounts_pending_validation). Un compte "Secours organisés" est créé
    is_active=False (seul champ qui bloque vraiment la connexion, voir UserSerializer.create) --
    un filtre is_active=True seul le rendait invisible (constaté le 19/10 en préparant le POC
    SDIS 40). Distingué d'un compte REJETÉ (même état enabled/is_active) par sa demande
    d'institution encore en attente, que reject_account efface."""
    from django.db.models import Q

    from .models import UserRole

    return Q(enabled=False) & (
        Q(is_active=True)
        | (Q(type=UserRole.ORGANIZED_RESCUE) & Q(pending_institution_type__isnull=False) & ~Q(pending_institution_type=''))
    )


def notifier_administrateurs(subject, message, request=None):
    """Ne lève jamais : une alerte qui échoue ne doit pas faire échouer l'action qui l'a
    déclenchée (l'échec reste tracé dans la main courante par send_mail_logged)."""
    from .audit import send_mail_logged

    destinataires = emails_administrateurs()
    if not destinataires:
        return
    try:
        send_mail_logged(
            request, subject=f"[Assista-Crise] {subject}", message=message,
            from_email=None, recipient_list=destinataires, fail_silently=False,
        )
    except Exception:
        from .metrics import EMAILS_FAILED

        logger.exception("Admin notification email failed: %s", subject)
        EMAILS_FAILED.labels(kind="admin_notification").inc()


@contextmanager
def notifications_institution_suspendues():
    jeton = _notifications_institution_suspendues.set(True)
    try:
        yield
    finally:
        _notifications_institution_suspendues.reset(jeton)


def _lien_admin(chemin):
    base = (getattr(settings, "SERVER_URL", "") or "").rstrip("/")
    return f"{base}{chemin}" if base else chemin


def institution_creee(sender, instance, created, raw=False, **kwargs):
    if not created or raw or _notifications_institution_suspendues.get():
        return
    institution_id = instance.pk
    transaction.on_commit(lambda: _notifier_institution_creee(institution_id))


def _notifier_institution_creee(institution_id):
    from .models import Institution

    institution = Institution.objects.select_related("type").filter(pk=institution_id).first()
    if institution is None:
        return
    environnement = getattr(institution, "environment", None)
    prefixe = "[DEMO] " if environnement == "DEMO" else ""
    commune = institution.commune_nom or institution.commune_code or "non renseignée"
    message = (
        "Une nouvelle institution vient d'être créée sur Assista-Crise.\n\n"
        f"- Nom : {institution.nom}\n"
        f"- Type : {institution.type.libelle if institution.type_id else 'non renseigné'}\n"
        f"- Commune : {commune}\n"
        f"- Département : {institution.departement_code or 'non renseigné'}\n"
        f"- Niveau de secteur : {institution.secteur_niveau_effectif or 'non renseigné'}\n"
        f"- Email déclaré : {institution.email or 'non renseigné'}\n"
        f"- Environnement : {environnement or 'PROD'}\n\n"
        f"Liste des institutions : {_lien_admin('/admin/institutions')}"
    )
    notifier_administrateurs(f"{prefixe}Nouvelle institution : {institution.nom}", message)
