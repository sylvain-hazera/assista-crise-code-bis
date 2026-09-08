"""Zone d'un contact institution (préparation PCS/PICS, voir ContactInstitution.zone) et
restriction de la création de zones aux mairies/EPCI (ZoneViewSet.perform_create)."""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Zone


def _institution(code="MAIRIE", libelle="Mairie"):
    itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": libelle})
    return Institution.objects.create(nom=f"Institution {code} zone test", type=itype)


@pytest.fixture
def mairie(db):
    return _institution("MAIRIE", "Mairie")


@pytest.fixture
def sdis(db):
    return _institution("SDIS_CONTACT_ZONE_TEST", "SDIS")


@pytest.fixture
def zone(mairie):
    return Zone.objects.create(institution=mairie, nom="Quartier Nord")


@pytest.fixture
def own_institution_client(create_user, mairie):
    user = create_user(username="membre-mairie-zone@test.fr", email="membre-mairie-zone@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def admin_client(create_user):
    user = create_user(username="admin-zone-contact@test.fr", email="admin-zone-contact@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestContactInstitutionZone:

    def test_create_contact_with_zone(self, own_institution_client, mairie, zone, create_user):
        client, _ = own_institution_client
        target = create_user(username="futur-contact-zone@test.fr", email="futur-contact-zone@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('contactinstitution-list'),
            {"institution": str(mairie.id), "utilisateur": str(target.id), "actif": True, "zone": str(zone.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data["zone"]) == str(zone.id)

    def test_update_contact_zone(self, own_institution_client, mairie, zone, create_user):
        client, user = own_institution_client
        contact = ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)

        response = client.put(
            reverse('contactinstitution-detail', args=[contact.id]),
            {
                "institution": str(mairie.id), "utilisateur": str(user.id),
                "actif": True, "fonction": "", "contact_principal": False, "zone": str(zone.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        contact.refresh_from_db()
        assert contact.zone_id == zone.id

    def test_zone_optional_and_defaults_to_none(self, own_institution_client, mairie, create_user):
        client, _ = own_institution_client
        target = create_user(username="sans-zone-contact@test.fr", email="sans-zone-contact@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('contactinstitution-list'),
            {"institution": str(mairie.id), "utilisateur": str(target.id), "actif": True},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["zone"] is None


@pytest.mark.django_db
class TestZoneCreationRestrictedToLocalAuthority:

    def test_mairie_can_create_zone(self, own_institution_client, mairie):
        client, _ = own_institution_client
        response = client.post(reverse('zone-list'), {"nom": "Quartier Sud"}, format='json')
        assert response.status_code == status.HTTP_201_CREATED

    def test_non_local_authority_institution_cannot_create_zone(self, create_user, sdis):
        user = create_user(username="membre-sdis-zone@test.fr", email="membre-sdis-zone@test.fr", type="SECOURS")
        ContactInstitution.objects.create(institution=sdis, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('zone-list'), {"nom": "Zone SDIS"}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Zone.objects.filter(institution=sdis).exists()

    def test_admin_can_create_zone_for_any_institution(self, admin_client, sdis):
        client, _ = admin_client
        response = client.post(
            reverse('zone-list'), {"nom": "Zone admin", "institution": str(sdis.id)}, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_epci_can_create_zone(self, create_user):
        epci = _institution("EPCI", "Communauté de communes")
        user = create_user(username="membre-epci-zone@test.fr", email="membre-epci-zone@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=epci, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('zone-list'), {"nom": "Zone EPCI"}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
