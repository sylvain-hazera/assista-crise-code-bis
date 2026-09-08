import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    Dossier,
    DossierParticipant,
    Information,
    InformationType,
    Offer,
    OfferType,
    Request,
    RequestType,
    Team,
)
from core.permissions import user_can_view_photo


def _fake_photo():
    return SimpleUploadedFile("photo.jpg", b"fake-bytes", content_type="image/jpeg")


def _req(user):
    """user_can_view_photo prend une request (pour résoudre l'environnement PROD/DEMO actif) —
    une RequestFactory nue suffit pour ces tests unitaires hors HTTP réel."""
    request = RequestFactory().get('/')
    request.user = user
    return request


@pytest.fixture
def crisis_with_photo(db, create_user):
    author = create_user(username="crisis-author@test.fr", email="crisis-author@test.fr", type="UTIL_SIMPLE")
    return Crisis.objects.create(
        name="Crise test photo", type="INCENDIE", location="POINT (5.72 45.18)",
        author=author, photo=_fake_photo(),
    )


@pytest.fixture
def information_with_photo(db):
    itype, _ = InformationType.objects.get_or_create(type="Test photo privacy", defaults={"description": ""})
    return Information.objects.create(
        title="Signalement test photo", information_type=itype, location="POINT (5.72 45.18)",
        first_name_information="A", last_name_information="B",
        email_information="a@test.fr", phone_information="0600000000",
        photo=_fake_photo(),
    )


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="institution-photo@test.fr", email="institution-photo@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestUserCanViewPhoto:

    def test_author_can_view(self, create_user, crisis_with_photo):
        assert user_can_view_photo(_req(crisis_with_photo.author), crisis_with_photo) is True

    def test_institutional_actor_can_view(self, create_user, crisis_with_photo):
        institutional = create_user(username="inst-helper@test.fr", email="inst-helper@test.fr", type="AUT_LOCALE")
        assert user_can_view_photo(_req(institutional), crisis_with_photo) is True

    def test_stranger_cannot_view(self, create_user, crisis_with_photo):
        stranger = create_user(username="stranger-photo@test.fr", email="stranger-photo@test.fr", type="UTIL_SIMPLE")
        assert user_can_view_photo(_req(stranger), crisis_with_photo) is False

    def test_anonymous_cannot_view(self, crisis_with_photo):
        assert user_can_view_photo(_req(None), crisis_with_photo) is False

    def test_team_member_can_view_via_teams_field(self, create_user, crisis_with_photo):
        member = create_user(username="team-member-photo@test.fr", email="team-member-photo@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe photo test", description="", color="#3b82f6")
        team.members.add(member)
        team.assigned_crises.add(crisis_with_photo)

        assert user_can_view_photo(_req(member), crisis_with_photo, teams_field='assigned_teams') is True

    def test_dossier_participant_can_view_via_dossiers_field(self, create_user, crisis_with_photo):
        participant = create_user(username="dossier-participant-photo@test.fr", email="dossier-participant-photo@test.fr", type="UTIL_SIMPLE")
        dossier = Dossier.objects.create(numero="DOS-PHOTOTEST", crise=crisis_with_photo, titre="Dossier photo test")
        DossierParticipant.objects.create(dossier=dossier, utilisateur=participant, role=DossierParticipant.Role.DEMANDEUR)

        assert user_can_view_photo(_req(participant), crisis_with_photo, dossiers_field='dossiers') is True

    def test_unrelated_team_or_dossier_does_not_grant_access(self, create_user, crisis_with_photo):
        outsider = create_user(username="outsider-photo@test.fr", email="outsider-photo@test.fr", type="UTIL_SIMPLE")
        other_crisis = Crisis.objects.create(name="Autre crise", type="INCENDIE", location="POINT (5.72 45.18)")
        team = Team.objects.create(name="Equipe autre crise", description="", color="#3b82f6")
        team.members.add(outsider)
        team.assigned_crises.add(other_crisis)

        assert user_can_view_photo(_req(outsider), crisis_with_photo, teams_field='assigned_teams', dossiers_field='dossiers') is False


