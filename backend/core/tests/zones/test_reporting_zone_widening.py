"""ReportingComponent (vue Signalements) : par défaut centrée sur la zone de compétence de
l'institution, avec des options d'élargissement (rayon km / département / région / national).
Offer/Request/Crisis n'appliquaient auparavant AUCUN filtrage géographique sur leur action
`list` par défaut (contrairement à Information) — n'importe quel acteur institutionnel y
voyait toute la France. Le scoping est strictement opt-in (`?scope=zone`) pour ne jamais
changer le comportement des AUTRES écrans qui consomment ce même endpoint `list` (ex:
CrisesComponent, qui doit lister toutes les crises pour permettre à une institution de
candidater n'importe où — pas seulement dans sa zone)."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    Commune, Crisis, Institution, InstitutionType, Offer, OfferType, Request, RequestType,
)


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


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code)


def _make_offer(commune=None, environment="DEMO", **kwargs):
    otype, _ = OfferType.objects.get_or_create(type="Reporting widening test")
    geo = {} if commune is None else {
        "commune_code": commune.code, "epci_code": commune.epci_code,
        "departement_code": commune.departement_code, "region_code": commune.region_code,
    }
    if commune is not None and "location" not in kwargs:
        geo["location"] = Point(commune.centre_longitude, commune.centre_latitude, srid=4326)
    return Offer.objects.create(
        title="Offre", offer_type=otype, environment=environment,
        first_name_offer="Test", last_name_offer="Test", email_offer="test@test.fr",
        **geo, **kwargs,
    )


def _make_request(commune=None, environment="DEMO"):
    rtype, _ = RequestType.objects.get_or_create(type="Reporting widening test")
    geo = {} if commune is None else {
        "commune_code": commune.code, "epci_code": commune.epci_code,
        "departement_code": commune.departement_code, "region_code": commune.region_code,
    }
    return Request.objects.create(
        title="Demande", request_type=rtype, environment=environment,
        first_name_request="Test", last_name_request="Test",
        email_request="test@test.fr", phone_request="0600000000", **geo,
    )


def _make_crisis(nom, zone_communes=None, environment="DEMO"):
    return Crisis.objects.create(
        name=nom, type="INONDATION", location=Point(5.72, 45.18, srid=4326),
        environment=environment, zone_communes=zone_communes or [],
    )


def _mairie_client(create_user, commune, username):
    institution = _make_institution("MAIRIE", commune.code)
    user = create_user(username=username, email=username, type="AUT_LOCALE", demo_role="AUT_LOCALE")
    user.institution = institution
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestScopeOptIn:
    """Sans ?scope=zone, le comportement des listes reste inchangé (national) quel que soit le
    rôle — préserve les autres écrans consommant ce même endpoint `list`."""

    def test_offer_list_stays_national_without_scope_param(self, create_user, commune_grenoble, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)
        client = _mairie_client(create_user, commune_grenoble, "mairie-noscope-offer@test.fr")

        response = client.get(reverse("offer-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_crisis_list_stays_national_without_scope_param(self, create_user, commune_grenoble, commune_lille):
        _make_crisis("Crise Grenoble", zone_communes=[commune_grenoble.code])
        _make_crisis("Crise Lille", zone_communes=[commune_lille.code])
        client = _mairie_client(create_user, commune_grenoble, "mairie-noscope-crisis@test.fr")

        response = client.get(reverse("crisis-list"), HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2


@pytest.mark.django_db
class TestScopeZone:

    def test_offer_scoped_to_commune(self, create_user, commune_grenoble, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)
        client = _mairie_client(create_user, commune_grenoble, "mairie-scope-offer@test.fr")

        response = client.get(reverse("offer-list"), {"scope": "zone"}, HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["commune_code"] == commune_grenoble.code

    def test_request_scoped_to_commune(self, create_user, commune_grenoble, commune_lille):
        _make_request(commune_grenoble)
        _make_request(commune_lille)
        client = _mairie_client(create_user, commune_grenoble, "mairie-scope-request@test.fr")

        response = client.get(reverse("request-list"), {"scope": "zone"}, HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_crisis_scoped_by_zone_communes_containment(self, create_user, commune_grenoble, commune_lille):
        _make_crisis("Crise Grenoble", zone_communes=[commune_grenoble.code])
        _make_crisis("Crise Lille", zone_communes=[commune_lille.code])
        client = _mairie_client(create_user, commune_grenoble, "mairie-scope-crisis@test.fr")

        response = client.get(reverse("crisis-list"), {"scope": "zone"}, HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Crise Grenoble"

    def test_widen_to_departement(self, create_user, commune_grenoble, commune_voiron, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_voiron)  # même département (38)
        _make_offer(commune_lille)   # autre département (59)
        client = _mairie_client(create_user, commune_grenoble, "mairie-widen-dept@test.fr")

        response = client.get(
            reverse("offer-list"), {"scope": "zone", "echelle": "departement"}, HTTP_X_ENVIRONMENT="DEMO",
        )

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_widen_to_national(self, create_user, commune_grenoble, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)
        client = _mairie_client(create_user, commune_grenoble, "mairie-widen-national@test.fr")

        response = client.get(
            reverse("offer-list"), {"scope": "zone", "echelle": "national"}, HTTP_X_ENVIRONMENT="DEMO",
        )

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_cannot_narrow_below_natural_level(self, create_user, commune_grenoble, commune_lille):
        """Une mairie (niveau naturel commune) ne peut pas se réduire à un niveau plus étroit —
        ?echelle=commune (déjà son niveau naturel) ne change rien."""
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)
        client = _mairie_client(create_user, commune_grenoble, "mairie-narrow@test.fr")

        response = client.get(
            reverse("offer-list"), {"scope": "zone", "echelle": "commune"}, HTTP_X_ENVIRONMENT="DEMO",
        )

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_simple_user_with_scope_gets_empty_not_national(self, create_user, commune_grenoble):
        """Un simple utilisateur (pas institutionnel) qui enverrait scope=zone par erreur
        obtient une liste vide, jamais un contournement vers plus de données."""
        _make_offer(commune_grenoble)
        user = create_user(username="simple-scope@test.fr", email="simple-scope@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-list"), {"scope": "zone"}, HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 0

    def test_administrator_sees_everything_even_with_scope(self, create_user, commune_grenoble, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_lille)
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(username="admin-scope@test.fr", email="admin-scope@test.fr", type="ADMIN", demo_role="ADMIN")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("offer-list"), {"scope": "zone"}, HTTP_X_ENVIRONMENT="DEMO")

        assert response.status_code == 200
        assert len(response.data) == 2


@pytest.mark.django_db
class TestRayonKm:

    def test_offer_filtered_by_radius(self, create_user, commune_grenoble, commune_voiron, commune_lille):
        _make_offer(commune_grenoble)  # ~0km de l'institution
        _make_offer(commune_voiron)    # ~20km
        _make_offer(commune_lille)     # très loin
        client = _mairie_client(create_user, commune_grenoble, "mairie-rayon@test.fr")

        response = client.get(
            reverse("offer-list"), {"scope": "zone", "rayon_km": "30"}, HTTP_X_ENVIRONMENT="DEMO",
        )

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_rayon_km_takes_precedence_over_echelle(self, create_user, commune_grenoble, commune_voiron, commune_lille):
        _make_offer(commune_grenoble)
        _make_offer(commune_voiron)
        _make_offer(commune_lille)
        client = _mairie_client(create_user, commune_grenoble, "mairie-rayon-precedence@test.fr")

        # rayon_km (5km, exclut même Voiron) doit l'emporter sur echelle=national (tout inclure).
        response = client.get(
            reverse("offer-list"),
            {"scope": "zone", "echelle": "national", "rayon_km": "5"},
            HTTP_X_ENVIRONMENT="DEMO",
        )

        assert response.status_code == 200
        assert len(response.data) == 1
