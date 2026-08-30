import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis, Institution, InstitutionType, MaterielCatalogue


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="env-institution@test.fr", email="env-institution@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _get(client, url, environment=None):
    headers = {"HTTP_X_ENVIRONMENT": environment} if environment else {}
    return client.get(url, **headers)


def _post(client, url, data, environment=None):
    headers = {"HTTP_X_ENVIRONMENT": environment} if environment else {}
    return client.post(url, data, format='json', **headers)


@pytest.mark.django_db
class TestCrisisEnvironmentIsolation:

    def test_crisis_created_in_prod_defaults_to_prod(self, institutional_client):
        client, _ = institutional_client
        response = _post(client, reverse('crisis-list'), {
            "name": "Crise env prod test", "type": "INCENDIE",
            "location": '{"type": "Point", "coordinates": [5.72, 45.18]}',
        })
        assert response.status_code == status.HTTP_201_CREATED
        crisis = Crisis.objects.get(id=response.data["id"])
        assert crisis.environment == "PROD"

    def test_crisis_created_in_demo_is_tagged_demo(self, institutional_client):
        client, user = institutional_client
        user.demo_role = "AUT_LOCALE"
        user.save()
        response = _post(client, reverse('crisis-list'), {
            "name": "Crise env demo test", "type": "INCENDIE",
            "location": '{"type": "Point", "coordinates": [5.72, 45.18]}',
        }, environment="DEMO")
        assert response.status_code == status.HTTP_201_CREATED
        crisis = Crisis.objects.get(id=response.data["id"])
        assert crisis.environment == "DEMO"

    def test_demo_crisis_invisible_in_prod_and_vice_versa(self, institutional_client):
        client, user = institutional_client
        user.demo_role = "AUT_LOCALE"
        user.save()

        prod_crisis = Crisis.objects.create(
            name="Crise prod isolation", type="INCENDIE", location="POINT (5.72 45.18)", environment="PROD",
        )
        demo_crisis = Crisis.objects.create(
            name="Crise demo isolation", type="INCENDIE", location="POINT (5.72 45.18)", environment="DEMO",
        )

        prod_ids = {c["id"] for c in _get(client, reverse('crisis-list')).data}
        demo_ids = {c["id"] for c in _get(client, reverse('crisis-list'), environment="DEMO").data}

        assert str(prod_crisis.id) in prod_ids
        assert str(demo_crisis.id) not in prod_ids
        assert str(demo_crisis.id) in demo_ids
        assert str(prod_crisis.id) not in demo_ids


@pytest.mark.django_db
class TestEffectiveRoleGating:

    def test_demo_header_without_demo_role_is_rejected(self, create_user):
        user = create_user(username="no-demo-access@test.fr", email="no-demo-access@test.fr", type="ADMIN")
        assert user.demo_role is None
        client = APIClient()
        client.force_authenticate(user=user)
        crisis = Crisis.objects.create(name="Crise gating test", type="INCENDIE", location="POINT (5.72 45.18)")

        response = _post(client, reverse('crisis-reouvrir', args=[crisis.id]), {}, environment="DEMO")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_role_differs_between_prod_and_demo_for_same_user(self, create_user):
        user = create_user(
            username="dual-role@test.fr", email="dual-role@test.fr", type="UTIL_SIMPLE", demo_role="ADMIN",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        prod_crisis = Crisis.objects.create(
            name="Crise dual role prod", type="INCENDIE", location="POINT (5.72 45.18)",
            environment="PROD", end_date=timezone.now(),
        )
        demo_crisis = Crisis.objects.create(
            name="Crise dual role demo", type="INCENDIE", location="POINT (5.72 45.18)",
            environment="DEMO", end_date=timezone.now(),
        )

        # UTIL_SIMPLE en prod : pas admin, donc refusé sur SA propre crise prod.
        prod_response = _post(client, reverse('crisis-reouvrir', args=[prod_crisis.id]), {})
        assert prod_response.status_code == status.HTTP_403_FORBIDDEN

        # ADMIN en démo : autorisé sur la crise démo correspondante.
        demo_response = _post(client, reverse('crisis-reouvrir', args=[demo_crisis.id]), {}, environment="DEMO")
        assert demo_response.status_code == status.HTTP_200_OK

    def test_invalid_environment_header_rejected(self, institutional_client):
        client, _ = institutional_client
        response = _get(client, reverse('crisis-list'), environment="STAGING")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestInstitutionAsymmetricVisibility:

    def test_prod_institution_visible_from_demo(self, institutional_client):
        client, user = institutional_client
        user.demo_role = "AUT_LOCALE"
        user.save()
        itype = InstitutionType.objects.create(code="MAIRIE_ENV_TEST", libelle="Mairie")
        prod_institution = Institution.objects.create(nom="Vraie mairie", type=itype, environment="PROD")

        response = _get(client, reverse('institution-list'), environment="DEMO")

        ids = {i["id"] for i in response.data}
        assert str(prod_institution.id) in ids

    def test_demo_institution_invisible_from_prod(self, institutional_client):
        client, user = institutional_client
        user.demo_role = "AUT_LOCALE"
        user.save()
        itype = InstitutionType.objects.create(code="ASSO_ENV_TEST", libelle="Association")
        demo_institution = Institution.objects.create(nom="Fausse asso demo", type=itype, environment="DEMO")

        response = _get(client, reverse('institution-list'))

        ids = {i["id"] for i in response.data}
        assert str(demo_institution.id) not in ids

    def test_institution_created_in_demo_is_tagged_demo(self, institutional_client):
        client, user = institutional_client
        user.demo_role = "AUT_LOCALE"
        user.save()
        itype = InstitutionType.objects.create(code="ENTREPRISE_ENV_TEST", libelle="Entreprise")

        response = _post(client, reverse('institution-list'), {
            "nom": "Institution créée en démo", "type": str(itype.id),
        }, environment="DEMO")

        assert response.status_code == status.HTTP_201_CREATED
        institution = Institution.objects.get(id=response.data["id"])
        assert institution.environment == "DEMO"


@pytest.mark.django_db
class TestSharedVocabularyNotIsolated:

    def test_materiel_catalogue_identical_in_both_environments(self, institutional_client):
        client, user = institutional_client
        user.demo_role = "AUT_LOCALE"
        user.save()
        item = MaterielCatalogue.objects.create(nom="Item vocabulaire partagé test")

        prod_names = {i["nom"] for i in _get(client, reverse('materielcatalogue-list')).data}
        demo_names = {i["nom"] for i in _get(client, reverse('materielcatalogue-list'), environment="DEMO").data}

        assert item.nom in prod_names
        assert item.nom in demo_names
