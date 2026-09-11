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


@pytest.mark.django_db
class TestAssignerCrise:
    """Rattache l'équipe à une crise (Team.assigned_crises) — distinct de lier_point, qui ne
    touche jamais ce champ (voir docstring de l'action) : gap réel trouvé sur une crise démo
    où des équipes liées à des points restaient invisibles des vues scopées par crise."""

    def test_assigns_crisis_additively(self, mairie_client, team):
        from core.models import Crisis
        client, _ = mairie_client
        crise = Crisis.objects.create(name='Crise test assigner', location='POINT (5.72 45.18)')

        response = client.post(reverse('team-assigner-crise', args=[team.id]), {'crise_id': str(crise.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert crise.id in team.assigned_crises.values_list('id', flat=True)

    def test_does_not_wipe_other_assigned_crises(self, mairie_client, team):
        from core.models import Crisis
        client, _ = mairie_client
        crise_1 = Crisis.objects.create(name='Crise test assigner 1', location='POINT (5.72 45.18)')
        crise_2 = Crisis.objects.create(name='Crise test assigner 2', location='POINT (5.72 45.18)')
        team.assigned_crises.add(crise_1)

        response = client.post(reverse('team-assigner-crise', args=[team.id]), {'crise_id': str(crise_2.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        ids = set(team.assigned_crises.values_list('id', flat=True))
        assert ids == {crise_1.id, crise_2.id}

    def test_is_idempotent(self, mairie_client, team):
        from core.models import Crisis
        client, _ = mairie_client
        crise = Crisis.objects.create(name='Crise test assigner idempotent', location='POINT (5.72 45.18)')

        client.post(reverse('team-assigner-crise', args=[team.id]), {'crise_id': str(crise.id)}, format='json')
        response = client.post(reverse('team-assigner-crise', args=[team.id]), {'crise_id': str(crise.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team.assigned_crises.count() == 1

    def test_rejects_unknown_crisis(self, mairie_client, team):
        client, _ = mairie_client
        response = client.post(
            reverse('team-assigner-crise', args=[team.id]),
            {'crise_id': '00000000-0000-0000-0000-000000000000'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_requires_own_institution(self, create_user, other_team):
        from core.models import Crisis
        outsider = create_user(username='outsider-assigner@test.fr', email='outsider-assigner@test.fr', type='AUT_LOCALE')
        client = APIClient()
        client.force_authenticate(user=outsider)
        crise = Crisis.objects.create(name='Crise test assigner interdit', location='POINT (5.72 45.18)')

        response = client.post(reverse('team-assigner-crise', args=[other_team.id]), {'crise_id': str(crise.id)}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
