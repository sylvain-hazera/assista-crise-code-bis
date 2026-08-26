import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    ImplicationInstitution,
    Institution,
    InstitutionType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise verrou", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_VERROU_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie verrou test", type=itype)


def _declare_responsable(crisis, institution, responsable):
    return ImplicationInstitution.objects.create(
        crise=crisis, institution=institution, type_implication="IMPLIQUE",
        responsable=responsable, actif=True,
    )


REQUEST_PAYLOAD_BASE = {
    "title": "Demande verrou", "location": "POINT (5.72 45.18)",
    "first_name_request": "A", "last_name_request": "B",
    "phone_request": "0600000000", "status": "NON_TRAITEE",
}


@pytest.mark.django_db
class TestCrisisOpenLockOnRequest:

    def test_rejected_when_crisis_has_no_responsable(self, crisis, request_type):
        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {**REQUEST_PAYLOAD_BASE, "email_request": "verrou1@test.fr",
             "request_type": str(request_type.id), "crisis": str(crisis.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "crisis" in response.data

    def test_rejected_when_crisis_is_closed(self, crisis, request_type, institution, create_user):
        responsable = create_user(username="resp-verrou@test.fr", email="resp-verrou@test.fr", type="AUT_LOCALE")
        _declare_responsable(crisis, institution, responsable)
        crisis.end_date = timezone.now()
        crisis.save()

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {**REQUEST_PAYLOAD_BASE, "email_request": "verrou2@test.fr",
             "request_type": str(request_type.id), "crisis": str(crisis.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "crisis" in response.data

    def test_accepted_when_crisis_open_and_monitored(self, crisis, request_type, institution, create_user):
        responsable = create_user(username="resp-verrou-ok@test.fr", email="resp-verrou-ok@test.fr", type="AUT_LOCALE")
        _declare_responsable(crisis, institution, responsable)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {**REQUEST_PAYLOAD_BASE, "email_request": "verrou-ok@test.fr",
             "request_type": str(request_type.id), "crisis": str(crisis.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_accepted_without_crisis(self, request_type):
        """Une demande non rattachée à une crise n'est pas concernée par ce verrou."""
        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {**REQUEST_PAYLOAD_BASE, "email_request": "sans-crise-verrou@test.fr",
             "request_type": str(request_type.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_rejected_when_responsable_inactive(self, crisis, request_type, institution, create_user):
        """Un responsable existe mais son implication n'est plus active : toujours bloqué."""
        responsable = create_user(username="resp-inactif@test.fr", email="resp-inactif@test.fr", type="AUT_LOCALE")
        ImplicationInstitution.objects.create(
            crise=crisis, institution=institution, type_implication="IMPLIQUE",
            responsable=responsable, actif=False,
        )

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {**REQUEST_PAYLOAD_BASE, "email_request": "resp-inactif-req@test.fr",
             "request_type": str(request_type.id), "crisis": str(crisis.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCrisisOpenLockOnOfferAndInformation:

    def test_offer_rejected_without_responsable(self, crisis, offer_type):
        client = APIClient()
        response = client.post(
            reverse('offer-list'),
            {
                "title": "Offre verrou", "location": "POINT (5.72 45.18)",
                "first_name_offer": "A", "last_name_offer": "B", "email_offer": "offre-verrou@test.fr",
                "phone_offer": "0600000000", "status": "NON_TRAITEE",
                "offer_type": str(offer_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_information_rejected_without_responsable(self, crisis, information_type):
        client = APIClient()
        response = client.post(
            reverse('information-list'),
            {
                "title": "Info verrou", "location": "POINT (5.72 45.18)", "description": "desc",
                "information_type": str(information_type.id), "crisis": str(crisis.id),
                "status": "NON_TRAITEE",
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCrisisSerializerFields:

    def test_is_open_true_without_end_date(self, crisis):
        client = APIClient()
        response = client.get(reverse('crisis-detail', args=[crisis.id]))
        assert response.data["is_open"] is True

    def test_is_open_false_with_end_date(self, crisis):
        crisis.end_date = timezone.now()
        crisis.save()
        client = APIClient()
        response = client.get(reverse('crisis-detail', args=[crisis.id]))
        assert response.data["is_open"] is False

    def test_has_responsable_actif(self, crisis, institution, create_user):
        client = APIClient()
        response = client.get(reverse('crisis-detail', args=[crisis.id]))
        assert response.data["has_responsable_actif"] is False

        responsable = create_user(username="resp-serializer@test.fr", email="resp-serializer@test.fr", type="AUT_LOCALE")
        _declare_responsable(crisis, institution, responsable)

        response = client.get(reverse('crisis-detail', args=[crisis.id]))
        assert response.data["has_responsable_actif"] is True
