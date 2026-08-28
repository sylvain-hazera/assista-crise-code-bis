import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status

from core.models import Information, Offer, Request


@pytest.mark.django_db
class TestEmailLinksUseCanonicalServerUrl:
    """Les liens dans les emails de confirmation (suppression) doivent toujours pointer vers
    settings.SERVER_URL — jamais vers le Host de la requête entrante (IP interne, domaine
    alternatif...). Bug réel corrigé : ces liens utilisaient request.build_absolute_uri(), et
    SERVER_URL n'était même pas positionnée en prod (valeur par défaut = IP privée)."""

    def test_request_confirmation_email_uses_canonical_url(self, api_client, request_type, settings):
        settings.SERVER_URL = "https://www.assista-crise.fr"
        response = api_client.post(reverse('request-list'), {
            'title': 'Besoin urgent', 'location': 'POINT (5.7245 45.1885)',
            'first_name_request': 'Jean', 'last_name_request': 'Dupont',
            'email_request': 'jean.dupont@test.fr', 'phone_request': '0600000000',
            'request_type': str(request_type.id),
        }, format='json', HTTP_HOST='172.16.1.113:4200')

        assert response.status_code == status.HTTP_201_CREATED
        assert len(mail.outbox) == 1
        assert 'https://www.assista-crise.fr/api/delete-request/' in mail.outbox[0].body
        assert '172.16.1.113' not in mail.outbox[0].body

    def test_offer_confirmation_email_uses_canonical_url(self, api_client, offer_type, settings):
        settings.SERVER_URL = "https://www.assista-crise.fr"
        response = api_client.post(reverse('offer-list'), {
            'title': 'Je peux aider', 'first_name_offer': 'Marie', 'last_name_offer': 'Curie',
            'email_offer': 'marie.curie@test.fr', 'offer_type': str(offer_type.id),
        }, format='json', HTTP_HOST='172.16.1.113:4200')

        assert response.status_code == status.HTTP_201_CREATED
        assert len(mail.outbox) == 1
        assert 'https://www.assista-crise.fr/api/delete-offer/' in mail.outbox[0].body
        assert '172.16.1.113' not in mail.outbox[0].body

    def test_information_confirmation_email_uses_canonical_url(self, api_client, information_type, settings):
        settings.SERVER_URL = "https://www.assista-crise.fr"
        response = api_client.post(reverse('information-list'), {
            'title': 'Arbre sur la route', 'location': 'POINT (5.7245 45.1885)',
            'first_name_information': 'Paul', 'last_name_information': 'Martin',
            'email_information': 'paul.martin@test.fr', 'phone_information': '0600000000',
            'information_type': str(information_type.id),
        }, format='json', HTTP_HOST='172.16.1.113:4200')

        assert response.status_code == status.HTTP_201_CREATED
        assert len(mail.outbox) == 1
        assert 'https://www.assista-crise.fr/api/delete-information/' in mail.outbox[0].body
        assert '172.16.1.113' not in mail.outbox[0].body
