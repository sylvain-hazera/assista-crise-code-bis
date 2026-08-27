import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationPointBenevole,
    Crisis,
    DisponibilitePointEquipe,
    Offer,
    OfferType,
    PointOperationnel,
    PointType,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise affectation test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def responsable(create_user):
    return create_user(username="resp-affectation@test.fr", email="resp-affectation@test.fr", type="AUT_LOCALE")


@pytest.fixture
def team(db):
    return Team.objects.create(name="Equipe affectation test")


@pytest.fixture
def point(crisis, responsable, team):
    point_type = PointType.objects.create(code="ACCUEIL_AFFECTATION_TEST", libelle="Centre affectation test")
    return PointOperationnel.objects.create(
        nom="Centre affectation test", type=point_type, crise=crisis, responsable=responsable, equipe=team,
    )


@pytest.fixture
def point_transit(crisis):
    transit_type = PointType.objects.create(code="TRANSIT_AFFECTATION_TEST", libelle="Point de transit test")
    return PointOperationnel.objects.create(nom="Transit test", type=transit_type, crise=crisis, adresse="1 rue du transit")


@pytest.fixture
def offer(db):
    offer_type = OfferType.objects.create(type="Bénévolat affectation test")
    return Offer.objects.create(
        title="Je peux aider", offer_type=offer_type,
        first_name_offer="Camille", last_name_offer="Bénévole",
        email_offer="camille-benevole-affectation@test.fr",
    )


@pytest.fixture
def responsable_client(responsable):
    client = APIClient()
    client.force_authenticate(user=responsable)
    return client, responsable


