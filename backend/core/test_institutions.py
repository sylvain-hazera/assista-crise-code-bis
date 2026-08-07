import pytest
from django.urls import reverse
from rest_framework import status

from core.models import Institution, InstitutionType


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
