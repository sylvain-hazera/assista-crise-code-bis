from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models import (
    Crisis,
    Dossier,
    Information,
    InformationType,
    Institution,
    InstitutionType,
    Offer,
    OfferType,
    PointOperationnel,
    PointType,
    Request,
    RequestType,
    Team,
    User,
)


def _make_mairie_user(commune_code="38185", code="MAIRIE_VME"):
    itype = InstitutionType.objects.create(code=code, libelle="Mairie")
    institution = Institution.objects.create(
        nom="Mairie Vue Mairie Étendue Test", type=itype, commune_code=commune_code, commune_nom="Grenoble",
    )
    user = User.objects.create_user(
        username=f"mairie-{code}@vmetest.fr", email=f"mairie-{code}@vmetest.fr", password="Test1234!",
        type="AUT_LOCALE", institution=institution,
    )
    return user, institution


@pytest.mark.django_db
class TestOfferVueMairie:

    @patch("core.views.commune_code_from_point")
    def test_filters_by_commune(self, mock_geocode, api_client):
        otype = OfferType.objects.create(type="Matériel (vue mairie test)", description="")
        offre_in = Offer.objects.create(
            title="Offre dans la commune", location=Point(1, 1, srid=4326),
            first_name_offer="A", last_name_offer="B", email_offer="a@t.fr", offer_type=otype,
        )
        offre_out = Offer.objects.create(
            title="Offre hors commune", location=Point(2, 2, srid=4326),
            first_name_offer="C", last_name_offer="D", email_offer="c@t.fr", offer_type=otype,
        )
        mock_geocode.side_effect = lambda p: "38185" if p.x == 1 else "75056"

        user, _ = _make_mairie_user()
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse('offer-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        titles = [o['title'] for o in response.data]
        assert titles == ["Offre dans la commune"]

    def test_requires_institution_with_commune(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.save()

        response = client.get(reverse('offer-vue-mairie'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_requires_authentication(self, api_client):
        response = api_client.get(reverse('offer-vue-mairie'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestPointOperationnelVueMairie:

    @patch("core.views.commune_code_from_point")
    def test_filters_by_commune(self, mock_geocode, api_client):
        ptype = PointType.objects.create(code="POINT_VME_TEST", libelle="Test")
        point_in = PointOperationnel.objects.create(nom="Point dans la commune", type=ptype, location=Point(1, 1, srid=4326))
        point_out = PointOperationnel.objects.create(nom="Point hors commune", type=ptype, location=Point(2, 2, srid=4326))
        mock_geocode.side_effect = lambda p: "38185" if p.x == 1 else "75056"

        user, _ = _make_mairie_user()
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse('pointoperationnel-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        noms = [p['nom'] for p in response.data]
        assert noms == ["Point dans la commune"]

    def test_requires_institution_with_commune(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.save()

        response = client.get(reverse('pointoperationnel-vue-mairie'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestTeamVueMairie:

    def test_filters_teams_by_institution_commune(self, api_client):
        user, institution = _make_mairie_user()
        autre_itype = InstitutionType.objects.create(code="MAIRIE_VME_AUTRE", libelle="Mairie")
        autre_institution = Institution.objects.create(
            nom="Autre institution", type=autre_itype, commune_code="75056", commune_nom="Paris",
        )
        equipe_in = Team.objects.create(name="Équipe de la mairie", institution=institution)
        Team.objects.create(name="Équipe d'ailleurs", institution=autre_institution)

        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('team-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        ids = [t['id'] for t in response.data]
        assert ids == [str(equipe_in.id)]

    def test_requires_institution_with_commune(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.save()

        response = client.get(reverse('team-vue-mairie'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestDossierVueMairie:

    def test_filters_by_demande_information_or_equipe_commune(self, api_client):
        user, institution = _make_mairie_user()
        crisis = Crisis.objects.create(name="Crise dossier vue mairie", type="INCENDIE", location=Point(1, 1, srid=4326))
        request_type = RequestType.objects.create(type="Besoin (vue mairie test)", description="")
        information_type = InformationType.objects.create(type="Signalement (vue mairie test)", description="")

        demande_in = Request.objects.create(
            title="Demande commune", location=Point(1, 1, srid=4326), first_name_request="A", last_name_request="B",
            email_request="a@t.fr", phone_request="0600000000", request_type=request_type, commune_code="38185",
        )
        dossier_via_demande = Dossier.objects.create(numero="D-VME-1", crise=crisis, demande=demande_in)

        demande_out = Request.objects.create(
            title="Demande ailleurs", location=Point(2, 2, srid=4326), first_name_request="C", last_name_request="D",
            email_request="c@t.fr", phone_request="0600000000", request_type=request_type, commune_code="75056",
        )
        Dossier.objects.create(numero="D-VME-2", crise=crisis, demande=demande_out)

        autre_itype = InstitutionType.objects.create(code="MAIRIE_VME_DOSSIER", libelle="Mairie")
        autre_institution = Institution.objects.create(nom="Autre institution dossier", type=autre_itype, commune_code="75056")
        equipe_ailleurs = Team.objects.create(name="Équipe ailleurs dossier", institution=autre_institution)
        Dossier.objects.create(numero="D-VME-3", crise=crisis, equipe=equipe_ailleurs)

        equipe_mairie = Team.objects.create(name="Équipe mairie dossier", institution=institution)
        dossier_via_equipe = Dossier.objects.create(numero="D-VME-4", crise=crisis, equipe=equipe_mairie)

        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('dossier-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        numeros = {d['numero'] for d in response.data}
        assert numeros == {"D-VME-1", "D-VME-4"}

    def test_requires_institution_with_commune(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.save()

        response = client.get(reverse('dossier-vue-mairie'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
