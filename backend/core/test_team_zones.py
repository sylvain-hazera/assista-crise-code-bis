import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Request, RequestType, Team


@pytest.fixture
def team(db):
    return Team.objects.create(name="Equipe zone test", description="", color="#3b82f6")


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="institution-zone@test.fr", email="institution-zone@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestTeamZones:

    def test_departements_and_communes_readable_and_writable(self, institutional_client, team):
        client, _ = institutional_client

        response = client.patch(
            reverse('team-detail', args=[team.id]),
            {"departements": ["38", "73"], "communes": ["38185"]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["departements"] == ["38", "73"]
        assert response.data["communes"] == ["38185"]
        team.refresh_from_db()
        assert team.departements == ["38", "73"]
        assert team.communes == ["38185"]

    def test_zone_precise_writable_via_wkt_readable_as_geojson(self, institutional_client, team):
        client, _ = institutional_client
        wkt = "POLYGON((5.7 45.1, 5.8 45.1, 5.8 45.2, 5.7 45.2, 5.7 45.1))"

        response = client.patch(
            reverse('team-detail', args=[team.id]),
            {"zone_precise": wkt},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["zone_precise_geojson"] is not None
        assert response.data["zone_precise_geojson"]["type"] == "Polygon"

    def test_defaults_are_empty_lists_not_null(self, team):
        assert team.departements == []
        assert team.communes == []
        assert team.zone_precise is None


@pytest.mark.django_db
class TestRequestCommuneCode:

    def test_request_accepts_commune_code(self, request_type):
        client = APIClient()

        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande avec code commune",
                "location": "POINT (5.7245 45.1885)",
                "commune_code": "38185",
                "first_name_request": "Jean",
                "last_name_request": "Test",
                "email_request": "jean.commune@test.fr",
                "phone_request": "0600000000",
                "status": "NON_TRAITEE",
                "request_type": str(request_type.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        request_obj = Request.objects.get(id=response.data["id"])
        assert request_obj.commune_code == "38185"
