"""Métriques métier exposées sur /metrics (core/metrics.py)."""
import pytest
from django.utils import timezone
from prometheus_client import REGISTRY

from core.models import Crisis, Offer, Request

REQUEST_FIELDS = {
    "title": "Besoin d'eau",
    "location": "POINT (5.72 45.18)",
    "first_name_request": "Jeanne",
    "last_name_request": "Test",
    "email_request": "jeanne@test.fr",
    "phone_request": "0600000000",
}


def sample(name, labels):
    return REGISTRY.get_sample_value(name, labels) or 0


@pytest.mark.django_db
def test_creating_a_request_increments_the_counter(request_type):
    labels = {"request_type": request_type.type}
    before = sample("assista_help_requests_total", labels)
    Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    assert sample("assista_help_requests_total", labels) == before + 1


@pytest.mark.django_db
def test_updating_a_request_does_not_count_again(request_type):
    req = Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    labels = {"request_type": request_type.type}
    before = sample("assista_help_requests_total", labels)
    req.title = "Besoin d'eau potable"
    req.save()
    assert sample("assista_help_requests_total", labels) == before


@pytest.mark.django_db
def test_creating_an_offer_increments_the_counter(offer_type):
    labels = {"offer_type": offer_type.type}
    before = sample("assista_offers_total", labels)
    Offer.objects.create(
        title="Chambre libre", location="POINT (5.72 45.18)", first_name_offer="Paul",
        last_name_offer="Martin", email_offer="paul@test.fr", offer_type=offer_type,
    )
    assert sample("assista_offers_total", labels) == before + 1


@pytest.mark.django_db
def test_requests_by_status_gauge_reflects_the_database(request_type):
    Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    counts = {
        s.labels["status"]: s.value
        for m in REGISTRY.collect() if m.name == "assista_requests_by_status"
        for s in m.samples
    }
    assert sum(counts.values()) == Request.objects.count() == 2


@pytest.mark.django_db
def test_active_crises_gauge_ignores_ended_crises():
    Crisis.objects.create(name="Crue", type="INONDATION", location="POINT (5.72 45.18)")
    Crisis.objects.create(name="Ancienne crue", type="INONDATION", location="POINT (5.72 45.18)",
                          end_date=timezone.now())
    total = sum(s.value for m in REGISTRY.collect() if m.name == "assista_active_crises" for s in m.samples)
    assert total == 1


@pytest.mark.django_db
def test_metrics_endpoint_exposes_business_metrics(api_client, request_type):
    Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    response = api_client.get("/metrics", HTTP_HOST="localhost")
    assert response.status_code == 200
    body = response.content.decode()
    assert f'assista_help_requests_total{{request_type="{request_type.type}"}}' in body
    assert "assista_requests_by_status" in body
