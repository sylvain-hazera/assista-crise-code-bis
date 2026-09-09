"""InformationViewSet.get_queryset appliquait filter_queryset_to_viewer_zone sans resolver
dédié : le filtre par défaut tente `.filter(epci_code=...)`/`.filter(departement_code=...)`,
des champs qui n'existent pas sur Information (contrairement à Offer/Request) — toute
institution de niveau EPCI/département/région (SDIS, préfecture, EPCI...) consultant la liste
des signalements obtenait une FieldError (500) plutôt qu'une liste. Corrigé par
_information_zone_resolver, qui passe par le référentiel Commune pour résoudre le niveau
demandé en un ensemble de commune_code (même principe que commune_secteur_codes)."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Commune, Information, InformationType, Institution, InstitutionType


@pytest.fixture
def commune_grenoble(db):
    return Commune.objects.create(
        code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


@pytest.fixture
def commune_voiron(db, commune_grenoble):
    return Commune.objects.create(
        code="38544", nom="Voiron", departement_code="38", epci_code="200070078",
        region_code="84", centre_latitude=45.36, centre_longitude=5.59,
    )


@pytest.fixture
def commune_lille(db):
    return Commune.objects.create(
        code="59350", nom="Lille", departement_code="59", epci_code="200093201",
        region_code="32", centre_latitude=50.63, centre_longitude=3.06,
    )


def _make_information(commune, environment="DEMO"):
    itype, _ = InformationType.objects.get_or_create(type="Zone scoping test")
    return Information.objects.create(
        title=f"Signalement {commune.nom}", information_type=itype, environment=environment,
        first_name_information="Test", last_name_information="Test",
        email_information="test@test.fr", phone_information="0600000000",
        location=Point(1, 1, srid=4326), commune_code=commune.code,
    )


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code)


@pytest.mark.django_db
class TestInformationZoneScoping:

    def test_mairie_sees_only_its_commune(self, create_user, commune_grenoble, commune_lille):
        _make_information(commune_grenoble)
        _make_information(commune_lille)

        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="mairie-info@test.fr", email="mairie-info@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["commune_code"] == commune_grenoble.code

    def test_epci_does_not_crash_and_sees_its_intercommunalite(self, create_user, commune_grenoble):
        commune_meylan = Commune.objects.create(
            code="38229", nom="Meylan", departement_code="38", epci_code=commune_grenoble.epci_code,
            centre_latitude=45.21, centre_longitude=5.77,
        )
        _make_information(commune_grenoble)
        _make_information(commune_meylan)

        institution = _make_institution("EPCI", commune_grenoble.code)
        user = create_user(username="epci-info@test.fr", email="epci-info@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_sdis_does_not_crash_and_sees_whole_departement(self, create_user, commune_grenoble, commune_voiron):
        _make_information(commune_grenoble)
        _make_information(commune_voiron)

        institution = _make_institution("SDIS", commune_grenoble.code)
        user = create_user(username="sdis-info@test.fr", email="sdis-info@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2  # Grenoble + Voiron, même département 38

    def test_cr_does_not_crash_and_sees_whole_region(self, create_user, commune_grenoble, commune_lille):
        _make_information(commune_grenoble)
        _make_information(commune_lille)

        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(username="cr-info@test.fr", email="cr-info@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1  # seule Grenoble est dans la région 84 (Lille est en 32)
        assert response.data[0]["commune_code"] == commune_grenoble.code


@pytest.mark.django_db
class TestInformationLocationVisibleAcrossZoneLevels:
    """InformationSerializer._location_visible appelait object_in_viewer_zone (pas
    object_in_viewer_zone_via_commune) : ce prédicat compare getattr(obj, "epci_code"/
    "departement_code"/"region_code", None) au code de la zone du viewer — des champs qui
    n'existent pas sur Information (seul commune_code existe, voir _information_zone_resolver
    plus haut). Résultat : latitude/longitude restaient toujours à None (donc invisibles sur
    la carte) pour toute institution dont le secteur effectif dépasse "commune" (EPCI,
    département, région), alors même que le signalement était bien dans le queryset renvoyé
    par la liste (bug distinct de celui couvert par TestInformationZoneScoping ci-dessus, qui
    ne vérifiait que commune_code, jamais latitude/longitude)."""

    def test_epci_sees_location_of_information_in_its_intercommunalite(self, create_user, commune_grenoble):
        commune_meylan = Commune.objects.create(
            code="38229", nom="Meylan", departement_code="38", epci_code=commune_grenoble.epci_code,
            centre_latitude=45.21, centre_longitude=5.77,
        )
        _make_information(commune_meylan)

        institution = _make_institution("EPCI", commune_grenoble.code)
        user = create_user(username="epci-loc@test.fr", email="epci-loc@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["latitude"] is not None
        assert response.data[0]["longitude"] is not None

    def test_sdis_sees_location_of_information_in_its_departement(self, create_user, commune_grenoble, commune_voiron):
        _make_information(commune_voiron)

        institution = _make_institution("SDIS", commune_grenoble.code)
        user = create_user(username="sdis-loc@test.fr", email="sdis-loc@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["latitude"] is not None
        assert response.data[0]["longitude"] is not None

    def test_cr_sees_location_of_information_in_its_region(self, create_user, commune_grenoble):
        _make_information(commune_grenoble)

        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(username="cr-loc@test.fr", email="cr-loc@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["latitude"] is not None
        assert response.data[0]["longitude"] is not None

    def test_cr_does_not_see_location_of_information_outside_its_region(self, create_user, commune_grenoble, commune_lille):
        _make_information(commune_lille)

        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(username="cr-loc-out@test.fr", email="cr-loc-out@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        user.institution = institution
        user.save()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("information-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        # Hors zone dès le queryset (voir TestInformationZoneScoping) : n'apparaît pas du tout.
        assert len(response.data) == 0
