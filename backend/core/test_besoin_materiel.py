import pytest
from django.urls import reverse
from rest_framework import status

from core.models import Besoin, BesoinMateriel, MaterielCatalogue


@pytest.mark.django_db
class TestBesoinNature:

    def test_nature_writable_via_patch(self, authenticated_client):
        client, _ = authenticated_client
        besoin = Besoin.objects.create(nom="Besoin nature test")

        response = client.patch(reverse('besoin-detail', args=[besoin.id]), {'nature': 'MATERIEL'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        besoin.refresh_from_db()
        assert besoin.nature == 'MATERIEL'

    def test_nature_defaults_to_null(self, authenticated_client):
        client, _ = authenticated_client
        response = client.post(reverse('besoin-list'), {'nom': 'Besoin sans nature test'}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['nature'] is None

    def test_nature_rejects_invalid_choice(self, authenticated_client):
        client, _ = authenticated_client
        besoin = Besoin.objects.create(nom="Besoin nature invalide test")

        response = client.patch(reverse('besoin-detail', args=[besoin.id]), {'nature': 'PAS_UNE_VRAIE_NATURE'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestBesoinMateriel:

    def test_create_and_list_correspondance(self, authenticated_client):
        client, _ = authenticated_client
        besoin = Besoin.objects.create(nom="Besoin materiel test", nature='MATERIEL')
        materiel = MaterielCatalogue.objects.create(nom="Materiel correspondance test")

        response = client.post(reverse('besoinmateriel-list'), {
            'besoin': str(besoin.id), 'materiel': str(materiel.id),
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['besoin_nom'] == besoin.nom
        assert response.data['materiel_nom'] == materiel.nom

        listing = client.get(reverse('besoinmateriel-list'))
        assert listing.status_code == status.HTTP_200_OK
        assert any(row['id'] == response.data['id'] for row in listing.data)

    def test_delete_correspondance(self, authenticated_client):
        client, _ = authenticated_client
        besoin = Besoin.objects.create(nom="Besoin materiel suppr test", nature='MATERIEL')
        materiel = MaterielCatalogue.objects.create(nom="Materiel correspondance suppr test")
        lien = BesoinMateriel.objects.create(besoin=besoin, materiel=materiel)

        response = client.delete(reverse('besoinmateriel-detail', args=[lien.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not BesoinMateriel.objects.filter(id=lien.id).exists()

    def test_requires_authentication(self, api_client):
        response = api_client.get(reverse('besoinmateriel-list'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_deleting_materiel_in_use_is_protected(self, authenticated_client):
        client, _ = authenticated_client
        besoin = Besoin.objects.create(nom="Besoin materiel protect test", nature='MATERIEL')
        materiel = MaterielCatalogue.objects.create(nom="Materiel protege test")
        BesoinMateriel.objects.create(besoin=besoin, materiel=materiel)

        response = client.delete(reverse('materielcatalogue-detail', args=[materiel.id]))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert MaterielCatalogue.objects.filter(id=materiel.id).exists()
