"""Endpoint d'agrégats du tableau de bord admin (/api/stats/dashboard/) : remplace l'ancien
comportement du frontend (getAll() sur crises/offres/demandes, sérialisation complète juste
pour compter) par des requêtes d'agrégation. Ces tests verrouillent la scoping environnement,
la sémantique des filtres de période, et surtout le nombre de requêtes constant (pas de N+1
qui reviendrait proportionnel au volume de données)."""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Commune, Crisis, Information, InformationType, Institution, InstitutionType,
    Offer, OfferType, Request, RequestType,
)


def _make_crisis(name, environment="DEMO", crisis_type="INONDATION"):
    return Crisis.objects.create(
        name=name, type=crisis_type, location="POINT (5.72 45.18)", environment=environment,
    )


def _make_request(title, environment="DEMO"):
    rtype, _ = RequestType.objects.get_or_create(type="Dashboard stats test")
    return Request.objects.create(
        title=title, request_type=rtype, environment=environment,
        first_name_request="Test", last_name_request="Test",
        email_request="test@test.fr", phone_request="0600000000",
    )


def _make_offer(title, environment="DEMO", commune=None):
    otype, _ = OfferType.objects.get_or_create(type="Dashboard stats test")
    geo = _commune_geo_kwargs(commune)
    return Offer.objects.create(
        title=title, offer_type=otype, environment=environment,
        first_name_offer="Test", last_name_offer="Test", email_offer="test@test.fr", **geo,
    )


def _make_benevole(title, environment="DEMO", commune=None):
    otype, _ = OfferType.objects.get_or_create(type="Bénévolat")
    geo = _commune_geo_kwargs(commune)
    return Offer.objects.create(
        title=title, offer_type=otype, environment=environment,
        first_name_offer="Test", last_name_offer="Test", email_offer="test@test.fr", **geo,
    )


def _make_information(title, environment="DEMO", commune=None):
    # Information n'a que commune_code (pas epci/departement/region_code, contrairement à
    # Offer/Request) — voir le commentaire de DashboardStatsView._scope_to_zone.
    itype, _ = InformationType.objects.get_or_create(type="Dashboard stats test")
    commune_code = commune.code if commune else None
    return Information.objects.create(
        title=title, information_type=itype, environment=environment,
        first_name_information="Test", last_name_information="Test",
        email_information="test@test.fr", phone_information="0600000000",
        location=Point(1, 1, srid=4326), commune_code=commune_code,
    )


def _commune_geo_kwargs(commune):
    if commune is None:
        return {}
    return {
        "commune_code": commune.code, "epci_code": commune.epci_code,
        "departement_code": commune.departement_code, "region_code": commune.region_code,
    }


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code)


