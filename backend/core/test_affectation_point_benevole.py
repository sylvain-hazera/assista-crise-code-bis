import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationPointBenevole,
    Competence,
    Crisis,
    DisponibiliteOffre,
    DisponibilitePointEquipe,
    Offer,
    OfferType,
    PointOperationnel,
    PointType,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise affectation test", type="INCENDIE", location="POINT (5.72 45.18)")


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
                "offer_ids": [str(offer.id)],
                "date_attendue": "2026-09-01T08:00:00Z",
                "point_transit_id": str(point_transit.id),
                "creneaux": [{"date": "2026-09-01", "creneau": "MATIN"}],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["created"]) == 1
        assert response.data["errors"] == []
        created = response.data["created"][0]
        assert created["statut"] == "EN_ATTENTE"
        assert created["benevole_nom"]
        assert created["point_transit_nom"] == point_transit.nom

        affectation = AffectationPointBenevole.objects.get(id=created["id"])
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
            {"offer_ids": [str(offer.id)], "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invite_unrelated_user_forbidden(self, create_user, point, offer):
        user = create_user(username="tiers-affectation@test.fr", email="tiers-affectation@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {"offer_ids": [str(offer.id)], "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invite_blocked_on_closed_crisis(self, responsable_client, point, crisis, offer):
        client, _ = responsable_client
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {"offer_ids": [str(offer.id)], "date_attendue": "2026-09-01T08:00:00Z"},
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
            {"offer_ids": [str(offer.id)], "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        affectation = AffectationPointBenevole.objects.get(id=response.data["created"][0]["id"])
        assert affectation.benevole_id == existing.id

    def test_bulk_invite_creates_affectation_for_each_offer(self, responsable_client, point):
        client, _ = responsable_client
        offer_type = OfferType.objects.create(type="Bénévolat bulk test")
        offer1 = Offer.objects.create(
            title="Aide 1", offer_type=offer_type,
            first_name_offer="Alice", last_name_offer="Un", email_offer="alice-bulk@test.fr",
        )
        offer2 = Offer.objects.create(
            title="Aide 2", offer_type=offer_type,
            first_name_offer="Bob", last_name_offer="Deux", email_offer="bob-bulk@test.fr",
        )

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {
                "offer_ids": [str(offer1.id), str(offer2.id)],
                "date_attendue": "2026-09-01T08:00:00Z",
                "creneaux": [{"date": "2026-09-01", "creneau": "SOIR"}],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["created"]) == 2
        assert response.data["errors"] == []
        assert len(mail.outbox) == 2
        assert point.equipe.members.filter(email="alice-bulk@test.fr").exists()
        assert point.equipe.members.filter(email="bob-bulk@test.fr").exists()
        for email in ("alice-bulk@test.fr", "bob-bulk@test.fr"):
            benevole = point.equipe.members.get(email=email)
            assert DisponibilitePointEquipe.objects.filter(point=point, membre=benevole, creneau="SOIR").exists()

    def test_bulk_invite_partial_failure_reports_error_without_blocking_others(self, responsable_client, point, offer):
        client, _ = responsable_client
        missing_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {
                "offer_ids": [str(offer.id), missing_id],
                "date_attendue": "2026-09-01T08:00:00Z",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["created"]) == 1
        assert len(response.data["errors"]) == 1
        assert response.data["errors"][0]["offer_id"] == missing_id

    def test_bulk_invite_all_fail_returns_400(self, responsable_client, point):
        client, _ = responsable_client
        missing_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            reverse('pointoperationnel-inviter-benevole', args=[point.id]),
            {"offer_ids": [missing_id], "date_attendue": "2026-09-01T08:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


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
                "offer_ids": [str(offer.id)], "date_attendue": "2026-09-01T08:00:00Z",
                "creneaux": [{"date": "2026-09-01", "creneau": "MATIN"}],
            },
            format='json',
        )

        response = client.get(reverse('pointoperationnel-equipe', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["affectations"]) == 1
        membre = next(m for m in response.data["membres"] if m["email"] == "camille-benevole-affectation@test.fr")
        assert membre["temps_total_heures"] == 6


@pytest.mark.django_db
class TestCandidatsBenevoles:

    def _make_offer(self, nom_prefix, email, location=None, competences=None, dispos=None):
        offer_type = OfferType.objects.create(type=f"Bénévolat candidats {email}")
        offer = Offer.objects.create(
            title=f"Aide {nom_prefix}", offer_type=offer_type,
            first_name_offer=nom_prefix, last_name_offer="Candidat", email_offer=email,
            location=location,
        )
        if competences:
            offer.competences.set(competences)
        for date, creneau in (dispos or []):
            DisponibiliteOffre.objects.create(offer=offer, date=date, creneau=creneau)
        return offer

    def test_forbidden_for_unrelated_user(self, create_user, point):
        user = create_user(username="tiers-candidats@test.fr", email="tiers-candidats@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('pointoperationnel-candidats-benevoles', args=[point.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_lists_available_offers_paginated(self, responsable_client, point):
        client, _ = responsable_client
        self._make_offer("Alice", "alice-candidats@test.fr")
        self._make_offer("Bob", "bob-candidats@test.fr")

        response = client.get(reverse('pointoperationnel-candidats-benevoles', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert "count" in response.data
        assert response.data["count"] >= 2

    def test_excludes_unavailable_offers(self, responsable_client, point):
        client, _ = responsable_client
        offer_type = OfferType.objects.create(type="Bénévolat indispo test")
        Offer.objects.create(
            title="Aide indispo", offer_type=offer_type,
            first_name_offer="Indispo", last_name_offer="Candidat", email_offer="indispo-candidats@test.fr",
            status="INDISPONIBLE",
        )

        response = client.get(reverse('pointoperationnel-candidats-benevoles', args=[point.id]))

        emails = {o["email_offer"] for o in response.data["results"]}
        assert "indispo-candidats@test.fr" not in emails

    def test_filters_by_search(self, responsable_client, point):
        client, _ = responsable_client
        self._make_offer("Zoe", "zoe-candidats@test.fr")
        self._make_offer("Yann", "yann-candidats@test.fr")

        response = client.get(reverse('pointoperationnel-candidats-benevoles', args=[point.id]), {"search": "Zoe"})

        emails = {o["email_offer"] for o in response.data["results"]}
        assert emails == {"zoe-candidats@test.fr"}

    def test_filters_by_creneau(self, responsable_client, point):
        client, _ = responsable_client
        self._make_offer(
            "Dispo", "dispo-candidats@test.fr", dispos=[("2026-09-05", "MATIN")],
        )
        self._make_offer("Sansdispo", "sansdispo-candidats@test.fr")

        response = client.get(
            reverse('pointoperationnel-candidats-benevoles', args=[point.id]),
            {"creneaux": "2026-09-05:MATIN"},
        )

        emails = {o["email_offer"] for o in response.data["results"]}
        assert emails == {"dispo-candidats@test.fr"}

    def test_filters_by_competence(self, responsable_client, point):
        client, _ = responsable_client
        secourisme = Competence.objects.create(nom="Secourisme candidats test")
        Competence.objects.create(nom="Cuisine candidats test")
        self._make_offer("Secours", "secours-candidats@test.fr", competences=[secourisme])
        self._make_offer("Autre", "autre-candidats@test.fr")

        response = client.get(
            reverse('pointoperationnel-candidats-benevoles', args=[point.id]),
            {"competences": str(secourisme.id)},
        )

        emails = {o["email_offer"] for o in response.data["results"]}
        assert emails == {"secours-candidats@test.fr"}
        result = next(o for o in response.data["results"] if o["email_offer"] == "secours-candidats@test.fr")
        assert result["competences_libelles"] == ["Secourisme candidats test"]

    def test_sorts_by_distance_when_point_has_location(self, responsable_client, crisis, responsable, team):
        point_type = PointType.objects.create(code="AVEC_LOC_TEST", libelle="Centre avec localisation")
        point_avec_loc = PointOperationnel.objects.create(
            nom="Centre avec loc", type=point_type, crise=crisis, responsable=responsable, equipe=team,
            location="POINT (5.72 45.18)",
        )
        client, _ = responsable_client
        self._make_offer("Loin", "loin-candidats@test.fr", location="POINT (2.35 48.85)")
        self._make_offer("Pres", "pres-candidats@test.fr", location="POINT (5.73 45.19)")

        response = client.get(reverse('pointoperationnel-candidats-benevoles', args=[point_avec_loc.id]))

        results = response.data["results"]
        emails_in_order = [o["email_offer"] for o in results]
        assert emails_in_order.index("pres-candidats@test.fr") < emails_in_order.index("loin-candidats@test.fr")
        pres = next(o for o in results if o["email_offer"] == "pres-candidats@test.fr")
        assert pres["distance_km"] is not None

    def test_distance_null_when_point_has_no_location(self, responsable_client, point):
        client, _ = responsable_client
        self._make_offer("SansLoc", "sansloc-candidats@test.fr", location="POINT (5.73 45.19)")

        response = client.get(reverse('pointoperationnel-candidats-benevoles', args=[point.id]))

        result = next(o for o in response.data["results"] if o["email_offer"] == "sansloc-candidats@test.fr")
        assert result["distance_km"] is None
