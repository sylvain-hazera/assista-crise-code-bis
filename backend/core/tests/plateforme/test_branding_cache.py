"""La charte est gardée 5 minutes par le navigateur (19/11/2026, « le site rame »)."""
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_la_charte_est_gardee_cinq_minutes_par_le_navigateur():
    reponse = APIClient().get("/api/branding/")
    assert reponse.status_code == 200
    assert reponse["Cache-Control"] == "public, max-age=300"


@pytest.mark.django_db
def test_les_autres_reponses_de_l_api_restent_sans_cache():
    reponse = APIClient().get("/api/sonde/")
    assert reponse["Cache-Control"] == "no-store"
