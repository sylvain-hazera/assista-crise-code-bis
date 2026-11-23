"""Les messages de Django et DRF partent en français (23/11/2026) : un testeur de l'application
mobile lisait « Date has wrong format » sous le champ date de naissance."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_les_erreurs_de_validation_sont_en_francais():
    r = APIClient().post(reverse("token_refresh"), {"refresh": ""}, format="json")
    assert r.status_code == 400
    message = str(r.data["refresh"][0])
    assert "may not be blank" not in message
    assert "vide" in message.lower(), message
    assert r.headers.get("Content-Language") == "fr"
