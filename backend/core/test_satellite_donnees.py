"""Rafraîchissement central -> local (SatelliteViewSet.donnees) — voir le cadrage "Chantier B"
section 4 : le satellite doit voir non seulement les crises actives de SA zone, mais aussi ce
qui leur est rattaché (demandes/offres/signalements), y compris soumis directement au site
public par un citoyen — sans quoi un satellite resté hors-ligne au moment d'une remontée
citoyenne ne la verrait jamais. Réutilise filter_queryset_to_viewer_zone tel quel (le compte de
service a bien `institution` renseignée), voir test_reporting_zone_widening.py/
test_information_zone_scoping.py pour les mêmes fixtures Commune/Offer/Request/Information."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Commune, Crisis, Information, InformationType, Institution, InstitutionType, Offer,
    OfferType, Request, RequestType, Satellite, StatutEnrolementSatellite,
)


@pytest.fixture
def commune_a(db):
    return Commune.objects.create(
        code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


@pytest.fixture
def commune_b(db):
    return Commune.objects.create(
        code="59350", nom="Lille", departement_code="59", epci_code="200093201",
        region_code="32", centre_latitude=50.63, centre_longitude=3.06,
    )


@pytest.fixture
def institution_a(commune_a):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie A", type=itype, commune_code=commune_a.code)


@pytest.fixture
def satellite_a(create_user, institution_a):
    # institution DOIT être posée ici, exactement comme le fait SatelliteViewSet.valider en
    # conditions réelles — sinon _institution_commune_or_400/filter_queryset_to_viewer_zone ne
    # peut pas résoudre la zone de ce compte de service.
    compte = create_user(
        username="satellite-donnees-a@service.fr", email="satellite-donnees-a@service.fr",
        type="UTIL_SIMPLE", institution=institution_a,
    )
    return Satellite.objects.create(
        institution=institution_a, nom="Sat A", profil="GW",
        statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte,
    )


@pytest.fixture
def satellite_client(satellite_a):
    client = APIClient()
    client.force_authenticate(user=satellite_a.compte_service)
    return client


@pytest.fixture
def crisis_a(commune_a):
    return Crisis.objects.create(
        name="Crise A", type="INONDATION", location=Point(commune_a.centre_longitude, commune_a.centre_latitude, srid=4326),
        zone_communes=[commune_a.code],
    )


@pytest.fixture
def crisis_fermee(commune_a):
    return Crisis.objects.create(
        name="Crise fermée", type="INONDATION",
        location=Point(commune_a.centre_longitude, commune_a.centre_latitude, srid=4326),
        zone_communes=[commune_a.code], end_date=timezone.now(),
    )


def _geo(commune):
    return {
        "commune_code": commune.code, "epci_code": commune.epci_code,
        "departement_code": commune.departement_code, "region_code": commune.region_code,
    }


def _make_request(commune, **kwargs):
    rtype, _ = RequestType.objects.get_or_create(type="Satellite donnees test")
    return Request.objects.create(
        title="Demande", request_type=rtype, first_name_request="T", last_name_request="T",
        email_request="t@test.fr", phone_request="0600000000", **_geo(commune), **kwargs,
    )


def _make_offer(commune, **kwargs):
    otype, _ = OfferType.objects.get_or_create(type="Satellite donnees test")
    return Offer.objects.create(
        title="Offre", offer_type=otype, first_name_offer="T", last_name_offer="T",
        email_offer="t@test.fr", **_geo(commune), **kwargs,
    )


def _make_information(commune, **kwargs):
    itype, _ = InformationType.objects.get_or_create(type="Satellite donnees test")
    return Information.objects.create(
        title="Signalement", information_type=itype, first_name_information="T", last_name_information="T",
        email_information="t@test.fr", phone_information="0600000000",
        location=Point(1, 1, srid=4326), commune_code=commune.code, **kwargs,
    )


@pytest.mark.django_db
class TestDonneesScopeParZone:

    def test_crise_active_de_la_zone_incluse(self, satellite_client, satellite_a, crisis_a):
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert response.status_code == status.HTTP_200_OK
        assert any(c["id"] == str(crisis_a.id) for c in response.data["crises"])

    def test_crise_fermee_exclue(self, satellite_client, satellite_a, crisis_fermee):
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert not any(c["id"] == str(crisis_fermee.id) for c in response.data["crises"])

    def test_demande_rattachee_a_la_crise_de_la_zone_incluse(self, satellite_client, satellite_a, commune_a, crisis_a):
        demande = _make_request(commune_a, crisis=crisis_a)
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert any(d["id"] == str(demande.id) for d in response.data["demandes"])

    def test_demande_soumise_par_internet_sans_crise_encore_triee_incluse(self, satellite_client, satellite_a, commune_a):
        # Simule une demande d'aide soumise directement au site public, pas encore rattachée à
        # une crise (crisis=None) — c'est exactement le cas que la redescente doit couvrir.
        demande = _make_request(commune_a, crisis=None)
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert any(d["id"] == str(demande.id) for d in response.data["demandes"])

    def test_demande_hors_zone_exclue(self, satellite_client, satellite_a, commune_b, crisis_a):
        demande = _make_request(commune_b, crisis=crisis_a)
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert not any(d["id"] == str(demande.id) for d in response.data["demandes"])

    def test_offre_de_la_zone_incluse(self, satellite_client, satellite_a, commune_a, crisis_a):
        offre = _make_offer(commune_a, crisis=crisis_a)
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert any(o["id"] == str(offre.id) for o in response.data["offres"])

    def test_signalement_de_la_zone_incluse(self, satellite_client, satellite_a, commune_a, crisis_a):
        signalement = _make_information(commune_a, crisis=crisis_a)
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert any(s["id"] == str(signalement.id) for s in response.data["signalements"])

    def test_signalement_hors_zone_exclu(self, satellite_client, satellite_a, commune_b, crisis_a):
        signalement = _make_information(commune_b, crisis=crisis_a)
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert not any(s["id"] == str(signalement.id) for s in response.data["signalements"])


@pytest.mark.django_db
class TestDonneesAccesEtHeartbeat:

    def test_met_a_jour_dernier_contact(self, satellite_client, satellite_a):
        assert satellite_a.dernier_contact is None
        satellite_client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        satellite_a.refresh_from_db()
        assert satellite_a.dernier_contact is not None

    def test_un_autre_compte_ne_peut_pas_lire_les_donnees(self, create_user, satellite_a):
        autre = create_user(username="pas-le-satellite@test.fr", email="pas-le-satellite@test.fr")
        client = APIClient()
        client.force_authenticate(user=autre)
        response = client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_anonyme_refuse(self, satellite_a):
        client = APIClient()
        response = client.get(reverse('satellite-donnees', args=[satellite_a.id]))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
