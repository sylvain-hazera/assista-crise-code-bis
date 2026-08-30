import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Team


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_HIERARCHIE', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test hiérarchie', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution():
    return _make_institution()


@pytest.fixture
def other_institution():
    return _make_institution(nom='Autre mairie hiérarchie')


@pytest.fixture
def team_a(institution):
    return Team.objects.create(name='Équipe secteur A', institution=institution)


@pytest.fixture
def team_b(institution):
    return Team.objects.create(name='Équipe entreprise B', institution=institution)


@pytest.fixture
def team_c(institution):
    return Team.objects.create(name='Équipe association C', institution=institution)


@pytest.fixture
def team_cross_institution(other_institution):
    # Institution différente de team_a — cas d'usage central : une entreprise privée sans
    # aucun lien avec la mairie A doit pouvoir rejoindre son équipe de secteur.
    return Team.objects.create(name='Équipe entreprise cross-institution', institution=other_institution)


@pytest.fixture
def mairie_client(create_user, institution):
    user = create_user(username='mairie-hierarchie@test.fr', email='mairie-hierarchie@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestRattacherEquipe:

    def test_attaches_across_institutions(self, mairie_client, team_a, team_cross_institution):
        client, _ = mairie_client
        response = client.post(
            reverse('team-rattacher-equipe', args=[team_a.id]),
            {'equipe_id': str(team_cross_institution.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team_cross_institution.refresh_from_db()
        assert team_cross_institution.equipe_parente_id == team_a.id
        assert team_a.sous_equipes.filter(id=team_cross_institution.id).exists()

    def test_rejects_self_attach(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(
            reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_a.id)}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_direct_cycle(self, mairie_client, team_a, team_b):
        client, _ = mairie_client
        client.post(reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json')

        # team_b est déjà sous team_a : tenter de mettre team_a sous team_b créerait un cycle A->B->A.
        response = client.post(
            reverse('team-rattacher-equipe', args=[team_b.id]), {'equipe_id': str(team_a.id)}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        team_a.refresh_from_db()
        assert team_a.equipe_parente_id is None

    def test_rejects_deep_cycle(self, mairie_client, team_a, team_b, team_c):
        client, _ = mairie_client
        # C sous B, B sous A : A -> ... -> C, tenter C parente de A créerait un cycle profond.
        client.post(reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json')
        client.post(reverse('team-rattacher-equipe', args=[team_b.id]), {'equipe_id': str(team_c.id)}, format='json')

        response = client.post(
            reverse('team-rattacher-equipe', args=[team_c.id]), {'equipe_id': str(team_a.id)}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_already_attached_elsewhere(self, mairie_client, team_a, team_b, team_c):
        client, _ = mairie_client
        client.post(reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json')

        response = client.post(
            reverse('team-rattacher-equipe', args=[team_c.id]), {'equipe_id': str(team_b.id)}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        team_b.refresh_from_db()
        assert team_b.equipe_parente_id == team_a.id

    def test_reattaching_same_parent_is_idempotent(self, mairie_client, team_a, team_b):
        client, _ = mairie_client
        client.post(reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json')

        response = client.post(
            reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK

    def test_rejects_unknown_team(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(
            reverse('team-rattacher-equipe', args=[team_a.id]),
            {'equipe_id': '00000000-0000-0000-0000-000000000000'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_outside_team_institution(self, create_user, team_a, team_b, other_institution):
        tiers = create_user(username='tiers-hierarchie@test.fr', email='tiers-hierarchie@test.fr', type='AUT_LOCALE')
        third_institution = _make_institution(nom='Troisième mairie hiérarchie')
        ContactInstitution.objects.create(institution=third_institution, utilisateur=tiers, actif=True)
        client = APIClient()
        client.force_authenticate(user=tiers)

        response = client.post(
            reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_sous_equipes_info_reflects_attachment(self, mairie_client, team_a, team_b):
        client, _ = mairie_client
        response = client.post(
            reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json',
        )
        assert response.data['sous_equipes_info'] == [{'id': str(team_b.id), 'nom': team_b.name}]

        detail = client.get(reverse('team-detail', args=[team_b.id]))
        assert detail.data['equipe_parente_nom'] == team_a.name


@pytest.mark.django_db
class TestDetacherEquipe:

    def test_detaches_team(self, mairie_client, team_a, team_b):
        client, _ = mairie_client
        client.post(reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json')

        response = client.post(
            reverse('team-detacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team_b.refresh_from_db()
        assert team_b.equipe_parente_id is None

    def test_rejects_team_attached_elsewhere(self, mairie_client, team_a, team_b, team_c):
        client, _ = mairie_client
        client.post(reverse('team-rattacher-equipe', args=[team_a.id]), {'equipe_id': str(team_b.id)}, format='json')

        response = client.post(
            reverse('team-detacher-equipe', args=[team_c.id]), {'equipe_id': str(team_b.id)}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        team_b.refresh_from_db()
        assert team_b.equipe_parente_id == team_a.id
