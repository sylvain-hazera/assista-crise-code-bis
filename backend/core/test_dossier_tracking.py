import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from core.models import Crisis, Dossier, DossierParticipant, Request, Team
from core.views import build_magic_link, resolve_or_invite_demandeur

User = get_user_model()

REQUEST_PAYLOAD = {
    "title": "Besoin de nourriture",
    "location": "POINT (5.7245 45.1885)",
    "email_request": "anonyme.demandeur@test.fr",
    "phone_request": "0600000000",
    "status": "NON_TRAITEE",
}


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise suivi dossier", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def team(db):
    return Team.objects.create(name="Equipe suivi", description="", color="#3b82f6")


@pytest.fixture
def anonymous_request(db, request_type, crisis):
    return Request.objects.create(
        request_type=request_type, crisis=crisis, author=None,
        first_name_request="Anna", last_name_request="Nonyme", **REQUEST_PAYLOAD,
    )


@pytest.fixture
def local_authority_client(create_user):
    user = create_user(username="autorite-suivi@test.fr", email="autorite-suivi@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def dossier_with_demandeur(db, crisis, team, create_user):
    demandeur = create_user(username="demandeur-suivi@test.fr", email="demandeur-suivi@test.fr", type="UTIL_SIMPLE")
    dossier = Dossier.objects.create(
        numero="DOS-TESTSUIVI", crise=crisis, equipe=team, titre="Dossier de test", statut=Dossier.Statut.AFFECTE,
    )
    DossierParticipant.objects.create(dossier=dossier, utilisateur=demandeur, role=DossierParticipant.Role.DEMANDEUR)
    return dossier, demandeur


class DummyRequest:
    def build_absolute_uri(self, path):
        return f"http://testserver{path}"


@pytest.mark.django_db
class TestBuildMagicLink:

    def test_magic_login_routes_to_frontend_with_next(self, create_user, settings):
        settings.SERVER_URL = "https://assista-crise.fr"
        user = create_user(username="magiclink@test.fr", email="magiclink@test.fr", type="UTIL_SIMPLE")

        link = build_magic_link(DummyRequest(), user, "magic-login", next_url="/dossier-suivi/abc")

        assert link.startswith("https://assista-crise.fr/connexion-magique/")
        assert link.endswith("?next=%2Fdossier-suivi%2Fabc")

    def test_other_actions_still_route_to_api(self, create_user):
        user = create_user(username="apilink@test.fr", email="apilink@test.fr", type="UTIL_SIMPLE")

        link = build_magic_link(DummyRequest(), user, "delete-request")

        assert link.startswith("http://testserver/api/delete-request/")


@pytest.mark.django_db
class TestResolveOrInviteDemandeur:

    def test_anonymous_request_creates_enabled_user(self, anonymous_request):
        user, created = resolve_or_invite_demandeur(anonymous_request)

        assert created is True
        assert user.email == anonymous_request.email_request
        assert user.enabled is True
        assert user.is_active is True

    def test_existing_email_is_reused_not_duplicated(self, anonymous_request, create_user):
        existing = create_user(
            username=anonymous_request.email_request, email=anonymous_request.email_request, type="UTIL_SIMPLE",
        )

        user, created = resolve_or_invite_demandeur(anonymous_request)

        assert created is False
        assert user.pk == existing.pk


@pytest.mark.django_db
class TestAssignTeamCreatesTrackingAccess:

    def test_anonymous_request_gets_demandeur_account_and_link(self, local_authority_client, anonymous_request, team):
        client, _ = local_authority_client

        response = client.post(
            reverse('request-assign-team', args=[anonymous_request.id]), {"team": str(team.id)}, format='json'
        )

        assert response.status_code == status.HTTP_200_OK
        dossier = Dossier.objects.get(id=response.data["dossier"])
        created_user = User.objects.get(email=anonymous_request.email_request)
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=created_user, role=DossierParticipant.Role.DEMANDEUR
        ).exists()
        assert len(mail.outbox) == 1
        assert "connexion-magique" in mail.outbox[0].body
        assert f"next=%2Fdossier-suivi%2F{dossier.id}" in mail.outbox[0].body


@pytest.mark.django_db
class TestDossierAccessScoping:

    def test_non_participant_sees_nothing(self, create_user):
        outsider = create_user(username="outsider@test.fr", email="outsider@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        assert client.get(reverse('dossier-list')).data == []
        assert client.get(reverse('document-list')).data == []
        assert client.get(reverse('dossiercommentaire-list')).data == []

    def test_participant_sees_only_own_dossier(self, dossier_with_demandeur, create_user, crisis, team):
        dossier, demandeur = dossier_with_demandeur
        Dossier.objects.create(numero="DOS-AUTRE", crise=crisis, equipe=team, titre="Autre dossier")
        client = APIClient()
        client.force_authenticate(user=demandeur)

        response = client.get(reverse('dossier-list'))

        assert [d["id"] for d in response.data] == [str(dossier.id)]

    def test_participant_can_comment_and_auteur_is_forced(self, dossier_with_demandeur, create_user):
        dossier, demandeur = dossier_with_demandeur
        someone_else = create_user(username="spoofed@test.fr", email="spoofed@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=demandeur)

        response = client.post(
            reverse('dossiercommentaire-list'),
            {"dossier": str(dossier.id), "commentaire": "Merci pour votre aide", "auteur": str(someone_else.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["auteur"] == demandeur.id

    def test_non_participant_cannot_comment_on_dossier(self, dossier_with_demandeur, create_user):
        dossier, _ = dossier_with_demandeur
        outsider = create_user(username="outsider2@test.fr", email="outsider2@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.post(
            reverse('dossiercommentaire-list'),
            {"dossier": str(dossier.id), "commentaire": "Je m'incruste"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_actor_sees_all_dossiers(self, dossier_with_demandeur, local_authority_client, crisis, team):
        Dossier.objects.create(numero="DOS-AUTRE2", crise=crisis, equipe=team, titre="Autre dossier 2")
        client, _ = local_authority_client

        response = client.get(reverse('dossier-list'))

        assert len(response.data) >= 2
