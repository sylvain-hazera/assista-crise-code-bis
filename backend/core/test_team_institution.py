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

    def test_any_institutional_actor_can_assign_institution_to_orphan_team(self, institutional_client):
        """Une équipe SANS institution (cas de toutes les équipes DEMO créées jusqu'ici) doit
        pouvoir en recevoir une — sans ce cas particulier, _appartient_a_institution(request,
        None) ne peut par construction jamais être vrai (aucun ContactInstitution n'a
        institution=NULL), ce qui bloquait DÉFINITIVEMENT toute première affectation."""
        client, user = institutional_client
        team = Team.objects.create(name='Equipe orpheline')
        assert team.institution_id is None
        institution = _make_institution()

        response = client.patch(
            reverse('team-detail', args=[team.id]), {'institution': str(institution.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert team.institution_id == institution.id

    def test_reassigning_already_owned_team_still_requires_membership(self, institutional_client):
        """Contrairement au cas orphelin ci-dessus, une équipe DÉJÀ rattachée à une institution
        ne doit pouvoir être réaffectée que par un membre de cette institution actuelle — sinon
        n'importe quel acteur institutionnel pourrait voler l'équipe d'une institution tierce."""
        client, user = institutional_client
        institution_actuelle = _make_institution(nom='Institution actuelle')
        institution_cible = _make_institution(nom='Institution cible')
        team = Team.objects.create(name='Equipe deja rattachee', institution=institution_actuelle)
        # L'utilisateur n'est membre (ContactInstitution) d'AUCUNE des deux institutions.

        response = client.patch(
            reverse('team-detail', args=[team.id]), {'institution': str(institution_cible.id)}, format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        team.refresh_from_db()
        assert team.institution_id == institution_actuelle.id
