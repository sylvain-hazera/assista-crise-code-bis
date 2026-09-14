import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CompagnonMeshtastic, Institution, InstitutionType


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_MESHTASTIC', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test meshtastic', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie Meshtastic A')


@pytest.fixture
def institutional_client(create_user, institution_a):
    from core.models import ContactInstitution
    user = create_user(username='mairie-tastic@test.fr', email='mairie-tastic@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def compagnon(institution_a):
    return CompagnonMeshtastic.objects.create(
        nom='Pont Gaulix test', node_num=1234, broker_host='mqtt.gaulix.fr',
        institution=institution_a,
    )


@pytest.mark.django_db
class TestChiffrementSupporte:

    def test_default_false(self, compagnon):
        assert compagnon.chiffrement_supporte is False

    def test_exposed_and_writable_via_create(self, institutional_client):
        client, _ = institutional_client
        response = client.post(reverse('compagnonmeshtastic-list'), {
            'nom': 'Pont chiffré', 'node_num': 5678, 'broker_host': 'mqtt.example.fr',
            'chiffrement_supporte': True,
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['chiffrement_supporte'] is True
        assert CompagnonMeshtastic.objects.get(id=response.data['id']).chiffrement_supporte is True

    def test_create_defaults_to_false_when_omitted(self, institutional_client):
        client, _ = institutional_client
        response = client.post(reverse('compagnonmeshtastic-list'), {
            'nom': 'Pont clair', 'node_num': 9012, 'broker_host': 'mqtt.gaulix.fr',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['chiffrement_supporte'] is False

    def test_editable_via_patch(self, institutional_client, compagnon):
        client, _ = institutional_client
        response = client.patch(
            reverse('compagnonmeshtastic-detail', args=[compagnon.id]), {'chiffrement_supporte': True}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        compagnon.refresh_from_db()
        assert compagnon.chiffrement_supporte is True

    def test_visible_in_read(self, institutional_client, compagnon):
        client, _ = institutional_client
        response = client.get(reverse('compagnonmeshtastic-detail', args=[compagnon.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['chiffrement_supporte'] is False
