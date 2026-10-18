import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


@pytest.fixture
def logged_in_client(create_user, user_data):
    create_user()
    client = APIClient()
    response = client.post(
        reverse('token_obtain_pair'),
        {"email": user_data["email"], "password": user_data["password"]},
        format='json',
    )
    assert response.status_code == status.HTTP_200_OK
    return client, response.data["access"], response.data["refresh"]


@pytest.mark.django_db
class TestTokenRotationAndBlacklist:

    def test_refresh_returns_a_new_refresh_token(self, logged_in_client):
        client, _, refresh = logged_in_client

        response = client.post(reverse('token_refresh'), {"refresh": refresh}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert "refresh" in response.data
        assert response.data["refresh"] != refresh

    def test_old_refresh_token_is_blacklisted_after_rotation(self, logged_in_client):
        client, _, refresh = logged_in_client

        client.post(reverse('token_refresh'), {"refresh": refresh}, format='json')
        reuse_response = client.post(reverse('token_refresh'), {"refresh": refresh}, format='json')

        assert reuse_response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_blacklisted_refresh_token_cannot_be_used(self, logged_in_client):
        client, _, refresh = logged_in_client

        blacklist_response = client.post(reverse('token_blacklist'), {"refresh": refresh}, format='json')
        assert blacklist_response.status_code == status.HTTP_200_OK

        reuse_response = client.post(reverse('token_refresh'), {"refresh": refresh}, format='json')

        assert reuse_response.status_code == status.HTTP_401_UNAUTHORIZED
