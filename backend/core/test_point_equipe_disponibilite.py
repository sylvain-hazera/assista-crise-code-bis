import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    DisponibilitePointEquipe,
    PointOperationnel,
    PointType,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise point equipe test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def point_type(db):
    return PointType.objects.create(code="COLLECTE_EQUIPE_TEST", libelle="Point de collecte test")


@pytest.fixture
def team_with_member(create_user):
    leader = create_user(username="leader-point@test.fr", email="leader-point@test.fr", type="UTIL_SIMPLE")
    membre = create_user(username="membre-point@test.fr", email="membre-point@test.fr", type="UTIL_SIMPLE")
    team = Team.objects.create(name="Equipe point test", description="", color="#3b82f6", leader=leader)
    team.members.add(leader, membre)
    return team, leader, membre


@pytest.fixture
def point_with_team(crisis, point_type, team_with_member):
    team, _, _ = team_with_member
    return PointOperationnel.objects.create(nom="Point avec equipe", type=point_type, crise=crisis, equipe=team)


@pytest.mark.django_db
class TestPointEquipeAction:

    def test_equipe_action_returns_members_and_dispos(self, point_with_team, team_with_member):
        _, leader, membre = team_with_member
        DisponibilitePointEquipe.objects.create(point=point_with_team, membre=membre, date="2026-09-01", creneau="MATIN")

        client = APIClient()
        client.force_authenticate(user=leader)
        response = client.get(reverse('pointoperationnel-equipe', args=[point_with_team.id]))

        assert response.status_code == status.HTTP_200_OK
        emails = {m["email"] for m in response.data["membres"]}
        assert emails == {"leader-point@test.fr", "membre-point@test.fr"}
        assert len(response.data["disponibilites"]) == 1

    def test_equipe_action_empty_when_no_team(self, crisis, point_type, create_user):
        point = PointOperationnel.objects.create(nom="Point sans equipe", type=point_type, crise=crisis)
        user = create_user(username="qq-point-eq@test.fr", email="qq-point-eq@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('pointoperationnel-equipe', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"membres": [], "disponibilites": []}


@pytest.mark.django_db
class TestDisponibilitePointEquipe:

    def test_member_can_declare_own_availability(self, point_with_team, team_with_member):
        _, _, membre = team_with_member
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.post(
            reverse('disponibilitepointequipe-list'),
            {"point": str(point_with_team.id), "membre": str(membre.id), "date": "2026-09-01", "creneau": "MATIN"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_leader_can_declare_for_another_member(self, point_with_team, team_with_member):
        _, leader, membre = team_with_member
        client = APIClient()
        client.force_authenticate(user=leader)

        response = client.post(
            reverse('disponibilitepointequipe-list'),
            {"point": str(point_with_team.id), "membre": str(membre.id), "date": "2026-09-02", "creneau": "SOIR"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_unrelated_user_cannot_declare_for_member(self, point_with_team, team_with_member, create_user):
        _, _, membre = team_with_member
        autre = create_user(username="autre-dispo-point@test.fr", email="autre-dispo-point@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=autre)

        response = client.post(
            reverse('disponibilitepointequipe-list'),
            {"point": str(point_with_team.id), "membre": str(membre.id), "date": "2026-09-03", "creneau": "MIDI"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_member_cannot_be_declared_available(self, point_with_team, team_with_member, create_user):
        team, leader, _ = team_with_member
        non_member = create_user(username="non-membre-point@test.fr", email="non-membre-point@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=leader)

        response = client.post(
            reverse('disponibilitepointequipe-list'),
            {"point": str(point_with_team.id), "membre": str(non_member.id), "date": "2026-09-01", "creneau": "NUIT"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "membre" in response.data

    def test_duplicate_slot_rejected(self, point_with_team, team_with_member):
        _, _, membre = team_with_member
        DisponibilitePointEquipe.objects.create(point=point_with_team, membre=membre, date="2026-09-01", creneau="MATIN")
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.post(
            reverse('disponibilitepointequipe-list'),
            {"point": str(point_with_team.id), "membre": str(membre.id), "date": "2026-09-01", "creneau": "MATIN"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_blocked_on_closed_crisis(self, point_with_team, team_with_member, crisis):
        _, _, membre = team_with_member
        crisis.end_date = timezone.now()
        crisis.save()
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.post(
            reverse('disponibilitepointequipe-list'),
            {"point": str(point_with_team.id), "membre": str(membre.id), "date": "2026-09-01", "creneau": "MATIN"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_can_delete_own_availability(self, point_with_team, team_with_member):
        _, _, membre = team_with_member
        dispo = DisponibilitePointEquipe.objects.create(point=point_with_team, membre=membre, date="2026-09-01", creneau="MATIN")
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.delete(reverse('disponibilitepointequipe-detail', args=[dispo.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_unrelated_user_cannot_delete(self, point_with_team, team_with_member, create_user):
        _, _, membre = team_with_member
        dispo = DisponibilitePointEquipe.objects.create(point=point_with_team, membre=membre, date="2026-09-01", creneau="MATIN")
        autre = create_user(username="autre-del-dispo@test.fr", email="autre-del-dispo@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=autre)

        response = client.delete(reverse('disponibilitepointequipe-detail', args=[dispo.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert DisponibilitePointEquipe.objects.filter(id=dispo.id).exists()
