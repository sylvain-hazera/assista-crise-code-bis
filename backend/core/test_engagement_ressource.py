import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, EngagementRessource, Institution, InstitutionType, Offer, OfferType, Team,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_ENGAGEMENT', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test engagement', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution():
    return _make_institution()


@pytest.fixture
def team(institution):
    return Team.objects.create(name='Équipe engagement test', institution=institution)


@pytest.fixture
def other_team(institution):
    return Team.objects.create(name='Autre équipe engagement test', institution=institution)


@pytest.fixture
def offer_type():
    ot, _ = OfferType.objects.get_or_create(type='Matériel (test engagement)', defaults={'description': ''})
    return ot


@pytest.fixture
def offer(offer_type, create_user):
    author = create_user(username='offreur-engagement@test.fr', email='offreur-engagement@test.fr', type='UTIL_SIMPLE')
    return Offer.objects.create(
        title='Camion-citerne', first_name_offer='O', last_name_offer='Ffreur',
        email_offer='offreur-engagement@test.fr', status='DISPONIBLE', offer_type=offer_type, author=author,
    )


@pytest.fixture
def mairie_client(create_user, institution):
    user = create_user(username='mairie-engagement@test.fr', email='mairie-engagement@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _assign(client, team, offer):
    client.post(reverse('team-definir-mission', args=[team.id]), {'titre': 'Mission engagement'}, format='json')
    return client.post(reverse('team-assigner-ressource', args=[team.id]), {'offer_id': str(offer.id)}, format='json')


@pytest.mark.django_db
class TestEngagementCreationEtNettoyage:

    def test_assigning_resource_creates_pending_engagement(self, mairie_client, team, offer):
        client, _ = mairie_client
        response = _assign(client, team, offer)

        assert response.status_code == status.HTTP_200_OK
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.team_id == team.id
        assert engagement.statut == 'EN_ATTENTE'
        assert engagement.token_confirmation

    def test_reassigning_replaces_previous_engagement(self, mairie_client, team, other_team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        first_token = EngagementRessource.objects.get(offer=offer).token_confirmation

        _assign(client, other_team, offer)

        assert EngagementRessource.objects.filter(offer=offer).count() == 1
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.team_id == other_team.id
        assert engagement.token_confirmation != first_token

    def test_removing_resource_deletes_engagement(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)

        client.post(reverse('team-retirer-ressource', args=[team.id]), {'offer_id': str(offer.id)}, format='json')

        assert not EngagementRessource.objects.filter(offer=offer).exists()

    def test_offer_serializer_exposes_engagement_status(self, mairie_client, team, offer):
        client, _ = mairie_client
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['engagement_statut'] is None
        assert response.data['engagement_statut_libelle'] is None

        _assign(client, team, offer)
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['engagement_statut'] == 'EN_ATTENTE'
        assert response.data['engagement_statut_libelle'] == 'En attente de confirmation'


@pytest.mark.django_db
class TestDefinirStatutRessource:

    def test_advances_status_and_stamps_date(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)

        response = client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'CONFIRME'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.statut == 'CONFIRME'
        assert engagement.date_confirmation is not None
        assert engagement.date_transit is None

    def test_can_skip_directly_to_arrive(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)

        response = client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'ARRIVE'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.statut == 'ARRIVE'
        assert engagement.date_arrivee is not None

    def test_rejects_invalid_statut(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)

        response = client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'PAS_UN_STATUT'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_offer_without_engagement(self, mairie_client, team, offer):
        client, _ = mairie_client
        response = client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'CONFIRME'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_outside_team_institution(self, create_user, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)

        tiers = create_user(username='tiers-engagement@test.fr', email='tiers-engagement@test.fr', type='AUT_LOCALE')
        other_institution = _make_institution(nom='Autre mairie engagement')
        ContactInstitution.objects.create(institution=other_institution, utilisateur=tiers, actif=True)
        tiers_client = APIClient()
        tiers_client.force_authenticate(user=tiers)

        response = tiers_client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'CONFIRME'}, format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_does_not_overwrite_existing_date_on_repeated_call(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'CONFIRME'}, format='json',
        )
        first_date = EngagementRessource.objects.get(offer=offer).date_confirmation

        client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'EN_TRANSIT'}, format='json',
        )
        client.post(
            reverse('team-definir-statut-ressource', args=[team.id]),
            {'offer_id': str(offer.id), 'statut': 'CONFIRME'}, format='json',
        )

        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.date_confirmation == first_date


@pytest.mark.django_db
class TestEmailConfirmation:

    def test_assigning_resource_sends_confirmation_email(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['offreur-engagement@test.fr']
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.token_confirmation in mail.outbox[0].body
        assert '/confirmation-ressource/' in mail.outbox[0].body


@pytest.mark.django_db
class TestEngagementRessourcePublicView:

    def test_get_returns_current_status_and_available_actions(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        token = EngagementRessource.objects.get(offer=offer).token_confirmation

        public_client = APIClient()
        response = public_client.get(reverse('engagement_ressource_public', args=[token]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['statut'] == 'EN_ATTENTE'
        assert set(response.data['actions_possibles']) == {'confirmer', 'decliner'}
        assert response.data['team_nom'] == team.name

    def test_unknown_token_returns_404(self):
        public_client = APIClient()
        response = public_client.get(reverse('engagement_ressource_public', args=['jeton-inconnu']))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_confirmer_advances_to_confirme(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        token = EngagementRessource.objects.get(offer=offer).token_confirmation

        public_client = APIClient()
        response = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'confirmer'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['statut'] == 'CONFIRME'
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.date_confirmation is not None

    def test_decliner_is_terminal(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        token = EngagementRessource.objects.get(offer=offer).token_confirmation

        public_client = APIClient()
        response = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'decliner'}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['actions_possibles'] == []

        # Plus aucune action possible après décliné.
        response2 = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'confirmer'}, format='json')
        assert response2.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_skipping_steps(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        token = EngagementRessource.objects.get(offer=offer).token_confirmation

        public_client = APIClient()
        # Encore EN_ATTENTE : "transit"/"arrivee" ne sont pas dans les actions possibles.
        response = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'arrivee'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.statut == 'EN_ATTENTE'

    def test_full_sequential_journey(self, mairie_client, team, offer):
        client, _ = mairie_client
        _assign(client, team, offer)
        token = EngagementRessource.objects.get(offer=offer).token_confirmation
        public_client = APIClient()

        r1 = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'confirmer'}, format='json')
        assert r1.data['statut'] == 'CONFIRME'

        r2 = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'transit'}, format='json')
        assert r2.data['statut'] == 'EN_TRANSIT'

        r3 = public_client.post(reverse('engagement_ressource_public', args=[token]), {'action': 'arrivee'}, format='json')
        assert r3.data['statut'] == 'ARRIVE'
        assert r3.data['actions_possibles'] == []

        engagement = EngagementRessource.objects.get(offer=offer)
        assert engagement.date_confirmation is not None
        assert engagement.date_transit is not None
        assert engagement.date_arrivee is not None
