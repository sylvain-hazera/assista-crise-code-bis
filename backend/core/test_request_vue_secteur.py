"""vue_secteur pour les demandes (Request) — même patron que OfferViewSet.vue_secteur (voir
test_vue_secteur.py), plus l'annotation nb_equipes_affectees consommée par
RequestSerializer.get_est_affectee pour le récapitulatif affectée/non affectée de la Vue Ma
Collectivité."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Commune, Institution, InstitutionType, Request, RequestType, Status, Team


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


def _make_request(commune, status=Status.UNPROCESSED, title="Besoin d'aide"):
    rtype, _ = RequestType.objects.get_or_create(type="Aide urgente", defaults={"description": "x"})
    return Request.objects.create(
        title=title, request_type=rtype,
        first_name_request="Jean", last_name_request="Dupont",
        email_request="jean@test.fr", phone_request="0600000000",
        commune_code=commune.code, epci_code=commune.epci_code,
        departement_code=commune.departement_code, region_code=commune.region_code,
        status=status,
    )


def _make_institution(type_code, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=f"Institution {type_code} {commune_code}", type=itype, commune_code=commune_code)


@pytest.mark.django_db
class TestRequestVueSecteur:

    def test_departement_actor_sees_all_communes_of_its_departement(self, create_user, commune_grenoble, commune_voiron):
        institution = _make_institution("SDIS", commune_grenoble.code)
        user = create_user(email="sdis@test.fr", username="sdis@test.fr", type="AUT_LOCALE", institution=institution)
        _make_request(commune_grenoble)
        _make_request(commune_voiron)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("request-vue-secteur"))

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_mairie_sees_only_its_commune(self, create_user, commune_grenoble, commune_voiron):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(email="mairie@test.fr", username="mairie@test.fr", type="AUT_LOCALE", institution=institution)
        _make_request(commune_grenoble)
        _make_request(commune_voiron)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("request-vue-secteur"))

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_region_actor_sees_all(self, create_user, commune_grenoble, commune_voiron):
        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(email="region@test.fr", username="region@test.fr", type="AUT_LOCALE", institution=institution)
        _make_request(commune_grenoble)
        _make_request(commune_voiron)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("request-vue-secteur"))

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_est_affectee_reflects_team_assignment(self, create_user, commune_grenoble):
        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(email="region2@test.fr", username="region2@test.fr", type="AUT_LOCALE", institution=institution)
        non_affectee = _make_request(commune_grenoble, title="Non affectée")
        affectee = _make_request(commune_grenoble, title="Affectée")
        equipe = Team.objects.create(name="Équipe 1")
        equipe.assigned_requests.add(affectee)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("request-vue-secteur"))

        assert response.status_code == 200
        par_titre = {r["title"]: r["est_affectee"] for r in response.data}
        assert par_titre["Non affectée"] is False
        assert par_titre["Affectée"] is True

    def test_status_counts_available_for_recap(self, create_user, commune_grenoble):
        institution = _make_institution("CR", commune_grenoble.code)
        user = create_user(email="region3@test.fr", username="region3@test.fr", type="AUT_LOCALE", institution=institution)
        _make_request(commune_grenoble, status=Status.UNPROCESSED)
        _make_request(commune_grenoble, status=Status.IN_PROGRESS)
        _make_request(commune_grenoble, status=Status.PROCESSED)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("request-vue-secteur"))

        statuts = [r["status"] for r in response.data]
        assert statuts.count(Status.UNPROCESSED) == 1
        assert statuts.count(Status.IN_PROGRESS) == 1
        assert statuts.count(Status.PROCESSED) == 1

    def test_simple_user_forbidden(self, create_user, commune_grenoble):
        institution = _make_institution("MAIRIE", commune_grenoble.code)
        user = create_user(email="simple@test.fr", username="simple@test.fr", type="UTIL_SIMPLE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("request-vue-secteur"))

        assert response.status_code == 403
