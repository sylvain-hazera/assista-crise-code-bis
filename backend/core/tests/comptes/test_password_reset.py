import pytest
from django.core import mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APIClient

from core.views import MAGIC_LINK_SIGNER


@pytest.mark.django_db
class TestSendPasswordReset:
    def test_administrator_can_trigger_password_reset_email(self, create_user):
        admin = create_user(username="admin-reset@test.fr", email="admin-reset@test.fr", type="ADMIN")
        target = create_user(username="cible-reset@test.fr", email="cible-reset@test.fr", type="UTIL_SIMPLE")

        client = APIClient()
        client.force_authenticate(user=admin)
        url = reverse("user-send-password-reset", kwargs={"pk": target.id})
        response = client.post(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [target.email]
        assert "https://www.assista-crise.fr/reinitialiser-mot-de-passe/" in mail.outbox[0].body

    def test_non_administrator_cannot_trigger_password_reset_email(self, create_user):
        regulateur = create_user(username="regulateur-reset@test.fr", email="regulateur-reset@test.fr", type="REGULATEUR")
        target = create_user(username="cible-reset2@test.fr", email="cible-reset2@test.fr", type="UTIL_SIMPLE")

        client = APIClient()
        client.force_authenticate(user=regulateur)
        url = reverse("user-send-password-reset", kwargs={"pk": target.id})
        response = client.post(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert len(mail.outbox) == 0

    def test_anonymous_cannot_trigger_password_reset_email(self, create_user):
        target = create_user(username="cible-reset3@test.fr", email="cible-reset3@test.fr", type="UTIL_SIMPLE")

        client = APIClient()
        url = reverse("user-send-password-reset", kwargs={"pk": target.id})
        response = client.post(url)

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert len(mail.outbox) == 0


@pytest.mark.django_db
class TestPasswordResetConfirm:
    def _valid_link_parts(self, user):
        uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
        token = MAGIC_LINK_SIGNER.sign(uidb64)
        return uidb64, token

    def test_valid_token_sets_new_password(self, create_user):
        user = create_user(username="reset-confirm@test.fr", email="reset-confirm@test.fr", type="UTIL_SIMPLE")
        uidb64, token = self._valid_link_parts(user)

        client = APIClient()
        url = reverse("reset_password_confirm", kwargs={"uidb64": uidb64, "token": token})
        response = client.post(url, {"new_password": "NouveauMotDePasse123!"})

        assert response.status_code == status.HTTP_204_NO_CONTENT
        user.refresh_from_db()
        assert user.check_password("NouveauMotDePasse123!")

    def test_invalid_token_is_rejected(self, create_user):
        user = create_user(username="reset-invalid@test.fr", email="reset-invalid@test.fr", type="UTIL_SIMPLE")
        uidb64, _ = self._valid_link_parts(user)

        client = APIClient()
        url = reverse("reset_password_confirm", kwargs={"uidb64": uidb64, "token": "token-invalide"})
        response = client.post(url, {"new_password": "NouveauMotDePasse123!"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert not user.check_password("NouveauMotDePasse123!")

    def test_too_short_password_is_rejected(self, create_user):
        user = create_user(username="reset-short@test.fr", email="reset-short@test.fr", type="UTIL_SIMPLE")
        uidb64, token = self._valid_link_parts(user)

        client = APIClient()
        url = reverse("reset_password_confirm", kwargs={"uidb64": uidb64, "token": token})
        response = client.post(url, {"new_password": "short"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert not user.check_password("short")

    def test_token_cannot_be_reused_for_a_different_user(self, create_user):
        user = create_user(username="reset-a@test.fr", email="reset-a@test.fr", type="UTIL_SIMPLE")
        other = create_user(username="reset-b@test.fr", email="reset-b@test.fr", type="UTIL_SIMPLE")
        _, token = self._valid_link_parts(user)
        other_uidb64 = urlsafe_base64_encode(force_bytes(str(other.pk)))

        client = APIClient()
        url = reverse("reset_password_confirm", kwargs={"uidb64": other_uidb64, "token": token})
        response = client.post(url, {"new_password": "NouveauMotDePasse123!"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
