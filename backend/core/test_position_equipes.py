import pytest
from django.urls import reverse
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

    def test_non_institutional_user_cannot_list_positions(self, create_user):
        simple_user = create_user(username="simple-pos@test.fr", email="simple-pos@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.get(reverse("positions_equipes"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
