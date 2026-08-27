import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise zone secteurs test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def admin(create_user):
    return create_user(username="admin-zone-secteurs@test.fr", email="admin-zone-secteurs@test.fr", type="ADMIN")


@pytest.mark.django_db
class TestCrisisZoneSecteurs:

    def test_patch_zone_communes_departements(self, admin, crisis):
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(
            reverse('crisis-detail', args=[crisis.id]),
            {"zone_communes": ["38185"], "zone_departements": ["73"]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        crisis.refresh_from_db()
        assert crisis.zone_communes == ["38185"]
        assert crisis.zone_departements == ["73"]

    def test_zone_secteurs_accepts_multipolygon_wkt(self, admin, crisis):
        client = APIClient()
        client.force_authenticate(user=admin)
        wkt = "MULTIPOLYGON (((5.7 45.1, 5.8 45.1, 5.8 45.2, 5.7 45.2, 5.7 45.1)))"

        response = client.patch(
            reverse('crisis-detail', args=[crisis.id]),
            {"zone_secteurs": wkt},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        crisis.refresh_from_db()
        assert crisis.zone_secteurs is not None
        assert response.data["zone_secteurs_geojson"]["type"] == "MultiPolygon"

    def test_defaults_are_empty(self, crisis):
        assert crisis.zone_communes == []
        assert crisis.zone_departements == []
        assert crisis.zone_secteurs is None
