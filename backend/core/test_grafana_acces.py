"""Accès à Grafana depuis la page admin Monitoring (core/grafana_acces.py)."""
import pytest
from django.core import signing
from django.urls import reverse
from rest_framework.test import APIClient

from core.grafana_acces import COOKIE, _SEL


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestGrafanaAcces:

    def test_admin_obtient_un_cookie_limite_a_grafana(self, create_user):
        admin = create_user(username="admin-grafana@test.fr", email="admin-grafana@test.fr", type="ADMIN")
        response = _client(admin).post(reverse("grafana_session"))
        assert response.status_code == 200
        cookie = response.cookies[COOKIE]
        assert cookie["path"] == "/grafana/"
        assert cookie["httponly"]

    def test_non_admin_refuse(self, create_user):
        mairie = create_user(username="mairie-grafana@test.fr", email="mairie-grafana@test.fr", type="AUT_LOCALE")
        assert _client(mairie).post(reverse("grafana_session")).status_code == 403
        assert APIClient().post(reverse("grafana_session")).status_code == 401

    def test_verifier_renvoie_l_identite_de_l_admin(self, create_user):
        admin = create_user(username="admin-verif@test.fr", email="admin-verif@test.fr", type="ADMIN")
        client = APIClient()
        client.cookies[COOKIE] = _client(admin).post(reverse("grafana_session")).cookies[COOKIE].value
        response = client.get(reverse("grafana_verifier"))
        assert response.status_code == 200
        assert response["X-Grafana-User"] == "admin-verif@test.fr"

    def test_verifier_refuse_sans_cookie_ou_cookie_falsifie(self, create_user):
        assert APIClient().get(reverse("grafana_verifier")).status_code == 401
        mairie = create_user(username="mairie-falsif@test.fr", email="mairie-falsif@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.cookies[COOKIE] = signing.dumps(str(mairie.pk), salt="autre-sel")
        assert client.get(reverse("grafana_verifier")).status_code == 401

    def test_verifier_refuse_un_admin_retrograde_depuis(self, create_user):
        admin = create_user(username="ex-admin@test.fr", email="ex-admin@test.fr", type="ADMIN")
        client = APIClient()
        client.cookies[COOKIE] = signing.dumps(str(admin.pk), salt=_SEL)
        admin.type = "AUT_LOCALE"
        admin.save(update_fields=["type"])
        assert client.get(reverse("grafana_verifier")).status_code == 401
