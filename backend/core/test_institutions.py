import pytest
from django.urls import reverse
from rest_framework import status

from core.models import Institution, InstitutionType, InstitutionDomaine, ContactInstitution, AffectationRoleOperationnel


@pytest.mark.django_db
class TestInstitutionCRUD:

    def test_create_institution_authenticated(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")

        response = client.post(
            reverse('institution-list'),
            {"nom": "Mairie de Test", "type": str(institution_type.id), "actif": True},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Institution.objects.filter(nom="Mairie de Test").exists()
        assert response.data["type_libelle"] == "Mairie"

    def test_list_institutions_requires_authentication(self, api_client):
        response = api_client.get(reverse('institution-list'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_update_institution(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Ancien nom", type=institution_type)

        response = client.patch(
            reverse('institution-detail', args=[institution.id]),
            {"nom": "Nouveau nom"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        institution.refresh_from_db()
        assert institution.nom == "Nouveau nom"

    def test_delete_institution(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="À supprimer", type=institution_type)

        response = client.delete(reverse('institution-detail', args=[institution.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Institution.objects.filter(id=institution.id).exists()

    def test_anonymous_cannot_delete_institution(self, api_client):
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Protégée", type=institution_type)

        response = api_client.delete(reverse('institution-detail', args=[institution.id]))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert Institution.objects.filter(id=institution.id).exists()


@pytest.mark.django_db
class TestInstitutionAutoAttachment:
    """Un utilisateur doit être rattaché automatiquement à une institution qu'il crée,
    ou dont il partage le domaine email connu lors de son inscription."""

    def test_creator_becomes_principal_contact(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")

        response = client.post(
            reverse('institution-list'),
            {"nom": "SDIS 33", "type": str(institution_type.id), "actif": True},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        institution = Institution.objects.get(id=response.data["id"])

        contact = ContactInstitution.objects.get(institution=institution, utilisateur=user)
        assert contact.contact_principal is True

    def test_registration_with_known_domain_attaches_contact(self, api_client, user_data):
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=True)

        payload = {**user_data, "email": "agent@sdis33.fr", "username": "agent@sdis33.fr"}
        response = api_client.post(reverse('user-register'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert ContactInstitution.objects.filter(
            institution=institution, utilisateur_id=response.data["user"]["id"]
        ).exists()

    def test_registration_with_unknown_domain_attaches_nothing(self, api_client, user_data):
        payload = {**user_data, "email": "someone@unknown-domain.fr", "username": "someone@unknown-domain.fr"}
        response = api_client.post(reverse('user-register'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert not ContactInstitution.objects.filter(utilisateur_id=response.data["user"]["id"]).exists()

    def test_invalid_domaine_is_not_matched(self, api_client, user_data):
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=False)

        payload = {**user_data, "email": "agent@sdis33.fr", "username": "agent@sdis33.fr"}
        response = api_client.post(reverse('user-register'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert not ContactInstitution.objects.filter(institution=institution).exists()

    def test_local_authority_registration_reuses_matched_institution(self, api_client, user_data):
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie de Bordeaux", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="mairie-bordeaux.fr", valide=True)

        payload = {
            **user_data,
            "email": "agent@mairie-bordeaux.fr",
            "username": "agent@mairie-bordeaux.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie de Bordeaux",
            "institution_type": "mairie",
        }
        response = api_client.post(reverse('user-register'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert Institution.objects.filter(nom="Mairie de Bordeaux").count() == 1
        assert AffectationRoleOperationnel.objects.filter(
            institution=institution, utilisateur_id=response.data["user"]["id"]
        ).exists()
