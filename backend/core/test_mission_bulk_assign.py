import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis, Dossier, DossierParticipant, Information, Mission, Offer, Request, Team, User


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

    def test_mission_can_be_created_without_crise(self, authenticated_client):
        # `crise` est devenue optionnelle : une mission "courante" d'équipe (voir
        # Team.mission_active / TeamViewSet.definir_mission) se crée souvent en texte libre,
        # sans crise précise identifiée dès le départ.
        client, _ = _make_admin(authenticated_client)

        response = client.post(reverse('mission-list'), {'titre': 'Sans crise'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['crise'] is None


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

    def test_bulk_create_team_notifies_each_offer_author(self, authenticated_client, offer_type):
        client, _ = _make_admin(authenticated_client)
        offer1 = Offer.objects.create(
            title='Offre A', first_name_offer='A', last_name_offer='B',
            email_offer='a@test.fr', offer_type=offer_type,
        )
        offer2 = Offer.objects.create(
            title='Offre B', first_name_offer='C', last_name_offer='D',
            email_offer='b@test.fr', offer_type=offer_type,
        )

        response = client.post(
            reverse('offer-bulk-create-team'),
            {'offer_ids': [str(offer1.id), str(offer2.id)], 'team_name': 'Equipe notif'},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(mail.outbox) == 2
        assert {m.to[0] for m in mail.outbox} == {'a@test.fr', 'b@test.fr'}

    def test_bulk_create_team_email_includes_vue_equipe_link_for_authored_offer(self, authenticated_client, offer_type):
        client, _ = _make_admin(authenticated_client)
        author = User.objects.create_user(username='auteur-lien@test.fr', email='auteur-lien@test.fr', password='Test1234!')
        offer = Offer.objects.create(
            title='Offre avec compte', first_name_offer='A', last_name_offer='B',
            email_offer='auteur-lien@test.fr', offer_type=offer_type, author=author,
        )

        response = client.post(
            reverse('offer-bulk-create-team'),
            {'offer_ids': [str(offer.id)], 'team_name': 'Equipe avec lien'},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        team_id = response.data['id']
        assert len(mail.outbox) == 1
        assert f'mon-equipe%2F{team_id}' in mail.outbox[0].body

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
    existante (ex: voirie) : crée un Dossier de suivi par signalement rattaché à une crise
    (statut AFFECTE), comme pour les demandes — un signalement affecté doit pouvoir être suivi
    au même titre qu'une demande. Limitation connue : un signalement sans crise associée ne
    peut pas générer de dossier (Dossier.crise est obligatoire), il reste alors seulement
    rattaché à l'équipe — voir test_bulk_assign_skips_dossier_for_crisis_less_information."""

    def test_bulk_assign_creates_dossiers_and_adds_authors_as_members(self, authenticated_client, information_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        author = User.objects.create_user(username='signaleur@test.fr', email='signaleur@test.fr', password='Test1234!')
        i1 = Information.objects.create(
            title='Arbre sur la chaussée', location=Point(1, 1, srid=4326), crisis=crisis,
            first_name_information='A', last_name_information='B', email_information='a@t.fr',
            phone_information='0600000000', information_type=information_type, author=author,
        )
        i2 = Information.objects.create(
            title='Autre arbre', location=Point(1, 1, srid=4326), crisis=crisis,
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
        assert len(response.data['dossiers_created']) == 2
        assert response.data['already_assigned'] == []
        assert response.data['no_crisis'] == []
        assert set(team.assigned_informations.values_list('id', flat=True)) == {i1.id, i2.id}
        assert author in team.members.all()
        for i in (i1, i2):
            dossier = Dossier.objects.get(information=i)
            assert dossier.equipe_id == team.id
            assert dossier.crise_id == crisis.id
            assert dossier.statut == Dossier.Statut.AFFECTE
        assert {m.to[0] for m in mail.outbox} == {'a@t.fr', 'c@t.fr'}

    def test_bulk_assign_is_noop_for_already_assigned_information(self, authenticated_client, information_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        i1 = Information.objects.create(
            title='Arbre sur la chaussée', location=Point(1, 1, srid=4326), crisis=crisis,
            first_name_information='A', last_name_information='B', email_information='a@t.fr',
            phone_information='0600000000', information_type=information_type,
        )
        team = Team.objects.create(name='Voirie')

        first = client.post(
            reverse('information-bulk-assign-team'),
            {'information_ids': [str(i1.id)], 'team': str(team.id)},
            format='json',
        )
        assert len(first.data['dossiers_created']) == 1

        second = client.post(
            reverse('information-bulk-assign-team'),
            {'information_ids': [str(i1.id)], 'team': str(team.id)},
            format='json',
        )
        assert second.data['dossiers_created'] == []
        assert second.data['already_assigned'] == [str(i1.id)]
        assert Dossier.objects.filter(information=i1).count() == 1

    def test_bulk_assign_skips_dossier_for_crisis_less_information(self, authenticated_client, information_type):
        client, _ = _make_admin(authenticated_client)
        i1 = Information.objects.create(
            title='Arbre sur la chaussée', location=Point(1, 1, srid=4326),
            first_name_information='A', last_name_information='B', email_information='a@t.fr',
            phone_information='0600000000', information_type=information_type,
        )
        team = Team.objects.create(name='Voirie')

        response = client.post(
            reverse('information-bulk-assign-team'),
            {'information_ids': [str(i1.id)], 'team': str(team.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['dossiers_created'] == []
        assert response.data['no_crisis'] == [str(i1.id)]
        assert not Dossier.objects.filter(information=i1).exists()

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


@pytest.mark.django_db
class TestRequestLocationVisibleToDossierParticipant:
    """Un bénévole n'a pas de rôle institutionnel, mais doit voir la localisation précise
    d'une demande dont il est participant (via son équipe) — sinon impossible d'intervenir."""

    def test_team_member_sees_precise_location(self, create_user, request_type):
        crisis = _make_crisis(location=Point(0.0, 0.0, srid=4326))
        demande = _make_request(crisis, request_type, location=Point(2.5, 3.5, srid=4326))
        team = Team.objects.create(name='Equipe voirie')
        benevole = create_user(username='benevole-loc@test.fr', email='benevole-loc@test.fr', type='UTIL_SIMPLE')
        team.members.add(benevole)
        dossier = Dossier.objects.create(
            numero='DOS-LOCVIS', crise=crisis, equipe=team, demande=demande, titre='Test',
        )
        DossierParticipant.objects.create(dossier=dossier, utilisateur=benevole, role=DossierParticipant.Role.EQUIPE)

        client = APIClient()
        client.force_authenticate(user=benevole)
        response = client.get(reverse('request-detail', args=[demande.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] == pytest.approx(3.5)
        assert response.data['longitude'] == pytest.approx(2.5)

    def test_unrelated_user_does_not_see_precise_location(self, create_user, request_type):
        crisis = _make_crisis()
        demande = _make_request(crisis, request_type)
        unrelated = create_user(username='sans-lien@test.fr', email='sans-lien@test.fr', type='UTIL_SIMPLE')

        client = APIClient()
        client.force_authenticate(user=unrelated)
        response = client.get(reverse('request-detail', args=[demande.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None


@pytest.mark.django_db
class TestDossierLatitudeLongitude:

    def test_dossier_exposes_location_from_its_demande(self, authenticated_client, request_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        demande = _make_request(crisis, request_type, location=Point(2.5, 3.5, srid=4326))
        team = Team.objects.create(name='Equipe loc')
        dossier = Dossier.objects.create(
            numero='DOS-DOSSLOC', crise=crisis, equipe=team, demande=demande, titre='Test',
        )

        response = client.get(reverse('dossier-detail', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] == pytest.approx(3.5)
        assert response.data['longitude'] == pytest.approx(2.5)

    def test_dossier_exposes_description_from_its_demande(self, authenticated_client, request_type):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        demande = _make_request(crisis, request_type, description='Une cuve de 500L disponible')
        team = Team.objects.create(name='Equipe desc')
        dossier = Dossier.objects.create(
            numero='DOS-DESCORIGINE', crise=crisis, equipe=team, demande=demande, titre='Test',
        )

        response = client.get(reverse('dossier-detail', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['description_origine'] == 'Une cuve de 500L disponible'
        # Le champ "description" du dossier lui-même reste le texte auto-généré, pas confondu.
        assert response.data['description_origine'] != response.data['description']

    def test_dossier_without_origin_has_no_location(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team = Team.objects.create(name='Equipe sans origine')
        dossier = Dossier.objects.create(numero='DOS-SANSORIGINE', crise=crisis, equipe=team, titre='Test')

        response = client.get(reverse('dossier-detail', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None


@pytest.mark.django_db
class TestTeamMembersInfo:

    def test_members_info_exposes_id_and_name_without_pii(self, authenticated_client, create_user):
        client, _ = _make_admin(authenticated_client)
        membre = create_user(username='membre-info@test.fr', email='membre-info@test.fr', type='UTIL_SIMPLE', first_name='Alice', last_name='Martin')
        team = Team.objects.create(name='Equipe info')
        team.members.add(membre)

        response = client.get(reverse('team-detail', args=[team.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['members_info'] == [{'id': str(membre.id), 'nom': 'Alice Martin'}]
        assert 'email' not in response.data['members_info'][0]


@pytest.mark.django_db
class TestMissionVisibility:

    def test_institutional_actor_sees_all_missions(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team = Team.objects.create(name='Equipe non liée')
        Mission.objects.create(titre='Mission X', crise=crisis)

        response = client.get(reverse('mission-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_team_member_sees_only_missions_of_own_team(self, create_user):
        crisis = _make_crisis()
        team_membre = Team.objects.create(name='Equipe du membre')
        team_autre = Team.objects.create(name='Autre equipe')
        membre = create_user(username='membre-mission@test.fr', email='membre-mission@test.fr', type='UTIL_SIMPLE')
        team_membre.members.add(membre)

        mission_visible = Mission.objects.create(titre='Mission visible', crise=crisis)
        mission_visible.equipes.add(team_membre)
        mission_cachee = Mission.objects.create(titre='Mission cachée', crise=crisis)
        mission_cachee.equipes.add(team_autre)

        client = APIClient()
        client.force_authenticate(user=membre)
        response = client.get(reverse('mission-list'))

        assert response.status_code == status.HTTP_200_OK
        titres = [row['titre'] for row in response.data]
        assert 'Mission visible' in titres
        assert 'Mission cachée' not in titres

    def test_non_institutional_cannot_create_mission(self, create_user):
        crisis = _make_crisis()
        simple_user = create_user(username='pas-institutionnel@test.fr', email='pas-institutionnel@test.fr', type='UTIL_SIMPLE')

        client = APIClient()
        client.force_authenticate(user=simple_user)
        response = client.post(reverse('mission-list'), {'titre': 'Nouvelle mission', 'crise': str(crisis.id)})

        assert response.status_code == status.HTTP_403_FORBIDDEN
