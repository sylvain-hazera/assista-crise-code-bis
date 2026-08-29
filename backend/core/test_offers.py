import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    ContactInstitution,
    DisponibiliteOffre,
    Dossier,
    DossierParticipant,
    Institution,
    InstitutionType,
    MaterielCatalogue,
    Offer,
    OfferType,
)

OFFER_PAYLOAD = {
    "title": "Aide bénévole",
    "location": "POINT (5.7245 45.1885)",
    "first_name_offer": "Jean",
    "last_name_offer": "Bénévole",
    "email_offer": "jean.benevole@test.fr",
    "status": "DISPONIBLE",
}


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Hébergement (test)", description="")


@pytest.fixture
def offer(db, offer_type, create_user):
    author = create_user(username="offrant@test.fr", email="offrant@test.fr", type="UTIL_SIMPLE")
    return Offer.objects.create(offer_type=offer_type, author=author, **OFFER_PAYLOAD)


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_OFFER_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie de Test Offres", type=itype)


@pytest.fixture
def local_authority_client(create_user, institution):
    user = create_user(username="autorite-offres@test.fr", email="autorite-offres@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestDisponibiliteOffre:

    def test_declare_availability_slots(self, api_client, offer):
        response = api_client.post(
            reverse('disponibiliteoffre-list'),
            {"offer": str(offer.id), "date": "2026-09-01", "creneau": "MATIN"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert DisponibiliteOffre.objects.filter(offer=offer, date="2026-09-01", creneau="MATIN").exists()

    def test_availability_filterable_by_offer(self, api_client, offer):
        DisponibiliteOffre.objects.create(offer=offer, date="2026-09-01", creneau="MATIN")
        DisponibiliteOffre.objects.create(offer=offer, date="2026-09-01", creneau="SOIR")

        response = api_client.get(reverse('disponibiliteoffre-list'), {"offer": str(offer.id)})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2


@pytest.mark.django_db
class TestAssignOfferToDossier:

    def test_institutional_actor_can_assign_offer_to_dossier(self, local_authority_client, offer):
        client, _ = local_authority_client
        crisis = Crisis.objects.create(name="Crise test", type="INCEDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-TEST-1", crise=crisis, titre="Dossier test", description="desc",
        )

        response = client.post(
            reverse('offer-assign-dossier', args=[offer.id]),
            {"dossier": str(dossier.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=offer.author, role=DossierParticipant.Role.OFFRANT
        ).exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [offer.email_offer]

    def test_cannot_assign_authorless_offer_to_dossier(self, local_authority_client, offer_type):
        client, _ = local_authority_client
        anonymous_offer = Offer.objects.create(offer_type=offer_type, author=None, **{
            **OFFER_PAYLOAD, "email_offer": "anonyme@test.fr",
        })
        crisis = Crisis.objects.create(name="Crise test 2", type="INCEDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-TEST-2", crise=crisis, titre="Dossier test 2", description="desc",
        )

        response = client.post(
            reverse('offer-assign-dossier', args=[anonymous_offer.id]),
            {"dossier": str(dossier.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not DossierParticipant.objects.filter(dossier=dossier).exists()

    def test_simple_user_cannot_assign_offer_to_dossier(self, authenticated_client, offer):
        client, _ = authenticated_client
        crisis = Crisis.objects.create(name="Crise test 3", type="INCEDIE", location="POINT (5.72 45.18)")
        dossier = Dossier.objects.create(
            numero="DOS-TEST-3", crise=crisis, titre="Dossier test 3", description="desc",
        )

        response = client.post(
            reverse('offer-assign-dossier', args=[offer.id]),
            {"dossier": str(dossier.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestOfferTypeCatalog:

    def test_offer_type_list_is_public(self, api_client):
        response = api_client.get(reverse('offertype-list'))
        assert response.status_code == status.HTTP_200_OK

    def test_offer_type_list_excludes_inactive(self, api_client):
        OfferType.objects.create(type="Assistance immédiate (test)", actif=False)
        active = OfferType.objects.create(type="Actif (test)", actif=True)

        response = api_client.get(reverse('offertype-list'))
        labels = [t['type'] for t in response.data]

        assert "Assistance immédiate (test)" not in labels
        assert active.type in labels


@pytest.mark.django_db
class TestOfferLocationPrivacy:

    def test_anonymous_cannot_see_offer_location(self, api_client, offer):
        response = api_client.get(reverse('offer-detail', args=[offer.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        assert response.data['location'] is None

    def test_simple_authenticated_user_cannot_see_offer_location(self, authenticated_client, offer):
        client, _ = authenticated_client
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['latitude'] is None

    def test_institutional_actor_can_see_offer_location(self, local_authority_client, offer):
        client, _ = local_authority_client
        response = client.get(reverse('offer-detail', args=[offer.id]))
        assert response.data['latitude'] is not None
        assert response.data['longitude'] is not None
        assert response.data['location'] is not None

    def test_offer_creation_without_location_succeeds(self, api_client, offer_type):
        payload = {**OFFER_PAYLOAD, "email_offer": "sans-adresse@test.fr", "offer_type": str(offer_type.id)}
        del payload["location"]

        response = api_client.post(reverse('offer-list'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['latitude'] is None


@pytest.mark.django_db
class TestOfferEngagementFields:
    """diplome_secourisme (bénévole en personne) et materiel_livraison (offre de matériel
    seul) — voir propose-help-form pour la logique d'affichage conditionnelle."""

    def test_declares_diplome_secourisme(self, api_client, offer_type):
        payload = {
            **OFFER_PAYLOAD,
            "email_offer": "secouriste@test.fr",
            "offer_type": str(offer_type.id),
            "diplome_secourisme": True,
        }
        response = api_client.post(reverse('offer-list'), payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['diplome_secourisme'] is True
        assert Offer.objects.get(email_offer="secouriste@test.fr").diplome_secourisme is True

    def test_diplome_secourisme_defaults_to_false(self, offer):
        assert offer.diplome_secourisme is False

    def test_declares_materiel_livraison_possible(self, api_client, offer_type):
        payload = {
            **OFFER_PAYLOAD,
            "email_offer": "materiel-livrable@test.fr",
            "offer_type": str(offer_type.id),
            "materiel_livraison": "LIVRAISON_POSSIBLE",
        }
        response = api_client.post(reverse('offer-list'), payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['materiel_livraison'] == "LIVRAISON_POSSIBLE"

    def test_materiel_livraison_rejects_invalid_choice(self, api_client, offer_type):
        payload = {
            **OFFER_PAYLOAD,
            "email_offer": "materiel-invalide@test.fr",
            "offer_type": str(offer_type.id),
            "materiel_livraison": "TELEPORTATION",
        }
        response = api_client.post(reverse('offer-list'), payload, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_materiel_livraison_optional(self, offer):
        assert offer.materiel_livraison is None

    def test_declares_confirmation_reglementaire_et_immatriculation(self, api_client, offer_type):
        payload = {
            **OFFER_PAYLOAD,
            "email_offer": "vehicule-conforme@test.fr",
            "offer_type": str(offer_type.id),
            "confirmation_reglementaire": True,
            "immatriculation": "AB-123-CD",
        }
        response = api_client.post(reverse('offer-list'), payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['confirmation_reglementaire'] is True
        assert response.data['immatriculation'] == "AB-123-CD"

    def test_confirmation_reglementaire_defaults_to_false(self, offer):
        assert offer.confirmation_reglementaire is False
        assert offer.immatriculation is None

    def test_declares_materiel_catalogue_quantite_unite(self, api_client, offer_type):
        catalogue_item = MaterielCatalogue.objects.create(nom='Lits de camp (test offre)')
        payload = {
            **OFFER_PAYLOAD,
            "email_offer": "lits-de-camp@test.fr",
            "offer_type": str(offer_type.id),
            "materiel_type": "AUTRE",
            "materiel_catalogue": str(catalogue_item.id),
            "quantite": 12,
            "unite": "unité",
        }
        response = api_client.post(reverse('offer-list'), payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['materiel_catalogue_nom'] == 'Lits de camp (test offre)'
        assert response.data['quantite'] == 12
        assert response.data['unite'] == 'unité'

    def test_materiel_catalogue_quantite_unite_optional(self, offer):
        assert offer.materiel_catalogue is None
        assert offer.quantite is None
        assert offer.unite is None
