import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis, Dossier, DossierParticipant, Request, Team, RequestType


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise déblaiement", type="INCENDIE", location=Point(5.72, 45.18, srid=4326))


@pytest.fixture
def request_type(db):
    return RequestType.objects.create(type="Nettoyage / déblaiement test")


def _make_dossier(crisis, equipe, **kwargs):
    defaults = dict(
        numero=f"DOS-{Dossier.objects.count()}",
        crise=crisis, equipe=equipe, titre="Maison à déblayer", description="",
    )
    defaults.update(kwargs)
    return Dossier.objects.create(**defaults)


@pytest.mark.django_db
class TestChefEquipeVoitTousLesDossiers:
    def test_leader_sees_dossiers_without_being_participant(self, create_user, crisis):
        chef = create_user(username="chef-terrain@test.fr", email="chef-terrain@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 1", leader=chef)
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.get(reverse("dossier-detail", args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK

    def test_regulateur_sees_dossiers_across_teams(self, create_user, crisis):
        chef = create_user(username="regul-terrain@test.fr", email="regul-terrain@test.fr", type="UTIL_SIMPLE")
        team_a = Team.objects.create(name="Equipe A", regulateur=chef)
        team_b = Team.objects.create(name="Equipe B", regulateur=chef)
        d1 = _make_dossier(crisis, team_a)
        d2 = _make_dossier(crisis, team_b)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.get(reverse("dossier-list"))

        ids = [row["id"] for row in response.data]
        assert str(d1.id) in ids
        assert str(d2.id) in ids

    def test_unrelated_user_does_not_see_dossier(self, create_user, crisis):
        chef = create_user(username="chef2@test.fr", email="chef2@test.fr", type="UTIL_SIMPLE")
        unrelated = create_user(username="sans-lien2@test.fr", email="sans-lien2@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 2", leader=chef)
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=unrelated)
        response = client.get(reverse("dossier-detail", args=[dossier.id]))

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestDefinirPriorite:
    def test_team_leader_can_set_priority_and_order(self, create_user, crisis):
        chef = create_user(username="chef3@test.fr", email="chef3@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 3", leader=chef)
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.post(
            reverse("dossier-definir-priorite", args=[dossier.id]),
            {"priorite": "URGENTE", "ordre": 1},
        )

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.priorite == "URGENTE"
        assert dossier.ordre == 1

    def test_team_regulateur_can_set_priority(self, create_user, crisis):
        regulateur = create_user(username="regul2@test.fr", email="regul2@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 4", regulateur=regulateur)
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=regulateur)
        response = client.post(
            reverse("dossier-definir-priorite", args=[dossier.id]),
            {"priorite": "BASSE"},
        )

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.priorite == "BASSE"

    def test_plain_member_cannot_set_priority(self, create_user, crisis):
        chef = create_user(username="chef4@test.fr", email="chef4@test.fr", type="UTIL_SIMPLE")
        membre = create_user(username="membre4@test.fr", email="membre4@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 5", leader=chef)
        team.members.add(membre)
        dossier = _make_dossier(crisis, team)
        DossierParticipant.objects.create(dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE)

        client = APIClient()
        client.force_authenticate(user=membre)
        response = client.post(
            reverse("dossier-definir-priorite", args=[dossier.id]),
            {"priorite": "URGENTE"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        dossier.refresh_from_db()
        assert dossier.priorite == "NORMALE"

    def test_invalid_priority_is_rejected(self, create_user, crisis):
        chef = create_user(username="chef5@test.fr", email="chef5@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 6", leader=chef)
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.post(
            reverse("dossier-definir-priorite", args=[dossier.id]),
            {"priorite": "PAS_UNE_VRAIE_PRIORITE"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_institutional_actor_can_always_set_priority(self, authenticated_client, crisis):
        client, admin = authenticated_client
        admin.type = "ADMIN"
        admin.save()
        team = Team.objects.create(name="Equipe 7")
        dossier = _make_dossier(crisis, team)

        response = client.post(
            reverse("dossier-definir-priorite", args=[dossier.id]),
            {"priorite": "URGENTE", "ordre": 5},
        )

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestDossierContactEtCommune:
    def test_contact_fields_come_from_demande(self, create_user, crisis, request_type):
        chef = create_user(username="chef8@test.fr", email="chef8@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 11", leader=chef)
        demande = Request.objects.create(
            title="Besoin", location=Point(5.72, 45.18, srid=4326),
            first_name_request="Jean", last_name_request="Dupont",
            email_request="jean.dupont@test.fr", phone_request="0601020304",
            crisis=crisis, request_type=request_type,
        )
        dossier = _make_dossier(crisis, team, demande=demande)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.get(reverse("dossier-detail", args=[dossier.id]))

        assert response.data["contact_nom"] == "Jean Dupont"
        assert response.data["contact_email"] == "jean.dupont@test.fr"
        assert response.data["contact_telephone"] == "0601020304"

    def test_contact_fields_masked_in_demo(self, create_user, crisis, request_type):
        chef = create_user(username="chef9@test.fr", email="chef9@test.fr", type="UTIL_SIMPLE", demo_role="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 12", leader=chef, environment="DEMO")
        demande = Request.objects.create(
            title="Besoin", location=Point(5.72, 45.18, srid=4326),
            first_name_request="Jean", last_name_request="Dupont",
            email_request="jean.dupont@test.fr", phone_request="0601020304",
            crisis=crisis, request_type=request_type, environment="DEMO",
        )
        dossier = _make_dossier(crisis, team, demande=demande, environment="DEMO")

        client = APIClient()
        client.force_authenticate(user=chef)
        client.credentials(HTTP_X_ENVIRONMENT="DEMO")
        response = client.get(reverse("dossier-detail", args=[dossier.id]))

        assert response.data["contact_email"] != "jean.dupont@test.fr"
        assert response.data["contact_telephone"] != "0601020304"


@pytest.mark.django_db
class TestMesEquipesInclutChefEtRegulateur:
    def test_leader_appears_in_mes_equipes(self, create_user):
        chef = create_user(username="chef6@test.fr", email="chef6@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe 8", leader=chef)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.get(reverse("team-mes-equipes"))

        names = [row["name"] for row in response.data]
        assert "Equipe 8" in names

    def test_regulateur_of_multiple_teams_sees_all(self, create_user):
        chef = create_user(username="chef7@test.fr", email="chef7@test.fr", type="UTIL_SIMPLE")
        team_a = Team.objects.create(name="Equipe 9", regulateur=chef)
        team_b = Team.objects.create(name="Equipe 10", regulateur=chef)

        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.get(reverse("team-mes-equipes"))

        names = {row["name"] for row in response.data}
        assert {"Equipe 9", "Equipe 10"}.issubset(names)
