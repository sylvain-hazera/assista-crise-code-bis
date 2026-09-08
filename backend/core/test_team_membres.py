import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType,
    RoleOperationnel, Team, User,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_MEMBRES', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test membres', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie A')


@pytest.fixture
def institution_b():
    return _make_institution(nom='Mairie B')


@pytest.fixture
def role_responsable():
    return RoleOperationnel.objects.create(code='RESP_TEST_MEMBRES', libelle="Chef d'équipe")


@pytest.fixture
def mairie_client(create_user, institution_a):
    user = create_user(username='mairie-a@test.fr', email='mairie-a@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def team_a(institution_a):
    return Team.objects.create(name='Équipe A', institution=institution_a)


@pytest.mark.django_db
class TestUserListFilteredByInstitution:

    def test_institution_filter_returns_only_active_contacts(self, create_user, institution_a, institution_b):
        admin = create_user(username='admin-membres@test.fr', email='admin-membres@test.fr', type='ADMIN')
        membre_a = create_user(username='membre-a@test.fr', email='membre-a@test.fr', type='UTIL_SIMPLE')
        membre_b = create_user(username='membre-b@test.fr', email='membre-b@test.fr', type='UTIL_SIMPLE')
        inactif_a = create_user(username='inactif-a@test.fr', email='inactif-a@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=membre_a, actif=True)
        ContactInstitution.objects.create(institution=institution_b, utilisateur=membre_b, actif=True)
        ContactInstitution.objects.create(institution=institution_a, utilisateur=inactif_a, actif=False)

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('user-list'), {'institution': str(institution_a.id)})

        assert response.status_code == status.HTTP_200_OK
        emails = {u['email'] for u in response.data}
        assert emails == {'membre-a@test.fr'}

    def test_without_institution_param_returns_all(self, create_user, institution_a):
        admin = create_user(username='admin-membres2@test.fr', email='admin-membres2@test.fr', type='ADMIN')
        create_user(username='autre@test.fr', email='autre@test.fr', type='UTIL_SIMPLE')

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('user-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 2

    def test_repeated_institution_param_searches_across_both(self, create_user, institution_a, institution_b):
        # Recherche de membres à rattacher à une équipe déléguée : doit porter sur l'institution
        # responsable ET l'institution délégataire à la fois.
        admin = create_user(username='admin-membres3@test.fr', email='admin-membres3@test.fr', type='ADMIN')
        membre_a = create_user(username='membre-a3@test.fr', email='membre-a3@test.fr', type='UTIL_SIMPLE')
        membre_b = create_user(username='membre-b3@test.fr', email='membre-b3@test.fr', type='UTIL_SIMPLE')
        membre_c = create_user(username='membre-c3@test.fr', email='membre-c3@test.fr', type='UTIL_SIMPLE')
        institution_c = _make_institution(nom='Mairie C')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=membre_a, actif=True)
        ContactInstitution.objects.create(institution=institution_b, utilisateur=membre_b, actif=True)
        ContactInstitution.objects.create(institution=institution_c, utilisateur=membre_c, actif=True)

        client = APIClient()
        client.force_authenticate(user=admin)
        from django.http import QueryDict
        qs = QueryDict(mutable=True)
        qs.setlist('institution', [str(institution_a.id), str(institution_b.id)])
        response = client.get(f"{reverse('user-list')}?{qs.urlencode()}")

        assert response.status_code == status.HTTP_200_OK
        emails = {u['email'] for u in response.data}
        assert emails == {'membre-a3@test.fr', 'membre-b3@test.fr'}


@pytest.mark.django_db
class TestInviterMembre:

    def test_invite_creates_inactive_local_authority_account(self, mairie_client, team_a, role_responsable):
        client, _ = mairie_client
        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'Alice', 'last_name': 'Martin', 'email': 'alice.martin@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email='alice.martin@test.fr')
        assert user.type == 'AUT_LOCALE'
        assert user.enabled is False
        assert user.is_active is False
        assert team_a.members.filter(id=user.id).exists()
        assert ContactInstitution.objects.filter(institution=team_a.institution, utilisateur=user, actif=True).exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['alice.martin@test.fr']

    def test_invite_reuses_existing_account_without_downgrading_type(self, mairie_client, team_a, role_responsable, create_user):
        client, _ = mairie_client
        existing = create_user(username='existant@test.fr', email='existant@test.fr', type='ADMIN')

        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'X', 'last_name': 'Y', 'email': 'existant@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        existing.refresh_from_db()
        assert existing.type == 'ADMIN'
        assert team_a.members.filter(id=existing.id).exists()

    def test_invite_rejects_missing_fields(self, mairie_client, team_a, role_responsable):
        client, _ = mairie_client
        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': '', 'last_name': 'Martin', 'email': 'x@test.fr', 'role_code': role_responsable.code,
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invite_rejects_unknown_role(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'ab@test.fr',
            'phone_number': '0600000000', 'role_code': 'CODE_INEXISTANT',
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_invite_into_another_institution_team(self, create_user, institution_a, institution_b, role_responsable):
        team_b = Team.objects.create(name='Équipe B', institution=institution_b)
        mairie_a_user = create_user(username='mairie-a2@test.fr', email='mairie-a2@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=mairie_a_user, actif=True)
        client = APIClient()
        client.force_authenticate(user=mairie_a_user)

        response = client.post(reverse('team-inviter-membre', args=[team_b.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'cross@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_invite_into_any_institution_team(self, create_user, team_a, role_responsable):
        admin = create_user(username='admin-invite@test.fr', email='admin-invite@test.fr', type='ADMIN')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'admin-invited@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED

    def test_rejects_team_without_institution(self, create_user, role_responsable):
        admin = create_user(username='admin-noinst@test.fr', email='admin-noinst@test.fr', type='ADMIN')
        team = Team.objects.create(name='Équipe orpheline')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('team-inviter-membre', args=[team.id]), {
            'first_name': 'A', 'last_name': 'B', 'email': 'orph@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delegataire_invite_attaches_to_delegated_institution(self, create_user, team_a, role_responsable, institution_a, institution_b):
        # Une équipe déléguée à la mairie B : un référent de la mairie B qui invite quelqu'un le
        # rattache à SA propre institution (B), pas à celle du responsable (A).
        team_a.institution_delegataire = institution_b
        team_a.save(update_fields=['institution_delegataire'])
        deleg_user = create_user(username='deleg-inviteur@test.fr', email='deleg-inviteur@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=deleg_user, actif=True)
        client = APIClient()
        client.force_authenticate(user=deleg_user)

        response = client.post(reverse('team-inviter-membre', args=[team_a.id]), {
            'first_name': 'D', 'last_name': 'E', 'email': 'invite-via-delegation@test.fr',
            'phone_number': '0600000000', 'role_code': role_responsable.code,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        invited = User.objects.get(email='invite-via-delegation@test.fr')
        assert invited.institution_id == institution_b.id
        assert ContactInstitution.objects.filter(institution=institution_b, utilisateur=invited, actif=True).exists()


@pytest.mark.django_db
class TestPatchScopedToOwnTeam:
    """Avant ce correctif, un PATCH générique sur une équipe n'était scopé par aucune
    vérification d'appartenance — tout acteur institutionnel pouvait modifier une équipe
    d'une institution tierce tant qu'il ne touchait pas le champ `institution` lui-même."""

    def test_cannot_patch_another_institutions_team(self, create_user, institution_a, institution_b):
        team_b = Team.objects.create(name='Équipe B', institution=institution_b)
        mairie_a_user = create_user(username='patch-cross-a@test.fr', email='patch-cross-a@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=mairie_a_user, actif=True)
        client = APIClient()
        client.force_authenticate(user=mairie_a_user)

        response = client.patch(reverse('team-detail', args=[team_b.id]), {'color': '#000000'}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_own_institution_can_still_patch(self, mairie_client, team_a):
        client, _ = mairie_client
        response = client.patch(reverse('team-detail', args=[team_a.id]), {'color': '#123456'}, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_orphan_team_still_patchable_by_any_institutional_actor(self, create_user):
        team = Team.objects.create(name='Équipe orpheline patch')
        itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_MEMBRES', defaults={'libelle': 'Test'})
        institution = Institution.objects.create(nom='Mairie orpheline patch', type=itype)
        user = create_user(username='patch-orphan@test.fr', email='patch-orphan@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(reverse('team-detail', args=[team.id]), {'color': '#abcdef'}, format='json')

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_patch_any_team(self, create_user, institution_b):
        team_b = Team.objects.create(name='Équipe B admin patch', institution=institution_b)
        admin = create_user(username='admin-patch-cross@test.fr', email='admin-patch-cross@test.fr', type='ADMIN')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(reverse('team-detail', args=[team_b.id]), {'color': '#ffffff'}, format='json')

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestMembreInstitutionLiee:
    """Ajout d'un membre appartenant à une institution tierce, restreint aux institutions
    "déjà liées" à celle de l'équipe : sa délégataire, ou une institution co-impliquée avec
    elle sur une même crise (voir _institutions_liees)."""

    def test_cannot_add_member_from_unrelated_institution(self, mairie_client, team_a, institution_b, create_user):
        client, _ = mairie_client
        outsider = create_user(username='outsider-membre@test.fr', email='outsider-membre@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=outsider, actif=True)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(outsider.id)]}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not team_a.members.filter(id=outsider.id).exists()

    def test_can_add_member_from_delegated_institution(self, mairie_client, team_a, institution_b, create_user):
        team_a.institution_delegataire = institution_b
        team_a.save(update_fields=['institution_delegataire'])
        client, _ = mairie_client
        deleg_member = create_user(username='deleg-membre@test.fr', email='deleg-membre@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=deleg_member, actif=True)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(deleg_member.id)]}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.members.filter(id=deleg_member.id).exists()

    def test_can_add_member_from_institution_co_implicated_on_same_crisis(self, mairie_client, team_a, institution_a, institution_b, create_user):
        crisis = Crisis.objects.create(name='Crise liée test', type='INCENDIE', location='POINT (5.72 45.18)')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_a, type_implication='ACTEUR')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_b, type_implication='IMPLIQUE')
        # L'équipe doit être elle-même affectée à CETTE crise pour que la co-implication compte
        # (voir _institutions_liees) — sans ça, une équipe sans aucun lien avec l'incendie
        # exposerait quand même le personnel d'une institution co-actrice, simplement parce que
        # sa propre institution y participe par ailleurs.
        team_a.assigned_crises.add(crisis)
        client, _ = mairie_client
        liee_member = create_user(username='liee-membre@test.fr', email='liee-membre@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=liee_member, actif=True)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(liee_member.id)]}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.members.filter(id=liee_member.id).exists()

    def test_cannot_add_member_from_institution_implicated_on_an_unrelated_crisis(self, mairie_client, team_a, institution_a, institution_b, create_user):
        """Régression : institution_a (celle de team_a) est actrice d'un incident SANS AUCUN
        RAPPORT avec team_a (team_a.assigned_crises reste vide) — institution_b, co-actrice de
        ce même incident, ne devient PAS "liée" à team_a pour autant (avant ce correctif, elle
        l'aurait été, exposant tout son personnel à n'importe quelle équipe de institution_a,
        même sans lien avec la crise en question)."""
        crisis = Crisis.objects.create(name='Incident sans lien avec team_a', type='INCENDIE', location='POINT (5.72 45.18)')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_a, type_implication='ACTEUR')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_b, type_implication='IMPLIQUE')
        client, _ = mairie_client
        outsider = create_user(username='outsider-crise-non-liee@test.fr', email='outsider-crise-non-liee@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=outsider, actif=True)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(outsider.id)]}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not team_a.members.filter(id=outsider.id).exists()

    def test_admin_can_add_member_from_any_institution(self, create_user, team_a, institution_b):
        admin = create_user(username='admin-add-cross@test.fr', email='admin-add-cross@test.fr', type='ADMIN')
        outsider = create_user(username='outsider-admin-add@test.fr', email='outsider-admin-add@test.fr', type='UTIL_SIMPLE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=outsider, actif=True)
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(outsider.id)]}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.members.filter(id=outsider.id).exists()

    def test_can_add_member_with_no_institution_at_all(self, mairie_client, team_a, create_user):
        # Cas normal : un bénévole ordinaire, sans aucun ContactInstitution (ex: l'auteur d'une
        # offre rattaché automatiquement à une équipe depuis ReportingComponent) — ne doit
        # jamais être bloqué par cette validation, seule une affiliation à une institution
        # TIERCE l'est.
        client, _ = mairie_client
        volontaire = create_user(username='volontaire-sans-institution@test.fr', email='volontaire-sans-institution@test.fr', type='UTIL_SIMPLE')

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': [str(volontaire.id)]}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.members.filter(id=volontaire.id).exists()

    def test_removing_a_member_is_unaffected_by_this_validation(self, mairie_client, team_a, create_user):
        member = create_user(username='removable-membre@test.fr', email='removable-membre@test.fr', type='UTIL_SIMPLE')
        team_a.members.add(member)
        client, _ = mairie_client

        response = client.patch(reverse('team-detail', args=[team_a.id]), {'member_ids': []}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert not team_a.members.filter(id=member.id).exists()


@pytest.mark.django_db
class TestInstitutionsLiees:

    def test_lists_delegataire_and_co_implicated_institutions(self, mairie_client, team_a, institution_a, institution_b):
        team_c_institution = _make_institution(nom='Mairie C liée')
        crisis = Crisis.objects.create(name='Crise institutions liées', type='INCENDIE', location='POINT (5.72 45.18)')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_a, type_implication='ACTEUR')
        ImplicationInstitution.objects.create(crise=crisis, institution=team_c_institution, type_implication='IMPLIQUE')
        team_a.assigned_crises.add(crisis)
        team_a.institution_delegataire = institution_b
        team_a.save(update_fields=['institution_delegataire'])
        client, _ = mairie_client

        response = client.get(reverse('team-institutions-liees', args=[team_a.id]))

        assert response.status_code == status.HTTP_200_OK
        noms = {i['nom'] for i in response.data}
        assert noms == {institution_b.nom, team_c_institution.nom}

    def test_empty_for_team_without_institution(self, create_user):
        team = Team.objects.create(name='Équipe orpheline liées')
        admin = create_user(username='admin-liees-orph@test.fr', email='admin-liees-orph@test.fr', type='ADMIN')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('team-institutions-liees', args=[team.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_forbidden_for_unrelated_institutional_actor(self, create_user, team_a, institution_b):
        outsider = create_user(username='outsider-liees@test.fr', email='outsider-liees@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_b, utilisateur=outsider, actif=True)
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.get(reverse('team-institutions-liees', args=[team_a.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_excludes_institution_from_crisis_team_is_not_assigned_to(self, mairie_client, team_a, institution_a, institution_b):
        """Régression : team_a n'est affectée à AUCUNE crise — une co-implication entre
        institution_a (celle de team_a) et institution_b sur une crise sans rapport avec team_a
        ne doit rendre visible ni son personnel ni son nom dans ce sélecteur."""
        crisis = Crisis.objects.create(name='Crise sans team_a', type='INCENDIE', location='POINT (5.72 45.18)')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_a, type_implication='ACTEUR')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_b, type_implication='IMPLIQUE')
        client, _ = mairie_client

        response = client.get(reverse('team-institutions-liees', args=[team_a.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []


@pytest.mark.django_db
class TestInstitutionsLieesTypeActeur:
    """?type=acteur : sélecteur "institution délégataire" — avant ce correctif, teams.
    component.ts proposait TOUTES les institutions de la plateforme comme délégataire (aucun
    filtre côté frontend ni endpoint dédié côté backend), sans lien avec la crise de l'équipe."""

    def test_excludes_implique_only_institution(self, mairie_client, team_a, institution_a, institution_b):
        """IMPLIQUE (pas ACTEUR) : proposée pour le recrutement de membres (type par défaut),
        mais pas comme délégataire."""
        acteur_institution = _make_institution(nom='Mairie ACTEUR')
        crisis = Crisis.objects.create(name='Crise acteur/implique', type='INCENDIE', location='POINT (5.72 45.18)')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_a, type_implication='ACTEUR')
        ImplicationInstitution.objects.create(crise=crisis, institution=institution_b, type_implication='IMPLIQUE')
        ImplicationInstitution.objects.create(crise=crisis, institution=acteur_institution, type_implication='ACTEUR')
        team_a.assigned_crises.add(crisis)
        client, _ = mairie_client

        response = client.get(reverse('team-institutions-liees', args=[team_a.id]), {'type': 'acteur'})

        assert response.status_code == status.HTTP_200_OK
        noms = {i['nom'] for i in response.data}
        assert noms == {acteur_institution.nom}

    def test_current_delegataire_always_included_even_if_not_acteur(self, mairie_client, team_a, institution_a, institution_b):
        """Le délégataire déjà réglé (ex: posé avant ce correctif) reste visible dans le
        sélecteur même s'il n'est plus ACTEUR sur aucune crise commune — pour ne pas le faire
        disparaître silencieusement d'un formulaire d'édition."""
        team_a.institution_delegataire = institution_b
        team_a.save(update_fields=['institution_delegataire'])
        client, _ = mairie_client

        response = client.get(reverse('team-institutions-liees', args=[team_a.id]), {'type': 'acteur'})

        assert response.status_code == status.HTTP_200_OK
        assert {i['nom'] for i in response.data} == {institution_b.nom}
