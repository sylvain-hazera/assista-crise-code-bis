import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Competence,
    Crisis,
    DelegationCompetence,
    ImplicationInstitution,
    Institution,
    InstitutionType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise delegation secteur", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def mairie(db):
    itype = InstitutionType.objects.create(code="MAIRIE_DELEG_SECTEUR_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie delegation secteur test", type=itype)


@pytest.fixture
def association(db):
    itype = InstitutionType.objects.create(code="ASSO_DELEG_SECTEUR_TEST", libelle="Association")
    return Institution.objects.create(nom="Association delegation secteur test", type=itype)


@pytest.fixture
def competence(db):
    return Competence.objects.create(nom="Competence delegation secteur test")


@pytest.fixture
def mairie_client(create_user, crisis, mairie):
    user = create_user(username="mairie-deleg-secteur@test.fr", email="mairie-deleg-secteur@test.fr", type="AUT_LOCALE")
    ImplicationInstitution.objects.create(
        crise=crisis, institution=mairie, type_implication="ACTEUR",
        responsable=user, actif=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestDelegationCompetenceSecteur:

    def test_create_with_departements(self, mairie_client, crisis, mairie, association, competence):
        client, _ = mairie_client
        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
                "departements": ["38", "73"],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["departements"] == ["38", "73"]

    def test_create_with_communes(self, mairie_client, crisis, mairie, association, competence):
        client, _ = mairie_client
        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
                "communes": ["38185"],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["communes"] == ["38185"]

    def test_create_without_secteur_covers_whole_crisis(self, mairie_client, crisis, mairie, association, competence):
        client, _ = mairie_client
        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["departements"] == []
        assert response.data["communes"] == []
        assert response.data["zone_precise"] is None

    def test_unicity_still_enforced_regardless_of_secteur(self, mairie_client, crisis, mairie, association, competence):
        client, _ = mairie_client
        DelegationCompetence.objects.create(
            institution_source=mairie, institution_cible=association,
            competence=competence, crise=crisis, departements=["38"],
        )
        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
                "departements": ["73"],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_institution_source_not_implicated_is_rejected(self, create_user, crisis, mairie, association, competence):
        # `mairie` n'a ici aucune ImplicationInstitution sur `crisis` (contrairement à la
        # fixture mairie_client) : la délégation ne doit pas être acceptée.
        user = create_user(username="tiers-deleg-secteur@test.fr", email="tiers-deleg-secteur@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "institution_source" in response.data

    def test_non_institutional_user_cannot_create(self, create_user, crisis, mairie, association, competence):
        user = create_user(username="simple-deleg-secteur@test.fr", email="simple-deleg-secteur@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
            },
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_blocked_on_closed_crisis(self, mairie_client, crisis, mairie, association, competence):
        from django.utils import timezone
        crisis.end_date = timezone.now()
        crisis.save()
        client, _ = mairie_client

        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(mairie.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
