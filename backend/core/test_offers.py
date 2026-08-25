import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    ContactInstitution,
    DisponibiliteOffre,
    Dossier,
    DossierParticipant,
    Institution,
    InstitutionType,
    Offer,
    OfferType,
)

OFFER_PAYLOAD = {
    "title": "Aide bénévole",
    "location": "POINT (5.7245 45.1885)",
    "first_name_offer": "Jean",
    "last_name_offer": "Bénévole",
    "email_offer": "jean.benevole@test.fr",
    "status": "DISPONIBLE",
}


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Hébergement (test)", description="")


@pytest.fixture
def offer(db, offer_type, create_user):
    author = create_user(username="offrant@test.fr", email="offrant@test.fr", type="UTIL_SIMPLE")
    return Offer.objects.create(offer_type=offer_type, author=author, **OFFER_PAYLOAD)


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_OFFER_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie de Test Offres", type=itype)


@pytest.fixture
def local_authority_client(create_user, institution):
    user = create_user(username="autorite-offres@test.fr", email="autorite-offres@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestDisponibiliteOffre:

    def test_declare_availability_slots(self, api_client, offer):
        response = api_client.post(
            reverse('disponibiliteoffre-list'),
            {"offer": str(offer.id), "date": "2026-09-01", "creneau": "MATIN"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert DisponibiliteOffre.objects.filter(offer=offer, date="2026-09-01", creneau="MATIN").exists()

    def test_availability_filterable_by_offer(self, api_client, offer):
        DisponibiliteOffre.objects.create(offer=offer, date="2026-09-01", creneau="MATIN")
        DisponibiliteOffre.objects.create(offer=offer, date="2026-09-01", creneau="SOIR")

        response = api_client.get(reverse('disponibiliteoffre-list'), {"offer": str(offer.id)})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2


@pytest.mark.django_db
class TestAssignOfferToDossier:

    def test_institutional_actor_can_assign_offer_to_dossier(self, local_authority_client, offer):
        client, _ = local_authority_client
        crisis = Crisis.objects.create(name="Crise test", type="INCEDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-TEST-1", crise=crisis, titre="Dossier test", description="desc",
        )

        response = client.post(
            reverse('offer-assign-dossier', args=[offer.id]),
            {"dossier": str(dossier.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=offer.author, role=DossierParticipant.Role.OFFRANT
        ).exists()

    def test_cannot_assign_authorless_offer_to_dossier(self, local_authority_client, offer_type):
        client, _ = local_authority_client
        anonymous_offer = Offer.objects.create(offer_type=offer_type, author=None, **{
            **OFFER_PAYLOAD, "email_offer": "anonyme@test.fr",
        })
        crisis = Crisis.objects.create(name="Crise test 2", type="INCEDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-TEST-2", crise=crisis, titre="Dossier test 2", description="desc",
        )

        response = client.post(
            reverse('offer-assign-dossier', args=[anonymous_offer.id]),
            {"dossier": str(dossier.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not DossierParticipant.objects.filter(dossier=dossier).exists()

    def test_simple_user_cannot_assign_offer_to_dossier(self, authenticated_client, offer):
        client, _ = authenticated_client
        crisis = Crisis.objects.create(name="Crise test 3", type="INCEDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-TEST-3", crise=crisis, titre="Dossier test 3", description="desc",
        )

        response = client.post(
            reverse('offer-assign-dossier', args=[offer.id]),
            {"dossier": str(dossier.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
