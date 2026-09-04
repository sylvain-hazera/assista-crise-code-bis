"""Endpoint d'agrégats du tableau de bord admin (/api/stats/dashboard/) : remplace l'ancien
comportement du frontend (getAll() sur crises/offres/demandes, sérialisation complète juste
pour compter) par des requêtes d'agrégation. Ces tests verrouillent la scoping environnement,
la sémantique des filtres de période, et surtout le nombre de requêtes constant (pas de N+1
qui reviendrait proportionnel au volume de données)."""
import uuid

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Crisis, Offer, OfferType, Request, RequestType


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


def _make_offer(title, environment="DEMO"):
    otype, _ = OfferType.objects.get_or_create(type="Dashboard stats test")
    return Offer.objects.create(
        title=title, offer_type=otype, environment=environment,
        first_name_offer="Test", last_name_offer="Test", email_offer="test@test.fr",
    )


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
