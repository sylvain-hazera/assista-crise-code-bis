import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis, PointOperationnel, PointType, RegistrePresence, Team


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise registre test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def responsable(create_user):
    return create_user(username="resp-registre@test.fr", email="resp-registre@test.fr", type="AUT_LOCALE")


@pytest.fixture
def point(crisis, responsable):
    point_type = PointType.objects.create(code="ACCUEIL_REGISTRE_TEST", libelle="Centre d'accueil test")
    return PointOperationnel.objects.create(nom="Centre registre test", type=point_type, crise=crisis, responsable=responsable)


@pytest.fixture
def responsable_client(responsable):
    client = APIClient()
    client.force_authenticate(user=responsable)
    return client, responsable


@pytest.mark.django_db
class TestRegistrePresenceCrud:

    def test_create_entree(self, responsable_client, point):
        client, user = responsable_client
        response = client.post(
            reverse('registrepresence-list'),
            {"point": str(point.id), "type_personne": "EVACUE", "nom": "Famille Martin", "nombre": 4},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["type_personne_libelle"] == "Personne évacuée"
        assert response.data["enregistre_par_nom"]
        assert response.data["date_depart"] is None

    def test_unrelated_user_cannot_create(self, create_user, point):
        user = create_user(username="tiers-registre@test.fr", email="tiers-registre@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('registrepresence-list'),
            {"point": str(point.id), "type_personne": "POMPIER"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_team_member_can_create(self, create_user, point):
        member = create_user(username="membre-registre@test.fr", email="membre-registre@test.fr", type="AUT_LOCALE")
        team = Team.objects.create(name="Equipe registre test")
        team.members.add(member)
        point.equipe = team
        point.save()

        client = APIClient()
        client.force_authenticate(user=member)
        response = client.post(
            reverse('registrepresence-list'),
            {"point": str(point.id), "type_personne": "BENEVOLE_AUTRE_EQUIPE"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_blocked_on_closed_crisis(self, responsable_client, point, crisis):
        client, _ = responsable_client
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.post(
            reverse('registrepresence-list'),
            {"point": str(point.id), "type_personne": "AUTRE"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestRegistrePresenceSortie:

    def test_sortie_sets_date_depart(self, responsable_client, point):
        client, _ = responsable_client
        entree = RegistrePresence.objects.create(point=point, type_personne="POMPIER")

        response = client.post(reverse('registrepresence-sortie', args=[entree.id]))

        assert response.status_code == status.HTTP_200_OK
        entree.refresh_from_db()
        assert entree.date_depart is not None

    def test_sortie_twice_rejected(self, responsable_client, point):
        client, _ = responsable_client
        entree = RegistrePresence.objects.create(point=point, type_personne="POMPIER", date_depart=timezone.now())

        response = client.post(reverse('registrepresence-sortie', args=[entree.id]))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unrelated_user_cannot_mark_sortie(self, create_user, point):
        entree = RegistrePresence.objects.create(point=point, type_personne="POMPIER")
        user = create_user(username="tiers-sortie@test.fr", email="tiers-sortie@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('registrepresence-sortie', args=[entree.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPersonnesPresentes:

    def test_counts_only_present(self, responsable_client, point):
        client, _ = responsable_client
        RegistrePresence.objects.create(point=point, type_personne="EVACUE", nombre=4)
        RegistrePresence.objects.create(point=point, type_personne="POMPIER", nombre=2, date_depart=timezone.now())

        response = client.get(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["personnes_presentes"] == 4

    def test_zero_when_empty(self, responsable_client, point):
        client, _ = responsable_client

        response = client.get(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.data["personnes_presentes"] == 0
