"""Un formulaire d'édition affiche l'email masqué en zone DEMO (to_representation) puis le
renvoie tel quel au save, même si un tout autre champ a changé — sans garde-fou, ça écrase
silencieusement la vraie adresse par son masque affiché. Reproduit en direct sur deux comptes
réels (GRUISSAN/NICOLAS sur .114) avant d'être corrigé ; ces tests verrouillent le correctif
sur les 4 serializers concernés (User, Request, Offer, Information)."""
import pytest
from rest_framework.test import APIClient
from django.urls import reverse

from core.models import Offer, OfferType, Request, RequestType, Information, InformationType, User
from core.permissions import mask_email


@pytest.mark.django_db
class TestUserEmailProtectedInDemo:

    def test_editing_demo_role_with_masked_email_roundtrip_does_not_corrupt_real_email(self, create_user):
        target = create_user(
            username="vraie.personne@commune.fr", email="vraie.personne@commune.fr",
            type="AUT_LOCALE", demo_role=None,
        )
        admin = create_user(username="admin-demo@test.fr", email="admin-demo@test.fr", type="ADMIN", demo_role="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        masked = mask_email("vraie.personne@commune.fr")
        response = client.patch(
            reverse('user-detail', args=[target.id]),
            {"email": masked, "username": masked, "demo_role": "AUT_LOCALE"},
            format='json', HTTP_X_ENVIRONMENT='DEMO',
        )
        assert response.status_code == 200

        target.refresh_from_db()
        assert target.email == "vraie.personne@commune.fr"
        assert target.username == "vraie.personne@commune.fr"
        assert target.demo_role == "AUT_LOCALE"

    def test_legitimate_email_edit_still_works_in_prod(self, create_user):
        target = create_user(username="ancien@commune.fr", email="ancien@commune.fr", type="AUT_LOCALE")
        admin = create_user(username="admin-prod@test.fr", email="admin-prod@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(
            reverse('user-detail', args=[target.id]), {"email": "nouveau@commune.fr"}, format='json',
        )
        assert response.status_code == 200
        target.refresh_from_db()
        assert target.email == "nouveau@commune.fr"


@pytest.mark.django_db
class TestRequestOfferInformationEmailProtectedInDemo:

    def test_request_email_not_corrupted_in_demo(self, create_user):
        rtype, _ = RequestType.objects.get_or_create(type="Test")
        demande = Request.objects.create(
            title="Besoin test", request_type=rtype, environment="DEMO",
            first_name_request="A", last_name_request="B",
            email_request="reel@commune.fr", phone_request="0600000000",
        )
        user = create_user(username="regul-demo@test.fr", email="regul-demo@test.fr", type="REGULATEUR", demo_role="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        masked = mask_email("reel@commune.fr")
        response = client.patch(
            reverse('request-detail', args=[demande.id]),
            {"email_request": masked, "title": "Titre modifié"},
            format='json', HTTP_X_ENVIRONMENT='DEMO',
        )
        assert response.status_code == 200
        demande.refresh_from_db()
        assert demande.email_request == "reel@commune.fr"
        assert demande.title == "Titre modifié"

    def test_offer_email_not_corrupted_in_demo(self, create_user):
        otype, _ = OfferType.objects.get_or_create(type="Test")
        offre = Offer.objects.create(
            title="Offre test", offer_type=otype, environment="DEMO",
            first_name_offer="A", last_name_offer="B", email_offer="reel@commune.fr",
        )
        user = create_user(username="regul-demo-offer@test.fr", email="regul-demo-offer@test.fr", type="REGULATEUR", demo_role="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        masked = mask_email("reel@commune.fr")
        response = client.patch(
            reverse('offer-detail', args=[offre.id]),
            {"email_offer": masked, "title": "Titre modifié"},
            format='json', HTTP_X_ENVIRONMENT='DEMO',
        )
        assert response.status_code == 200
        offre.refresh_from_db()
        assert offre.email_offer == "reel@commune.fr"

    def test_information_email_not_corrupted_in_demo(self, create_user):
        itype, _ = InformationType.objects.get_or_create(type="Test")
        info = Information.objects.create(
            title="Info test", information_type=itype, environment="DEMO",
            first_name_information="A", last_name_information="B",
            email_information="reel@commune.fr", phone_information="0600000000",
            location="POINT (5.72 45.18)",
        )
        user = create_user(username="regul-demo-info@test.fr", email="regul-demo-info@test.fr", type="REGULATEUR", demo_role="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        masked = mask_email("reel@commune.fr")
        response = client.patch(
            reverse('information-detail', args=[info.id]),
            {"email_information": masked, "title": "Titre modifié"},
            format='json', HTTP_X_ENVIRONMENT='DEMO',
        )
        assert response.status_code == 200
        info.refresh_from_db()
        assert info.email_information == "reel@commune.fr"
