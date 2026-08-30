import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel,
    Competence,
    Crisis,
    Dossier,
    DossierParticipant,
    Institution,
    InstitutionType,
    Notification,
    Request,
    RoleOperationnel,
    Team,
)

REQUEST_PAYLOAD = {
    "title": "Besoin de nourriture",
    "location": "POINT (5.7245 45.1885)",
    "first_name_request": "Marie",
    "last_name_request": "Demandeuse",
    "email_request": "marie.demandeuse@test.fr",
    "phone_request": "0600000000",
    "status": "NON_TRAITEE",
}


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise test demandes", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def request_obj(db, request_type, crisis, create_user):
    author = create_user(username="demandeur@test.fr", email="demandeur@test.fr", type="UTIL_SIMPLE")
    return Request.objects.create(request_type=request_type, crisis=crisis, author=author, **REQUEST_PAYLOAD)


@pytest.fixture
def team(db):
    return Team.objects.create(name="Equipe Alpha", description="", color="#3b82f6")


@pytest.fixture
def local_authority_client(create_user):
    user = create_user(username="autorite-requests@test.fr", email="autorite-requests@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestAssignRequestToTeam:

    def test_assign_creates_dossier_with_demandeur_participant(self, local_authority_client, request_obj, team):
        client, _ = local_authority_client

        response = client.post(
            reverse('request-assign-team', args=[request_obj.id]),
            {"team": str(team.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        dossier = Dossier.objects.get(id=response.data["dossier"])
        assert dossier.demande == request_obj
        assert dossier.equipe == team
        assert dossier.crise == request_obj.crisis
        assert dossier.statut == Dossier.Statut.AFFECTE
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=request_obj.author, role=DossierParticipant.Role.DEMANDEUR
        ).exists()
        assert team.assigned_requests.filter(pk=request_obj.pk).exists()

    def test_demandeur_receives_email(self, local_authority_client, request_obj, team):
        client, _ = local_authority_client
        client.post(reverse('request-assign-team', args=[request_obj.id]), {"team": str(team.id)}, format='json')

        assert len(mail.outbox) == 1
        assert request_obj.email_request in mail.outbox[0].to

    def test_team_regulateur_gets_notified(self, local_authority_client, request_obj, team, create_user):
        client, _ = local_authority_client
        regulateur = create_user(username="regulateur@test.fr", email="regulateur@test.fr", type="UTIL_SIMPLE")
        team.members.add(regulateur)
        role = RoleOperationnel.objects.create(code="REGULATEUR", libelle="Régulateur")
        competence = Competence.objects.create(nom="Nourriture (test)")
        team.competences.add(competence)
        itype = InstitutionType.objects.create(code="MAIRIE_REQ_TEST", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie regulateur test", type=itype)
        AffectationRoleOperationnel.objects.create(
            utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
        )

        response = client.post(
            reverse('request-assign-team', args=[request_obj.id]), {"team": str(team.id)}, format='json'
        )

        assert response.data["regulateurs_notifies"] == 1
        assert Notification.objects.filter(utilisateur=regulateur, titre__icontains="affectée").exists()

    def test_reassigning_same_team_is_noop(self, local_authority_client, request_obj, team):
        client, _ = local_authority_client
        client.post(reverse('request-assign-team', args=[request_obj.id]), {"team": str(team.id)}, format='json')
        assert Dossier.objects.filter(demande=request_obj).count() == 1

        response = client.post(
            reverse('request-assign-team', args=[request_obj.id]), {"team": str(team.id)}, format='json'
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data.get("already_assigned") is True
        assert Dossier.objects.filter(demande=request_obj).count() == 1

    def test_request_without_crisis_cannot_be_assigned(self, local_authority_client, request_type, team, create_user):
        client, _ = local_authority_client
        author = create_user(username="sanscrisis@test.fr", email="sanscrisis@test.fr", type="UTIL_SIMPLE")
        orphan_request = Request.objects.create(
            request_type=request_type, crisis=None, author=author,
            **{**REQUEST_PAYLOAD, "email_request": "sanscrisis@test.fr"},
        )

        response = client.post(
            reverse('request-assign-team', args=[orphan_request.id]), {"team": str(team.id)}, format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Dossier.objects.filter(demande=orphan_request).exists()
        assert not team.assigned_requests.filter(pk=orphan_request.pk).exists()

    def test_simple_user_cannot_assign_request_to_team(self, authenticated_client, request_obj, team):
        client, _ = authenticated_client
        response = client.post(
            reverse('request-assign-team', args=[request_obj.id]), {"team": str(team.id)}, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestNotificationApi:

    def test_user_only_sees_own_notifications(self, create_user):
        me = create_user(username="me@test.fr", email="me@test.fr", type="UTIL_SIMPLE")
        other = create_user(username="other@test.fr", email="other@test.fr", type="UTIL_SIMPLE")
        Notification.objects.create(utilisateur=me, titre="Pour moi", message="...")
        Notification.objects.create(utilisateur=other, titre="Pas pour moi", message="...")

        client = APIClient()
        client.force_authenticate(user=me)
        response = client.get(reverse('notification-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["titre"] == "Pour moi"

    def test_anonymous_cannot_list_notifications(self):
        client = APIClient()
        response = client.get(reverse('notification-list'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_user_can_mark_own_notification_as_read(self, create_user):
        me = create_user(username="me2@test.fr", email="me2@test.fr", type="UTIL_SIMPLE")
        notif = Notification.objects.create(utilisateur=me, titre="Test", message="...")

        client = APIClient()
        client.force_authenticate(user=me)
        response = client.patch(reverse('notification-detail', args=[notif.id]), {"lu": True}, format='json')

        assert response.status_code == status.HTTP_200_OK
        notif.refresh_from_db()
        assert notif.lu is True