@pytest.mark.django_db
class TestCrisisPhotoEndpoint:

    def test_photo_not_in_list_or_retrieve_response(self, crisis_with_photo):
        client = APIClient()

        response = client.get(reverse('crisis-detail', args=[crisis_with_photo.id]))

        assert response.status_code == status.HTTP_200_OK
        assert 'photo' not in response.data
        assert response.data['has_photo'] is True

    def test_preview_forbidden_for_stranger(self, crisis_with_photo, create_user):
        stranger = create_user(username="crisis-stranger@test.fr", email="crisis-stranger@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=stranger)

        response = client.get(reverse('crisis-preview', args=[crisis_with_photo.id]))

        assert response.status_code == 403

    def test_preview_forbidden_for_anonymous(self, crisis_with_photo):
        client = APIClient()

        response = client.get(reverse('crisis-preview', args=[crisis_with_photo.id]))

        assert response.status_code == 403

    def test_preview_allowed_for_author(self, crisis_with_photo):
        client = APIClient()
        client.force_authenticate(user=crisis_with_photo.author)

        response = client.get(reverse('crisis-preview', args=[crisis_with_photo.id]))

        assert response.status_code == 200

    def test_preview_allowed_for_institutional_actor(self, crisis_with_photo, institutional_client):
        client, _ = institutional_client

        response = client.get(reverse('crisis-preview', args=[crisis_with_photo.id]))

        assert response.status_code == 200


@pytest.mark.django_db
class TestOfferAndRequestPhotoHidden:

    def test_offer_photo_write_only(self, db, create_user):
        offer_type = OfferType.objects.create(type="Test photo offre", description="")
        author = create_user(username="offer-photo-author@test.fr", email="offer-photo-author@test.fr", type="UTIL_SIMPLE")
        offer = Offer.objects.create(
            title="Offre test photo", location="POINT (5.72 45.18)",
            first_name_offer="A", last_name_offer="B", email_offer="offer-photo-author@test.fr",
            status="DISPONIBLE", offer_type=offer_type, author=author, photo=_fake_photo(),
        )
        client = APIClient()

        response = client.get(reverse('offer-detail', args=[offer.id]))

        assert 'photo' not in response.data
        assert response.data['has_photo'] is True

    def test_request_photo_write_only(self, db, create_user, request_type):
        author = create_user(username="request-photo-author@test.fr", email="request-photo-author@test.fr", type="UTIL_SIMPLE")
        demande = Request.objects.create(
            title="Demande test photo", location="POINT (5.72 45.18)",
            first_name_request="A", last_name_request="B", email_request="request-photo-author@test.fr",
            phone_request="0600000000", status="NON_TRAITEE", request_type=request_type, author=author,
            photo=_fake_photo(),
        )
        client = APIClient()

        response = client.get(reverse('request-detail', args=[demande.id]))

        assert 'photo' not in response.data
        assert response.data['has_photo'] is True


@pytest.mark.django_db
class TestInformationPhotoDossierParticipant:
    """InformationViewSet.preview n'accordait l'accès qu'à l'auteur/un institutionnel — pas à
    un participant du dossier issu de ce signalement, contrairement à RequestViewSet.preview
    (dossiers_field='dossiers'). Corrigé pour la symétrie."""

    def test_dossier_participant_can_preview_information_photo(self, create_user, information_with_photo):
        participant = create_user(username="info-photo-participant@test.fr", email="info-photo-participant@test.fr", type="UTIL_SIMPLE")
        crisis = Crisis.objects.create(name="Crise photo info", type="INCENDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-INFO-PHOTO-1", titre="Dossier signalement photo", description="",
            crise=crisis, information=information_with_photo,
        )
        DossierParticipant.objects.create(dossier=dossier, utilisateur=participant)
        client = APIClient()
        client.force_authenticate(user=participant)

        response = client.get(reverse('information-preview', args=[information_with_photo.id]))

        assert response.status_code == status.HTTP_200_OK

    def test_unrelated_user_still_forbidden(self, create_user, information_with_photo):
        outsider = create_user(username="info-photo-outsider@test.fr", email="info-photo-outsider@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.get(reverse('information-preview', args=[information_with_photo.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDossierHasPhoto:
    """DossierSerializer.has_photo (nouveau) : indique côté frontend s'il faut tenter de charger
    la photo de la demande/du signalement d'origine (voir dossiers.component.ts)."""

    def test_true_when_origin_request_has_photo(self, create_user, request_type):
        author = create_user(username="dossier-photo-author@test.fr", email="dossier-photo-author@test.fr", type="UTIL_SIMPLE")
        demande = Request.objects.create(
            title="Demande photo dossier", location="POINT (5.72 45.18)",
            first_name_request="A", last_name_request="B", email_request="a@test.fr",
            phone_request="0600000000", status="NON_TRAITEE", request_type=request_type, author=author,
            photo=_fake_photo(),
        )
        crisis = Crisis.objects.create(name="Crise photo dossier", type="INCENDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(numero="DOS-PHOTO-1", titre="Dossier photo", description="", crise=crisis, demande=demande)
        admin = create_user(username="dossier-photo-admin@test.fr", email="dossier-photo-admin@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('dossier-detail', args=[dossier.id]))

        assert response.data['has_photo'] is True

    def test_false_when_no_origin_photo(self, create_user, request_type):
        author = create_user(username="dossier-nophoto-author@test.fr", email="dossier-nophoto-author@test.fr", type="UTIL_SIMPLE")
        demande = Request.objects.create(
            title="Demande sans photo", location="POINT (5.72 45.18)",
            first_name_request="A", last_name_request="B", email_request="a@test.fr",
            phone_request="0600000000", status="NON_TRAITEE", request_type=request_type, author=author,
        )
        crisis = Crisis.objects.create(name="Crise sans photo dossier", type="INCENDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(numero="DOS-PHOTO-2", titre="Dossier sans photo", description="", crise=crisis, demande=demande)
        admin = create_user(username="dossier-nophoto-admin@test.fr", email="dossier-nophoto-admin@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('dossier-detail', args=[dossier.id]))

        assert response.data['has_photo'] is False
