"""Réglages de quantité de la Vue Ma Collectivité : filtrage par type d'offre (séparer les
bénévoles des offres de crise) et pagination opt-in (page_size) sur Offer.vue_secteur et
Information.vue_mairie — pour plafonner le volume chargé sur un grand secteur (voir
VueMairieComponent, le cas concret étant l'annuaire de bénévoles pouvant compter des centaines
de fiches à l'échelle d'une région)."""
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient
import pytest

from core.models import Commune, Information, InformationType, Institution, InstitutionType, Offer, OfferType


@pytest.fixture
def commune_grenoble(db):
    return Commune.objects.create(
        code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code)


def _make_offer(commune, type_libelle="Autre"):
    otype, _ = OfferType.objects.get_or_create(type=type_libelle)
    return Offer.objects.create(
        title=f"Offre {type_libelle}", offer_type=otype,
        first_name_offer="Jean", last_name_offer="Dupont", email_offer="jean@test.fr",
        commune_code=commune.code, epci_code=commune.epci_code, departement_code=commune.departement_code,
        region_code=commune.region_code,
    )


@pytest.mark.django_db
class TestOfferVueSecteurFiltrageType:

    def test_type_filter_returns_only_that_type(self, create_user, commune_grenoble):
        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(email="cr@test.fr", username="cr@test.fr", type="AUT_LOCALE", institution=institution)
        _make_offer(commune_grenoble, "Bénévolat")
        _make_offer(commune_grenoble, "Bénévolat")
        _make_offer(commune_grenoble, "Transport")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), {"type": "Bénévolat"})

        assert response.status_code == 200
        assert len(response.data) == 2
        assert all(o["title"] == "Offre Bénévolat" for o in response.data)

    def test_exclude_type_filters_it_out(self, create_user, commune_grenoble):
        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(email="cr2@test.fr", username="cr2@test.fr", type="AUT_LOCALE", institution=institution)
        _make_offer(commune_grenoble, "Bénévolat")
        _make_offer(commune_grenoble, "Transport")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), {"exclude_type": "Bénévolat"})

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["title"] == "Offre Transport"

    def test_page_size_caps_results(self, create_user, commune_grenoble):
        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(email="cr3@test.fr", username="cr3@test.fr", type="AUT_LOCALE", institution=institution)
        for _ in range(5):
            _make_offer(commune_grenoble, "Bénévolat")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("offer-vue-secteur"), {"page": "1", "page_size": "2"})

        assert response.status_code == 200
        assert response.data["count"] == 5
        assert len(response.data["results"]) == 2


@pytest.mark.django_db
class TestInformationVueMairiePagination:

    def test_page_size_caps_results(self, create_user, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(email="mairie@test.fr", username="mairie@test.fr", type="AUT_LOCALE", institution=institution)
        itype, _ = InformationType.objects.get_or_create(type="Autre")
        for i in range(4):
            Information.objects.create(
                title=f"Signalement {i}", information_type=itype,
                first_name_information="Jean", last_name_information="Dupont",
                email_information="jean@test.fr", phone_information="0600000000",
                location=Point(5.72, 45.18, srid=4326), commune_code=commune_grenoble.code,
            )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-vue-mairie"), {"page": "1", "page_size": "2"})

        assert response.status_code == 200
        assert response.data["count"] == 4
        assert len(response.data["results"]) == 2

    def test_without_page_returns_plain_list(self, create_user, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(email="mairie2@test.fr", username="mairie2@test.fr", type="AUT_LOCALE", institution=institution)
        itype, _ = InformationType.objects.get_or_create(type="Autre")
        Information.objects.create(
            title="Signalement", information_type=itype,
            first_name_information="Jean", last_name_information="Dupont",
            email_information="jean@test.fr", phone_information="0600000000",
            location=Point(5.72, 45.18, srid=4326), commune_code=commune_grenoble.code,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-vue-mairie"))

        assert response.status_code == 200
        assert isinstance(response.data, list)
        assert len(response.data) == 1
