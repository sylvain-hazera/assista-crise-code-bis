"""OfferViewSet et RequestViewSet doivent résoudre commune_code une seule fois à la création
(via commune_code_from_point) plutôt que de le laisser NULL — sans lui, get_commune retombe sur
un reverse-géocodage en direct à CHAQUE lecture. Trouvé en mesurant la carte DEMO en direct :
RequestViewSet ne le faisait pas du tout (112 demandes DEMO, commune_code NULL à 100%), d'où
9.3s pour charger /api/demandes/ sur la carte de Grenoble, contre 0.5s une fois corrigé."""
from unittest.mock import patch

import pytest
from django.urls import reverse

from core.models import Offer, OfferType, Request, RequestType


@pytest.mark.django_db
class TestRequestCommuneCodeResolvedAtCreation:

    @patch("core.views.commune_code_from_point")
    def test_commune_code_set_from_location_on_create(self, mock_geocode, api_client, create_user):
        mock_geocode.return_value = "38185"
        rtype = RequestType.objects.create(type="Test résolution commune")
        user = create_user(username="createur-demande@test.fr", email="createur-demande@test.fr", type="UTIL_SIMPLE")
        api_client.force_authenticate(user=user)

        response = api_client.post(reverse('request-list'), {
            "title": "Besoin test", "request_type": rtype.id,
            "location": "POINT (5.72 45.18)",
            "first_name_request": "A", "last_name_request": "B",
            "email_request": "a@test.fr", "phone_request": "0600000000",
        }, format='json')

        assert response.status_code == 201
        demande = Request.objects.get(id=response.data["id"])
        assert demande.commune_code == "38185"
        mock_geocode.assert_called_once()


@pytest.mark.django_db
class TestOfferCommuneCodeResolvedAtCreation:

    @patch("core.views.commune_code_from_point")
    def test_commune_code_set_from_location_on_create(self, mock_geocode, api_client):
        mock_geocode.return_value = "38185"
        otype = OfferType.objects.create(type="Test résolution commune")

        response = api_client.post(reverse('offer-list'), {
            "title": "Offre test", "offer_type": otype.id,
            "location": "POINT (5.72 45.18)",
            "first_name_offer": "A", "last_name_offer": "B", "email_offer": "a@test.fr",
        }, format='json')

        assert response.status_code == 201
        offre = Offer.objects.get(id=response.data["id"])
        assert offre.commune_code == "38185"
