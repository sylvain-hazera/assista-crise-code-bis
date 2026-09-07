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
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


@pytest.fixture
def commune_voiron(db, commune_grenoble):
    # Même département (38) et région (84), EPCI différent de Grenoble.
    return Commune.objects.create(
        code="38544", nom="Voiron", departement_code="38", epci_code="200070078",
        region_code="84", centre_latitude=45.36, centre_longitude=5.59,
    )


@pytest.fixture
def commune_lille(db):
    # Autre département (59) et région (32) — pour vérifier qu'une portée plus large les
    # englobe tous, et qu'une portée départementale/régionale les distingue bien.
    return Commune.objects.create(
        code="59350", nom="Lille", departement_code="59", epci_code="200093201",
        region_code="32", centre_latitude=50.63, centre_longitude=3.06,
    )


def _make_offer(commune, environment="DEMO"):
    otype, _ = OfferType.objects.get_or_create(type="Bénévolat")
    return Offer.objects.create(
        title="Ancien sapeur-pompier disponible comme bénévole",
        offer_type=otype, environment=environment,
        first_name_offer="Jean", last_name_offer="Dupont", email_offer="jean@test.fr",
        commune_code=commune.code, epci_code=commune.epci_code, departement_code=commune.departement_code,
        region_code=commune.region_code,
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
    def test_returns_epci_departement_region(self, mock_fetch):
        from core.geo_lookup import commune_secteur_codes
        mock_fetch.return_value = {
            "nom": "Grenoble", "codeDepartement": "38", "codeEpci": "200040715", "codeRegion": "84",
        }
        result = commune_secteur_codes("38185")
        assert result == {"epci_code": "200040715", "departement_code": "38", "region_code": "84"}

    def test_none_input(self):
        from core.geo_lookup import commune_secteur_codes
        assert commune_secteur_codes(None) == {"epci_code": None, "departement_code": None, "region_code": None}


@pytest.mark.django_db
class TestInstitutionSaveDenormalizesSecteur:

    def test_save_populates_epci_departement_region_from_commune(self, commune_grenoble):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_DENORM_TEST", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie dénorm test", type=itype, commune_code=commune_grenoble.code)
        assert institution.epci_code == "200040715"
        assert institution.departement_code == "38"
        assert institution.region_code == "84"


@pytest.mark.django_db
class TestVueSecteurRegionAndNational:

    def test_conseil_regional_sees_whole_region(self, create_user, commune_grenoble, commune_voiron, commune_lille):
        _make_offer(commune_grenoble)   # région 84
        _make_offer(commune_voiron)     # région 84
        _make_offer(commune_lille)      # région 32

        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(username="cr-secteur@test.fr", email="cr-secteur@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert response.status_code == 200
        assert len(response.data) == 2  # Grenoble + Voiron (région 84), pas Lille (région 32)

    def test_secteur_override_national_sees_everything(self, create_user, commune_grenoble, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        institution.secteur_override = "national"
        institution.save()
        user = create_user(username="national-secteur@test.fr", email="national-secteur@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert response.status_code == 200
        assert len(response.data) == 2  # les deux, malgré un type MAIRIE (normalement commune)

    def test_secteur_override_takes_precedence_over_type(self, create_user, commune_grenoble, commune_voiron):
        _make_offer(commune_grenoble)
        _make_offer(commune_voiron)

        # MAIRIE serait "commune" par défaut (ne verrait que Grenoble) — l'override la fait
        # passer en "departement" (voit aussi Voiron, même département 38).
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        institution.secteur_override = "departement"
        institution.save()
        user = create_user(username="override-secteur@test.fr", email="override-secteur@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert response.status_code == 200
        assert len(response.data) == 2

    def test_secteur_override_is_read_only_via_api(self, create_user, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="tamper-secteur@test.fr", email="tamper-secteur@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            reverse("institution-detail", args=[institution.id]),
            {"secteur_override": "national"}, format="json",
        )
        assert response.status_code == 200
        institution.refresh_from_db()
        assert institution.secteur_override is None


@pytest.mark.django_db
class TestVueSecteurEchelleNationalPartial:
    """"Voir toute la France (partiel)" (?echelle=national) : donne à N'IMPORTE QUEL acteur
    institutionnel — même une simple mairie, normalement limitée à sa commune — une vue
    nationale, mais toujours réduite (OfferNationalPartialSerializer), jamais le détail complet
    (voir OfferViewSet.vue_secteur)."""

    def test_mairie_sees_national_count_with_echelle_param(self, create_user, commune_grenoble, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="mairie-echelle@test.fr", email="mairie-echelle@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        # Sans ?echelle=national : limité à sa commune (1 seule, Grenoble).
        response_zone = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")
        assert len(response_zone.data) == 1

        # Avec ?echelle=national : les deux, France entière.
        response_national = client.get(
            reverse("offer-vue-secteur"), {"echelle": "national"}, HTTP_X_ENVIRONMENT="DEMO"
        )
        assert response_national.status_code == 200
        assert len(response_national.data) == 2

    def test_echelle_national_never_exposes_contact_fields(self, create_user, commune_grenoble):
        offer = _make_offer(commune_grenoble)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="mairie-echelle-pii@test.fr", email="mairie-echelle-pii@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(
            reverse("offer-vue-secteur"), {"echelle": "national"}, HTTP_X_ENVIRONMENT="DEMO"
        )

        assert response.status_code == 200
        entry = next(o for o in response.data if o["id"] == str(offer.id))
        assert set(entry.keys()) == {"id", "offer_type_nom", "status", "crisis_nom", "created_at"}

    def test_own_national_institution_also_gets_partial_serializer(self, create_user, commune_grenoble, commune_lille):
        # Même une institution dont le NIVEAU PROPRE est déjà national (secteur_override) ne
        # doit plus voir le détail complet ici — corrige le comportement d'avant ce correctif.
        offer = _make_offer(commune_grenoble)
        _make_offer(commune_lille)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        institution.secteur_override = "national"
        institution.save()
        user = create_user(username="national-partial@test.fr", email="national-partial@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-vue-secteur"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        entry = next(o for o in response.data if o["id"] == str(offer.id))
        assert "email_offer" not in entry
        assert "first_name_offer" not in entry
