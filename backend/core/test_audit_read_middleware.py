"""Journalisation automatique de la main courante (AuditTraceMiddleware) : toute requête
/api/ (GET comme POST/PUT/PATCH/DELETE) doit produire une ligne AuditLog (utilisateur, IP,
user-agent, horodatage — RGPD registre des accès), qu'une vue l'ait explicitement journalisée
ou non. Vérifie aussi que RegisterView journalise la création de compte, et que l'envoi
d'email est lui-même tracé (send_mail_logged)."""
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import AuditLog, Crisis, PointType, User


@pytest.mark.django_db
class TestAuditReadMiddleware:

    def test_list_request_is_logged_once(self, create_user):
        Crisis.objects.create(name="Crise A", type="INONDATION", location="POINT (5.72 45.18)")
        Crisis.objects.create(name="Crise B", type="INCENDIE", location="POINT (5.72 45.18)")

        user = create_user(username="lecteur@test.fr", email="lecteur@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        before = AuditLog.objects.filter(action__code="LECTURE", objet_type="Crisis").count()
        response = client.get(reverse('crisis-list'), REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="pytest-agent")
        assert response.status_code == 200

        entries = AuditLog.objects.filter(action__code="LECTURE", objet_type="Crisis").order_by('-date_action')
        # Une seule ligne pour la requête, jamais une par crise renvoyée dans la liste.
        assert entries.count() == before + 1
        entry = entries.first()
        assert entry.utilisateur == user
        assert entry.adresse_ip == "203.0.113.7"
        assert entry.user_agent == "pytest-agent"
        assert entry.objet_id is None  # liste, pas de fiche précise
        assert entry.succes is True

    def test_retrieve_request_logs_the_object_id(self, create_user):
        crisis = Crisis.objects.create(name="Crise détail", type="INONDATION", location="POINT (5.72 45.18)")
        user = create_user(username="lecteur-detail@test.fr", email="lecteur-detail@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('crisis-detail', args=[crisis.id]))
        assert response.status_code == 200

        entry = AuditLog.objects.filter(action__code="LECTURE", objet_type="Crisis", objet_id=crisis.id).first()
        assert entry is not None
        assert entry.utilisateur == user

    def test_failed_request_is_logged_as_not_succes(self, create_user):
        # Une crise inexistante -> 404, doit quand même être journalisée (tentative d'accès).
        import uuid
        user = create_user(username="lecteur-404@test.fr", email="lecteur-404@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)
        fake_id = uuid.uuid4()

        response = client.get(reverse('crisis-detail', args=[fake_id]))
        assert response.status_code == 404

        entry = AuditLog.objects.filter(action__code="LECTURE", objet_type="Crisis", objet_id=fake_id).first()
        assert entry is not None
        assert entry.succes is False

    def test_anonymous_request_is_still_logged(self):
        Crisis.objects.create(name="Crise publique", type="INONDATION", location="POINT (5.72 45.18)")
        client = APIClient()

        response = client.get(reverse('crisis-list'))
        assert response.status_code == 200

        entry = AuditLog.objects.filter(action__code="LECTURE", objet_type="Crisis").order_by('-date_action').first()
        assert entry is not None
        assert entry.utilisateur is None

    def test_token_endpoints_are_never_logged(self, create_user):
        user = create_user(username="lecteur-token@test.fr", email="lecteur-token@test.fr", type="UTIL_SIMPLE", password="Test1234!")
        client = APIClient()

        before = AuditLog.objects.filter(objet_type__icontains="token").count()
        client.post(reverse('token_obtain_pair'), {"email": user.email, "password": "Test1234!"})
        after = AuditLog.objects.filter(objet_type__icontains="token").count()
        assert after == before

    def test_post_with_explicit_audit_log_is_not_duplicated(self, create_user):
        # CrisisViewSet.perform_create appelle déjà audit_log(action_code="CREATION", ...) —
        # le middleware doit voir request._audit_log_written et ne pas écrire une seconde
        # ligne générique pour la même requête.
        user = create_user(username="createur@test.fr", email="createur@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        before = AuditLog.objects.filter(action__code="CREATION", objet_type="Crisis").count()
        response = client.post(reverse('crisis-list'), {
            "name": "Nouvelle crise", "type": "INONDATION", "location": "POINT (5.72 45.18)",
        })
        assert response.status_code == 201
        after = AuditLog.objects.filter(action__code="CREATION", objet_type="Crisis").count()
        assert after == before + 1


@pytest.mark.django_db
class TestAuditTraceMiddlewareWriteMethods:
    """PointTypeViewSet est un ModelViewSet nu, sans le moindre appel audit_log() explicite —
    exactement le genre d'endpoit qui, avant ce middleware, ne laissait aucune trace."""

    def test_post_without_explicit_audit_log_is_logged_as_creation(self, create_user):
        user = create_user(username="createur-pointtype@test.fr", email="createur-pointtype@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('pointtype-list'), {"code": "TEST_PT", "libelle": "Test"})
        assert response.status_code == 201

        entry = AuditLog.objects.filter(action__code="CREATION", objet_type="PointType").order_by('-date_action').first()
        assert entry is not None
        assert entry.utilisateur == user
        assert entry.succes is True

    def test_patch_without_explicit_audit_log_is_logged_as_modification(self, create_user):
        pt = PointType.objects.create(code="TEST_PATCH", libelle="Avant")
        user = create_user(username="modif-pointtype@test.fr", email="modif-pointtype@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(reverse('pointtype-detail', args=[pt.id]), {"libelle": "Après"}, format='json')
        assert response.status_code == 200

        entry = AuditLog.objects.filter(action__code="MODIFICATION", objet_type="PointType", objet_id=pt.id).first()
        assert entry is not None

    def test_delete_without_explicit_audit_log_is_logged_as_suppression(self, create_user):
        pt = PointType.objects.create(code="TEST_DELETE", libelle="À supprimer")
        user = create_user(username="suppr-pointtype@test.fr", email="suppr-pointtype@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.delete(reverse('pointtype-detail', args=[pt.id]))
        assert response.status_code == 204

        entry = AuditLog.objects.filter(action__code="SUPPRESSION", objet_type="PointType", objet_id=pt.id).first()
        assert entry is not None


@pytest.mark.django_db
class TestSendMailLogged:

    def test_successful_send_is_logged(self, rf):
        from core.audit import send_mail_logged

        request = rf.get('/api/whatever/')
        request.user = type('Anon', (), {'is_authenticated': False})()

        with patch('django.core.mail.send_mail') as mock_send:
            mock_send.return_value = 1
            send_mail_logged(request, "Sujet test", "Corps", None, ["dest@test.fr"])

        entry = AuditLog.objects.filter(action__code="ENVOI_EMAIL").order_by('-date_action').first()
        assert entry is not None
        assert "Sujet test" in entry.commentaire
        assert "dest@test.fr" in entry.commentaire
        assert entry.succes is True

    def test_failed_send_is_logged_as_not_succes_and_reraises(self, rf):
        from core.audit import send_mail_logged

        request = rf.get('/api/whatever/')
        request.user = type('Anon', (), {'is_authenticated': False})()

        with patch('django.core.mail.send_mail', side_effect=RuntimeError("SMTP down")):
            with pytest.raises(RuntimeError):
                send_mail_logged(request, "Sujet échec", "Corps", None, ["dest@test.fr"])

        entry = AuditLog.objects.filter(action__code="ENVOI_EMAIL", commentaire__icontains="Sujet échec").first()
        assert entry is not None
        assert entry.succes is False


@pytest.mark.django_db
class TestRegisterViewAuditLog:

    def test_registration_is_logged(self):
        client = APIClient()
        response = client.post(reverse('auth_register'), {
            "username": "nouveau@test.fr", "email": "nouveau@test.fr", "password": "Test1234!",
            "first_name": "Nouveau", "last_name": "Compte",
        })
        assert response.status_code in (200, 201)

        user = User.objects.get(email="nouveau@test.fr")
        entry = AuditLog.objects.filter(action__code="CREATION", objet_type="User", objet_id=user.id).first()
        assert entry is not None
