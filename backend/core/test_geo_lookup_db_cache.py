from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point

from core.geo_lookup import (
    commune_center_from_code, commune_code_from_point, commune_from_code, commune_from_point,
)
from core.models import Commune, PointCommune


@pytest.mark.django_db
class TestCommuneFromCode:

    @patch("core.geo_lookup._fetch_json")
    def test_resolves_and_persists(self, mock_fetch):
        mock_fetch.return_value = {"nom": "Grenoble"}
        assert commune_from_code("38185") == "Grenoble"
        mock_fetch.assert_called_once()

        commune = Commune.objects.get(code="38185")
        assert commune.nom == "Grenoble"

    @patch("core.geo_lookup._fetch_json")
    def test_second_call_does_not_refetch(self, mock_fetch):
        mock_fetch.return_value = {"nom": "Grenoble"}
        commune_from_code("38185")
        commune_from_code("38185")
        # Une seule requête externe : la seconde lecture vient de la base, jamais du réseau —
        # exactement le comportement qui manquait au cache Django (vidé à chaque redémarrage).
        assert mock_fetch.call_count == 1

    @patch("core.geo_lookup._fetch_json")
    def test_retries_after_a_failed_resolution(self, mock_fetch):
        # Contrairement à l'ancien cache (qui mémorisait un échec pour 30 jours), une commune
        # non résolue reste "à retenter" : nom encore None en base, donc un appel ultérieur
        # retente l'API externe.
        mock_fetch.return_value = None
        assert commune_from_code("99999") is None
        mock_fetch.return_value = {"nom": "Trouvée"}
        assert commune_from_code("99999") == "Trouvée"
        assert mock_fetch.call_count == 2

    def test_none_for_empty_code(self):
        assert commune_from_code("") is None
        assert commune_from_code(None) is None


@pytest.mark.django_db
class TestCommuneCenterFromCode:

    @patch("core.geo_lookup._fetch_json")
    def test_resolves_and_persists(self, mock_fetch):
        mock_fetch.return_value = {"centre": {"coordinates": [5.7245, 45.1885]}}
        result = commune_center_from_code("38185")
        assert result == {"latitude": 45.1885, "longitude": 5.7245}

        commune = Commune.objects.get(code="38185")
        assert commune.centre_latitude == 45.1885
        assert commune.centre_longitude == 5.7245

    @patch("core.geo_lookup._fetch_json")
    def test_second_call_does_not_refetch(self, mock_fetch):
        mock_fetch.return_value = {"centre": {"coordinates": [5.7245, 45.1885]}}
        commune_center_from_code("38185")
        commune_center_from_code("38185")
        assert mock_fetch.call_count == 1

    @patch("core.geo_lookup._fetch_json")
    def test_shares_commune_row_with_commune_from_code(self, mock_fetch):
        # Une seule ligne Commune par code, que la résolution vienne du nom ou du centroïde —
        # c'est tout l'intérêt de la table normalisée par rapport au cache (pas de duplication).
        mock_fetch.return_value = {"nom": "Grenoble"}
        commune_from_code("38185")
        mock_fetch.return_value = {"centre": {"coordinates": [5.7245, 45.1885]}}
        commune_center_from_code("38185")

        assert Commune.objects.filter(code="38185").count() == 1
        commune = Commune.objects.get(code="38185")
        assert commune.nom == "Grenoble"
        assert commune.centre_latitude == 45.1885


@pytest.mark.django_db
class TestReverseGeocodePoint:

    @patch("core.geo_lookup._fetch_json")
    def test_resolves_and_persists(self, mock_fetch):
        mock_fetch.return_value = {
            "features": [{"properties": {"city": "Grenoble", "citycode": "38185"}}]
        }
        point = Point(5.7245, 45.1885, srid=4326)

        assert commune_from_point(point) == "Grenoble"
        assert PointCommune.objects.filter(lat=45.1885, lon=5.7245).exists()
        assert Commune.objects.get(code="38185").nom == "Grenoble"

    @patch("core.geo_lookup._fetch_json")
    def test_second_call_does_not_refetch(self, mock_fetch):
        mock_fetch.return_value = {
            "features": [{"properties": {"city": "Grenoble", "citycode": "38185"}}]
        }
        point = Point(5.7245, 45.1885, srid=4326)
        commune_from_point(point)
        commune_from_point(point)
        # Reproduit la régression constatée en direct : sans stockage durable, chaque appel
        # (donc chaque item d'une liste) refaisait l'appel externe.
        assert mock_fetch.call_count == 1

    @patch("core.geo_lookup._fetch_json")
    def test_distinct_points_share_commune_row(self, mock_fetch):
        mock_fetch.return_value = {
            "features": [{"properties": {"city": "Grenoble", "citycode": "38185"}}]
        }
        commune_from_point(Point(5.7245, 45.1885, srid=4326))
        commune_from_point(Point(5.7246, 45.1886, srid=4326))

        assert PointCommune.objects.count() == 2
        assert Commune.objects.filter(code="38185").count() == 1

    def test_none_for_missing_point(self):
        assert commune_from_point(None) is None
        assert commune_code_from_point(None) is None

    @patch("core.geo_lookup._fetch_json")
    def test_citycode_from_point(self, mock_fetch):
        mock_fetch.return_value = {
            "features": [{"properties": {"city": "Grenoble", "citycode": "38185"}}]
        }
        assert commune_code_from_point(Point(5.7245, 45.1885, srid=4326)) == "38185"
