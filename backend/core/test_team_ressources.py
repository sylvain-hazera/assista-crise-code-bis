import uuid

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

    def test_adds_member_via_email_for_anonymous_offer_with_material(self, mairie_client, team_a, offer_type):
        """La quasi-totalité des offres viennent du formulaire public (propose-help-form),
        soumis sans compte : author reste None. Repéré en direct (personne + matériel,
        matériel seul, personne seule : le compteur "Membres" restait toujours à 0) —
        resolve_or_invite_benevole doit créer/retrouver un compte via email_offer."""
        offer = Offer.objects.create(
            title='Tronçonneuse + moi-même', first_name_offer='Anna', last_name_offer='Nonyme',
            email_offer='anna-nonyme@test.fr', status='DISPONIBLE', offer_type=offer_type,
            author=None, presence_physique=True, materiel_type='AUTRE',
        )
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')

        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.members.filter(email__iexact='anna-nonyme@test.fr').exists()

    def test_adds_member_via_email_for_anonymous_offer_person_only(self, mairie_client, team_a, offer_type):
        """Personne seule sans matériel (ex: traducteur) — même correctif, aucune raison que
        ça se comporte différemment d'une offre avec matériel."""
        offer = Offer.objects.create(
            title='Traduction', first_name_offer='Traducteur', last_name_offer='Bénévole',
            email_offer='traducteur-benevole@test.fr', status='DISPONIBLE', offer_type=offer_type,
            author=None, presence_physique=True,
        )
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')

        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.members.filter(email__iexact='traducteur-benevole@test.fr').exists()

    def test_marks_offer_unavailable_once_retained(self, mairie_client, team_a, offer):
        """Une ressource retenue par une équipe ne doit plus apparaître disponible dans le
        tableau des offres/bénévoles (recherche de moyens disponibles) — sinon deux équipes
        pouvaient la retenir en même temps."""
        assert offer.status == 'DISPONIBLE'
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')

        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.status == 'INDISPONIBLE'

    def test_does_not_add_member_for_anonymous_material_only_offer(self, mairie_client, team_a, offer_type):
        """Matériel seul (presence_physique=False, ex: dépôt sans l'offreur) : toujours
        aucun membre ajouté, anonyme ou non — seule l'affectation de la ressource compte."""
        offer = Offer.objects.create(
            title='Groupe électrogène déposé', first_name_offer='Dépose', last_name_offer='Seul',
            email_offer='depose-seul@test.fr', status='DISPONIBLE', offer_type=offer_type,
            author=None, presence_physique=False, materiel_type='AUTRE',
        )
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')

        response = client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert team_a.assigned_offers.filter(id=offer.id).exists()
        assert not team_a.members.filter(email__iexact='depose-seul@test.fr').exists()


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

    def test_marks_offer_available_again_when_removed(self, mairie_client, team_a, offer):
        """Symétrique de test_marks_offer_unavailable_once_retained : la retirer la rend de
        nouveau disponible pour une autre équipe."""
        client, _ = mairie_client
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')
        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')
        offer.refresh_from_db()
        assert offer.status == 'INDISPONIBLE'

        client.post(reverse('team-retirer-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        offer.refresh_from_db()
        assert offer.status == 'DISPONIBLE'

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


@pytest.mark.django_db
class TestRessourcesMobilisees:
    """Récapitulatif personnes/matériel mobilisés — voir TeamViewSet.ressources_mobilisees,
    consommé par la page admin /admin/ressources-mobilisees."""

    def test_lists_members_and_material_offers_with_context(self, mairie_client, team_a, offer_type, institution_a):
        from core.models import AffectationRoleOperationnel, PointOperationnel, PointType, RoleOperationnel

        client, user = mairie_client
        team_a.members.add(user)
        role, _ = RoleOperationnel.objects.get_or_create(code='RESSOURCES_TEST_ROLE', defaults={'libelle': 'Régulateur'})
        AffectationRoleOperationnel.objects.create(utilisateur=user, institution=institution_a, role=role, actif=True)
        point_type, _ = PointType.objects.get_or_create(code='RESSOURCES_TEST_PT', defaults={'libelle': 'Point test'})
        PointOperationnel.objects.create(nom='Centre Ressources Test', type=point_type, equipe=team_a)

        # materiel_type explicitement posé (contrairement au fixture `offer` générique, qui n'a
        # aucune info matériel structurée) : c'est ce qui distingue une ligne "matériel" d'une
        # simple offre de bénévolat pur côté ressources_mobilisees (voir est_materiel).
        offer = Offer.objects.create(
            title='Cuve à prêter avec matériel', first_name_offer='O', last_name_offer='Ffreur',
            email_offer='offreur-materiel-test@test.fr', status='DISPONIBLE', offer_type=offer_type,
            materiel_type='CUVE',
        )

        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')
        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        response = client.get(reverse('team-ressources-mobilisees'))

        assert response.status_code == status.HTTP_200_OK
        personne_rows = [r for r in response.data if r['type'] == 'personne' and r['equipe_id'] == str(team_a.id)]
        materiel_rows = [r for r in response.data if r['type'] == 'materiel' and r['equipe_id'] == str(team_a.id)]
        assert any(r['nom'] == user.email or 'Régulateur' in (r['detail'] or '') for r in personne_rows)
        assert any(r['nom'] == offer.title and r['centres'] == ['Centre Ressources Test'] for r in materiel_rows)
        assert all(r['institution'] == institution_a.nom for r in personne_rows + materiel_rows)

    def test_pure_benevolat_offer_not_duplicated_as_material(self, mairie_client, team_a, offer_type):
        """Une offre de bénévolat pur (aucun matériel) ne doit pas apparaître une seconde fois
        comme ligne "matériel" — la personne qui la porte est déjà comptée côté membre."""
        client, _ = mairie_client
        benevole = Offer.objects.create(
            title='Bénévolat pur test', first_name_offer='A', last_name_offer='B',
            email_offer='benevole-pur@test.fr', status='DISPONIBLE', offer_type=offer_type,
        )
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')
        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(benevole.id)}, format='json')

        response = client.get(reverse('team-ressources-mobilisees'))

        assert response.status_code == status.HTTP_200_OK
        materiel_rows = [r for r in response.data if r['type'] == 'materiel' and r['equipe_id'] == str(team_a.id)]
        assert materiel_rows == []

    def test_requires_institutional_actor(self, api_client):
        response = api_client.get(reverse('team-ressources-mobilisees'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_authenticated_non_institutional_user_is_forbidden(self, create_user):
        user = create_user(username='simple-ress@test.fr', email='simple-ress@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse('team-ressources-mobilisees'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_admin_scoped_to_own_institution_only(self, mairie_client, team_a, create_user):
        """Corrigé le 2026-09-19 : une mairie ne doit voir QUE les ressources mobilisées de sa
        propre institution (ou d'une institution qui lui délègue une équipe) — pas celles d'une
        institution tierce sans aucun lien avec elle."""
        client, _ = mairie_client
        autre_institution = _make_institution(nom='Mairie Ressources B')
        autre_team = Team.objects.create(name='Équipe Ressources B', institution=autre_institution)
        # Un membre est nécessaire pour que cette équipe produise ne serait-ce qu'une ligne —
        # sinon l'assertion ci-dessous serait vraie même sans le correctif de portée.
        autre_membre = create_user(username='membre-ress-b@test.fr', email='membre-ress-b@test.fr')
        autre_team.members.add(autre_membre)

        response = client.get(reverse('team-ressources-mobilisees'))

        assert response.status_code == status.HTTP_200_OK
        assert not any(r['equipe_id'] == str(autre_team.id) for r in response.data)

    def test_non_admin_sees_delegated_team(self, mairie_client, institution_a, create_user):
        """Une institution délégataire d'une équipe (voir Team.institution_delegataire) doit
        aussi voir ses ressources mobilisées, pas seulement l'institution responsable — même
        périmètre que _appartient_a_equipe."""
        client, _ = mairie_client
        responsable = _make_institution(nom='Mairie Ressources Responsable')
        team_deleguee = Team.objects.create(
            name='Équipe Déléguée', institution=responsable, institution_delegataire=institution_a,
        )
        membre = create_user(username='membre-ress-deleg@test.fr', email='membre-ress-deleg@test.fr')
        team_deleguee.members.add(membre)

        response = client.get(reverse('team-ressources-mobilisees'))

        assert any(r['equipe_id'] == str(team_deleguee.id) for r in response.data)

    def test_admin_sees_all_institutions(self, create_user, team_a):
        autre_institution = _make_institution(nom='Mairie Ressources C')
        autre_team = Team.objects.create(name='Équipe Ressources C', institution=autre_institution)
        autre_membre = create_user(username='membre-ress-c@test.fr', email='membre-ress-c@test.fr')
        autre_team.members.add(autre_membre)
        admin = create_user(username='admin-ress@test.fr', email='admin-ress@test.fr', type='ADMIN')
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('team-ressources-mobilisees'))

        equipe_ids = {r['equipe_id'] for r in response.data}
        assert str(autre_team.id) in equipe_ids

    def test_material_row_exposes_proprietaire_and_groupe(self, mairie_client, team_a, offer_type, create_user):
        """Corrigé le 2026-09-19 : une ligne "matériel" doit exposer qui l'a déposé (jamais
        évident depuis `nom`, le titre de l'offre) — présence physique, groupe de dépôt
        (association/entreprise) et accompagnants, pour retrouver facilement le propriétaire
        d'un matériel déposé sans lui, ou relier matériel + personne quand indissociables."""
        client, _ = mairie_client
        proprietaire = create_user(username='proprietaire-ress@test.fr', email='proprietaire-ress@test.fr')
        groupe_id = uuid.uuid4()
        offer = Offer.objects.create(
            title='Camion-citerne + équipage', first_name_offer='Jean', last_name_offer='Dupont',
            email_offer='proprietaire-ress@test.fr', phone_offer='0600000001', status='DISPONIBLE',
            offer_type=offer_type, materiel_type='CUVE', author=proprietaire,
            presence_physique=True, accompagne=True, nombre_accompagnants=2,
            organisation_nom='Asso Secours Bénévoles', groupe_id=groupe_id,
        )
        client.post(reverse('team-definir-mission', args=[team_a.id]), {'titre': 'Mission'}, format='json')
        client.post(reverse('team-assigner-ressource', args=[team_a.id]), {'offer_id': str(offer.id)}, format='json')

        response = client.get(reverse('team-ressources-mobilisees'))

        ligne = next(r for r in response.data if r['type'] == 'materiel' and r['equipe_id'] == str(team_a.id))
        assert ligne['proprietaire_nom'] == 'Jean Dupont'
        assert ligne['proprietaire_id'] == str(proprietaire.id)
        assert ligne['proprietaire_email'] == 'proprietaire-ress@test.fr'
        assert ligne['proprietaire_telephone'] == '0600000001'
        assert ligne['presence_physique'] is True
        assert ligne['accompagne'] is True
        assert ligne['nombre_accompagnants'] == 2
        assert ligne['organisation_nom'] == 'Asso Secours Bénévoles'
        assert ligne['groupe_id'] == str(groupe_id)

    def test_personne_row_exposes_user_id(self, mairie_client, team_a):
        client, user = mairie_client
        team_a.members.add(user)

        response = client.get(reverse('team-ressources-mobilisees'))

        ligne = next(r for r in response.data if r['type'] == 'personne' and r['equipe_id'] == str(team_a.id))
        assert ligne['user_id'] == str(user.id)
