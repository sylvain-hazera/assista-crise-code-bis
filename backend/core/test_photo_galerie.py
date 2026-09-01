from io import BytesIO

import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution,
    Institution,
    InstitutionType,
    Offer,
    OfferPhoto,
    OfferType,
    Request,
    RequestPhoto,
    RequestType,
)


def _make_test_image(name="test.png"):
    img = Image.new("RGB", (10, 10), color="blue")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Hébergement (test galerie)", description="")


@pytest.fixture
def offer(db, offer_type, create_user):
    author = create_user(username="galerie-offrant@test.fr", email="galerie-offrant@test.fr", type="UTIL_SIMPLE")
    return Offer.objects.create(
        title="Aide bénévole galerie", location="POINT (5.7245 45.1885)",
        first_name_offer="Jean", last_name_offer="Bénévole", email_offer="galerie-offrant@test.fr",
        status="DISPONIBLE", offer_type=offer_type, author=author,
    )


@pytest.fixture
def request_type(db):
    return RequestType.objects.create(type="Matériel (test galerie)", description="")


@pytest.fixture
def demande(db, request_type, create_user):
    author = create_user(username="galerie-demandeur@test.fr", email="galerie-demandeur@test.fr", type="UTIL_SIMPLE")
    return Request.objects.create(
        title="Demande galerie", location=Point(5.7245, 45.1885, srid=4326),
        first_name_request="Anne", last_name_request="Demandeuse", email_request="galerie-demandeur@test.fr",
        phone_request="0600000000", status="NON_TRAITEE", request_type=request_type, author=author,
    )


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_GALERIE_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie galerie test", type=itype)


@pytest.fixture
def institutional_client(create_user, institution):
    user = create_user(username="institutionnel-galerie@test.fr", email="institutionnel-galerie@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestOfferPhotoGalerie:

    def test_anonymous_can_add_photo(self, offer):
        client = APIClient()
        response = client.post(
            reverse('offerphoto-list'),
            {"offer": str(offer.id), "image": _make_test_image(), "ordre": 0},
            format='multipart',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert OfferPhoto.objects.filter(offer=offer).count() == 1

    def test_tenth_additional_photo_rejected(self, offer):
        client = APIClient()
        for i in range(9):
            response = client.post(
                reverse('offerphoto-list'),
                {"offer": str(offer.id), "image": _make_test_image(f"photo-{i}.png"), "ordre": i},
                format='multipart',
            )
            assert response.status_code == status.HTTP_201_CREATED

        response = client.post(
            reverse('offerphoto-list'),
            {"offer": str(offer.id), "image": _make_test_image("photo-10.png"), "ordre": 9},
            format='multipart',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert OfferPhoto.objects.filter(offer=offer).count() == 9

    def test_preview_forbidden_for_anonymous(self, offer):
        photo = OfferPhoto.objects.create(offer=offer, image=_make_test_image(), environment=offer.environment)
        client = APIClient()
        response = client.get(reverse('offerphoto-preview', args=[photo.id]))
        assert response.status_code == 403

    def test_preview_forbidden_for_unrelated_authenticated_user(self, offer, create_user):
        photo = OfferPhoto.objects.create(offer=offer, image=_make_test_image(), environment=offer.environment)
        tiers = create_user(username="tiers-galerie@test.fr", email="tiers-galerie@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=tiers)
        response = client.get(reverse('offerphoto-preview', args=[photo.id]))
        assert response.status_code == 403

    def test_preview_allowed_for_institutional_actor(self, offer, institutional_client):
        photo = OfferPhoto.objects.create(offer=offer, image=_make_test_image(), environment=offer.environment)
        client, _ = institutional_client
        response = client.get(reverse('offerphoto-preview', args=[photo.id]))
        assert response.status_code == status.HTTP_200_OK

    def test_preview_allowed_for_offer_author(self, offer):
        photo = OfferPhoto.objects.create(offer=offer, image=_make_test_image(), environment=offer.environment)
        client = APIClient()
        client.force_authenticate(user=offer.author)
        response = client.get(reverse('offerphoto-preview', args=[photo.id]))
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRequestPhotoGalerie:

    def test_anonymous_can_add_photo(self, demande):
        client = APIClient()
        response = client.post(
            reverse('requestphoto-list'),
            {"request": str(demande.id), "image": _make_test_image(), "ordre": 0},
            format='multipart',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert RequestPhoto.objects.filter(request=demande).count() == 1

    def test_tenth_additional_photo_rejected(self, demande):
        client = APIClient()
        for i in range(9):
            response = client.post(
                reverse('requestphoto-list'),
                {"request": str(demande.id), "image": _make_test_image(f"photo-{i}.png"), "ordre": i},
                format='multipart',
            )
            assert response.status_code == status.HTTP_201_CREATED

        response = client.post(
            reverse('requestphoto-list'),
            {"request": str(demande.id), "image": _make_test_image("photo-10.png"), "ordre": 9},
            format='multipart',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert RequestPhoto.objects.filter(request=demande).count() == 9

    def test_preview_forbidden_for_anonymous(self, demande):
        photo = RequestPhoto.objects.create(request=demande, image=_make_test_image(), environment=demande.environment)
        client = APIClient()
        response = client.get(reverse('requestphoto-preview', args=[photo.id]))
        assert response.status_code == 403

    def test_preview_allowed_for_institutional_actor(self, demande, institutional_client):
        photo = RequestPhoto.objects.create(request=demande, image=_make_test_image(), environment=demande.environment)
        client, _ = institutional_client
        response = client.get(reverse('requestphoto-preview', args=[photo.id]))
        assert response.status_code == status.HTTP_200_OK
