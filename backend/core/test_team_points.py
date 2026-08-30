import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Institution, InstitutionType, PointOperationnel, PointType, Team,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_TEAM_POINTS', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test points équipe', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution():
    return _make_institution()


@pytest.fixture
def team(institution):
    return Team.objects.create(name='Équipe points test', institution=institution)


@pytest.fixture
def other_team(institution):
    return Team.objects.create(name='Autre équipe points test', institution=institution)


@pytest.fixture
def point_type_regroupement():
    ptype, _ = PointType.objects.get_or_create(
        code='REGROUPEMENT_MOYENS', defaults={'libelle': 'Point de regroupement des moyens'},
    )
    return ptype


@pytest.fixture
def mairie_client(create_user, institution):
    user = create_user(username='mairie-points@test.fr', email='mairie-points@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestLierPoint:

    def test_links_unassigned_point(self, mairie_client, team, point_type_regroupement):
        client, _ = mairie_client
        point = PointOperationnel.objects.create(nom='Point libre', type=point_type_regroupement)

        response = client.post(reverse('team-lier-point', args=[team.id]), {'point_id': str(point.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        point.refresh_from_db()
        assert point.equipe_id == team.id

    def test_rejects_point_already_linked_to_another_team(self, mairie_client, team, other_team, point_type_regroupement):
        client, _ = mairie_client
        point = PointOperationnel.objects.create(nom='Point pris', type=point_type_regroupement, equipe=other_team)

        response = client.post(reverse('team-lier-point', args=[team.id]), {'point_id': str(point.id)}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        point.refresh_from_db()
        assert point.equipe_id == other_team.id

    def test_relinking_same_team_is_idempotent(self, mairie_client, team, point_type_regroupement):
        client, _ = mairie_client
        point = PointOperationnel.objects.create(nom='Point déjà lié', type=point_type_regroupement, equipe=team)

        response = client.post(reverse('team-lier-point', args=[team.id]), {'point_id': str(point.id)}, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_rejects_unknown_point(self, mairie_client, team):
        client, _ = mairie_client
        response = client.post(
            reverse('team-lier-point', args=[team.id]),
            {'point_id': '00000000-0000-0000-0000-000000000000'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestDelierPoint:

    def test_unlinks_point(self, mairie_client, team, point_type_regroupement):
        client, _ = mairie_client
        point = PointOperationnel.objects.create(nom='Point à délier', type=point_type_regroupement, equipe=team)

        response = client.post(reverse('team-delier-point', args=[team.id]), {'point_id': str(point.id)}, format='json')

        assert response.status_code == status.HTTP_204_NO_CONTENT
        point.refresh_from_db()
        assert point.equipe_id is None

    def test_rejects_point_linked_to_a_different_team(self, mairie_client, team, other_team, point_type_regroupement):
        client, _ = mairie_client
        point = PointOperationnel.objects.create(nom='Point autre équipe', type=point_type_regroupement, equipe=other_team)

        response = client.post(reverse('team-delier-point', args=[team.id]), {'point_id': str(point.id)}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        point.refresh_from_db()
        assert point.equipe_id == other_team.id
