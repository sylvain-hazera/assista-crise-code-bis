import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Commune, Institution, InstitutionType, Request, RequestType, Team


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
class TestTeamListZoneScoping:
    """La liste des équipes (action `list`) est réduite à la zone de compétence de
    l'appelant — retrieve reste ouvert (voir TeamViewSet.get_permissions/get_queryset)."""

    def _make_institution(self, code, commune):
        itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})
        return Institution.objects.create(nom=f"Institution {code}", type=itype, commune_code=commune.code)

    @pytest.fixture
    def commune_a(self, db):
        return Commune.objects.create(
            code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
            region_code="84", centre_latitude=45.18, centre_longitude=5.72,
        )

    @pytest.fixture
    def commune_b(self, db):
        return Commune.objects.create(
            code="38544", nom="Voiron", departement_code="38", epci_code="200070078",
            region_code="84", centre_latitude=45.36, centre_longitude=5.59,
        )

    def test_mairie_list_only_shows_teams_in_its_commune(self, create_user, commune_a, commune_b):
        institution_a = self._make_institution("MAIRIE_TEAM_ZONE_A", commune_a)
        institution_b = self._make_institution("MAIRIE_TEAM_ZONE_B", commune_b)
        team_a = Team.objects.create(name="Equipe A", institution=institution_a)
        team_b = Team.objects.create(name="Equipe B", institution=institution_b)

        user = create_user(username="mairie-a-team@test.fr", email="mairie-a-team@test.fr", type="AUT_LOCALE")
        user.institution = institution_a
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-list'))
        assert response.status_code == status.HTTP_200_OK
        names = {t['name'] for t in response.data}
        assert team_a.name in names
        assert team_b.name not in names

    def test_retrieve_stays_open_across_zones(self, create_user, commune_a, commune_b):
        institution_a = self._make_institution("MAIRIE_TEAM_ZONE_C", commune_a)
        institution_b = self._make_institution("MAIRIE_TEAM_ZONE_D", commune_b)
        team_b = Team.objects.create(name="Equipe D", institution=institution_b)

        user = create_user(username="mairie-c-team@test.fr", email="mairie-c-team@test.fr", type="AUT_LOCALE")
        user.institution = institution_a
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-detail', args=[team_b.id]))
        assert response.status_code == status.HTTP_200_OK

    def test_admin_list_sees_all_zones(self, create_user, commune_a, commune_b):
        institution_a = self._make_institution("MAIRIE_TEAM_ZONE_E", commune_a)
        institution_b = self._make_institution("MAIRIE_TEAM_ZONE_F", commune_b)
        Team.objects.create(name="Equipe E", institution=institution_a)
        Team.objects.create(name="Equipe F", institution=institution_b)

        user = create_user(username="admin-team-zone@test.fr", email="admin-team-zone@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-list'))
        assert response.status_code == status.HTTP_200_OK
        names = {t['name'] for t in response.data}
        assert {"Equipe E", "Equipe F"}.issubset(names)

    def test_no_institution_sees_no_team_in_list(self, create_user, commune_a):
        institution_a = self._make_institution("MAIRIE_TEAM_ZONE_G", commune_a)
        Team.objects.create(name="Equipe G", institution=institution_a)

        # Compte AUT_LOCALE sans institution rattachée : aucune zone résolvable, donc aucune
        # équipe visible en liste — jamais la liste complète par défaut.
        user = create_user(username="sans-institution-team@test.fr", email="sans-institution-team@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-list'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []


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
