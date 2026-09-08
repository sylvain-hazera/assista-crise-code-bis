import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Besoin, ContactInstitution, Crisis, Dossier, Institution, InstitutionType,
    Notification, Plan, PlanMissionModele, PointOperationnel, PointType, Team, Zone,
)


def _make_institution(nom, code):
    itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={'libelle': 'Test'})
    return Institution.objects.create(nom=nom, type=itype)


@pytest.fixture
def institution_a():
    # code MAIRIE (et pas un code arbitraire) : ZoneViewSet.perform_create réserve la création
    # de zones aux mairies/EPCI (préparation PCS/PICS), voir _institution_est_autorite_locale.
    return _make_institution('Mairie Dispositif A', 'MAIRIE')


@pytest.fixture
def institution_b():
    return _make_institution('Mairie Dispositif B', 'MAIRIE')


@pytest.fixture
def acteur_a(create_user, institution_a):
    user = create_user(username='acteur-dispositif-a@test.fr', email='acteur-dispositif-a@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    return user


@pytest.fixture
def acteur_b(create_user, institution_b):
    user = create_user(username='acteur-dispositif-b@test.fr', email='acteur-dispositif-b@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_b, utilisateur=user, actif=True)
    return user


@pytest.fixture
def client_a(acteur_a):
    client = APIClient()
    client.force_authenticate(user=acteur_a)
    return client


@pytest.fixture
def client_b(acteur_b):
    client = APIClient()
    client.force_authenticate(user=acteur_b)
    return client


@pytest.fixture
def point_type():
    return PointType.objects.create(code='TEST_DISPOSITIF', libelle='Test dispositif', actif=True)


@pytest.mark.django_db
class TestZoneViewSet:

    def test_create_resolves_own_institution(self, client_a, institution_a):
        response = client_a.post(reverse('zone-list'), {'nom': 'Quartier Nord'}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data['institution']) == str(institution_a.id)

    def test_create_rejects_foreign_institution(self, client_a, institution_b):
        response = client_a.post(
            reverse('zone-list'), {'nom': 'Quartier Nord', 'institution': str(institution_b.id)}, format='json'
        )
        # L'institution demandée n'est pas la sienne : retombe sur sa propre institution active,
        # jamais celle d'un tiers.
        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data['institution']) != str(institution_b.id)

    def test_list_scoped_to_own_institution(self, client_a, client_b, institution_a, institution_b):
        Zone.objects.create(institution=institution_a, nom='Zone A')
        Zone.objects.create(institution=institution_b, nom='Zone B')

        response_a = client_a.get(reverse('zone-list'))
        noms_a = {z['nom'] for z in response_a.data}
        assert 'Zone A' in noms_a
        assert 'Zone B' not in noms_a

    def test_destroy_deactivates_not_deletes(self, client_a, institution_a):
        zone = Zone.objects.create(institution=institution_a, nom='Zone à retirer')
        response = client_a.delete(reverse('zone-detail', args=[zone.id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        zone.refresh_from_db()
        assert zone.actif is False


@pytest.mark.django_db
class TestPlanViewSet:

    def test_create_and_attach_members(self, client_a, institution_a):
        zone = Zone.objects.create(institution=institution_a, nom='Zone A')
        team = Team.objects.create(name='Equipe A', institution=institution_a)

        response = client_a.post(
            reverse('plan-list'),
            {'nom': 'Plan canicule', 'zones_ids': [str(zone.id)], 'equipes_ids': [str(team.id)]},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data['institution']) == str(institution_a.id)
        assert response.data['zones_noms'] == ['Zone A']
        assert response.data['equipes_noms'] == ['Equipe A']

    def test_list_scoped_to_own_institution(self, client_a, client_b, institution_a, institution_b):
        Plan.objects.create(institution=institution_a, nom='Plan A')
        Plan.objects.create(institution=institution_b, nom='Plan B')

        response_a = client_a.get(reverse('plan-list'))
        noms_a = {p['nom'] for p in response_a.data}
        assert 'Plan A' in noms_a
        assert 'Plan B' not in noms_a


@pytest.mark.django_db
class TestPlanActiver:

    def test_activates_teams_and_points_on_existing_crisis(self, client_a, institution_a, point_type):
        team = Team.objects.create(name='Equipe Activation', institution=institution_a)
        point = PointOperationnel.objects.create(nom='Point Activation', type=point_type)
        plan = Plan.objects.create(institution=institution_a, nom='Plan test')
        plan.equipes.add(team)
        plan.points.add(point)

        crise = Crisis.objects.create(name='Crise cible', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}], 'points': [str(point.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        point.refresh_from_db()
        assert crise in team.assigned_crises.all()
        assert point.crise_id == crise.id

    def test_replaces_team_themes_when_provided(self, client_a, institution_a, point_type):
        theme_conserve = Besoin.objects.create(nom='ZZ Thème conservé')
        theme_retire = Besoin.objects.create(nom='ZZ Thème retiré')
        theme_ajoute = Besoin.objects.create(nom='ZZ Thème ajouté')

        team = Team.objects.create(name='Equipe Thèmes', institution=institution_a)
        team.themes.set([theme_conserve, theme_retire])
        plan = Plan.objects.create(institution=institution_a, nom='Plan thèmes')
        plan.equipes.add(team)

        crise = Crisis.objects.create(name='Crise thèmes', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {
                'crise_id': str(crise.id),
                'equipes': [{'team_id': str(team.id), 'themes_ids': [str(theme_conserve.id), str(theme_ajoute.id)]}],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        theme_ids = set(team.themes.values_list('id', flat=True))
        assert theme_ids == {theme_conserve.id, theme_ajoute.id}

    def test_keeps_current_themes_when_not_provided(self, client_a, institution_a):
        theme = Besoin.objects.create(nom='ZZ Thème inchangé')
        team = Team.objects.create(name='Equipe Thèmes Inchangés', institution=institution_a)
        team.themes.set([theme])
        plan = Plan.objects.create(institution=institution_a, nom='Plan sans override')
        plan.equipes.add(team)

        crise = Crisis.objects.create(name='Crise sans override', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert list(team.themes.values_list('id', flat=True)) == [theme.id]

    def test_ignores_team_not_in_plan(self, client_a, institution_a):
        plan = Plan.objects.create(institution=institution_a, nom='Plan restreint')
        equipe_hors_plan = Team.objects.create(name='Equipe hors plan', institution=institution_a)
        crise = Crisis.objects.create(name='Crise spoof', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(equipe_hors_plan.id)}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        equipe_hors_plan.refresh_from_db()
        assert crise not in equipe_hors_plan.assigned_crises.all()
        assert response.data['equipes_activees'] == []

    def test_idempotent_reactivation(self, client_a, institution_a):
        team = Team.objects.create(name='Equipe Idempotente', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan idempotent')
        plan.equipes.add(team)
        crise = Crisis.objects.create(name='Crise idempotente', location=Point(5.7, 45.2, srid=4326))

        payload = {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}]}
        first = client_a.post(reverse('plan-activer', args=[plan.id]), payload, format='json')
        second = client_a.post(reverse('plan-activer', args=[plan.id]), payload, format='json')

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert list(team.assigned_crises.values_list('id', flat=True)) == [crise.id]

    def test_creates_crisis_inline(self, client_a, institution_a):
        team = Team.objects.create(name='Equipe Nouvelle Crise', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan nouvelle crise')
        plan.equipes.add(team)

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {
                'nouvelle_crise': {
                    'name': 'Crise créée à l’activation',
                    'type': 'INCENDIE',
                    'location': '{"type": "Point", "coordinates": [5.72, 45.18]}',
                },
                'equipes': [{'team_id': str(team.id)}],
            },
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['crise']['name'] == 'Crise créée à l’activation'
        team.refresh_from_db()
        assert team.assigned_crises.filter(name='Crise créée à l’activation').exists()

    def test_not_found_for_other_institution(self, client_b, institution_a):
        # get_queryset() scope le plan à l'institution de l'appelant (ou admin) pour TOUTE
        # action, y compris activer : un plan d'une autre institution n'existe simplement pas
        # pour cet appelant, jamais un 403 qui confirmerait son existence.
        plan = Plan.objects.create(institution=institution_a, nom='Plan protégé')
        crise = Crisis.objects.create(name='Crise protégée', location=Point(5.7, 45.2, srid=4326))

        response = client_b.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': []},
            format='json',
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPlanActiverNotifications:
    """Avant ce correctif, PlanViewSet.activer n'écrivait qu'un audit_log : aucun responsable
    (leader/régulateur d'équipe, responsable de point) n'était notifié des moyens effectivement
    mobilisés sur la crise."""

    def test_notifies_team_leader_and_regulateur(self, client_a, institution_a, create_user):
        leader = create_user(username='leader-notif-plan@test.fr', email='leader-notif-plan@test.fr', type='AUT_LOCALE')
        regulateur = create_user(username='regul-notif-plan@test.fr', email='regul-notif-plan@test.fr', type='AUT_LOCALE')
        team = Team.objects.create(name='Equipe Notif', institution=institution_a, leader=leader, regulateur=regulateur)
        plan = Plan.objects.create(institution=institution_a, nom='Plan notif équipe')
        plan.equipes.add(team)
        crise = Crisis.objects.create(name='Crise notif équipe', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        for user in (leader, regulateur):
            assert Notification.objects.filter(utilisateur=user, crise=crise, titre__icontains='Plan activé').exists()
            assert any(user.email in m.to for m in mail.outbox)

    def test_notifies_point_responsable_and_responsables(self, client_a, institution_a, point_type, create_user):
        responsable = create_user(username='resp-notif-plan@test.fr', email='resp-notif-plan@test.fr', type='AUT_LOCALE')
        autre_responsable = create_user(username='resp2-notif-plan@test.fr', email='resp2-notif-plan@test.fr', type='AUT_LOCALE')
        point = PointOperationnel.objects.create(nom='Point Notif', type=point_type, responsable=responsable)
        point.responsables.add(autre_responsable)
        plan = Plan.objects.create(institution=institution_a, nom='Plan notif point')
        plan.points.add(point)
        crise = Crisis.objects.create(name='Crise notif point', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'points': [str(point.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        for user in (responsable, autre_responsable):
            assert Notification.objects.filter(utilisateur=user, crise=crise, titre__icontains='Plan activé').exists()
            assert any(user.email in m.to for m in mail.outbox)

    def test_no_notification_for_teams_or_points_not_activated(self, client_a, institution_a, create_user):
        leader = create_user(username='leader-hors-plan@test.fr', email='leader-hors-plan@test.fr', type='AUT_LOCALE')
        team_dans_plan = Team.objects.create(name='Equipe activée', institution=institution_a)
        team_hors_plan = Team.objects.create(name='Equipe non activée', institution=institution_a, leader=leader)
        plan = Plan.objects.create(institution=institution_a, nom='Plan partiel')
        plan.equipes.add(team_dans_plan, team_hors_plan)
        crise = Crisis.objects.create(name='Crise partielle', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team_dans_plan.id)}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert not Notification.objects.filter(utilisateur=leader, crise=crise).exists()


@pytest.mark.django_db
class TestClotureNonRegression:
    """S'assure que ce chantier n'a rien changé au comportement de clôture d'une crise (voir
    décision explicite du plan : la réutilisabilité vient de Plan, pas d'un détachement à la
    clôture, pour ne pas casser l'export main courante)."""

    def test_cloturer_does_not_detach_points_or_teams(self, create_user, institution_a, point_type):
        responsable = create_user(username='resp-cloture@test.fr', email='resp-cloture@test.fr', type='AUT_LOCALE')
        crise = Crisis.objects.create(name='Crise à clôturer', location=Point(5.7, 45.2, srid=4326))
        from core.models import ImplicationInstitution, TypeImplication
        ImplicationInstitution.objects.create(
            crise=crise, institution=institution_a, responsable=responsable,
            type_implication=TypeImplication.ACTEUR, actif=True,
        )
        point = PointOperationnel.objects.create(nom='Point clôture', type=point_type, crise=crise)
        team = Team.objects.create(name='Equipe clôture', institution=institution_a)
        team.assigned_crises.add(crise)

        client = APIClient()
        client.force_authenticate(user=responsable)
        response = client.post(reverse('crisis-cloturer', args=[crise.id]))

        assert response.status_code == status.HTTP_200_OK
        point.refresh_from_db()
        assert point.crise_id == crise.id
        assert crise in team.assigned_crises.all()


@pytest.mark.django_db
class TestPlanMissionModeleViewSet:

    def test_create_for_own_institution_plan(self, client_a, institution_a):
        team = Team.objects.create(name='Equipe surveillance crue', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan crue')
        plan.equipes.add(team)

        response = client_a.post(
            reverse('planmissionmodele-list'),
            {'plan': str(plan.id), 'equipe': str(team.id), 'titre': 'Patrouille le long des berges'},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['titre'] == 'Patrouille le long des berges'

    def test_rejects_team_not_in_plan(self, client_a, institution_a):
        team_hors_plan = Team.objects.create(name='Equipe hors plan modele', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan sans équipe')

        response = client_a.post(
            reverse('planmissionmodele-list'),
            {'plan': str(plan.id), 'equipe': str(team_hors_plan.id), 'titre': 'Mission invalide'},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_foreign_institution_plan(self, client_b, institution_a):
        team = Team.objects.create(name='Equipe institution A modele', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan A modele')
        plan.equipes.add(team)

        response = client_b.post(
            reverse('planmissionmodele-list'),
            {'plan': str(plan.id), 'equipe': str(team.id), 'titre': 'Mission volée'},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPlanActiverInstancieMissions:
    """Instanciation d'une Mission + d'un Dossier réels depuis un PlanMissionModele à
    l'activation de l'équipe correspondante — voir _instancier_mission_modele."""

    def test_activer_instancie_mission_avec_referent_seul_participant(self, client_a, institution_a, create_user):
        referent = create_user(username='elu-referent@test.fr', email='elu-referent@test.fr', type='AUT_LOCALE')
        autre_membre = create_user(username='autre-membre-equipe@test.fr', email='autre-membre-equipe@test.fr', type='AUT_LOCALE')
        team = Team.objects.create(name='Equipe surveillance crue instanciation', institution=institution_a)
        team.members.add(autre_membre)
        plan = Plan.objects.create(institution=institution_a, nom='Plan crue instanciation')
        plan.equipes.add(team)
        PlanMissionModele.objects.create(
            plan=plan, equipe=team, titre='Patrouille le long des berges',
            description='Surveiller la montée des eaux', referent=referent,
        )
        crise = Crisis.objects.create(name='Crise crue', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['dossiers_crees']) == 1

        dossier = Dossier.objects.get(id=response.data['dossiers_crees'][0])
        assert dossier.titre == 'Patrouille le long des berges'
        assert dossier.crise_id == crise.id
        assert dossier.equipe_id == team.id
        assert dossier.demande is None
        assert dossier.mission is not None
        assert dossier.mission.modele_origine_id is not None
        assert team in dossier.mission.equipes.all()

        participants_equipe = set(
            dossier.participants.filter(role='EQUIPE').values_list('utilisateur_id', flat=True)
        )
        # Seul le référent désigné, PAS tous les membres de l'équipe (contrairement à
        # TeamViewSet.creer_dossier) — une mission de plan est typiquement confiée à une
        # personne précise, pas à toute l'équipe.
        assert participants_equipe == {referent.id}
        assert autre_membre.id not in participants_equipe

    def test_activer_ne_cree_pas_de_mission_sans_modele(self, client_a, institution_a):
        team = Team.objects.create(name='Equipe sans modele', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan sans modele')
        plan.equipes.add(team)
        crise = Crisis.objects.create(name='Crise sans modele', location=Point(5.7, 45.2, srid=4326))

        response = client_a.post(
            reverse('plan-activer', args=[plan.id]),
            {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['dossiers_crees'] == []

    def test_activer_reste_idempotent_pour_les_missions(self, client_a, institution_a):
        team = Team.objects.create(name='Equipe idempotente modele', institution=institution_a)
        plan = Plan.objects.create(institution=institution_a, nom='Plan idempotent modele')
        plan.equipes.add(team)
        PlanMissionModele.objects.create(plan=plan, equipe=team, titre='Mission répétée')
        crise = Crisis.objects.create(name='Crise idempotente modele', location=Point(5.7, 45.2, srid=4326))
        payload = {'crise_id': str(crise.id), 'equipes': [{'team_id': str(team.id)}]}

        first = client_a.post(reverse('plan-activer', args=[plan.id]), payload, format='json')
        second = client_a.post(reverse('plan-activer', args=[plan.id]), payload, format='json')

        assert len(first.data['dossiers_crees']) == 1
        assert second.data['dossiers_crees'] == []
        assert Dossier.objects.filter(crise=crise, titre='Mission répétée').count() == 1
