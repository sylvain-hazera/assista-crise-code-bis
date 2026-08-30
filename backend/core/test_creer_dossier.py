import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Crisis, Dossier, DossierHistorique, DossierParticipant,
    Institution, InstitutionType, Team,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_CREER_DOSSIER', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test créer dossier', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution():
    return _make_institution()


@pytest.fixture
def crisis():
    return Crisis.objects.create(name='Crise dossier direct', type='INCENDIE', location='POINT (5.72 45.18)')


@pytest.fixture
def team(institution):
    return Team.objects.create(name='Équipe garde du feu', institution=institution)


@pytest.fixture
def membre(create_user, team):
    user = create_user(username='membre-dossier@test.fr', email='membre-dossier@test.fr', type='UTIL_SIMPLE')
    team.members.add(user)
    return user


@pytest.fixture
def mairie_client(create_user, institution):
    user = create_user(username='mairie-creer-dossier@test.fr', email='mairie-creer-dossier@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestCreerDossier:

    def test_creates_dossier_with_participants_and_history(self, mairie_client, team, crisis, membre):
        client, _ = mairie_client
        response = client.post(reverse('team-creer-dossier', args=[team.id]), {
            'titre': 'Garde du feu', 'description': 'Surveillance du site pendant la nuit',
            'crise_id': str(crisis.id),
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(id=response.data['id'])
        assert dossier.equipe_id == team.id
        assert dossier.crise_id == crisis.id
        assert dossier.demande_id is None
        assert dossier.information_id is None
        assert dossier.numero.startswith('DOS-')
        assert dossier.statut == Dossier.Statut.AFFECTE
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE
        ).exists()
        assert DossierHistorique.objects.filter(dossier=dossier, evenement='Création').exists()

    def test_uses_team_active_mission(self, mairie_client, team, crisis):
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team.id]), {'titre': 'Mission active'}, format='json')
        team.refresh_from_db()

        response = client.post(reverse('team-creer-dossier', args=[team.id]), {
            'titre': 'Dossier avec mission', 'description': 'Description', 'crise_id': str(crisis.id),
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(id=response.data['id'])
        assert dossier.mission_id == team.mission_active_id

    def test_rejects_missing_titre_or_description(self, mairie_client, team, crisis):
        client, _ = mairie_client
        response = client.post(reverse('team-creer-dossier', args=[team.id]), {
            'titre': '', 'description': 'Description', 'crise_id': str(crisis.id),
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_unknown_crisis(self, mairie_client, team):
        client, _ = mairie_client
        response = client.post(reverse('team-creer-dossier', args=[team.id]), {
            'titre': 'Titre', 'description': 'Description', 'crise_id': '00000000-0000-0000-0000-000000000000',
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_closed_crisis(self, mairie_client, team):
        client, _ = mairie_client
        closed_crisis = Crisis.objects.create(
            name='Crise fermée dossier', type='INCENDIE', location='POINT (5.72 45.18)', end_date=timezone.now(),
        )
        response = client.post(reverse('team-creer-dossier', args=[team.id]), {
            'titre': 'Titre', 'description': 'Description', 'crise_id': str(closed_crisis.id),
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_outside_team_institution(self, create_user, team, crisis):
        tiers = create_user(username='tiers-creer-dossier@test.fr', email='tiers-creer-dossier@test.fr', type='AUT_LOCALE')
        other_institution = _make_institution(nom='Autre mairie créer dossier')
        ContactInstitution.objects.create(institution=other_institution, utilisateur=tiers, actif=True)
        client = APIClient()
        client.force_authenticate(user=tiers)

        response = client.post(reverse('team-creer-dossier', args=[team.id]), {
            'titre': 'Titre', 'description': 'Description', 'crise_id': str(crisis.id),
        }, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDossierDirectCreationLocked:
    """Verrou ajouté en même temps que TeamViewSet.creer_dossier : POSTer un dossier brut sur
    /dossiers/ était jusqu'ici ouvert à n'importe quel compte authentifié, sans peupler les
    participants ni l'historique — désormais réservé aux comptes institutionnels (le chemin
    normal reste TeamViewSet.creer_dossier)."""

    def test_plain_user_cannot_post_dossier_directly(self, create_user, crisis):
        user = create_user(username='simple-post-dossier@test.fr', email='simple-post-dossier@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('dossier-list'), {
            'numero': 'DOS-DIRECT1', 'crise': str(crisis.id), 'titre': 'Titre', 'description': 'Description',
        }, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_user_can_still_post_directly(self, create_user, crisis):
        user = create_user(username='institutionnel-post-dossier@test.fr', email='institutionnel-post-dossier@test.fr', type='AUT_LOCALE')
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('dossier-list'), {
            'numero': 'DOS-DIRECT2', 'crise': str(crisis.id), 'titre': 'Titre', 'description': 'Description',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
