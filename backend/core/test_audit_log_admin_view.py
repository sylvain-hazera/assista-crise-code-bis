"""Consultation globale + export CSV de la main courante (AuditLogViewSet, mode "browse" —
sans ?objet_type=&objet_id=) : réservée à un administrateur, paginée, filtrable. Le mode
"fiche précise" existant (avec objet_type+objet_id) n'est pas touché — voir test_vue_mairie
et consorts pour ce comportement historique."""
import csv
import io

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import AuditAction, AuditLog, Crisis


def _make_log(utilisateur=None, action_code="CREATION", objet_type="Crisis", commentaire=""):
    action, _ = AuditAction.objects.get_or_create(code=action_code, defaults={"libelle": action_code})
    return AuditLog.objects.create(
        utilisateur=utilisateur, action=action, objet_type=objet_type,
        commentaire=commentaire, environment="PROD",
    )


@pytest.mark.django_db
class TestAuditLogBrowseMode:

    def test_non_admin_gets_empty_list(self, create_user):
        Crisis.objects.create(name="Une crise", type="INONDATION", location="POINT (5.72 45.18)")
        user = create_user(username="regul-browse@test.fr", email="regul-browse@test.fr", type="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('auditlog-list'))
        assert response.status_code == 200
        assert response.data == []

    def test_admin_sees_everything_paginated(self, create_user):
        _make_log()
        admin = create_user(username="admin-browse@test.fr", email="admin-browse@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        # Sans ?page= : comportement non paginé, mais toujours restreint aux admins.
        response = client.get(reverse('auditlog-list'))
        assert response.status_code == 200
        assert len(response.data) >= 1

        paginated = client.get(reverse('auditlog-list'), {"page": 1, "page_size": 5})
        assert set(paginated.data.keys()) == {"count", "next", "previous", "results"}

    def test_filter_by_action(self, create_user):
        _make_log(action_code="CREATION")
        _make_log(action_code="SUPPRESSION")
        admin = create_user(username="admin-filter-action@test.fr", email="admin-filter-action@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('auditlog-list'), {"action": "CREATION", "objet_type": "Crisis"})
        assert response.status_code == 200
        assert len(response.data) >= 1
        assert all(e["action_code"] == "CREATION" for e in response.data)

    def test_filter_by_utilisateur(self, create_user):
        admin = create_user(username="admin-filter-user@test.fr", email="admin-filter-user@test.fr", type="ADMIN")
        _make_log(utilisateur=admin)
        client = APIClient()
        client.force_authenticate(user=admin)

        matching = client.get(reverse('auditlog-list'), {"utilisateur": "admin-filter-user"})
        assert matching.status_code == 200
        assert len(matching.data) >= 1

        not_matching = client.get(reverse('auditlog-list'), {"utilisateur": "personne-inexistante-xyz"})
        assert not_matching.data == []


@pytest.mark.django_db
class TestAuditLogExport:

    def test_export_is_admin_only(self, create_user):
        user = create_user(username="regul-export@test.fr", email="regul-export@test.fr", type="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('auditlog-export'))
        assert response.status_code == 403

    def test_export_returns_readable_csv(self, create_user):
        Crisis.objects.create(name="Crise export", type="INONDATION", location="POINT (5.72 45.18)")
        admin = create_user(username="admin-export@test.fr", email="admin-export@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('auditlog-export'))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert "main-courante-" in response["Content-Disposition"]

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.reader(io.StringIO(content), delimiter=';')
        rows = list(reader)
        assert rows[0] == [
            "Date", "Heure", "Utilisateur", "Institution", "Adresse IP", "Action",
            "Type d'objet", "ID objet", "Commentaire", "Succès", "Environnement", "Navigateur",
        ]
        assert len(rows) > 1

    def test_export_itself_is_logged(self, create_user):
        admin = create_user(username="admin-export-log@test.fr", email="admin-export-log@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        before = AuditLog.objects.filter(action__code="EXPORT", objet_type="AuditLog").count()
        response = client.get(reverse('auditlog-export'))
        list(response.streaming_content)  # force la génération (StreamingHttpResponse est paresseux)
        after = AuditLog.objects.filter(action__code="EXPORT", objet_type="AuditLog").count()
        assert after == before + 1
