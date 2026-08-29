import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import User


@pytest.mark.django_db
class TestUserDemoMasking:
    """UserSerializer masque email/phone_number en zone DEMO — username doit l'être aussi :
    par convention (compte créé via l'email), username vaut souvent l'email en clair, et
    c'est justement ce champ qu'affiche la page Utilisateurs dans sa colonne toujours visible
    (contrairement à "contact", qui peut sortir du cadre sur mobile) — un compte réel ne doit
    jamais être identifiable par ce biais pendant une démonstration."""

    def test_username_masked_in_demo(self, authenticated_client):
        client, admin = authenticated_client
        admin.type = 'ADMIN'
        admin.demo_role = 'ADMIN'
        admin.save()
        target = User.objects.create_user(
            username='vraie.personne@test.fr', email='vraie.personne@test.fr', password='Test1234!',
        )

        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.get(reverse('user-list'))

        assert response.status_code == status.HTTP_200_OK
        entry = next(u for u in response.data if u['id'] == str(target.id))
        assert entry['username'] != 'vraie.personne@test.fr'
        assert entry['email'] != 'vraie.personne@test.fr'
        assert entry['username'].endswith('@zone.demo')

    def test_username_not_masked_in_prod(self, authenticated_client):
        client, admin = authenticated_client
        admin.type = 'ADMIN'
        admin.save()
        target = User.objects.create_user(
            username='vraie.personne2@test.fr', email='vraie.personne2@test.fr', password='Test1234!',
        )

        response = client.get(reverse('user-list'))

        assert response.status_code == status.HTTP_200_OK
        entry = next(u for u in response.data if u['id'] == str(target.id))
        assert entry['username'] == 'vraie.personne2@test.fr'
