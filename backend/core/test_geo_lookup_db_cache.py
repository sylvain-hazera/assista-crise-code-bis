from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from core.geo_lookup import (
    RETRY_COOLDOWN, commune_center_from_code, commune_code_from_point, commune_from_code,
    commune_from_point,
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
    def test_does_not_retry_a_failed_resolution_within_the_cooldown(self, mock_fetch):
        # Contrairement à un cache qui n'expire jamais l'échec, mais aussi contrairement à un
        # retry à chaque lecture (régression constatée en direct : ~15-20s ajoutés à
        # /api/demandes/ par des points non résolus retentés à chaque requête) — un échec
        # récent n'est PAS retenté avant RETRY_COOLDOWN.
        mock_fetch.return_value = None
        assert commune_from_code("99999") is None
        assert commune_from_code("99999") is None
        assert mock_fetch.call_count == 1

    @patch("core.geo_lookup._fetch_json")
    def test_retries_a_failed_resolution_after_the_cooldown(self, mock_fetch):
        mock_fetch.return_value = None
        commune_from_code("99999")
        assert mock_fetch.call_count == 1

        commune = Commune.objects.get(code="99999")
        commune.derniere_tentative = timezone.now() - RETRY_COOLDOWN - timezone.timedelta(minutes=1)
        commune.save(update_fields=["derniere_tentative"])

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
    def test_shares_commune_row_and_single_fetch_with_commune_from_code(self, mock_fetch):
        # Une seule ligne Commune par code, et un seul appel externe pour les deux : nom et
        # centre sont demandés ensemble (?fields=nom,centre) — sinon la résolution du nom
        # poserait déjà `derniere_tentative`, empêchant la résolution du centre avant le
        # cooldown (et inversement).
        mock_fetch.return_value = {"nom": "Grenoble", "centre": {"coordinates": [5.7245, 45.1885]}}
        assert commune_from_code("38185") == "Grenoble"
        assert commune_center_from_code("38185") == {"latitude": 45.1885, "longitude": 5.7245}
        assert mock_fetch.call_count == 1

        assert Commune.objects.filter(code="38185").count() == 1


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
    def test_does_not_retry_an_unresolved_point_within_the_cooldown(self, mock_fetch):
        # C'est LA régression constatée en direct : un point sans correspondance (coordonnées
        # de test imprécises, zone sans adresse répertoriée...) — 119 sur 225 points DEMO au
        # moment du constat — était retenté à chaque lecture, ajoutant ~15-20s à
        # /api/demandes/ (un appel externe par point non résolu, à chaque requête).
        mock_fetch.return_value = {"type": "FeatureCollection", "features": []}
        point = Point(5.7, 45.2, srid=4326)
        assert commune_from_point(point) is None
        assert commune_from_point(point) is None
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
