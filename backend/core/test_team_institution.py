import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Notification, Team, User


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Institution test', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="createur@test.fr", email="createur@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestTeamInstitution:

    def test_team_auto_attached_to_creator_institution(self, institutional_client):
        client, user = institutional_client
        institution = _make_institution()
        user.institution = institution
        user.save()

        response = client.post(reverse('team-list'), {'name': 'Equipe auto'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['institution'] == institution.id
        team = Team.objects.get(id=response.data['id'])
        assert team.institution_id == institution.id

    def test_team_creation_still_works_without_institution(self, institutional_client):
        client, user = institutional_client
        assert user.institution is None

        response = client.post(reverse('team-list'), {'name': 'Equipe sans institution'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['institution'] is None

    def test_principal_referent_is_notified_on_team_creation(self, institutional_client):
        client, user = institutional_client
        institution = _make_institution()
        user.institution = institution
        user.save()
        referent = User.objects.create_user(username='referent@test.fr', email='referent@test.fr', password='Test1234!')
        ContactInstitution.objects.create(institution=institution, utilisateur=referent, contact_principal=True)

        response = client.post(reverse('team-list'), {'name': 'Equipe notifiee'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert Notification.objects.filter(utilisateur=referent).exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['referent@test.fr']

    def test_no_notification_when_institution_has_no_contact(self, institutional_client):
        client, user = institutional_client
        institution = _make_institution()
        user.institution = institution
        user.save()

        response = client.post(reverse('team-list'), {'name': 'Equipe orpheline de contact'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert Notification.objects.count() == 0
        assert len(mail.outbox) == 0
