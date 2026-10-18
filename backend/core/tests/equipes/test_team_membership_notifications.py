import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Team


@pytest.mark.django_db
class TestTeamCreationNotifiesInitialMembers:
    def test_members_set_at_creation_are_notified(self, create_user):
        creator = create_user(username="createur@test.fr", email="createur@test.fr", type="AUT_LOCALE")
        membre = create_user(username="membre-init@test.fr", email="membre-init@test.fr", type="UTIL_SIMPLE")

        client = APIClient()
        client.force_authenticate(user=creator)
        response = client.post(reverse("team-list"), {
            "name": "Equipe initiale",
            "member_ids": [str(membre.id)],
        })

        assert response.status_code == status.HTTP_201_CREATED
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [membre.email]
        assert "mon-equipe" in mail.outbox[0].body


@pytest.mark.django_db
class TestTeamUpdateNotifiesOnlyNewMembers:
    def test_newly_added_member_is_notified(self, create_user):
        admin = create_user(username="admin-team@test.fr", email="admin-team@test.fr", type="ADMIN")
        deja_membre = create_user(username="deja-membre@test.fr", email="deja-membre@test.fr", type="UTIL_SIMPLE")
        nouveau_membre = create_user(username="nouveau-membre@test.fr", email="nouveau-membre@test.fr", type="UTIL_SIMPLE")

        team = Team.objects.create(name="Equipe existante", description="", color="#3b82f6")
        team.members.add(deja_membre)

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(
            reverse("team-detail", kwargs={"pk": team.id}),
            {"member_ids": [str(deja_membre.id), str(nouveau_membre.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [nouveau_membre.email]
        assert f"mon-equipe%2F{team.id}" in mail.outbox[0].body

    def test_update_without_membership_change_sends_no_email(self, create_user):
        admin = create_user(username="admin-team2@test.fr", email="admin-team2@test.fr", type="ADMIN")
        membre = create_user(username="membre-stable@test.fr", email="membre-stable@test.fr", type="UTIL_SIMPLE")

        team = Team.objects.create(name="Equipe stable", description="", color="#3b82f6")
        team.members.add(membre)

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(
            reverse("team-detail", kwargs={"pk": team.id}),
            {"color": "#ff0000"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 0


@pytest.mark.django_db
class TestMesEquipes:
    def test_returns_only_teams_the_user_belongs_to(self, create_user):
        membre = create_user(username="mes-equipes@test.fr", email="mes-equipes@test.fr", type="UTIL_SIMPLE")
        ma_team = Team.objects.create(name="Mon equipe", description="", color="#3b82f6")
        ma_team.members.add(membre)
        Team.objects.create(name="Autre equipe", description="", color="#ff0000")

        client = APIClient()
        client.force_authenticate(user=membre)
        response = client.get(reverse("team-mes-equipes"))

        assert response.status_code == status.HTTP_200_OK
        team_ids = [row["id"] for row in response.data]
        assert str(ma_team.id) in team_ids
        assert len(team_ids) == 1
