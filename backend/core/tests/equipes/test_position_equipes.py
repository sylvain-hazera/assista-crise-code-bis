import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import DernierePositionUtilisateur, Team


@pytest.mark.django_db
class TestMaPosition:
    def test_authenticated_user_can_report_own_position(self, create_user):
        user = create_user(username="terrain@test.fr", email="terrain@test.fr", type="SECOURS")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["latitude"] == pytest.approx(45.19)
        assert response.data["longitude"] == pytest.approx(5.72)
        assert DernierePositionUtilisateur.objects.filter(utilisateur=user).count() == 1

    def test_second_report_updates_instead_of_duplicating(self, create_user):
        user = create_user(username="terrain2@test.fr", email="terrain2@test.fr", type="SECOURS")
        client = APIClient()
        client.force_authenticate(user=user)

        client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})
        response = client.post(reverse("ma_position"), {"latitude": 45.20, "longitude": 5.73})

        assert response.status_code == status.HTTP_200_OK
        assert DernierePositionUtilisateur.objects.filter(utilisateur=user).count() == 1
        position = DernierePositionUtilisateur.objects.get(utilisateur=user)
        assert position.location.y == pytest.approx(45.20)
        assert position.location.x == pytest.approx(5.73)

    def test_anonymous_cannot_report_position(self):
        client = APIClient()
        response = client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_invalid_coordinates_are_rejected(self, create_user):
        user = create_user(username="terrain3@test.fr", email="terrain3@test.fr", type="SECOURS")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse("ma_position"), {"latitude": "pas-un-nombre", "longitude": 5.72})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert DernierePositionUtilisateur.objects.count() == 0

    def test_prod_and_demo_positions_are_kept_separate(self, create_user):
        user = create_user(username="terrain4@test.fr", email="terrain4@test.fr", type="SECOURS")
        client = APIClient()
        client.force_authenticate(user=user)

        client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})
        client.credentials(HTTP_X_ENVIRONMENT="DEMO")
        client.post(reverse("ma_position"), {"latitude": 48.85, "longitude": 2.35})

        assert DernierePositionUtilisateur.objects.filter(utilisateur=user).count() == 2


@pytest.mark.django_db
class TestPositionsEquipes:
    def test_institutional_actor_sees_positions_of_team_members_only(self, create_user):
        regulateur = create_user(username="regul-pos@test.fr", email="regul-pos@test.fr", type="AUT_LOCALE")
        membre_equipe = create_user(username="membre-equipe@test.fr", email="membre-equipe@test.fr", type="SECOURS")
        hors_equipe = create_user(username="hors-equipe@test.fr", email="hors-equipe@test.fr", type="SECOURS")

        team = Team.objects.create(name="Equipe terrain", description="", color="#3b82f6")
        team.members.add(membre_equipe)

        client = APIClient()
        client.force_authenticate(user=membre_equipe)
        client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})

        client.force_authenticate(user=hors_equipe)
        client.post(reverse("ma_position"), {"latitude": 43.6, "longitude": 1.44})

        client.force_authenticate(user=regulateur)
        response = client.get(reverse("positions_equipes"))

        assert response.status_code == status.HTTP_200_OK
        utilisateur_ids = [str(row["utilisateur"]) for row in response.data]
        assert str(membre_equipe.id) in utilisateur_ids
        assert str(hors_equipe.id) not in utilisateur_ids

    def test_user_with_no_team_sees_no_positions(self, create_user):
        simple_user = create_user(username="simple-pos@test.fr", email="simple-pos@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.get(reverse("positions_equipes"))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    def test_anonymous_cannot_list_positions(self):
        client = APIClient()
        response = client.get(reverse("positions_equipes"))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_team_member_sees_only_own_team_positions(self, create_user):
        membre_a = create_user(username="membre-a@test.fr", email="membre-a@test.fr", type="UTIL_SIMPLE")
        membre_b = create_user(username="membre-b@test.fr", email="membre-b@test.fr", type="UTIL_SIMPLE")
        autre_equipe_membre = create_user(username="autre-equipe@test.fr", email="autre-equipe@test.fr", type="UTIL_SIMPLE")

        team_a = Team.objects.create(name="Equipe A", description="", color="#3b82f6")
        team_a.members.add(membre_a, membre_b)
        team_b = Team.objects.create(name="Equipe B", description="", color="#ff0000")
        team_b.members.add(autre_equipe_membre)

        client = APIClient()
        client.force_authenticate(user=membre_a)
        client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})
        client.force_authenticate(user=membre_b)
        client.post(reverse("ma_position"), {"latitude": 45.20, "longitude": 5.73})
        client.force_authenticate(user=autre_equipe_membre)
        client.post(reverse("ma_position"), {"latitude": 43.6, "longitude": 1.44})

        client.force_authenticate(user=membre_a)
        response = client.get(reverse("positions_equipes"))

        assert response.status_code == status.HTTP_200_OK
        utilisateur_ids = [str(row["utilisateur"]) for row in response.data]
        assert str(membre_a.id) in utilisateur_ids
        assert str(membre_b.id) in utilisateur_ids
        assert str(autre_equipe_membre.id) not in utilisateur_ids

    def test_stale_position_is_excluded(self, create_user):
        # horodatage a `auto_now=True` : on la recule via .update() (bypass save()) plutôt que
        # de la passer à la création, qui serait de toute façon écrasée par now().
        admin = create_user(username="admin-pos-ttl@test.fr", email="admin-pos-ttl@test.fr", type="ADMIN")
        frais = create_user(username="frais-pos@test.fr", email="frais-pos@test.fr", type="SECOURS")
        perime = create_user(username="perime-pos@test.fr", email="perime-pos@test.fr", type="SECOURS")

        team = Team.objects.create(name="Equipe TTL", description="", color="#3b82f6")
        team.members.add(frais, perime)

        client = APIClient()
        client.force_authenticate(user=frais)
        client.post(reverse("ma_position"), {"latitude": 45.19, "longitude": 5.72})
        client.force_authenticate(user=perime)
        client.post(reverse("ma_position"), {"latitude": 43.6, "longitude": 1.44})

        DernierePositionUtilisateur.objects.filter(utilisateur=perime).update(
            horodatage=timezone.now() - datetime.timedelta(hours=4)
        )

        client.force_authenticate(user=admin)
        response = client.get(reverse("positions_equipes"))

        assert response.status_code == status.HTTP_200_OK
        utilisateur_ids = [str(row["utilisateur"]) for row in response.data]
        assert str(frais.id) in utilisateur_ids
        assert str(perime.id) not in utilisateur_ids
