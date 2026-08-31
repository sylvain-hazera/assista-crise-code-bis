import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Crisis, Institution, InstitutionType, Offer, OfferType, Team


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_RESSOURCES', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test ressources', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie Ressources A')


@pytest.fixture
def mairie_client(create_user, institution_a):
    user = create_user(username='mairie-ress@test.fr', email='mairie-ress@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def team_a(institution_a):
    return Team.objects.create(name='Équipe Ressources A', institution=institution_a)


@pytest.fixture
def offer_type():
    ot, _ = OfferType.objects.get_or_create(type='Matériel (test ressources)', defaults={'description': ''})
    return ot


@pytest.fixture
def offer(offer_type, create_user):
    author = create_user(username='offreur-ress@test.fr', email='offreur-ress@test.fr', type='UTIL_SIMPLE')
    return Offer.objects.create(
        title='Cuve à prêter', first_name_offer='O', last_name_offer='Ffreur',
        email_offer='offreur-ress@test.fr', status='DISPONIBLE', offer_type=offer_type, author=author,
    )


@pytest.mark.django_db
class TestDefinirMission:

    def test_defines_active_mission(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Déblaiement secteur nord'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        team_a.refresh_from_db()
        assert team_a.mission_active is not None
        assert team_a.mission_active.titre == 'Déblaiement secteur nord'
        assert team_a.mission_active.equipes.filter(id=team_a.id).exists()

    def test_redefining_replaces_active_mission(self, mairie_client, team_a):
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Première mission'}, format='json')
        team_a.refresh_from_db()
        first_mission_id = team_a.mission_active_id

        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Deuxième mission'}, format='json')
        team_a.refresh_from_db()

        assert team_a.mission_active_id != first_mission_id
        assert team_a.mission_active.titre == 'Deuxième mission'

    def test_rejects_empty_title(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': '  '}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_attaches_open_crisis(self, mairie_client, team_a):
        client, _ = mairie_client
        crisis = Crisis.objects.create(name='Crise mission test', type='INCENDIE', location='POINT (5.72 45.18)')

        response = client.post(
            reverse('team-definir-mission', args=[team_a.id]),
            {'titre': 'Mission liée à une crise', 'crise_id': str(crisis.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team_a.refresh_from_db()
        assert team_a.mission_active.crise_id == crisis.id

    def test_rejects_closed_crisis(self, mairie_client, team_a):
        from django.utils import timezone
        client, _ = mairie_client
        crisis = Crisis.objects.create(
            name='Crise fermée test', type='INCENDIE', location='POINT (5.72 45.18)', end_date=timezone.now(),
        )

        response = client.post(
            reverse('team-definir-mission', args=[team_a.id]),
            {'titre': 'Mission sur crise fermée', 'crise_id': str(crisis.id)}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_unknown_crisis(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(
            reverse('team-definir-mission', args=[team_a.id]),
            {'titre': 'Mission crise inconnue', 'crise_id': '00000000-0000-0000-0000-000000000000'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_mission_without_crisis_still_works(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(
            reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission sans crise'}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        team_a.refresh_from_db()
        assert team_a.mission_active.crise_id is None


@pytest.mark.django_db
class TestAssignerRessource:

    def test_requires_active_mission_first(self, mairie_client, team_a, offer):
        client, _ = mairie_client
        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_assigns_resource_to_active_mission(self, mairie_client, team_a, offer):
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Collecte matériel'}, format='json')
        team_a.refresh_from_db()

        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.mission_id == team_a.mission_active_id
        assert team_a.assigned_offers.filter(id=offer.id).exists()
        assert team_a.members.filter(id=offer.author_id).exists()

    def test_rejects_unknown_offer(self, mairie_client, team_a):
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')
        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': '00000000-0000-0000-0000-000000000000'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_does_not_add_member_when_presence_physique_explicitly_false(self, mairie_client, team_a, offer):
        """Un hébergement prêté (offreur non présent) ne doit pas faire de son auteur un
        membre d'équipe — voir presence_physique."""
        offer.presence_physique = False
        offer.save(update_fields=['presence_physique'])
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')

        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert not team_a.members.filter(id=offer.author_id).exists()

    def test_adds_member_when_presence_physique_unknown(self, mairie_client, team_a, offer):
        """None (offre antérieure à ce champ) garde l'ancien comportement — seul False exclut."""
        assert offer.presence_physique is None
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')

        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert team_a.members.filter(id=offer.author_id).exists()


@pytest.mark.django_db
class TestRetirerRessource:

    def test_removes_resource_and_clears_mission_link(self, mairie_client, team_a, offer):
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')
        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        response = client.post(reverse('team-retirer-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.mission_id is None
        assert not team_a.assigned_offers.filter(id=offer.id).exists()

    def test_does_not_clear_mission_link_of_a_different_team(self, mairie_client, team_a, offer, institution_a):
        client, _ = mairie_client
        other_team = Team.objects.create(name='Autre équipe', institution=institution_a)
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission A'}, format='json')
        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')
        team_a.refresh_from_db()

        # other_team n'a pas de mission active : retirer la ressource sur other_team ne doit
        # pas toucher au lien mission de l'offre posé par team_a.
        response = client.post(reverse('team-retirer-ressource', args=[other_team.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.mission_id == team_a.mission_active_id
