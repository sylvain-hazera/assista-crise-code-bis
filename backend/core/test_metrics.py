"""Métriques métier exposées sur /metrics (core/metrics.py)."""
import pytest
from django.utils import timezone
from prometheus_client import REGISTRY

from core.models import Crisis, Institution, InstitutionType, Offer, Request, User

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
    labels = {"request_type": request_type.type, "environment": "PROD"}
    before = sample("assista_help_requests_total", labels)
    Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    assert sample("assista_help_requests_total", labels) == before + 1


@pytest.mark.django_db
def test_updating_a_request_does_not_count_again(request_type):
    req = Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    labels = {"request_type": request_type.type, "environment": "PROD"}
    before = sample("assista_help_requests_total", labels)
    req.title = "Besoin d'eau potable"
    req.save()
    assert sample("assista_help_requests_total", labels) == before


@pytest.mark.django_db
def test_creating_an_offer_increments_the_counter(offer_type):
    labels = {"offer_type": offer_type.type, "environment": "PROD"}
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
    assert f'assista_help_requests_total{{environment="PROD",request_type="{request_type.type}"}}' in body
    assert "assista_requests_by_status" in body


def gauge(name, labels=None):
    return sum(
        s.value for m in REGISTRY.collect() for s in m.samples
        if s.name == name and all(s.labels.get(k) == v for k, v in (labels or {}).items())
    )


@pytest.mark.django_db
def test_business_gauges_separate_prod_from_demo(request_type):
    Request.objects.create(request_type=request_type, **REQUEST_FIELDS)
    Request.objects.create(request_type=request_type, environment="DEMO", **REQUEST_FIELDS)
    assert gauge("assista_requests_by_status", {"environment": "PROD"}) == 1
    assert gauge("assista_requests_by_status", {"environment": "DEMO"}) == 1


@pytest.mark.django_db
def test_creating_an_institution_increments_the_counter():
    itype = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
    before = sample("assista_institutions_created_total", {"environment": "DEMO"})
    institution = Institution.objects.create(nom="SDIS Metrique", type=itype, environment="DEMO")
    institution.save()
    assert sample("assista_institutions_created_total", {"environment": "DEMO"}) == before + 1


@pytest.mark.django_db
def test_pending_accounts_gauges():
    assert gauge("assista_accounts_pending_validation") == 0
    assert gauge("assista_oldest_pending_account_age_seconds") == 0
    attente = User.objects.create_user(
        username="attente@sdis40.fr", email="attente@sdis40.fr", password="Test1234!", type="SECOURS",
        enabled=False, is_active=False, pending_institution_type="sdis",
    )
    User.objects.filter(pk=attente.pk).update(date_joined=timezone.now() - timezone.timedelta(hours=30))
    assert gauge("assista_accounts_pending_validation") == 1
    assert gauge("assista_oldest_pending_account_age_seconds") >= 30 * 3600


@pytest.mark.django_db
def test_active_crises_gauge_ignores_test_crises():
    Crisis.objects.create(name="Crue réelle", type="INONDATION", location="POINT (5.72 45.18)")
    Crisis.objects.create(name="Crue d'essai", type="INONDATION", location="POINT (5.72 45.18)", essai=True)
    assert gauge("assista_active_crises") == 1
