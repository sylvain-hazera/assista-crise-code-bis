import pytest
from django.urls import reverse
from rest_framework import status

from core.models import Institution, InstitutionType, User


def _make_user(email, type_code, institution=None):
    return User.objects.create_user(
        username=email, email=email, password="Test1234!", type="AUT_LOCALE", institution=institution,
    )


@pytest.mark.django_db
class TestCrisisRadiusDefaultMairie:
    """Une mairie couvre un territoire bien plus resserré qu'une intercommunalité/préfecture :
    1 km de rayon par défaut à la création plutôt que les 10 km génériques — demande
    utilisateur du 2026-09-15. Reste un simple défaut, modifiable ensuite comme toujours."""

    def _payload(self):
        return {
            'name': 'Crise test rayon', 'type': 'AUTRE',
            'location': '{"type": "Point", "coordinates": [1.0, 1.0]}',
        }

    def test_mairie_gets_1km_default(self, api_client):
        itype, _ = InstitutionType.objects.get_or_create(code='MAIRIE', defaults={'libelle': 'Mairie'})
        institution = Institution.objects.create(nom='Mairie Rayon', type=itype, commune_code='38185')
        user = _make_user('mairie-rayon@test.fr', 'AUT_LOCALE', institution=institution)
        api_client.force_authenticate(user=user)

        response = api_client.post(reverse('crisis-list'), self._payload(), format='multipart')

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['radius'] == 1

    def test_epci_keeps_10km_default(self, api_client):
        itype = InstitutionType.objects.create(code='EPCI_RAYON', libelle='EPCI')
        institution = Institution.objects.create(nom='EPCI Rayon', type=itype, commune_code='38185')
        user = _make_user('epci-rayon@test.fr', 'AUT_LOCALE', institution=institution)
        api_client.force_authenticate(user=user)

        response = api_client.post(reverse('crisis-list'), self._payload(), format='multipart')

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['radius'] == 10

    def test_no_institution_keeps_10km_default(self, api_client):
        user = _make_user('sans-institution@test.fr', 'ADMIN', institution=None)
        api_client.force_authenticate(user=user)

        response = api_client.post(reverse('crisis-list'), self._payload(), format='multipart')

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['radius'] == 10

    def test_explicit_radius_overrides_default(self, api_client):
        itype, _ = InstitutionType.objects.get_or_create(code='MAIRIE', defaults={'libelle': 'Mairie'})
        institution = Institution.objects.create(nom='Mairie Rayon 2', type=itype, commune_code='38185')
        user = _make_user('mairie-rayon2@test.fr', 'AUT_LOCALE', institution=institution)
        api_client.force_authenticate(user=user)

        response = api_client.post(reverse('crisis-list'), {**self._payload(), 'radius': 25}, format='multipart')

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['radius'] == 25
