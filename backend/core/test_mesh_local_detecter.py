from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CompagnonMeshCore, CompagnonMeshtastic, Institution, InstitutionType


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_MESHLOCAL', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test mesh local', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institutional_client(create_user):
    institution = _make_institution()
    from core.models import ContactInstitution
    user = create_user(username='mairie-local@test.fr', email='mairie-local@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestMeshLocalDetecter:
    """Vraie connexion réseau impossible en test — on mocke les deux fonctions de détection
    (_detecter_meshtastic_local/_detecter_meshcore_local), déjà bornées dans le temps et isolées
    dans leurs propres fonctions justement pour être mockables ici sans dépendre du réseau."""

    def _mock_port_ouvert(self):
        return patch('socket.create_connection')

    def test_detects_meshtastic(self, institutional_client):
        client, _ = institutional_client
        with self._mock_port_ouvert(), \
             patch('core.views._detecter_meshtastic_local', return_value={'node_num': 3735928559, 'long_name': 'Test Node', 'short_name': 'TSTN'}):
            response = client.post(reverse('mesh_local_detecter'), {'ip': '192.168.1.42', 'port': 4403}, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['type'] == 'meshtastic'
        compagnon = CompagnonMeshtastic.objects.get(id=response.data['id'])
        assert compagnon.connexion_type == 'TCP'
        assert compagnon.tcp_host == '192.168.1.42'
        assert compagnon.tcp_port == 4403
        assert compagnon.node_num == 3735928559

    def test_detects_meshcore_when_meshtastic_fails(self, institutional_client):
        client, _ = institutional_client
        with self._mock_port_ouvert(), \
             patch('core.views._detecter_meshtastic_local', return_value=None), \
             patch('core.views._detecter_meshcore_local', return_value={'pubkey_hex': 'ab' * 32}):
            response = client.post(reverse('mesh_local_detecter'), {'ip': '192.168.1.50', 'port': 5000}, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['type'] == 'meshcore'
        compagnon = CompagnonMeshCore.objects.get(id=response.data['id'])
        assert compagnon.connexion_type == 'TCP'
        assert compagnon.tcp_host == '192.168.1.50'
        assert compagnon.pubkey_hex == 'ab' * 32

    def test_neither_protocol_detected(self, institutional_client):
        client, _ = institutional_client
        with self._mock_port_ouvert(), \
             patch('core.views._detecter_meshtastic_local', return_value=None), \
             patch('core.views._detecter_meshcore_local', return_value=None):
            response = client.post(reverse('mesh_local_detecter'), {'ip': '192.168.1.99', 'port': 9999}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not CompagnonMeshtastic.objects.filter(tcp_host='192.168.1.99').exists()
        assert not CompagnonMeshCore.objects.filter(tcp_host='192.168.1.99').exists()

    def test_port_unreachable_short_circuits(self, institutional_client):
        client, _ = institutional_client
        with patch('socket.create_connection', side_effect=OSError('refused')):
            response = client.post(reverse('mesh_local_detecter'), {'ip': '10.0.0.1', 'port': 1234}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'répond' in response.data['detail']

    def test_missing_ip_or_port(self, institutional_client):
        client, _ = institutional_client
        response = client.post(reverse('mesh_local_detecter'), {'port': 4403}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_requires_institutional_actor(self, create_user):
        user = create_user(username='simple-local@test.fr', email='simple-local@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(reverse('mesh_local_detecter'), {'ip': '192.168.1.1', 'port': 4403}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
