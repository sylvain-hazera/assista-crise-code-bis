import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis, Information, InformationType, Offer, OfferType, Request, RequestType, Team,
)


def _make_admin(authenticated_client):
    client, admin = authenticated_client
    admin.type = 'ADMIN'
    admin.save()
    return client, admin


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name='Crise transform', type='INCENDIE', location=Point(5.72, 45.18, srid=4326))


@pytest.fixture
def offer_type_autre(db):
    return OfferType.objects.get_or_create(type='Autre')[0]


@pytest.fixture
def information_type_autre(db):
    return InformationType.objects.get_or_create(type='Autre')[0]


@pytest.mark.django_db
class TestTransformerDemandeEnOffre:
    def test_creates_offer_and_deletes_request(self, authenticated_client, crisis, request_type, offer_type_autre):
        client, _ = _make_admin(authenticated_client)
        demande = Request.objects.create(
            title='Je propose une cuve', description='Une cuve de 500L disponible',
            location=Point(5.72, 45.18, srid=4326),
            first_name_request='Jeanine', last_name_request='Delacuve',
            email_request='jeanine@test.fr', phone_request='0102030405',
            crisis=crisis, request_type=request_type,
        )

        response = client.post(reverse('request-transformer', args=[demande.id]), {'cible': 'OFFER'})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['first_name_offer'] == 'Jeanine'
        assert response.data['last_name_offer'] == 'Delacuve'
        assert response.data['email_offer'] == 'jeanine@test.fr'
        assert response.data['description'] == 'Une cuve de 500L disponible'
        assert not Request.objects.filter(id=demande.id).exists()
        assert Offer.objects.filter(title='Je propose une cuve').exists()

    def test_photo_is_copied(self, authenticated_client, crisis, request_type, offer_type_autre):
        client, _ = _make_admin(authenticated_client)
        photo = SimpleUploadedFile('cuve.jpg', b'contenu-image-factice', content_type='image/jpeg')
        demande = Request.objects.create(
            title='Cuve avec photo', description='desc',
            location=Point(5.72, 45.18, srid=4326), photo=photo,
            first_name_request='A', last_name_request='B',
            email_request='a@test.fr', phone_request='0102030405',
            crisis=crisis, request_type=request_type,
        )

        response = client.post(reverse('request-transformer', args=[demande.id]), {'cible': 'OFFER'})

        assert response.status_code == status.HTTP_201_CREATED
        nouvelle_offre = Offer.objects.get(title='Cuve avec photo')
        assert nouvelle_offre.photo
        nouvelle_offre.photo.open('rb')
        assert nouvelle_offre.photo.read() == b'contenu-image-factice'
        nouvelle_offre.photo.close()

    def test_rejects_already_assigned_request(self, authenticated_client, crisis, request_type):
        client, _ = _make_admin(authenticated_client)
        demande = Request.objects.create(
            title='Deja affectee', location=Point(5.72, 45.18, srid=4326),
            first_name_request='A', last_name_request='B',
            email_request='a@test.fr', phone_request='0102030405',
            crisis=crisis, request_type=request_type,
        )
        team = Team.objects.create(name='Equipe transform test')
        team.assigned_requests.add(demande)

        response = client.post(reverse('request-transformer', args=[demande.id]), {'cible': 'OFFER'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Request.objects.filter(id=demande.id).exists()

    def test_non_institutional_cannot_transform(self, create_user, crisis, request_type):
        simple_user = create_user(username='simple-transform@test.fr', email='simple-transform@test.fr', type='UTIL_SIMPLE')
        demande = Request.objects.create(
            title='Test permission', location=Point(5.72, 45.18, srid=4326),
            first_name_request='A', last_name_request='B',
            email_request='a@test.fr', phone_request='0102030405',
            crisis=crisis, request_type=request_type,
        )
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.post(reverse('request-transformer', args=[demande.id]), {'cible': 'OFFER'})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert Request.objects.filter(id=demande.id).exists()

    def test_invalid_target_is_rejected(self, authenticated_client, crisis, request_type):
        client, _ = _make_admin(authenticated_client)
        demande = Request.objects.create(
            title='Cible invalide', location=Point(5.72, 45.18, srid=4326),
            first_name_request='A', last_name_request='B',
            email_request='a@test.fr', phone_request='0102030405',
            crisis=crisis, request_type=request_type,
        )

        response = client.post(reverse('request-transformer', args=[demande.id]), {'cible': 'CRISIS'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestTransformerDemandeEnSignalement:
    def test_description_is_lost_but_title_kept(self, authenticated_client, crisis, request_type, information_type_autre):
        client, _ = _make_admin(authenticated_client)
        demande = Request.objects.create(
            title='Arbre sur la route', description='Un chêne bloque la départementale',
            location=Point(5.72, 45.18, srid=4326),
            first_name_request='A', last_name_request='B',
            email_request='a@test.fr', phone_request='0102030405',
            crisis=crisis, request_type=request_type,
        )

        response = client.post(reverse('request-transformer', args=[demande.id]), {'cible': 'INFORMATION'})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['title'] == 'Arbre sur la route'
        assert Information.objects.filter(title='Arbre sur la route').exists()


@pytest.mark.django_db
class TestTransformerOffreSansLocalisation:
    def test_offer_without_location_cannot_become_request(self, authenticated_client, crisis, offer_type_autre):
        client, _ = _make_admin(authenticated_client)
        offre = Offer.objects.create(
            title='Offre sans loc', location=None,
            first_name_offer='A', last_name_offer='B', email_offer='a@test.fr',
            crisis=crisis, offer_type=offer_type_autre,
        )

        response = client.post(reverse('offer-transformer', args=[offre.id]), {'cible': 'REQUEST'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Offer.objects.filter(id=offre.id).exists()


@pytest.mark.django_db
class TestTransformerSignalementEnOffre:
    def test_creates_offer_from_information(self, authenticated_client, crisis, information_type_autre, offer_type_autre):
        client, _ = _make_admin(authenticated_client)
        signalement = Information.objects.create(
            title='Je peux prêter un groupe électrogène',
            location=Point(5.72, 45.18, srid=4326),
            first_name_information='C', last_name_information='D',
            email_information='c@test.fr', phone_information='0102030405',
            crisis=crisis, information_type=information_type_autre,
        )

        response = client.post(reverse('information-transformer', args=[signalement.id]), {'cible': 'OFFER'})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['first_name_offer'] == 'C'
        assert not Information.objects.filter(id=signalement.id).exists()
