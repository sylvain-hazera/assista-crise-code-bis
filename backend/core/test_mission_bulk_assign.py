import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models import Crisis, Dossier, Information, Mission, Offer, Request, Team, User


def _make_admin(authenticated_client):
    client, admin = authenticated_client
    admin.type = 'ADMIN'
    admin.save()
    return client, admin


def _make_crisis(**kwargs):
    defaults = {'name': 'Crise test', 'location': Point(1.0, 1.0, srid=4326)}
    defaults.update(kwargs)
    return Crisis.objects.create(**defaults)


def _make_request(crisis, request_type, **kwargs):
    defaults = {
        'title': 'Demande test',
        'location': Point(1.0, 1.0, srid=4326),
        'first_name_request': 'Jean',
        'last_name_request': 'Dupont',
        'email_request': 'demandeur@test.fr',
        'phone_request': '0600000000',
        'crisis': crisis,
        'request_type': request_type,
        'deletion_token': f'tok-{Request.objects.count()}-{id(kwargs)}',
    }
    defaults.update(kwargs)
    return Request.objects.create(**defaults)


@pytest.mark.django_db
class TestMissionCRUD:

    def test_create_mission_with_multiple_teams(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team1 = Team.objects.create(name='Voirie nord')
        team2 = Team.objects.create(name='Voirie sud')

        response = client.post(
            reverse('mission-list'),
            {'titre': 'Dégager les routes', 'crise': str(crisis.id), 'equipe_ids': [str(team1.id), str(team2.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert set(response.data['equipe_ids']) == {team1.id, team2.id}
        assert response.data['statut'] == 'EN_PREPARATION'

    def test_mission_requires_crise(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)

        response = client.post(reverse('mission-list'), {'titre': 'Sans crise'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestBulkCreateTeamOffers:

    def test_bulk_create_team_dedupes_authors_and_sets_regulateur(self, authenticated_client, offer_type):
        client, _ = _make_admin(authenticated_client)
        author = User.objects.create_user(username='auteur@test.fr', email='auteur@test.fr', password='Test1234!')
        regulateur = User.objects.create_user(username='regul@test.fr', email='regul@test.fr', password='Test1234!')
        offer1 = Offer.objects.create(
            title='Offre 1', first_name_offer='A', last_name_offer='B',
            email_offer='auteur@test.fr', offer_type=offer_type, author=author,
        )
        offer2 = Offer.objects.create(
            title='Offre 2', first_name_offer='A', last_name_offer='B',
            email_offer='auteur@test.fr', offer_type=offer_type, author=author,
        )

        response = client.post(
            reverse('offer-bulk-create-team'),
            {'offer_ids': [str(offer1.id), str(offer2.id)], 'team_name': 'Nouvelle équipe', 'regulateur': str(regulateur.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['member_ids'] == [author.id]
        assert set(response.data['assigned_offer_ids']) == {offer1.id, offer2.id}
        assert response.data['regulateur'] == regulateur.id

    def test_bulk_create_team_requires_name(self, authenticated_client, offer_type):
        client, _ = _make_admin(authenticated_client)
        offer = Offer.objects.create(
            title='Offre', first_name_offer='A', last_name_offer='B',
            email_offer='x@test.fr', offer_type=offer_type,
        )

        response = client.post(
            reverse('offer-bulk-create-team'),
            {'offer_ids': [str(offer.id)], 'team_name': ''},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestBulkAssignMissionRequests:

    def test_bulk_assign_creates_mission_and_dossiers(self, authenticated_client, request_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team = Team.objects.create(name='Equipe test')
        r1 = _make_request(crisis, request_type)
        r2 = _make_request(crisis, request_type)

        response = client.post(
            reverse('request-bulk-assign-mission'),
            {
                'request_ids': [str(r1.id), str(r2.id)],
                'team': str(team.id),
                'new_mission': {'titre': 'Mission groupée'},
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data['dossiers_created']) == 2
        mission = Mission.objects.get(id=response.data['mission'])
        assert mission.crise_id == crisis.id
        assert team in mission.equipes.all()
        for r in (r1, r2):
            dossier = Dossier.objects.get(demande=r)
            assert dossier.mission_id == mission.id
            assert dossier.equipe_id == team.id

    def test_bulk_assign_rejects_cross_crisis_selection(self, authenticated_client, request_type):
        client, _ = _make_admin(authenticated_client)
        crisis1 = _make_crisis(name='Crise 1')
        crisis2 = _make_crisis(name='Crise 2')
        team = Team.objects.create(name='Equipe test')
        r1 = _make_request(crisis1, request_type)
        r2 = _make_request(crisis2, request_type)

        response = client.post(
            reverse('request-bulk-assign-mission'),
            {
                'request_ids': [str(r1.id), str(r2.id)],
                'team': str(team.id),
                'new_mission': {'titre': 'Mission impossible'},
            },
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Mission.objects.filter(titre='Mission impossible').exists()

    def test_bulk_assign_is_noop_for_already_assigned_requests(self, authenticated_client, request_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team = Team.objects.create(name='Equipe test')
        r1 = _make_request(crisis, request_type)
        mission = Mission.objects.create(titre='Mission existante', crise=crisis)

        first = client.post(
            reverse('request-bulk-assign-mission'),
            {'request_ids': [str(r1.id)], 'team': str(team.id), 'mission': str(mission.id)},
            format='json',
        )
        assert first.status_code == status.HTTP_201_CREATED
        assert len(first.data['dossiers_created']) == 1

        second = client.post(
            reverse('request-bulk-assign-mission'),
            {'request_ids': [str(r1.id)], 'team': str(team.id), 'mission': str(mission.id)},
            format='json',
        )
        assert second.status_code == status.HTTP_201_CREATED
        assert second.data['dossiers_created'] == []
        assert second.data['already_assigned'] == [str(r1.id)]
        assert Dossier.objects.filter(demande=r1).count() == 1

    def test_single_assign_team_unaffected_by_bulk_refactor(self, authenticated_client, request_type):
        """Non-régression : assign_team (une seule demande) doit garder exactement le même
        contrat de réponse après l'extraction de _assign_request_to_team."""
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team = Team.objects.create(name='Equipe test')
        r1 = _make_request(crisis, request_type)

        response = client.post(reverse('request-assign-team', args=[r1.id]), {'team': str(team.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'dossier' in response.data and 'numero' in response.data

        again = client.post(reverse('request-assign-team', args=[r1.id]), {'team': str(team.id)}, format='json')
        assert again.status_code == status.HTTP_200_OK
        assert again.data == {'already_assigned': True}


@pytest.mark.django_db
class TestBulkAssignTeamInformations:
    """Signalements "divers" (ex: arbre sur la chaussée) affectés en bloc à une équipe
    existante (ex: voirie) — pas de dossier de suivi ici, juste un rattachement équipe, comme
    pour l'affectation individuelle d'une offre."""

    def test_bulk_assign_adds_authors_as_members(self, authenticated_client, information_type):
        client, _ = _make_admin(authenticated_client)
        author = User.objects.create_user(username='signaleur@test.fr', email='signaleur@test.fr', password='Test1234!')
        i1 = Information.objects.create(
            title='Arbre sur la chaussée', location=Point(1, 1, srid=4326),
            first_name_information='A', last_name_information='B', email_information='a@t.fr',
            phone_information='0600000000', information_type=information_type, author=author,
        )
        i2 = Information.objects.create(
            title='Autre arbre', location=Point(1, 1, srid=4326),
            first_name_information='C', last_name_information='D', email_information='c@t.fr',
            phone_information='0600000000', information_type=information_type,
        )
        team = Team.objects.create(name='Voirie')

        response = client.post(
            reverse('information-bulk-assign-team'),
            {'information_ids': [str(i1.id), str(i2.id)], 'team': str(team.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data['assigned_information_ids']) == {i1.id, i2.id}
        assert response.data['member_ids'] == [author.id]

    def test_bulk_assign_requires_information_ids(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        team = Team.objects.create(name='Voirie')

        response = client.post(
            reverse('information-bulk-assign-team'),
            {'information_ids': [], 'team': str(team.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCommuneAndDistanceFields:

    def test_fields_hidden_for_non_institutional_consumer(self, api_client, request_type):
        crisis = _make_crisis()
        r1 = _make_request(crisis, request_type)

        response = api_client.get(reverse('request-detail', args=[r1.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['commune'] is None
        assert response.data['distance_from_crisis_km'] is None

    def test_distance_from_crisis_computed_for_institutional_consumer(self, authenticated_client, request_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis(location=Point(0.0, 0.0, srid=4326))
        r1 = _make_request(crisis, request_type, location=Point(0.0, 0.0, srid=4326))

        response = client.get(reverse('request-detail', args=[r1.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['distance_from_crisis_km'] == 0.0
