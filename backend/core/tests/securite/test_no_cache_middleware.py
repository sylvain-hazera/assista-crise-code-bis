import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestNoCacheApiMiddleware:
    """Une même URL /api/... renvoie un contenu différent selon X-Environment (masquage
    email/téléphone en DEMO) — sans Cache-Control: no-store, un cache intermédiaire ou le
    navigateur pourrait resservir une réponse PROD (non masquée) après bascule en DEMO."""

    def test_api_response_has_no_store_and_vary_environment(self, api_client):
        response = api_client.get(reverse('user-list'))

        assert response.headers.get('Cache-Control') == 'no-store'
        vary = response.headers.get('Vary', '')
        assert 'X-Environment' in vary

    def test_non_api_response_is_untouched(self, api_client):
        response = api_client.get('/does-not-exist/')

        assert response.headers.get('Cache-Control') != 'no-store'
