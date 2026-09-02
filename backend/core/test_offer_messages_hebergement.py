import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Besoin,
    ContactInstitution,
    Crisis,
    Institution,
    InstitutionType,
    Notification,
    Offer,
    OfferMessage,
    OfferType,
    Team,
)

OFFER_PAYLOAD = {
    "title": "Studio à louer",
    "location": "POINT (5.7245 45.1885)",
    "first_name_offer": "Jean",
    "last_name_offer": "Proprietaire",
    "email_offer": "jean.proprietaire@test.fr",
    "status": "DISPONIBLE",
}


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Hébergement (test messages)", description="")


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise test messages", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def offer(db, offer_type, crisis):
    return Offer.objects.create(offer_type=offer_type, crisis=crisis, reponse_token="zz-token-test-hebergement", **OFFER_PAYLOAD)


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_MSG_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie de Test Messages", type=itype)


@pytest.fixture
def local_authority_client(create_user, institution):
    user = create_user(username="autorite-messages@test.fr", email="autorite-messages@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def equipe_hebergement(db, crisis, create_user):
    membre = create_user(username="equipier-hebergement@test.fr", email="equipier-hebergement@test.fr", type="UTIL_SIMPLE")
    theme = Besoin.objects.get(nom="Hébergement")
    team = Team.objects.create(name="Équipe Relogement", description="", color="#3b82f6")
    team.themes.add(theme)
    team.assigned_crises.add(crisis)
    team.members.add(membre)
    return team, membre


@pytest.mark.django_db
class TestTeamThemes:

    def test_team_can_be_tagged_with_hebergement_theme(self, local_authority_client):
        client, _ = local_authority_client
        theme = Besoin.objects.get(nom="Hébergement")
        team = Team.objects.create(name="Équipe test thèmes", description="", color="#3b82f6")
        response = client.patch(reverse('team-detail', args=[team.id]), {"theme_ids": [str(theme.id)]}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['themes_libelles'] == ["Hébergement"]


@pytest.mark.django_db
class TestOfferMessagesEquipe:

    def test_institutional_actor_can_list_messages(self, local_authority_client, offer):
        client, _ = local_authority_client
        response = client.get(reverse('offer-messages', args=[offer.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_non_institutional_cannot_send_message(self, api_client, offer):
        response = api_client.post(reverse('offer-messages', args=[offer.id]), {"contenu": "Bonjour"}, format='json')
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_institutional_actor_sends_message_and_owner_is_emailed(self, local_authority_client, offer):
        client, user = local_authority_client
        response = client.post(reverse('offer-messages', args=[offer.id]), {"contenu": "Le logement est-il toujours disponible ?"}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert OfferMessage.objects.filter(offer=offer, auteur_equipe=user).exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [offer.email_offer]
        assert "repondre-offre" in mail.outbox[0].body

    def test_empty_message_rejected(self, local_authority_client, offer):
        client, _ = local_authority_client
        response = client.post(reverse('offer-messages', args=[offer.id]), {"contenu": "  "}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_sending_message_generates_reponse_token_if_missing(self, local_authority_client, offer_type, crisis):
        client, _ = local_authority_client
        offre_sans_token = Offer.objects.create(offer_type=offer_type, crisis=crisis, email_offer="sans-token@test.fr",
                                                 title="T", location="POINT (5.72 45.18)",
                                                 first_name_offer="A", last_name_offer="B", status="DISPONIBLE")
        assert offre_sans_token.reponse_token is None
        response = client.post(reverse('offer-messages', args=[offre_sans_token.id]), {"contenu": "Bonjour"}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        offre_sans_token.refresh_from_db()
        assert offre_sans_token.reponse_token is not None


@pytest.mark.django_db
class TestOfferReponsePublicView:

    def test_get_returns_offer_and_messages(self, offer):
        client = APIClient()
        OfferMessage.objects.create(offer=offer, auteur_equipe=None, contenu="Message existant")
        response = client.get(reverse('offer_reponse_public', args=[offer.reponse_token]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['offer']['id'] == str(offer.id)
        assert len(response.data['messages']) == 1

    def test_get_with_invalid_token_404(self):
        client = APIClient()
        response = client.get(reverse('offer_reponse_public', args=['token-inexistant']))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_owner_can_reply_and_team_is_notified(self, offer, equipe_hebergement):
        team, membre = equipe_hebergement
        client = APIClient()
        response = client.post(reverse('offer_reponse_public', args=[offer.reponse_token]), {"contenu": "Oui, toujours dispo."}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert OfferMessage.objects.filter(offer=offer, auteur_equipe=None).exists()
        assert Notification.objects.filter(utilisateur=membre).exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [membre.email]

    def test_owner_reply_without_matching_team_sends_no_notification(self, offer):
        client = APIClient()
        response = client.post(reverse('offer_reponse_public', args=[offer.reponse_token]), {"contenu": "Oui"}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert Notification.objects.count() == 0
        assert len(mail.outbox) == 0

    def test_owner_can_edit_offer_and_team_is_notified(self, offer, equipe_hebergement):
        team, membre = equipe_hebergement
        client = APIClient()
        response = client.patch(reverse('offer_reponse_public', args=[offer.reponse_token]), {"description": "Disponible dès demain"}, format='json')
        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.description == "Disponible dès demain"
        assert Notification.objects.filter(utilisateur=membre).exists()
