import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Commune,
    ContactInstitution,
    Environment,
    Information,
    InformationType,
    Institution,
    InstitutionType,
    Offer,
    OfferType,
    Request,
    RequestType,
)

# Commune pré-résolue (même valeurs que core/test_vue_secteur.py) pour que Institution.save()
# (commune_secteur_codes) et la vue institutionnelle trouvent tout en base, sans appel réseau
# à geo.api.gouv.fr pendant les tests.
COMMUNE_CODE = "38185"

REQUEST_PAYLOAD = {
    "title": "Besoin de nourriture",
    "location": "POINT (5.7245 45.1885)",
    "commune_code": COMMUNE_CODE,
    "first_name_request": "Marie",
    "last_name_request": "Demandeuse",
    "email_request": "marie.demandeuse@test.fr",
    "phone_request": "0600000000",
    "status": "NON_TRAITEE",
}

INFORMATION_PAYLOAD = {
    "title": "Arbre sur la chaussée",
    "location": "POINT (5.7245 45.1885)",
    "commune_code": COMMUNE_CODE,
    "first_name_information": "Paul",
    "last_name_information": "Signaleur",
    "email_information": "paul.signaleur@test.fr",
    "phone_information": "0600000000",
    "status": "DISPONIBLE",
}

OFFER_PAYLOAD = {
    "title": "Don de couvertures",
    "location": "POINT (5.7245 45.1885)",
    "commune_code": COMMUNE_CODE,
    "first_name_offer": "Julie",
    "last_name_offer": "Donatrice",
    "email_offer": "julie.donatrice@test.fr",
    "phone_offer": "0600000000",
    "status": "DISPONIBLE",
}


@pytest.fixture
def commune_grenoble(db):
    return Commune.objects.create(
        code=COMMUNE_CODE, nom="Grenoble", departement_code="38", epci_code="200040715",
        region_code="84", centre_latitude=45.18, centre_longitude=5.72,
    )


@pytest.fixture
def request_type(db):
    return RequestType.objects.create(type="Nourriture (test privacy)", description="")


@pytest.fixture
def information_type(db):
    return InformationType.objects.create(type="Signalement (test privacy)", description="")


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Couvertures (test privacy)", description="")


@pytest.fixture
def demande(db, request_type, commune_grenoble):
    return Request.objects.create(request_type=request_type, **REQUEST_PAYLOAD)


@pytest.fixture
def information(db, information_type, commune_grenoble):
    return Information.objects.create(information_type=information_type, **INFORMATION_PAYLOAD)


@pytest.fixture
def offer(db, offer_type, commune_grenoble):
    return Offer.objects.create(offer_type=offer_type, **OFFER_PAYLOAD)


@pytest.fixture
def institution(db, commune_grenoble):
    itype = InstitutionType.objects.create(code="MAIRIE_PRIVACY_TEST", libelle="Mairie")
    return Institution.objects.create(
        nom="Mairie de Test Privacy", type=itype, commune_code=COMMUNE_CODE,
    )


