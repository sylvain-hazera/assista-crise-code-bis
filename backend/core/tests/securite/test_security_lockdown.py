import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Team


def _make_admin(authenticated_client):
    client, admin = authenticated_client
    admin.type = 'ADMIN'
    admin.save()
    return client, admin


@pytest.mark.django_db
class TestUserViewSetLockdown:
    def test_non_institutional_cannot_list_users(self, create_user):
        simple_user = create_user(username='lockdown-list@test.fr', email='lockdown-list@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.get(reverse('user-list'))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_institutional_cannot_retrieve_another_user(self, create_user):
        simple_user = create_user(username='lockdown-retrieve@test.fr', email='lockdown-retrieve@test.fr', type='UTIL_SIMPLE')
        other = create_user(username='lockdown-victim@test.fr', email='lockdown-victim@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.get(reverse('user-detail', args=[other.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_can_list_and_retrieve(self, authenticated_client, create_user):
        client, _ = _make_admin(authenticated_client)
        other = create_user(username='lockdown-visible@test.fr', email='lockdown-visible@test.fr', type='UTIL_SIMPLE')

        assert client.get(reverse('user-list')).status_code == status.HTTP_200_OK
        assert client.get(reverse('user-detail', args=[other.id])).status_code == status.HTTP_200_OK

    def test_user_cannot_escalate_own_type_to_admin(self, create_user):
        simple_user = create_user(username='lockdown-escalade@test.fr', email='lockdown-escalade@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(reverse('user-detail', args=[simple_user.id]), {'type': 'ADMIN'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        simple_user.refresh_from_db()
        assert simple_user.type == 'UTIL_SIMPLE'

    def test_user_cannot_grant_self_demo_role_or_enable(self, create_user):
        simple_user = create_user(username='lockdown-demo-escalade@test.fr', email='lockdown-demo-escalade@test.fr', type='UTIL_SIMPLE')
        simple_user.enabled = False
        simple_user.save()
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(
            reverse('user-detail', args=[simple_user.id]),
            {'demo_role': 'ADMIN', 'enabled': True},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        simple_user.refresh_from_db()
        assert simple_user.demo_role is None
        assert simple_user.enabled is False

    def test_user_can_still_edit_own_harmless_fields(self, create_user):
        simple_user = create_user(username='lockdown-profil@test.fr', email='lockdown-profil@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(reverse('user-detail', args=[simple_user.id]), {'first_name': 'NouveauPrenom'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        simple_user.refresh_from_db()
        assert simple_user.first_name == 'NouveauPrenom'

    def test_user_cannot_update_another_users_account(self, create_user):
        simple_user = create_user(username='lockdown-attaquant@test.fr', email='lockdown-attaquant@test.fr', type='UTIL_SIMPLE')
        victim = create_user(username='lockdown-cible@test.fr', email='lockdown-cible@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(reverse('user-detail', args=[victim.id]), {'first_name': 'Pirate'}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        victim.refresh_from_db()
        assert victim.first_name != 'Pirate'

    def test_institutional_can_change_another_users_type(self, authenticated_client, create_user):
        client, _ = _make_admin(authenticated_client)
        other = create_user(username='lockdown-promu@test.fr', email='lockdown-promu@test.fr', type='UTIL_SIMPLE')

        response = client.patch(reverse('user-detail', args=[other.id]), {'type': 'SECOURS'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        other.refresh_from_db()
        assert other.type == 'SECOURS'

    def test_register_still_open_to_anonymous(self, request_type):
        client = APIClient()
        response = client.post(reverse('user-register'), {
            'username': 'lockdown-inscription@test.fr',
            'email': 'lockdown-inscription@test.fr',
            'password': 'Test1234!',
            'type': 'UTIL_SIMPLE',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestTeamViewSetLockdown:
    def test_non_institutional_cannot_list_teams(self, create_user):
        simple_user = create_user(username='lockdown-team-list@test.fr', email='lockdown-team-list@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.get(reverse('team-list'))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_institutional_cannot_create_team(self, create_user):
        simple_user = create_user(username='lockdown-team-create@test.fr', email='lockdown-team-create@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.post(reverse('team-list'), {'name': 'Equipe pirate'}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_institutional_cannot_appoint_self_as_leader(self, create_user):
        simple_user = create_user(username='lockdown-team-leader@test.fr', email='lockdown-team-leader@test.fr', type='UTIL_SIMPLE')
        team = Team.objects.create(name='Equipe existante lockdown')
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(reverse('team-detail', args=[team.id]), {'leader': str(simple_user.id)}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        team.refresh_from_db()
        assert team.leader_id is None

    def test_member_can_still_retrieve_own_team(self, create_user):
        membre = create_user(username='lockdown-team-membre@test.fr', email='lockdown-team-membre@test.fr', type='UTIL_SIMPLE')
        team = Team.objects.create(name='Equipe membre lockdown')
        team.members.add(membre)
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.get(reverse('team-detail', args=[team.id]))

        assert response.status_code == status.HTTP_200_OK

    def test_institutional_can_still_list_and_create(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)

        assert client.get(reverse('team-list')).status_code == status.HTTP_200_OK
        response = client.post(reverse('team-list'), {'name': 'Equipe institutionnelle lockdown'}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
