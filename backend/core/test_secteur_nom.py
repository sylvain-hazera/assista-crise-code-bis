"""Institution.secteur_nom/secteur_niveau_effectif (dénormalisés dans Institution.save(), voir
core/geo_reference.py) et UserSerializer.get_ma_zone qui les expose — support de la bannière
"Ma zone est :" de la Vue Ma Collectivité (anciennement Vue Mairie)."""
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Commune, Institution, InstitutionType


@pytest.fixture
def commune_grenoble(db):
    return Commune.objects.create(
        code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(
        nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code,
    )


@pytest.mark.django_db
class TestSecteurNom:

    def test_mairie_secteur_nom_is_commune_name(self, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        assert institution.secteur_niveau_effectif == "commune"
        assert institution.secteur_nom == "Grenoble"

    def test_sdis_secteur_nom_is_departement_name(self, commune_grenoble):
        institution = _make_institution("SDIS", commune_grenoble.code)
        assert institution.secteur_niveau_effectif == "departement"
        assert institution.secteur_nom == "Isère"

    def test_cr_secteur_nom_is_region_name(self, commune_grenoble):
        institution = _make_institution("CR", commune_grenoble.code)
        assert institution.secteur_niveau_effectif == "region"
        assert institution.secteur_nom == "Auvergne-Rhône-Alpes"

    def test_override_national_secteur_nom(self, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        institution.secteur_override = "national"
        institution.save()
        assert institution.secteur_niveau_effectif == "national"
        assert institution.secteur_nom == "France entière"

    def test_epci_secteur_nom_resolved_via_geo_lookup(self, commune_grenoble):
        with patch("core.geo_lookup.epci_nom_from_code", return_value="Grenoble-Alpes-Métropole"):
            institution = _make_institution("EPCI", commune_grenoble.code)
        assert institution.secteur_niveau_effectif == "epci"
        assert institution.secteur_nom == "Grenoble-Alpes-Métropole"

    def test_institution_without_commune_has_no_secteur_nom(self):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
        institution = Institution.objects.create(nom="Sans commune", type=itype)
        assert institution.secteur_niveau_effectif is None
        assert institution.secteur_nom is None


@pytest.mark.django_db
class TestMaZone:

    def test_ma_zone_reflects_user_institution(self, create_user, commune_grenoble):
        institution = _make_institution("SDIS", commune_grenoble.code)
        user = create_user(email="pompier@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)
        with patch("core.serializers.commune_risques", return_value=[]):
            response = client.get(reverse("user-detail", args=[user.id]))
        assert response.status_code == 200
        assert response.data["ma_zone"] == {"niveau": "departement", "nom": "Isère", "risques": []}

    def test_ma_zone_includes_territory_risks(self, create_user, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(email="secretaire-risques@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)
        risques = [{"num_risque": "11", "libelle_risque_long": "Inondation"}]
        with patch("core.serializers.commune_risques", return_value=risques):
            response = client.get(reverse("user-detail", args=[user.id]))
        assert response.status_code == 200
        assert response.data["ma_zone"]["risques"] == risques

    def test_ma_zone_none_without_institution(self, create_user):
        user = create_user(email="sans-institution@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("user-detail", args=[user.id]))
        assert response.status_code == 200
        assert response.data["ma_zone"] is None
