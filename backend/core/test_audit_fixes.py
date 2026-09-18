"""Tests des correctifs issus de l'audit du 12/09/2026 (voir artefact "Angles morts") :
mandat des institutions privées sur une crise (InstitutionType.est_public), synchronisation
équipe<->crise via une mission, cohérence Dossier.crise/Dossier.mission.crise, et notifications
manquantes (verdict d'implication, changement de statut de dossier, personne retrouvée)."""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution,
    Crisis,
    Dossier,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    Mission,
    Notification,
    PointType,
    RecherchePersonne,
    RecherchePersonneLecture,
    StatutImplication,
    Team,
    TypeImplication,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise audit test", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def type_public(db):
    return InstitutionType.objects.create(code="mairie_audit_test", libelle="Mairie", est_public=True)


@pytest.fixture
def type_prive(db):
    return InstitutionType.objects.create(code="association_audit_test", libelle="Association", est_public=False)


@pytest.fixture
def mairie(db, type_public):
    return Institution.objects.create(nom="Mairie audit test", type=type_public)


@pytest.fixture
def association(db, type_prive):
    return Institution.objects.create(nom="Association audit test", type=type_prive)


@pytest.fixture
def regulateur_client(create_user, mairie, crisis):
    """Compte AUT_LOCALE, contact actif de `mairie`, dont l'institution est déjà VALIDEE sur
    `crisis` (institution publique, auto-validée) — habilité à valider/refuser une déclaration
    ACTEUR tierce (voir is_regulateur_aut_locale_de_la_crise)."""
    user = create_user(username="regulateur-audit@test.fr", email="regulateur-audit@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    ImplicationInstitution.objects.create(
        crise=crisis, institution=mairie, type_implication=TypeImplication.ACTEUR,
        statut=StatutImplication.VALIDEE, actif=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestMandatInstitutionActeur:

    def test_declaration_acteur_institution_publique_auto_validee(self, create_user, mairie, crisis):
        user = create_user(username="mairie-acteur@test.fr", email="mairie-acteur@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('implicationinstitution-list'), {
            "crise": str(crisis.id), "institution": str(mairie.id), "type_implication": "ACTEUR",
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['statut'] == StatutImplication.VALIDEE

    def test_declaration_acteur_institution_privee_en_attente(self, create_user, association, crisis):
        user = create_user(username="assoc-acteur@test.fr", email="assoc-acteur@test.fr", type="SECOURS")
        ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('implicationinstitution-list'), {
            "crise": str(crisis.id), "institution": str(association.id), "type_implication": "ACTEUR",
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['statut'] == StatutImplication.EN_ATTENTE

    def test_valider_notifie_les_contacts_institution(self, create_user, association, crisis, regulateur_client):
        client_reg, _ = regulateur_client
        contact = create_user(username="assoc-contact@test.fr", email="assoc-contact@test.fr", type="UTIL_SIMPLE")
        ContactInstitution.objects.create(institution=association, utilisateur=contact, actif=True)
        implication = ImplicationInstitution.objects.create(
            crise=crisis, institution=association, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.EN_ATTENTE, actif=True,
        )

        response = client_reg.post(reverse('implicationinstitution-valider', args=[implication.id]))

        assert response.status_code == status.HTTP_200_OK
        assert Notification.objects.filter(utilisateur=contact, titre__icontains="validée").exists()

    def test_refuser_notifie_les_contacts_institution(self, create_user, association, crisis, regulateur_client):
        client_reg, _ = regulateur_client
        contact = create_user(username="assoc-contact2@test.fr", email="assoc-contact2@test.fr", type="UTIL_SIMPLE")
        ContactInstitution.objects.create(institution=association, utilisateur=contact, actif=True)
        implication = ImplicationInstitution.objects.create(
            crise=crisis, institution=association, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.EN_ATTENTE, actif=True,
        )

        response = client_reg.post(reverse('implicationinstitution-refuser', args=[implication.id]))

        assert response.status_code == status.HTTP_200_OK
        assert Notification.objects.filter(utilisateur=contact, titre__icontains="refusée").exists()


@pytest.mark.django_db
class TestMandatPointOperationnel:
    """Vérifie le correctif du contournement trouvé en audit : créer un point valait
    auto-déclaration ACTEUR toujours VALIDEE, même pour une institution privée non mandatée."""

    def _point_payload(self, crisis, point_type, institution):
        return {
            "nom": "Centre d'accueil audit test", "type": str(point_type.id), "crise": str(crisis.id),
            "institution": str(institution.id),
        }

    def test_creation_point_bloquee_pour_institution_privee_non_mandatee(self, create_user, association, crisis):
        point_type = PointType.objects.create(code="AUDIT_TEST_TYPE", libelle="Centre d'accueil audit")
        user = create_user(username="assoc-point@test.fr", email="assoc-point@test.fr", type="SECOURS")
        ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('pointoperationnel-list'), self._point_payload(crisis, point_type, association), format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not ImplicationInstitution.objects.filter(crise=crisis, institution=association).exists()

    def test_creation_point_autorisee_pour_institution_publique(self, create_user, mairie, crisis):
        point_type = PointType.objects.create(code="AUDIT_TEST_TYPE_PUB", libelle="Centre d'accueil audit public")
        user = create_user(username="mairie-point@test.fr", email="mairie-point@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('pointoperationnel-list'), self._point_payload(crisis, point_type, mairie), format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        implication = ImplicationInstitution.objects.get(crise=crisis, institution=mairie)
        assert implication.statut == StatutImplication.VALIDEE

    def test_creation_point_autorisee_si_deja_mandatee(self, create_user, association, crisis):
        point_type = PointType.objects.create(code="AUDIT_TEST_TYPE_OK", libelle="Centre d'accueil audit mandaté")
        user = create_user(username="assoc-point-ok@test.fr", email="assoc-point-ok@test.fr", type="SECOURS")
        ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True)
        ImplicationInstitution.objects.create(
            crise=crisis, institution=association, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, actif=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('pointoperationnel-list'), self._point_payload(crisis, point_type, association), format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestSyncEquipeCriseMission:

    def test_definir_mission_synchronise_assigned_crises(self, create_user, mairie, crisis):
        user = create_user(username="mairie-mission@test.fr", email="mairie-mission@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
        team = Team.objects.create(name="Équipe audit sync", institution=mairie)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('team-definir-mission', args=[team.id]),
            {"titre": "Objectif audit test", "crise_id": str(crisis.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert crisis in team.assigned_crises.all()
        assert team.mission_active.crise_id == crisis.id


@pytest.mark.django_db
class TestValidationCroiseeDossierMission:

    def test_dossier_mission_autre_crise_rejetee(self, create_user, crisis):
        autre_crise = Crisis.objects.create(name="Autre crise audit", type="INONDATION", location="POINT (5 45)")
        mission = Mission.objects.create(titre="Mission autre crise", crise=autre_crise)
        dossier = Dossier.objects.create(numero="DOS-AUDIT-1", crise=crisis)
        admin = create_user(username="admin-audit@test.fr", email="admin-audit@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(
            reverse('dossier-detail', args=[dossier.id]), {"mission": str(mission.id)}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_dossier_mission_meme_crise_acceptee(self, create_user, crisis):
        mission = Mission.objects.create(titre="Mission même crise", crise=crisis)
        dossier = Dossier.objects.create(numero="DOS-AUDIT-2", crise=crisis)
        admin = create_user(username="admin-audit2@test.fr", email="admin-audit2@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(
            reverse('dossier-detail', args=[dossier.id]), {"mission": str(mission.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestNotificationDefinirStatutDossier:

    def test_definir_statut_notifie_participants_sauf_auteur(self, create_user, crisis):
        from core.models import DossierParticipant

        dossier = Dossier.objects.create(numero="DOS-AUDIT-3", crise=crisis)
        participant = create_user(username="participant-audit@test.fr", email="participant-audit@test.fr", type="UTIL_SIMPLE")
        DossierParticipant.objects.create(dossier=dossier, utilisateur=participant, role=DossierParticipant.Role.DEMANDEUR)
        admin = create_user(username="admin-audit3@test.fr", email="admin-audit3@test.fr", type="ADMIN")
        DossierParticipant.objects.create(dossier=dossier, utilisateur=admin, role=DossierParticipant.Role.REGULATION)
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(
            reverse('dossier-definir-statut', args=[dossier.id]), {"statut": "EN_COURS"}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert Notification.objects.filter(utilisateur=participant, dossier=dossier).exists()
        assert not Notification.objects.filter(utilisateur=admin, dossier=dossier).exists()


@pytest.mark.django_db
class TestNotificationRecherchePersonneRetrouvee:

    def test_retrouver_notifie_createur_et_lecteurs(self, create_user):
        createur = create_user(username="createur-audit@test.fr", email="createur-audit@test.fr", type="UTIL_SIMPLE")
        lecteur = create_user(username="lecteur-audit@test.fr", email="lecteur-audit@test.fr", type="UTIL_SIMPLE")
        # RecherchePersonneViewSet est réservé aux comptes institutionnels depuis le 2026-09-18
        # (voir /rgpd) — createur/lecteur ci-dessus ne sont que des destinataires de
        # notification, pas les auteurs de l'appel API, ils peuvent rester UTIL_SIMPLE.
        acteur = create_user(username="acteur-retrouve-audit@test.fr", email="acteur-retrouve-audit@test.fr", type="AUT_LOCALE")
        recherche = RecherchePersonne.objects.create(
            nom="Dupont", prenom="Jean", age=70, source="DOMICILE", ville="Test-ville",
            contact_nom="Contact test", contact_email="contact@test.fr", contact_telephone="0600000000",
            createur=createur,
        )
        RecherchePersonneLecture.objects.create(recherche=recherche, utilisateur=lecteur)
        client = APIClient()
        client.force_authenticate(user=acteur)

        response = client.post(reverse('recherchepersonne-retrouver', args=[recherche.id]))

        assert response.status_code == status.HTTP_200_OK
        assert Notification.objects.filter(utilisateur=createur).exists()
        assert Notification.objects.filter(utilisateur=lecteur).exists()
        assert not Notification.objects.filter(utilisateur=acteur).exists()
