import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Team, TeamDelegation


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_DELEGATION', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Institution délégation test', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_responsable():
    return _make_institution(nom='Institution responsable')


@pytest.fixture
def institution_delegataire():
    return _make_institution(nom='Institution délégataire')


@pytest.fixture
def institution_tierce():
    return _make_institution(nom='Institution tierce')


@pytest.fixture
def team(institution_responsable):
    return Team.objects.create(name='Équipe déléguée', institution=institution_responsable)


def _client_for(user_institution, create_user, email):
    user = create_user(username=email, email=email, type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=user_institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def responsable_client(institution_responsable, create_user):
    return _client_for(institution_responsable, create_user, 'responsable@test.fr')


@pytest.fixture
def delegataire_client(institution_delegataire, create_user):
    return _client_for(institution_delegataire, create_user, 'delegataire@test.fr')


@pytest.fixture
def tiers_client(institution_tierce, create_user):
    return _client_for(institution_tierce, create_user, 'tiers@test.fr')


@pytest.mark.django_db
class TestDefinirDelegation:

    def test_responsable_can_delegate(self, responsable_client, team, institution_delegataire):
        client, _ = responsable_client
        response = client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert team.institution_delegataire_id == institution_delegataire.id
        delegation = TeamDelegation.objects.get(team=team, active=True)
        assert delegation.institution_id == institution_delegataire.id

    def test_delegataire_cannot_delegate(self, delegataire_client, team, institution_delegataire):
        client, _ = delegataire_client
        response = client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_tiers_cannot_delegate(self, tiers_client, team, institution_delegataire):
        client, _ = tiers_client
        response = client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_delegate_to_self(self, responsable_client, team, institution_responsable):
        client, _ = responsable_client
        response = client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_responsable.id)}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_redelegating_closes_previous_delegation(self, responsable_client, team, institution_delegataire, institution_tierce):
        client, _ = responsable_client
        client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )
        first = TeamDelegation.objects.get(team=team, institution=institution_delegataire)

        response = client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_tierce.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        first.refresh_from_db()
        assert first.active is False
        assert first.date_fin is not None
        team.refresh_from_db()
        assert team.institution_delegataire_id == institution_tierce.id
        assert TeamDelegation.objects.filter(team=team, active=True).count() == 1


@pytest.mark.django_db
class TestRetirerDelegation:

    def test_responsable_can_remove_delegation(self, responsable_client, team, institution_delegataire):
        client, _ = responsable_client
        client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )

        response = client.post(reverse('team-retirer-delegation', args=[team.id]), format='json')

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert team.institution_delegataire_id is None
        assert not TeamDelegation.objects.filter(team=team, active=True).exists()

    def test_rejects_when_not_delegated(self, responsable_client, team):
        client, _ = responsable_client
        response = client.post(reverse('team-retirer-delegation', args=[team.id]), format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delegataire_cannot_remove_delegation(self, responsable_client, delegataire_client, team, institution_delegataire):
        resp_client, _ = responsable_client
        resp_client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )

        deleg_client, _ = delegataire_client
        response = deleg_client.post(reverse('team-retirer-delegation', args=[team.id]), format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGestionCourantePartageeAvecDelegation:
    """Une fois déléguée, l'institution délégataire a les mêmes droits de gestion courante que
    l'institution responsable (décision utilisateur) — mais pas sur la délégation elle-même."""

    def test_delegataire_can_define_mission(self, responsable_client, delegataire_client, team, institution_delegataire):
        resp_client, _ = responsable_client
        resp_client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )

        deleg_client, _ = delegataire_client
        response = deleg_client.post(
            reverse('team-definir-mission', args=[team.id]), {'titre': 'Mission via délégation'}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert team.mission_active.titre == 'Mission via délégation'

    def test_tiers_still_cannot_manage_team(self, responsable_client, tiers_client, team, institution_delegataire):
        resp_client, _ = responsable_client
        resp_client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )

        tiers, _ = tiers_client
        response = tiers.post(
            reverse('team-definir-mission', args=[team.id]), {'titre': 'Mission illégitime'}, format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestChangerInstitutionResponsable:

    def test_responsable_can_reassign_institution(self, responsable_client, team, institution_tierce):
        client, _ = responsable_client
        response = client.patch(
            reverse('team-detail', args=[team.id]), {'institution': str(institution_tierce.id)}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert team.institution_id == institution_tierce.id

    def test_delegataire_cannot_reassign_institution(self, responsable_client, delegataire_client, team, institution_delegataire, institution_tierce):
        resp_client, _ = responsable_client
        resp_client.post(
            reverse('team-definir-delegation', args=[team.id]),
            {'institution_id': str(institution_delegataire.id)}, format='json',
        )

        deleg_client, _ = delegataire_client
        response = deleg_client.patch(
            reverse('team-detail', args=[team.id]), {'institution': str(institution_tierce.id)}, format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        team.refresh_from_db()
        assert team.institution_id != institution_tierce.id

    def test_reassigning_institution_is_audit_logged(self, responsable_client, team, institution_tierce):
        from core.models import AuditLog

        client, _ = responsable_client
        client.patch(reverse('team-detail', args=[team.id]), {'institution': str(institution_tierce.id)}, format='json')

        assert AuditLog.objects.filter(objet_type='Team', objet_id=team.id, commentaire__icontains='Institution responsable').exists()

    def test_unrelated_patch_does_not_require_institution_check(self, responsable_client, team):
        # Changer la couleur ne touche pas à l'institution : ne doit pas exiger d'appartenance.
        client, _ = responsable_client
        response = client.patch(reverse('team-detail', args=[team.id]), {'color': '#ff0000'}, format='json')
        assert response.status_code == status.HTTP_200_OK