@pytest.mark.django_db
class TestDashboardStatsView:

    def test_requires_auth(self):
        client = APIClient()
        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')
        assert response.status_code == 401

    def test_totals_and_environment_scoping(self, create_user):
        _make_crisis("DEMO crisis")
        _make_request("DEMO request")
        _make_offer("DEMO offer")
        _make_crisis("PROD crisis", environment="PROD")
        _make_request("PROD request", environment="PROD")

        user = create_user(username="dash-stats@test.fr", email="dash-stats@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        data = response.data
        assert data["stats"]["crises"] == 1
        assert data["stats"]["offres"] == 1
        assert data["stats"]["demandes"] == 1
        assert data["total_items"] == 3
        assert data["totals"] == {"crises": 1, "offres": 1, "demandes": 1}
        assert len(data["day_points"]) == 30
        assert data["day_points"][-1]["crises"] == 1
        assert data["day_points"][-1]["offres"] == 1
        assert data["day_points"][-1]["demandes"] == 1

    def test_filter_week_excludes_older_items(self, create_user):
        old = _make_request("Old request")
        Request.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(days=40))
        _make_request("Recent request")

        user = create_user(username="dash-stats-filter@test.fr", email="dash-stats-filter@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dashboard_stats'), {"filter": "week"}, HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["demandes"] == 1
        # total_items reste le total global, indépendant du filtre de période (badge "N entités")
        assert response.data["total_items"] == 2

    def test_recent_items_and_pie_shape(self, create_user):
        _make_crisis("Crue", crisis_type="INONDATION")
        _make_crisis("Feu", crisis_type="INCENDIE")
        _make_request("Une demande")
        _make_offer("Une offre")

        user = create_user(username="dash-stats-recent@test.fr", email="dash-stats-recent@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        recent = response.data["recent_items"]
        assert len(recent) == 4
        assert {item["type"] for item in recent} == {"Crise", "Besoin", "Ressource"}
        pie = response.data["pie"]
        assert {slice_["type"] for slice_ in pie} == {"INONDATION", "INCENDIE"}
        assert all(slice_["count"] == 1 for slice_ in pie)

    def test_query_count_constant_regardless_of_volume(self, create_user):
        """Coeur de l'optimisation : le nombre de requêtes ne doit pas grimper avec le
        volume de données (contrairement à l'ancien getAll() + sérialisation complète)."""
        for i in range(120):
            _make_request(f"Demande {i}")
            _make_offer(f"Offre {i}")
        for i in range(10):
            _make_crisis(f"Crise {i}")

        user = create_user(username="dash-stats-volume@test.fr", email="dash-stats-volume@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        with CaptureQueriesContext(connection) as ctx:
            response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["demandes"] == 120
        assert response.data["stats"]["offres"] == 120
        assert response.data["stats"]["crises"] == 10
        # Une quinzaine de requêtes d'agrégation fixes, jamais proportionnelles au volume.
        assert len(ctx) <= 20

    def test_signalements_and_benevoles_counted(self, create_user):
        _make_information("Un signalement")
        _make_benevole("Un bénévole")
        _make_offer("Une offre normale")  # exclue du comptage bénévoles, comme avant

        user = create_user(username="dash-stats-signal@test.fr", email="dash-stats-signal@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["signalements"] == 1
        assert response.data["stats"]["benevoles"] == 1
        assert response.data["stats"]["offres"] == 1


@pytest.fixture
def commune_grenoble(db):
    return Commune.objects.create(
        code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


@pytest.fixture
def commune_lille(db):
    return Commune.objects.create(
        code="59350", nom="Lille", departement_code="59", epci_code="200093201",
        region_code="32", centre_latitude=50.63, centre_longitude=3.06,
    )


@pytest.mark.django_db
class TestDashboardStatsZoneScoping:
    """Les 5 cartes principales étaient strictement nationales, quel que soit le rôle de
    l'utilisateur connecté — corrigé pour scoper à la zone de compétence de son institution
    (même mécanisme que InformationViewSet/vue_secteur, voir zone_scoping.py), avec un
    repli national explicite pour les profils sans zone résolvable (administrateur, ou
    utilisateur sans institution/commune) plutôt qu'un tableau vide."""

    def test_local_authority_sees_only_its_commune(self, create_user, commune_grenoble, commune_lille):
        _make_offer("Offre Grenoble", commune=commune_grenoble)
        _make_offer("Offre Lille", commune=commune_lille)
        _make_information("Signalement Grenoble", commune=commune_grenoble)
        _make_information("Signalement Lille", commune=commune_lille)
        _make_benevole("Bénévole Grenoble", commune=commune_grenoble)
        _make_benevole("Bénévole Lille", commune=commune_lille)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(
            username="dash-mairie@test.fr", email="dash-mairie@test.fr",
            type="AUT_LOCALE", demo_role="AUT_LOCALE",
        )
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["offres"] == 1
        assert response.data["stats"]["signalements"] == 1
        assert response.data["stats"]["benevoles"] == 1
        assert response.data["is_zone_scoped"] is True
        # La 6ᵉ fenêtre nationale reste complète (les deux communes), contrairement aux cartes
        # principales scopées à Grenoble uniquement.
        assert response.data["national"]["stats"]["offres"] == 2
        assert response.data["national"]["stats"]["signalements"] == 2
        assert response.data["national"]["stats"]["benevoles"] == 2

    def test_crisis_scoped_by_zone_communes_containment(self, create_user, commune_grenoble, commune_lille):
        crise_grenoble = _make_crisis("Crise Grenoble")
        crise_grenoble.zone_communes = [commune_grenoble.code]
        crise_grenoble.save(update_fields=["zone_communes"])
        crise_lille = _make_crisis("Crise Lille")
        crise_lille.zone_communes = [commune_lille.code]
        crise_lille.save(update_fields=["zone_communes"])

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(
            username="dash-mairie2@test.fr", email="dash-mairie2@test.fr",
            type="AUT_LOCALE", demo_role="AUT_LOCALE",
        )
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["crises"] == 1
        assert response.data["national"]["stats"]["crises"] == 2

    def test_non_institutional_user_falls_back_to_national(self, create_user, commune_grenoble, commune_lille):
        """Un bénévole simple (UTIL_SIMPLE, sans institution) n'a pas de zone résolvable —
        doit voir les chiffres nationaux dans les 5 cartes principales plutôt qu'un dashboard
        vide (contrairement au comportement "liste de contenu" de filter_queryset_to_viewer_
        zone, qui renvoie .none() sans zone connue — inapproprié ici, le dashboard reste
        accessible à tout utilisateur authentifié)."""
        _make_offer("Offre Grenoble", commune=commune_grenoble)
        _make_offer("Offre Lille", commune=commune_lille)

        user = create_user(username="dash-simple@test.fr", email="dash-simple@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["offres"] == 2
        assert response.data["is_zone_scoped"] is False
        assert response.data["national"]["stats"] == response.data["stats"]

    def test_administrator_always_sees_national(self, create_user, commune_grenoble, commune_lille):
        _make_offer("Offre Grenoble", commune=commune_grenoble)
        _make_offer("Offre Lille", commune=commune_lille)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        # demo_role explicite : sans lui, get_effective_role échoue en DEMO (PermissionDenied
        # avalée par effective_role_or_none -> None, PAS ADMINISTRATOR) et l'utilisateur serait
        # traité comme un simple institutionnel scopé à sa commune plutôt que comme un admin.
        user = create_user(
            username="dash-admin-inst@test.fr", email="dash-admin-inst@test.fr",
            type="ADMIN", demo_role="ADMIN",
        )
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse('dashboard_stats'), HTTP_X_ENVIRONMENT='DEMO')

        assert response.status_code == 200
        assert response.data["stats"]["offres"] == 2
        assert response.data["is_zone_scoped"] is False