@pytest.mark.django_db
class TestInviterBenevole:

    def test_invite_creates_affectation_and_sends_email(self, responsable_client, point, offer, point_transit):
        client, _ = responsable_client
        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {
                "offer_id": str(offer.id),
                "date_attendue": "2026-09-01T08:00:00Z",
                "point_transit_id": str(point_transit.id),
                "creneaux": [{"date": "2026-09-01", "creneau": "MATIN"}],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["statut"] == "EN_ATTENTE"
        assert response.data["benevole_nom"]
        assert response.data["point_transit_nom"] == point_transit.nom

        affectation = AffectationPointBenevole.objects.get(id=response.data["id"])
        assert affectation.benevole.email == "camille-benevole-affectation@test.fr"
        assert point.equipe.members.filter(email="camille-benevole-affectation@test.fr").exists()
        assert DisponibilitePointEquipe.objects.filter(point=point, membre=affectation.benevole).exists()

        assert len(mail.outbox) == 1
        assert "camille-benevole-affectation@test.fr" in mail.outbox[0].to
        assert affectation.token_confirmation in mail.outbox[0].body
        assert point_transit.nom in mail.outbox[0].body

    def test_invite_requires_point_equipe(self, responsable_client, crisis, responsable, offer):
        point_type = PointType.objects.create(code="SANS_EQUIPE_TEST", libelle="Sans equipe test")
        point_sans_equipe = PointOperationnel.objects.create(
            nom="Sans equipe", type=point_type, crise=crisis, responsable=responsable,
        )
        client, _ = responsable_client

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point_sans_equipe.id]),
            {"offer_id": str(offer.id), "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invite_unrelated_user_forbidden(self, create_user, point, offer):
        user = create_user(username="tiers-affectation@test.fr", email="tiers-affectation@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {"offer_id": str(offer.id), "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invite_blocked_on_closed_crisis(self, responsable_client, point, crisis, offer):
        client, _ = responsable_client
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {"offer_id": str(offer.id), "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invite_reuses_existing_user_for_same_email(self, responsable_client, point, offer, create_user):
        existing = create_user(
            username="camille-benevole-affectation@test.fr", email="camille-benevole-affectation@test.fr", type="UTIL_SIMPLE",
        )
        client, _ = responsable_client

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {"offer_id": str(offer.id), "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        affectation = AffectationPointBenevole.objects.get(id=response.data["id"])
        assert affectation.benevole_id == existing.id


@pytest.mark.django_db
class TestConfirmationLien:

    def test_confirm_oui_sets_confirme(self, point, offer, create_user):
        benevole = create_user(username="benevole-confirm-oui@test.fr", email="benevole-confirm-oui@test.fr", type="UTIL_SIMPLE")
        affectation = AffectationPointBenevole.objects.create(
            point=point, benevole=benevole, offer=offer,
            date_attendue=timezone.now(), token_confirmation="token-oui-test",
        )
        client = APIClient()

        response = client.get(reverse('confirmer_affectation_benevole', args=["token-oui-test", "oui"]))

        assert response.status_code == status.HTTP_200_OK
        affectation.refresh_from_db()
        assert affectation.statut == "CONFIRME"
        assert affectation.date_reponse is not None

    def test_confirm_non_sets_decline_and_removes_creneaux(self, point, offer, create_user):
        benevole = create_user(username="benevole-confirm-non@test.fr", email="benevole-confirm-non@test.fr", type="UTIL_SIMPLE")
        affectation = AffectationPointBenevole.objects.create(
            point=point, benevole=benevole, offer=offer,
            date_attendue=timezone.now(), token_confirmation="token-non-test",
        )
        DisponibilitePointEquipe.objects.create(
            point=point, membre=benevole, date="2026-09-01", creneau="MATIN", affectation=affectation,
        )
        client = APIClient()

        response = client.get(reverse('confirmer_affectation_benevole', args=["token-non-test", "non"]))

        assert response.status_code == status.HTTP_200_OK
        affectation.refresh_from_db()
        assert affectation.statut == "DECLINE"
        assert not DisponibilitePointEquipe.objects.filter(point=point, membre=benevole).exists()

    def test_confirm_twice_does_not_change_first_response(self, point, offer, create_user):
        benevole = create_user(username="benevole-confirm-twice@test.fr", email="benevole-confirm-twice@test.fr", type="UTIL_SIMPLE")
        affectation = AffectationPointBenevole.objects.create(
            point=point, benevole=benevole, offer=offer,
            date_attendue=timezone.now(), token_confirmation="token-twice-test",
        )
        client = APIClient()
        client.get(reverse('confirmer_affectation_benevole', args=["token-twice-test", "oui"]))
        affectation.refresh_from_db()
        premiere_reponse = affectation.date_reponse

        client.get(reverse('confirmer_affectation_benevole', args=["token-twice-test", "non"]))

        affectation.refresh_from_db()
        assert affectation.statut == "CONFIRME"
        assert affectation.date_reponse == premiere_reponse

    def test_confirm_invalid_token_404(self):
        client = APIClient()
        response = client.get(reverse('confirmer_affectation_benevole', args=["token-inexistant", "oui"]))
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestOfferSearch:

    def test_search_by_name(self, responsable_client, offer):
        client, _ = responsable_client
        response = client.get(reverse('offer-list'), {"search": "Camille"})
        assert response.status_code == status.HTTP_200_OK
        assert any(o["id"] == str(offer.id) for o in response.data)

    def test_search_by_email(self, responsable_client, offer):
        client, _ = responsable_client
        response = client.get(reverse('offer-list'), {"search": "camille-benevole-affectation"})
        assert any(o["id"] == str(offer.id) for o in response.data)


@pytest.mark.django_db
class TestEquipeActionEnrichie:

    def test_includes_affectations_and_temps(self, responsable_client, point, offer):
        client, _ = responsable_client
        client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {
                "offer_id": str(offer.id), "date_attendue": "2026-09-01T08:00:00Z",
                "creneaux": [{"date": "2026-09-01", "creneau": "MATIN"}],
            },
            format='json',
        )

        response = client.get(reverse('pointoperationnel-equipe', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["affectations"]) == 1
        membre = next(m for m in response.data["membres"] if m["email"] == "camille-benevole-affectation@test.fr")
        assert membre["temps_total_heures"] == 6
