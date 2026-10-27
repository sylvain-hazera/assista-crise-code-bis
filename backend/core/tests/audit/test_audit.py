import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

import core
from core.models import AuditAction, AuditLog, InstitutionType, Institution


@pytest.mark.django_db
class TestAuditLogCreation:
    """La main courante doit tracer les créations d'entités et de comptes (qui/quoi/quand/IP)."""

    def test_institution_creation_writes_audit_log(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")

        url = reverse('institution-list')
        response = client.post(
            url,
            {"nom": "Mairie de Test", "type": str(institution_type.id), "actif": True},
            format='json',
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
            HTTP_USER_AGENT="pytest-agent",
        )

        assert response.status_code == status.HTTP_201_CREATED

        log = AuditLog.objects.filter(objet_type="Institution").latest('date_action')
        assert log.action.code == "CREATION"
        assert log.objet_type == "Institution"
        assert str(log.objet_id) == response.data["id"]
        assert log.utilisateur == user
        assert log.adresse_ip == "203.0.113.7"
        assert log.user_agent == "pytest-agent"

    def test_register_writes_audit_log(self, api_client, user_data):
        url = reverse('user-register')
        response = api_client.post(url, user_data, format='json')

        assert response.status_code == status.HTTP_201_CREATED

        log = AuditLog.objects.latest('date_action')
        assert log.action.code == "CREATION"
        assert log.objet_type == "User"
        assert str(log.objet_id) == response.data["user"]["id"]

    def test_anonymous_institution_creation_is_rejected(self, api_client):
        """Depuis le durcissement des permissions, la création d'institution requiert une authentification."""
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        url = reverse('institution-list')
        response = api_client.post(
            url, {"nom": "Mairie Anonyme", "type": str(institution_type.id), "actif": True}, format='json'
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestPurgeAuditLogs:

    def test_purge_deletes_only_expired_logs(self, settings):
        settings.AUDIT_LOG_RETENTION_DAYS = 30
        from core.models import AuditAction

        action = AuditAction.objects.get(code="CREATION")

        old_log = AuditLog.objects.create(
            action=action, objet_type="Institution", succes=True
        )
        AuditLog.objects.filter(pk=old_log.pk).update(
            date_action=timezone.now() - timedelta(days=45)
        )

        recent_log = AuditLog.objects.create(
            action=action, objet_type="Institution", succes=True
        )

        call_command('purge_audit_logs')

        assert not AuditLog.objects.filter(pk=old_log.pk).exists()
        assert AuditLog.objects.filter(pk=recent_log.pk).exists()

    def test_purge_dry_run_deletes_nothing(self, settings):
        settings.AUDIT_LOG_RETENTION_DAYS = 30
        from core.models import AuditAction

        action = AuditAction.objects.get(code="CREATION")
        old_log = AuditLog.objects.create(action=action, objet_type="Institution", succes=True)
        AuditLog.objects.filter(pk=old_log.pk).update(
            date_action=timezone.now() - timedelta(days=45)
        )

        call_command('purge_audit_logs', '--dry-run')

        assert AuditLog.objects.filter(pk=old_log.pk).exists()


@pytest.mark.django_db
class TestCodesActionReferences:
    """Tout code d'action écrit dans le code source doit exister dans la table de référence.

    `audit_log` cherche l'action par son code et, s'il ne la trouve pas, renonce à écrire la
    ligne sans faire échouer l'action métier — c'est voulu : la main courante ne doit jamais
    casser une opération de crise. Mais le trou devient invisible, sauf dans les logs.

    Constaté en production le 27/10/2026 sur deux codes à la fois : CONSULTATION (import open
    data des sites sensibles) et ACTIVATION (activation des points opérationnels au démarrage
    d'une crise), ce dernier jamais journalisé depuis sa mise en service. D'où ce test, qui
    relit les sources plutôt que d'attendre qu'un appelant soit exercé par un autre test."""

    MOTIF = re.compile(r"""action_code\s*=\s*["']([A-Z_]+)["']""")

    def _codes_du_code_source(self):
        racine = Path(core.__file__).parent
        codes = {}
        for fichier in racine.rglob("*.py"):
            if {"migrations", "tests"} & set(fichier.relative_to(racine).parts):
                continue
            for code in self.MOTIF.findall(fichier.read_text(encoding="utf-8")):
                codes.setdefault(code, []).append(fichier.relative_to(racine).as_posix())
        return codes

    def test_aucun_code_daction_orphelin(self):
        codes = self._codes_du_code_source()
        assert codes, "aucun appel à audit_log trouvé : le motif de recherche a dû changer"
        connus = set(AuditAction.objects.values_list("code", flat=True))
        orphelins = {code: sorted(set(fichiers))
                     for code, fichiers in codes.items() if code not in connus}
        assert not orphelins, (
            "Codes d'action absents de la table AuditAction : la main courante les refusera "
            f"silencieusement. Ajoutez une migration de semis. {orphelins}"
        )
