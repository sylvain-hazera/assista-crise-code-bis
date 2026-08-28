import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.urls import reverse
from rest_framework import status

from core.models import Crisis, Environment, Request, Team, User


def _make_admin(authenticated_client, demo_role=None):
    client, admin = authenticated_client
    admin.type = 'ADMIN'
    if demo_role:
        admin.demo_role = demo_role
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
class TestSendMailEnvAware:
    """En zone DEMO, les emails de notification opérationnelle (affectation, confirmation)
    doivent atterrir dans la boîte du compte démo qui a déclenché l'action — jamais vers un
    destinataire enregistré (souvent fictif en démo) — pour que les utilisateurs découvrent
    concrètement ce que l'appli aurait envoyé, sans jamais spammer un tiers."""

    def test_prod_email_goes_to_real_recipient(self, authenticated_client, request_type):
        client, admin = _make_admin(authenticated_client)
        crisis = _make_crisis()
        team = Team.objects.create(name='Equipe test')
        demande = _make_request(crisis, request_type, email_request='vraie.personne@test.fr')

        response = client.post(reverse('request-assign-team', args=[demande.id]), {'team': str(team.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['vraie.personne@test.fr']
        assert not mail.outbox[0].subject.startswith('[DEMO]')

    def test_demo_email_redirects_to_acting_user(self, authenticated_client, request_type):
        client, admin = _make_admin(authenticated_client, demo_role='ADMIN')
        crisis = _make_crisis(environment=Environment.DEMO)
        team = Team.objects.create(name='Equipe test', environment=Environment.DEMO)
        demande = _make_request(crisis, request_type, email_request='vraie.personne@test.fr', environment=Environment.DEMO)

        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.post(reverse('request-assign-team', args=[demande.id]), {'team': str(team.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [admin.email]
        assert 'vraie.personne@test.fr' not in mail.outbox[0].to
        assert mail.outbox[0].subject.startswith('[DEMO]')
