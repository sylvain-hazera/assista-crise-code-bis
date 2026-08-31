import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models import Information, Offer, Request, User


@pytest.mark.django_db
class TestOfferOwnershipPermissions:
    """OfferViewSet était en permission_classes = [AllowAny] pour permettre la création
    publique, mais sans get_permissions() dédié, update/partial_update/destroy héritaient de
    la même permission : n'importe qui, même anonyme, pouvait modifier ou supprimer l'offre de
    n'importe qui d'autre. Corrigé via IsOwnerOrInstitutional."""

    def test_anonymous_cannot_update(self, api_client, offer_type):
        offer = Offer.objects.create(
            title='Offre', first_name_offer='A', last_name_offer='B',
            email_offer='a@t.fr', offer_type=offer_type,
        )
        response = api_client.patch(reverse('offer-detail', args=[offer.id]), {'title': 'HACKED'}, format='json')
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        offer.refresh_from_db()
        assert offer.title == 'Offre'

    def test_anonymous_cannot_delete(self, api_client, offer_type):
        offer = Offer.objects.create(
            title='Offre', first_name_offer='A', last_name_offer='B',
            email_offer='a@t.fr', offer_type=offer_type,
        )
        response = api_client.delete(reverse('offer-detail', args=[offer.id]))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert Offer.objects.filter(id=offer.id).exists()

    def test_author_can_update_own_offer(self, authenticated_client, offer_type):
        client, author = authenticated_client
        offer = Offer.objects.create(
            title='Offre', first_name_offer='A', last_name_offer='B',
            email_offer='a@t.fr', offer_type=offer_type, author=author,
        )
        response = client.patch(reverse('offer-detail', args=[offer.id]), {'title': 'Modifiee'}, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_other_authenticated_user_cannot_update(self, authenticated_client, offer_type):
        client, user = authenticated_client
        author = User.objects.create_user(username='auteur-offre@test.fr', email='auteur-offre@test.fr', password='Test1234!')
        offer = Offer.objects.create(
            title='Offre', first_name_offer='A', last_name_offer='B',
            email_offer='a@t.fr', offer_type=offer_type, author=author,
        )
        response = client.patch(reverse('offer-detail', args=[offer.id]), {'title': 'HACKED'}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_actor_can_update_any_offer(self, authenticated_client, offer_type):
        client, admin = authenticated_client
        admin.type = 'ADMIN'
        admin.save()
        author = User.objects.create_user(username='auteur-offre2@test.fr', email='auteur-offre2@test.fr', password='Test1234!')
        offer = Offer.objects.create(
            title='Offre', first_name_offer='A', last_name_offer='B',
            email_offer='a@t.fr', offer_type=offer_type, author=author,
        )
        response = client.patch(reverse('offer-detail', args=[offer.id]), {'title': 'Modifiee par admin'}, format='json')
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRequestOwnershipPermissions:

    def test_anonymous_cannot_update(self, api_client, request_type):
        demande = Request.objects.create(
            title='Demande', location=Point(1, 1, srid=4326),
            first_name_request='A', last_name_request='B',
            email_request='a@t.fr', phone_request='0600000000', request_type=request_type,
        )
        response = api_client.patch(reverse('request-detail', args=[demande.id]), {'title': 'HACKED'}, format='json')
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_author_can_delete_own_request(self, authenticated_client, request_type):
        client, author = authenticated_client
        demande = Request.objects.create(
            title='Demande', location=Point(1, 1, srid=4326),
            first_name_request='A', last_name_request='B',
            email_request='a@t.fr', phone_request='0600000000', request_type=request_type,
            author=author,
        )
        response = client.delete(reverse('request-detail', args=[demande.id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        # Politique de désactivation (voir RequestViewSet.perform_destroy) : la demande reste
        # en base, désactivée, jusqu'à la clôture de la crise rattachée.
        demande.refresh_from_db()
        assert demande.actif is False


@pytest.mark.django_db
class TestInformationOwnershipPermissions:

    def test_anonymous_cannot_delete(self, api_client, information_type):
        info = Information.objects.create(
            title='Signalement', location=Point(1, 1, srid=4326),
            first_name_information='A', last_name_information='B',
            email_information='a@t.fr', phone_information='0600000000',
            information_type=information_type,
        )
        response = api_client.delete(reverse('information-detail', args=[info.id]))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert Information.objects.filter(id=info.id).exists()

    def test_author_can_update_own_information(self, authenticated_client, information_type):
        client, author = authenticated_client
        info = Information.objects.create(
            title='Signalement', location=Point(1, 1, srid=4326),
            first_name_information='A', last_name_information='B',
            email_information='a@t.fr', phone_information='0600000000',
            information_type=information_type, author=author,
        )
        response = client.patch(reverse('information-detail', args=[info.id]), {'title': 'Modifie'}, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_author_email_filter_returns_only_own_information(self, api_client, information_type):
        """InformationViewSet n'avait pas filterset_class = AuthorEmailFilter : ?author_email=
        était silencieusement ignoré et renvoyait tout le monde — utilisé par le nouvel onglet
        "Signalements" de Paramètres du compte (InformationService.getMines)."""
        author = User.objects.create_user(username='moi-info@test.fr', email='moi-info@test.fr', password='Test1234!')
        Information.objects.create(
            title='Le mien', location=Point(1, 1, srid=4326),
            first_name_information='A', last_name_information='B',
            email_information='a@t.fr', phone_information='0600000000',
            information_type=information_type, author=author,
        )
        Information.objects.create(
            title="Celui d'un autre", location=Point(1, 1, srid=4326),
            first_name_information='C', last_name_information='D',
            email_information='c@t.fr', phone_information='0600000000',
            information_type=information_type,
        )

        response = api_client.get(reverse('information-list'), {'author_email': 'moi-info@test.fr'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['title'] == 'Le mien'
