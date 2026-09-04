"""Consultation des offres de bénévoles par secteur (mairie -> commune, communauté de
communes -> EPCI, SDIS/gendarmerie/préfecture -> département) : verrouille le dispatch par
type d'institution, le filtrage sur colonnes indexées (pas de reverse-géocodage en lecture,
contrairement à l'ancien vue_mairie), et la pagination opt-in."""
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Commune, Institution, InstitutionType, Offer, OfferType


@pytest.fixture
def commune_grenoble(db):
    return Commune.objects.create(
        code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
        centre_latitude=45.18, centre_longitude=5.72,
    )


@pytest.fixture
def commune_voiron(db, commune_grenoble):
    # Même département (38), EPCI différent de Grenoble.
    return Commune.objects.create(
        code="38544", nom="Voiron", departement_code="38", epci_code="200070078",
        centre_latitude=45.36, centre_longitude=5.59,
    )


def _make_offer(commune, environment="DEMO"):
    otype, _ = OfferType.objects.get_or_create(type="Bénévolat")
    return Offer.objects.create(
        title="Ancien sapeur-pompier disponible comme bénévole",
        offer_type=otype, environment=environment,
        first_name_offer="Jean", last_name_offer="Dupont", email_offer="jean@test.fr",
        commune_code=commune.code, epci_code=commune.epci_code, departement_code=commune.departement_code,
    )


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code)


@pytest.mark.django_db
class TestVueSecteur:

    def test_mairie_sees_only_its_commune(self, create_user, commune_grenoble, commune_voiron):
        _make_offer(commune_grenoble)
        _make_offer(commune_voiron)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="mairie-secteur@test.fr", email="mairie-secteur@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["commune_code"] == commune_grenoble.code

    def test_epci_sees_its_intercommunalite_across_communes(self, create_user, commune_grenoble):
        commune_meylan = Commune.objects.create(
            code="38229", nom="Meylan", departement_code="38", epci_code=commune_grenoble.epci_code,
            centre_latitude=45.21, centre_longitude=5.77,
        )
        _make_offer(commune_grenoble)
        _make_offer(commune_meylan)

        institution = _make_institution("EPCI", commune_grenoble.code)
        user = create_user(username="epci-secteur@test.fr", email="epci-secteur@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_sdis_sees_whole_departement(self, create_user, commune_grenoble, commune_voiron):
        _make_offer(commune_grenoble)
        _make_offer(commune_voiron)

        institution = _make_institution("SDIS", commune_grenoble.code)
        user = create_user(username="sdis-secteur@test.fr", email="sdis-secteur@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2  # Grenoble + Voiron, même département 38

    def test_no_institution_returns_400_not_empty_list(self, create_user):
        user = create_user(username="sans-institution@test.fr", email="sans-institution@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert response.status_code == 400

    def test_pagination_is_opt_in(self, create_user, commune_grenoble):
        for _ in range(5):
            _make_offer(commune_grenoble)
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="mairie-pagination@test.fr", email="mairie-pagination@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        without_page = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert isinstance(without_page.data, list)
        assert len(without_page.data) == 5

        with_page = client.get(reverse("offer-vue-secteur"), {"page": 1, "page_size": 2}, HTTP_X_ENVIRONMENT="DEMO")
        assert set(with_page.data.keys()) == {"count", "next", "previous", "results"}
        assert with_page.data["count"] == 5
        assert len(with_page.data["results"]) == 2

    def test_environment_scoping_prod_not_leaked_into_demo_view(self, create_user, commune_grenoble):
        _make_offer(commune_grenoble, environment="PROD")
        _make_offer(commune_grenoble, environment="DEMO")
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="mairie-env@test.fr", email="mairie-env@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert len(response.data) == 1


@pytest.mark.django_db
class TestCommuneSecteurCodes:

    @patch("core.geo_lookup._fetch_json")
    def test_returns_epci_and_departement(self, mock_fetch):
        from core.geo_lookup import commune_secteur_codes
        mock_fetch.return_value = {"nom": "Grenoble", "codeDepartement": "38", "codeEpci": "200040715"}
        result = commune_secteur_codes("38185")
        assert result == {"epci_code": "200040715", "departement_code": "38"}

    def test_none_input(self):
        from core.geo_lookup import commune_secteur_codes
        assert commune_secteur_codes(None) == {"epci_code": None, "departement_code": None}
