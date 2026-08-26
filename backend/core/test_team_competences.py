import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import AffectationCompetence, AuditLog, Competence, Crisis, Team


@pytest.fixture
def competence(db):
    return Competence.objects.create(nom="Compétence équipe test")


@pytest.fixture
def team(db):
    return Team.objects.create(name="Equipe thèmes test", description="", color="#3b82f6")


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise affectation test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="institution-affectation@test.fr", email="institution-affectation@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestTeamCompetences:

    def test_competence_ids_readable_and_writable(self, institutional_client, team, competence):
        client, _ = institutional_client

        response = client.patch(
            reverse('team-detail', args=[team.id]),
            {"competence_ids": [str(competence.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["competence_ids"] == [competence.id] or [str(x) for x in response.data["competence_ids"]] == [str(competence.id)]
        team.refresh_from_db()
        assert list(team.competences.all()) == [competence]


@pytest.mark.django_db
class TestAffectationCompetencePermissions:

    def test_institutional_actor_can_create(self, institutional_client, crisis, competence, team):
        client, _ = institutional_client

        response = client.post(
            reverse('affectationcompetence-list'),
            {"crise": str(crisis.id), "competence": str(competence.id), "equipe": str(team.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert AuditLog.objects.filter(objet_type="AffectationCompetence", action__code="AFFECTATION").exists()

    def test_simple_user_cannot_create(self, create_user, crisis, competence, team):
        outsider = create_user(username="simple-affectation-comp@test.fr", email="simple-affectation-comp@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.post(
            reverse('affectationcompetence-list'),
            {"crise": str(crisis.id), "competence": str(competence.id), "equipe": str(team.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_update_logs_modification(self, institutional_client, crisis, competence, team):
        client, _ = institutional_client
        affectation = AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team, active=True)

        response = client.patch(
            reverse('affectationcompetence-detail', args=[affectation.id]),
            {"active": False},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert AuditLog.objects.filter(objet_type="AffectationCompetence", action__code="MODIFICATION").exists()