@pytest.fixture
def local_authority_client(create_user, institution):
    # La zone de compétence (viewer_zone_code) se résout sur User.institution (FK directe),
    # pas sur ContactInstitution (annuaire de contacts publics, sans rapport) — les deux sont
    # posés ici pour rester fidèle aux deux usages réels d'un compte AUT_LOCALE rattaché.
    user = create_user(username="autorite-privacy@test.fr", email="autorite-privacy@test.fr", type="AUT_LOCALE")
    user.institution = institution
    user.save()
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestRequestLocationPrivacy:

    def test_anonymous_cannot_see_request_location(self, api_client, demande):
        response = api_client.get(reverse('request-detail', args=[demande.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        assert response.data['location'] is None

    def test_anonymous_cannot_see_request_pii(self, api_client, demande):
        # Fuite PII corrigée : hors zone/anonyme, email/téléphone/nom masqués entièrement
        # (None) en PROD, pas seulement en DEMO — voir RequestSerializer.to_representation.
        response = api_client.get(reverse('request-detail', args=[demande.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['first_name_request'] is None
        assert response.data['last_name_request'] is None
        assert response.data['email_request'] is None
        assert response.data['phone_request'] is None

    def test_simple_authenticated_user_cannot_see_request_location(self, authenticated_client, demande):
        client, _ = authenticated_client
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['latitude'] is None

    def test_simple_authenticated_user_cannot_see_request_pii(self, authenticated_client, demande):
        client, _ = authenticated_client
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['email_request'] is None
        assert response.data['phone_request'] is None
        assert response.data['first_name_request'] is None
        assert response.data['last_name_request'] is None

    def test_institutional_actor_can_see_request_location(self, local_authority_client, demande):
        client, _ = local_authority_client
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['latitude'] is not None
        assert response.data['longitude'] is not None
        assert response.data['location'] is not None

    def test_institutional_actor_can_see_request_pii(self, local_authority_client, demande):
        client, _ = local_authority_client
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['first_name_request'] == 'Marie'
        assert response.data['last_name_request'] == 'Demandeuse'
        assert response.data['email_request'] == 'marie.demandeuse@test.fr'
        assert response.data['phone_request'] == '0600000000'

    def test_institutional_actor_in_demo_sees_masked_request_pii(self, local_authority_client, request_type):
        # Non-régression : le masquage réversible (mask_email/mask_phone) reste appliqué en
        # zone DEMO pour un acteur par ailleurs autorisé — seule la branche hors-zone est
        # passée au masquage total par le correctif PII. Objet créé en environment=DEMO :
        # EnvironmentScopedViewSetMixin filtre par zone active, une demande PROD serait 404 ici.
        demande = Request.objects.create(
            request_type=request_type, environment=Environment.DEMO, **REQUEST_PAYLOAD
        )
        client, user = local_authority_client
        # get_effective_role bascule sur demo_role (pas type) en zone DEMO — sans ça l'acteur
        # perd son rôle institutionnel en DEMO et retombe dans la branche hors-zone (None
        # partout) plutôt que dans le masquage réversible testé ici.
        user.demo_role = 'AUT_LOCALE'
        user.save()
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.get(reverse('request-detail', args=[demande.id]))
        assert response.data['email_request'] != 'marie.demandeuse@test.fr'
        assert response.data['email_request'] is not None
        assert response.data['email_request'].endswith('@zone.demo')
        assert response.data['phone_request'] != '0600000000'
        assert response.data['phone_request'] is not None


@pytest.mark.django_db
class TestInformationLocationPrivacy:

    def test_anonymous_cannot_see_information_location(self, api_client, information):
        response = api_client.get(reverse('information-detail', args=[information.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        assert response.data['location'] is None

    def test_anonymous_cannot_see_information_pii(self, api_client, information):
        response = api_client.get(reverse('information-detail', args=[information.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['first_name_information'] is None
        assert response.data['last_name_information'] is None
        assert response.data['email_information'] is None
        assert response.data['phone_information'] is None

    def test_institutional_actor_can_see_information_location(self, local_authority_client, information):
        client, _ = local_authority_client
        response = client.get(reverse('information-detail', args=[information.id]))
        assert response.data['latitude'] is not None
        assert response.data['longitude'] is not None
        assert response.data['location'] is not None

    def test_institutional_actor_can_see_information_pii(self, local_authority_client, information):
        client, _ = local_authority_client
        response = client.get(reverse('information-detail', args=[information.id]))
        assert response.data['first_name_information'] == 'Paul'
        assert response.data['last_name_information'] == 'Signaleur'
        assert response.data['email_information'] == 'paul.signaleur@test.fr'
        assert response.data['phone_information'] == '0600000000'


@pytest.mark.django_db
class TestOfferLocationPrivacy:
    """Offer suit la même règle que Request/Information (voir OfferSerializer._location_visible
    et to_representation) mais n'a pas de branche "participant du dossier lié" : seul le rôle
    institutionnel donne accès."""

    def test_anonymous_cannot_see_offer_location_or_pii(self, api_client, offer):
        response = api_client.get(reverse('offer-detail', args=[offer.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        assert response.data['location'] is None
        assert response.data['first_name_offer'] is None
        assert response.data['last_name_offer'] is None
        assert response.data['email_offer'] is None
        assert response.data['phone_offer'] is None

    def test_simple_authenticated_user_cannot_see_offer_location_or_pii(self, authenticated_client, offer):
        client, _ = authenticated_client
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['latitude'] is None
        assert response.data['email_offer'] is None
        assert response.data['phone_offer'] is None

    def test_institutional_actor_can_see_offer_location_and_pii(self, local_authority_client, offer):
        client, _ = local_authority_client
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['latitude'] is not None
        assert response.data['longitude'] is not None
        assert response.data['first_name_offer'] == 'Julie'
        assert response.data['last_name_offer'] == 'Donatrice'
        assert response.data['email_offer'] == 'julie.donatrice@test.fr'
        assert response.data['phone_offer'] == '0600000000'

    def test_institutional_actor_in_demo_sees_masked_offer_pii(self, local_authority_client, offer_type):
        offer = Offer.objects.create(
            offer_type=offer_type, environment=Environment.DEMO, **OFFER_PAYLOAD
        )
        client, user = local_authority_client
        user.demo_role = 'AUT_LOCALE'
        user.save()
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['email_offer'] != 'julie.donatrice@test.fr'
        assert response.data['email_offer'] is not None
        assert response.data['email_offer'].endswith('@zone.demo')
        assert response.data['phone_offer'] != '0600000000'
        assert response.data['phone_offer'] is not None
