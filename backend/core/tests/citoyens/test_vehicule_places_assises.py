"""nombre_places_assises (Offer/Request/MaterielPoint) : capacité d'un véhicule en nombre de
places assises disponibles EN PLUS du conducteur — même colonne "Nb de places" que le tableau
"Véhicules détenus par la commune" d'un PCS. Champ nullable simple, exposé via fields='__all__'
sur les trois serializers, sans logique conditionnelle particulière."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import MaterielCatalogue, MaterielPoint, Offer, OfferType, PointOperationnel, PointType, Request, RequestType


@pytest.mark.django_db
class TestOfferNombrePlacesAssises:

    def test_set_on_creation(self, api_client):
        otype = OfferType.objects.create(type="Transport véhicule test")

        response = api_client.post(reverse('offer-list'), {
            "title": "Minibus disponible", "offer_type": otype.id,
            "transport_type": "PERSONNES", "nombre_places_assises": 8,
            "first_name_offer": "A", "last_name_offer": "B", "email_offer": "a@test.fr",
        }, format='json')

        assert response.status_code == 201
        offre = Offer.objects.get(id=response.data["id"])
        assert offre.nombre_places_assises == 8

    def test_null_by_default(self, api_client):
        otype = OfferType.objects.create(type="Offre sans véhicule test")

        response = api_client.post(reverse('offer-list'), {
            "title": "Offre quelconque", "offer_type": otype.id,
            "first_name_offer": "A", "last_name_offer": "B", "email_offer": "a@test.fr",
        }, format='json')

        assert response.status_code == 201
        offre = Offer.objects.get(id=response.data["id"])
        assert offre.nombre_places_assises is None


@pytest.mark.django_db
class TestRequestNombrePlacesAssises:

    def test_set_on_creation(self, api_client):
        rtype = RequestType.objects.create(type="Transport véhicule test demande")

        response = api_client.post(reverse('request-list'), {
            "title": "Besoin de transport", "request_type": rtype.id,
            "nombre_places_assises": 4,
            "first_name_request": "A", "last_name_request": "B",
            "email_request": "a@test.fr", "phone_request": "0600000000",
        }, format='json')

        assert response.status_code == 201
        demande = Request.objects.get(id=response.data["id"])
        assert demande.nombre_places_assises == 4


@pytest.mark.django_db
class TestMaterielPointNombrePlacesAssises:

    def test_set_on_creation(self, create_user):
        user = create_user(username="resp-vehicule@test.fr", email="resp-vehicule@test.fr", type="AUT_LOCALE")
        point_type = PointType.objects.create(code="STOCK_VEHICULE_TEST", libelle="Point stock véhicule test")
        point = PointOperationnel.objects.create(nom="Centre véhicule test", type=point_type, responsable=user)
        item = MaterielCatalogue.objects.create(nom="Minibus communal")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(reverse('materielpoint-list'), {
            "point": str(point.id), "item": str(item.id), "nombre_places_assises": 9,
        }, format='json')

        assert response.status_code == 201
        materiel = MaterielPoint.objects.get(id=response.data["id"])
        assert materiel.nombre_places_assises == 9
