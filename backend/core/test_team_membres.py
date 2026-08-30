import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, RoleOperationnel, Team, User


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_MEMBRES', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test membres', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie A')


@pytest.fixture
def institution_b():
    return _make_institution(nom='Mairie B')


@pytest.fixture
def role_responsable():
    return RoleOperationnel.objects.create(code='RESP_TEST_MEMBRES', libelle="Chef d'équipe")


@pytest.fixture
def mairie_client(create_user, institution_a):
    user = create_user(username='mairie-a@test.fr', email='mairie-a@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def team_a(institution_a):
    return Team.objects.create(name='Équipe A', institution=institution_a)


@pytest.mark.django_db
class TestUserListFilteredByInstitution:

    def test_institution_filter_returns_only_active_contacts(self, create_user, institution_a, institution_b):
        admin = create_user(username='admin-membres@test.fr', email='admin-membres@test.fr', type='ADMIN')
        membre_a = create_user(username='membre-a@test.fr', email='membre-a@test.fr', type='UTIL_SIMPLE')
        membre_b = create_user(username='membre-b@test.fr', email='membre-b@test.fr', type='UTIL_SIMPLE')
        inactif_a = create_user(username='inactif-a@test.fr', email='inactif-a@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=membre_a, actif=True)
        ContactInstitution.objects.create(institution=institution_b, utilisateur=membre_b, actif=True)
        ContactInstitution.objects.create(institution=institution_a, utilisateur=inactif_a, actif=False)

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('user-list'), {'institution': str(institution_a.id)})

        assert response.status_code == status.HTTP_200_OK
        emails = {u['email'] for u in response.data}
        assert emails == {'membre-a@test.fr'}

    def test_without_institution_param_returns_all(self, create_user, institution_a):
        admin = create_user(username='admin-membres2@test.fr', email='admin-membres2@test.fr', type='ADMIN')
        create_user(username='autre@test.fr', email='autre@test.fr', type='UTIL_SIMPLE')

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('user-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 2

    def test_repeated_institution_param_searches_across_both(self, create_user, institution_a, institution_b):
        # Recherche de membres à rattacher à une équipe déléguée : doit porter sur l'institution
        # responsable ET l'institution délégataire à la fois.
        admin = create_user(username='admin-membres3@test.fr', email='admin-membres3@test.fr', type='ADMIN')
        membre_a = create_user(username='membre-a3@test.fr', email='membre-a3@test.fr', type='UTIL_SIMPLE')
        membre_b = create_user(username='membre-b3@test.fr', email='membre-b3@test.fr', type='UTIL_SIMPLE')
        membre_c = create_user(username='membre-c3@test.fr', email='membre-c3@test.fr', type='UTIL_SIMPLE')
        institution_c = _make_institution(nom='Mairie C')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=membre_a, actif=True)
        ContactInstitution.objects.create(institution=institution_b, utilisateur=membre_b, actif=True)
        ContactInstitution.objects.create(institution=institution_c, utilisateur=membre_c, actif=True)

        client = APIClient()
        client.force_authenticate(user=admin)
        from django.http import QueryDict
        qs = QueryDict(mutable=True)
        qs.setlist('institution', [str(institution_a.id), str(institution_b.id)])
        response = client.get(f"{reverse('user-list')}?{qs.urlencode()}")

        assert response.status_code == status.HTTP_200_OK
        emails = {u['email'] for u in response.data}
        assert emails == {'membre-a3@test.fr', 'membre-b3@test.fr'}


@pytest.mark.django_db
class TestInviterMembre:

    def test_invite_creates_inactive_local_authority_account(self, mairie_client, team_a, role_responsable):
        client, _ = mairie_client
        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'Alice', 'last_name': 'Martin', 'email': 'alice.martin@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email='alice.martin@test.fr')
        assert user.type == 'AUT_LOCALE'
        assert user.enabled is False
        assert user.is_active is False
        assert team_a.members.filter(id=user.id).exists()
        assert ContactInstitution.objects.filter(institution=team_a.institution, utilisateur=user, actif=True).exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['alice.martin@test.fr']

    def test_invite_reuses_existing_account_without_downgrading_type(self, mairie_client, team_a, role_responsable, create_user):
        client, _ = mairie_client
        existing = create_user(username='existant@test.fr', email='existant@test.fr', type='ADMIN')

        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'X', 'last_name': 'Y', 'email': 'existant@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        existing.refresh_from_db()
        assert existing.type == 'ADMIN'
        assert team_a.members.filter(id=existing.id).exists()

    def test_invite_rejects_missing_fields(self, mairie_client, team_a, role_responsable):
        client, _ = mairie_client
        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': '', 'last_name': 'Martin', 'email': 'x@test.fr', 'role_code': role_responsable.code,
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invite_rejects_unknown_role(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'ab@test.fr',
            'phone_number': '0600000000', 'role_code': 'CODE_INEXISTANT',
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_invite_into_another_institution_team(self, create_user, institution_a, institution_b, role_responsable):
        team_b = Team.objects.create(name='Équipe B', institution=institution_b)
        mairie_a_user = create_user(username='mairie-a2@test.fr', email='mairie-a2@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=mairie_a_user, actif=True)
        client = APIClient()
        client.force_authenticate(user=mairie_a_user)

        response = client.post(reverse('team-inviter-membre', args=[team_b.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'cross@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_invite_into_any_institution_team(self, create_user, team_a, role_responsable):
        admin = create_user(username='admin-invite@test.fr', email='admin-invite@test.fr', type='ADMIN')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'admin-invited@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED

    def test_rejects_team_without_institution(self, create_user, role_responsable):
        admin = create_user(username='admin-noinst@test.fr', email='admin-noinst@test.fr', type='ADMIN')
        team = Team.objects.create(name='Équipe orpheline')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('team-inviter-membre', args=[team.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'orph@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delegataire_invite_attaches_to_delegated_institution(self, create_user, team_a, role_responsable, institution_a, institution_b):
        # Une équipe déléguée à la mairie B : un référent de la mairie B qui invite quelqu'un le
        # rattache à SA propre institution (B), pas à celle du responsable (A).
        team_a.institution_delegataire = institution_b
        team_a.save(update_fields=['institution_delegataire'])
        deleg_user = create_user(username='deleg-inviteur@test.fr', email='deleg-inviteur@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=deleg_user, actif=True)
        client = APIClient()
        client.force_authenticate(user=deleg_user)

        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'D', 'last_name': 'E', 'email': 'invite-via-delegation@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        invited = User.objects.get(email='invite-via-delegation@test.fr')
        assert invited.institution_id == institution_b.id
        assert ContactInstitution.objects.filter(institution=institution_b, utilisateur=invited, actif=True).exists()
