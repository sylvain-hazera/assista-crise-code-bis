from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.geo_lookup import commune_center_from_code
from core.models import Institution, InstitutionType, Team


@pytest.mark.django_db
class TestCommuneCenterFromCode:

    @patch("core.geo_lookup._fetch_json")
    def test_returns_lat_lon_from_centre_field(self, mock_fetch):
        mock_fetch.return_value = {"nom": "Grenoble", "code": "38185", "centre": {"type": "Point", "coordinates": [5.7245, 45.1885]}}

        result = commune_center_from_code("38185")

        assert result == {"latitude": 45.1885, "longitude": 5.7245}

    @patch("core.geo_lookup._fetch_json")
    def test_returns_none_when_api_unavailable(self, mock_fetch):
        mock_fetch.return_value = None

        # Code distinct du test précédent : le cache (30 jours, partagé entre tests d'un même
        # run) renverrait sinon la valeur déjà mise en cache pour "38185" sans jamais rappeler
        # _fetch_json.
        result = commune_center_from_code("75056")

        assert result == {"latitude": None, "longitude": None}

    def test_returns_none_without_code(self):
        assert commune_center_from_code("") == {"latitude": None, "longitude": None}


@pytest.mark.django_db
class TestTeamSerializerCommuneCentre:

    @patch("core.serializers.commune_center_from_code")
    def test_exposes_commune_centre_from_institution(self, mock_center, create_user):
        mock_center.return_value = {"latitude": 45.1885, "longitude": 5.7245}
        itype = InstitutionType.objects.create(code="MAIRIE_COMMUNE_CENTRE_TEST", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie commune centre test", type=itype, commune_code="38185")
        team = Team.objects.create(name="Équipe commune centre test", institution=institution)
        user = create_user(username="commune-centre@test.fr", email="commune-centre@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-detail', args=[team.id]))

        assert response.data["commune_centre"] == {"latitude": 45.1885, "longitude": 5.7245}
        mock_center.assert_called_once_with("38185")

    def test_none_when_institution_has_no_commune_code(self, create_user):
        itype = InstitutionType.objects.create(code="MAIRIE_NO_COMMUNE_TEST", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie sans commune test", type=itype)
        team = Team.objects.create(name="Équipe sans commune test", institution=institution)
        user = create_user(username="no-commune-centre@test.fr", email="no-commune-centre@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-detail', args=[team.id]))

        assert response.data["commune_centre"] is None

    def test_none_when_team_has_no_institution(self, create_user):
        team = Team.objects.create(name="Équipe orpheline test")
        user = create_user(username="orpheline-commune@test.fr", email="orpheline-commune@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('team-detail', args=[team.id]))

        assert response.data["commune_centre"] is None
