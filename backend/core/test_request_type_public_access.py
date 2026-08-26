import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import RequestType


@pytest.mark.django_db
class TestRequestTypePublicAccess:

    def test_anonymous_can_list_request_types(self):
        """Régression : le formulaire public 'demander de l'aide' (request-help-form) n'a
        pas de garde d'authentification, mais RequestTypeViewSet renvoyait 401 à tout
        visiteur anonyme — d'où le menu 'Choisissez votre besoin' vide en pratique."""
        RequestType.objects.create(type="Transport")
        client = APIClient()

        response = client.get(reverse('requesttype-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
