"""commune_risques (geo_lookup.py) : aléas naturels/technologiques d'une commune, résolus via
l'API publique Géorisques (gaspar/risques, sans authentification) et dénormalisés sur Commune
(risques_territoire), jamais recalculés en lecture — même principe que commune_from_code."""
from unittest.mock import patch

import pytest

from core.geo_lookup import commune_risques
from core.models import Commune


GEORISQUES_RESPONSE = {
    "results": 1,
    "data": [{
        "code_insee": "38185",
        "libelle_commune": "GRENOBLE",
        "risques_detail": [
            {"num_risque": "11", "libelle_risque_long": "Inondation", "zone_sismicite": None},
            {"num_risque": "13", "libelle_risque_long": "Séisme", "zone_sismicite": None},
        ],
    }],
}


@pytest.mark.django_db
class TestCommuneRisques:

    def test_resolves_and_caches_risks(self):
        with patch("core.geo_lookup._fetch_json", return_value=GEORISQUES_RESPONSE) as mock_fetch:
            risques = commune_risques("38185")

        assert risques == [
            {"num_risque": "11", "libelle_risque_long": "Inondation"},
            {"num_risque": "13", "libelle_risque_long": "Séisme"},
        ]
        mock_fetch.assert_called_once()
        commune = Commune.objects.get(code="38185")
        assert commune.risques_territoire == risques
        assert commune.derniere_tentative_risques is not None

    def test_second_call_does_not_refetch(self):
        with patch("core.geo_lookup._fetch_json", return_value=GEORISQUES_RESPONSE) as mock_fetch:
            commune_risques("38185")
            commune_risques("38185")

        mock_fetch.assert_called_once()

    def test_empty_commune_code_returns_empty_list(self):
        assert commune_risques(None) == []
        assert commune_risques("") == []

    def test_failed_lookup_respects_cooldown(self):
        with patch("core.geo_lookup._fetch_json", return_value=None) as mock_fetch:
            first = commune_risques("38185")
            second = commune_risques("38185")

        assert first == []
        assert second == []
        # Un seul appel réseau malgré les deux lectures : le cooldown empêche de retenter
        # immédiatement une commune non résolue (voir RETRY_COOLDOWN).
        mock_fetch.assert_called_once()
