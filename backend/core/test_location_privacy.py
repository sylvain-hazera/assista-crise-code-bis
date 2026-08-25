import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution,
    Information,
    InformationType,
    Institution,
    InstitutionType,
    Request,
    RequestType,
)

REQUEST_PAYLOAD = {
    "title": "Besoin de nourriture",
    "location": "POINT (5.7245 45.1885)",
    "first_name_request": "Marie",
    "last_name_request": "Demandeuse",
    "email_request": "marie.demandeuse@test.fr",
    "phone_request": "0600000000",
    "status": "NON_TRAITEE",
}

INFORMATION_PAYLOAD = {
    "title": "Arbre sur la chaussée",
    "location": "POINT (5.7245 45.1885)",
    "first_name_information": "Paul",
    "last_name_information": "Signaleur",
    "email_information": "paul.signaleur@test.fr",
    "phone_information": "0600000000",
    "status": "DISPONIBLE",
}


@pytest.fixture
def request_type(db):
    return RequestType.objects.create(type="Nourriture (test privacy)", description="")


@pytest.fixture
def information_type(db):
    return InformationType.objects.create(type="Signalement (test privacy)", description="")


@pytest.fixture
def demande(db, request_type):
    return Request.objects.create(request_type=request_type, **REQUEST_PAYLOAD)


@pytest.fixture
def information(db, information_type):
    return Information.objects.create(information_type=information_type, **INFORMATION_PAYLOAD)


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_PRIVACY_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie de Test Privacy", type=itype)


@pytest.fixture
def local_authority_client(create_user, institution):
    user = create_user(username="autorite-privacy@test.fr", email="autorite-privacy@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestRequestLocationPrivacy:

    def test_anonymous_cannot_see_request_location(self, api_client, demande):
        response = api_client.get(reverse('request-detail', args=[demande.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        assert response.data['location'] is None

    def test_simple_authenticated_user_cannot_see_request_location(self, authenticated_client, demande):
        client, _ = authenticated_client
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['latitude'] is None

    def test_institutional_actor_can_see_request_location(self, local_authority_client, demande):
        client, _ = local_authority_client
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['latitude'] is not None
        assert response.data['longitude'] is not None
        assert response.data['location'] is not None


@pytest.mark.django_db
class TestInformationLocationPrivacy:

    def test_anonymous_cannot_see_information_location(self, api_client, information):
        response = api_client.get(reverse('information-detail', args=[information.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        assert response.data['location'] is None

    def test_institutional_actor_can_see_information_location(self, local_authority_client, information):
        client, _ = local_authority_client
        response = client.get(reverse('information-detail', args=[information.id]))
        assert response.data['latitude'] is not None
        assert response.data['longitude'] is not None
        assert response.data['location'] is not None
