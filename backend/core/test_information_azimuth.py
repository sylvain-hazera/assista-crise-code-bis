import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import InformationType


INFORMATION_PAYLOAD = {
    "title": "Arbre tombé",
    "location": "POINT (5.7245 45.1885)",
    "first_name_information": "Anonyme",
    "last_name_information": "Anonyme",
    "email_information": "signal@test.fr",
    "phone_information": "0600000000",
    "status": "DISPONIBLE",
}


@pytest.fixture
def information_type(db):
    return InformationType.objects.create(type="Arbre sur la chaussée")


@pytest.mark.django_db
class TestInformationAzimuth:

    def test_azimuth_accepted_and_returned(self, information_type):
        client = APIClient()
        response = client.post(
            reverse('information-list'),
            {**INFORMATION_PAYLOAD, "information_type": str(information_type.id), "azimuth": 187.5},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["azimuth"] == 187.5

    def test_azimuth_optional(self, information_type):
        client = APIClient()
        response = client.post(
            reverse('information-list'),
            {**INFORMATION_PAYLOAD, "information_type": str(information_type.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["azimuth"] is None

    def test_azimuth_rejected_out_of_range(self, information_type):
        client = APIClient()
        response = client.post(
            reverse('information-list'),
            {**INFORMATION_PAYLOAD, "information_type": str(information_type.id), "azimuth": 400},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "azimuth" in response.data

    def test_azimuth_rejected_negative(self, information_type):
        client = APIClient()
        response = client.post(
            reverse('information-list'),
            {**INFORMATION_PAYLOAD, "information_type": str(information_type.id), "azimuth": -10},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "azimuth" in response.data
