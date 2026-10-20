"""Jeton de connexion à Grafana (core/grafana.py) : réservé aux administrateurs, borné, vérifiable
avec la clé publique et sans donnée personnelle (il passe dans une URL)."""
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.urls import reverse
from rest_framework import status

from core.grafana import GRAFANA_JWT_TTL

URL = reverse('grafana_token')


@pytest.fixture
def cle_rsa(settings):
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings.GRAFANA_JWT_PRIVATE_KEY = cle.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode()
    return cle.public_key()


@pytest.mark.django_db
class TestGrafanaToken:

    def test_administrateur_recoit_un_jeton_viewer_verifiable(self, authenticated_client, cle_rsa):
        client, user = authenticated_client
        user.type = 'ADMIN'
        user.save()

        response = client.post(URL)

        assert response.status_code == status.HTTP_200_OK
        claims = jwt.decode(response.data['token'], cle_rsa, algorithms=['RS256'], audience='grafana')
        assert claims['sub'] == f'assista-{user.id}'
        assert claims['role'] == 'Viewer'
        assert claims['exp'] - claims['iat'] == response.data['expires_in'] == GRAFANA_JWT_TTL
        assert user.email not in response.data['token']
        assert not {'email', 'name'} & claims.keys()

    @pytest.mark.parametrize('role', ['AUT_LOCALE', 'SECOURS', 'REGULATEUR', 'UTIL_SIMPLE'])
    def test_autres_roles_refuses(self, authenticated_client, cle_rsa, role):
        client, user = authenticated_client
        user.type = role
        user.save()
        assert client.post(URL).status_code == status.HTTP_403_FORBIDDEN

    def test_role_demo_administrateur_ne_suffit_pas(self, authenticated_client, cle_rsa):
        client, user = authenticated_client
        user.type = 'AUT_LOCALE'
        user.demo_role = 'ADMIN'
        user.save()
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        assert client.post(URL).status_code == status.HTTP_403_FORBIDDEN

    def test_anonyme_refuse(self, api_client, cle_rsa):
        assert api_client.post(URL).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_sans_cle_configuree_503(self, authenticated_client, settings):
        client, user = authenticated_client
        user.type = 'ADMIN'
        user.save()
        settings.GRAFANA_JWT_PRIVATE_KEY = ''
        assert client.post(URL).status_code == status.HTTP_503_SERVICE_UNAVAILABLE
