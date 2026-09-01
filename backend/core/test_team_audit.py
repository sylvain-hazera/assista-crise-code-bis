import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import AuditLog, ContactInstitution, Institution, InstitutionType, Team


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_AUDIT', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test audit', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie Audit A')


@pytest.fixture
def institution_b():
    return _make_institution(nom='Mairie Audit B')


@pytest.fixture
def mairie_client(create_user, institution_a):
    user = create_user(username='mairie-audit@test.fr', email='mairie-audit@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def team_a(institution_a):
    return Team.objects.create(name='Équipe Audit A', institution=institution_a)


@pytest.mark.django_db
class TestAuditLogViewSet:

    def test_requires_objet_type_and_objet_id(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.get(reverse('auditlog-list'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_mairie_sees_audit_of_own_team(self, mairie_client, team_a):
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission audit'}, format='json')

        response = client.get(reverse('auditlog-list'), {'objet_type': 'Team', 'objet_id': str(team_a.id)})

        assert response.status_code == status.HTTP_200_OK
        assert any('Mission audit' in (e['commentaire'] or '') for e in response.data)

    def test_mairie_cannot_see_audit_of_other_institution_team(self, mairie_client, institution_b):
        client, _ = mairie_client
        other_team = Team.objects.create(name='Équipe Audit B', institution=institution_b)

        response = client.get(reverse('auditlog-list'), {'objet_type': 'Team', 'objet_id': str(other_team.id)})

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_admin_sees_any_team_audit(self, create_user, team_a):
        admin = create_user(username='admin-audit@test.fr', email='admin-audit@test.fr', type='ADMIN')
        client = APIClient()
        client.force_authenticate(user=admin)
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission admin audit'}, format='json')

        response = client.get(reverse('auditlog-list'), {'objet_type': 'Team', 'objet_id': str(team_a.id)})

        assert response.status_code == status.HTTP_200_OK
        assert any('Mission admin audit' in (e['commentaire'] or '') for e in response.data)

    def test_non_team_objet_type_reserved_to_admin(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.get(reverse('auditlog-list'), {'objet_type': 'Dossier', 'objet_id': str(team_a.id)})
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []


@pytest.mark.django_db
class TestMemberChangesAudited:

    def test_adding_member_creates_audit_entry(self, mairie_client, team_a, institution_a, create_user):
        client, _ = mairie_client
        nouveau = create_user(username='nouveau-membre@test.fr', email='nouveau-membre@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=nouveau, actif=True)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(nouveau.id)]}, format='json')
        assert response.status_code == status.HTTP_200_OK

        logs = AuditLog.objects.filter(objet_type='Team', objet_id=team_a.id)
        assert any('ajouté' in (l.commentaire or '') for l in logs)

    def test_removing_member_creates_audit_entry(self, mairie_client, team_a, create_user):
        client, _ = mairie_client
        membre = create_user(username='a-retirer@test.fr', email='a-retirer@test.fr', type='UTIL_SIMPLE')
        team_a.members.add(membre)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': []}, format='json')
        assert response.status_code == status.HTTP_200_OK

        logs = AuditLog.objects.filter(objet_type='Team', objet_id=team_a.id)
        assert any('retiré' in (l.commentaire or '') for l in logs)
