import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CanalMeshtastic, CompagnonMeshtastic, Institution, InstitutionType


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


@pytest.mark.django_db
class TestMqttAuth:

    def test_password_write_only_never_returned(self, institutional_client):
        client, _ = institutional_client
        response = client.post(reverse('compagnonmeshtastic-list'), {
            'nom': 'Pont authentifié', 'node_num': 4242, 'broker_host': 'mqtt.example.fr',
            'mqtt_username': 'assista', 'mqtt_password': 'secret123', 'mqtt_use_tls': True,
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert 'mqtt_password' not in response.data
        assert response.data['mqtt_username'] == 'assista'
        assert response.data['mqtt_use_tls'] is True
        compagnon = CompagnonMeshtastic.objects.get(id=response.data['id'])
        assert compagnon.mqtt_password == 'secret123'

    def test_default_no_auth(self, compagnon):
        assert compagnon.mqtt_username == ''
        assert compagnon.mqtt_password == ''
        assert compagnon.mqtt_use_tls is False

    def test_patch_without_password_keeps_existing(self, institutional_client, compagnon):
        client, _ = institutional_client
        compagnon.mqtt_password = 'kept-secret'
        compagnon.save()
        response = client.patch(
            reverse('compagnonmeshtastic-detail', args=[compagnon.id]), {'mqtt_username': 'nouveau'}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        compagnon.refresh_from_db()
        assert compagnon.mqtt_username == 'nouveau'
        assert compagnon.mqtt_password == 'kept-secret'


@pytest.mark.django_db
class TestCompagnonsActifsAvecIdentifiants:

    def test_returns_full_config_for_active_only(self, institutional_client, compagnon):
        client, _ = institutional_client
        compagnon.mqtt_password = 'secret'
        compagnon.actif = True
        compagnon.save()
        inactif = CompagnonMeshtastic.objects.create(
            nom='Pont inactif', node_num=5555, broker_host='mqtt.example.fr', actif=False,
        )
        response = client.get(reverse('compagnonmeshtastic-actifs-avec-identifiants'))
        assert response.status_code == status.HTTP_200_OK, response.data
        ids = [c['id'] for c in response.data]
        assert str(compagnon.id) in ids
        assert str(inactif.id) not in ids
        entry = next(c for c in response.data if c['id'] == str(compagnon.id))
        assert entry['mqtt_password'] == 'secret'
        assert entry['x25519_private_key_hex'] == compagnon.x25519_private_key_hex

    def test_empty_when_no_active_companion(self, institutional_client):
        client, _ = institutional_client
        CompagnonMeshtastic.objects.create(nom='Inactif', node_num=6789, actif=False)
        response = client.get(reverse('compagnonmeshtastic-actifs-avec-identifiants'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []


@pytest.mark.django_db
class TestCanauxAvecCleFiltragePartBroker:

    def test_scoped_to_compagnon_plus_shared(self, institutional_client, compagnon):
        client, _ = institutional_client
        autre_compagnon = CompagnonMeshtastic.objects.create(nom='Autre broker', node_num=7777)
        canal_a = CanalMeshtastic.objects.create(nom='Fr_Balise', compagnon=compagnon, actif=True)
        canal_b = CanalMeshtastic.objects.create(nom='LongFast', compagnon=autre_compagnon, actif=True)
        canal_partage = CanalMeshtastic.objects.create(nom='Partage', compagnon=None, actif=True)

        response = client.get(reverse('canalmeshtastic-avec-cle'), {'compagnon': str(compagnon.id)})
        assert response.status_code == status.HTTP_200_OK, response.data
        noms = {c['nom'] for c in response.data}
        assert noms == {'Fr_Balise', 'Partage'}

    def test_no_filter_returns_all_active(self, institutional_client, compagnon):
        client, _ = institutional_client
        CanalMeshtastic.objects.create(nom='Fr_Balise', compagnon=compagnon, actif=True)
        CanalMeshtastic.objects.create(nom='LongFast', compagnon=None, actif=True)
        response = client.get(reverse('canalmeshtastic-avec-cle'))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2


@pytest.mark.django_db
class TestSuppressionCanal:

    def test_institutional_actor_can_delete(self, institutional_client, compagnon):
        client, _ = institutional_client
        canal = CanalMeshtastic.objects.create(nom='Fr_Balise', compagnon=compagnon)
        response = client.delete(reverse('canalmeshtastic-detail', args=[canal.id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not CanalMeshtastic.objects.filter(id=canal.id).exists()

    def test_non_institutional_cannot_delete(self, create_user, compagnon):
        user = create_user(username='simple@test.fr', email='simple@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        canal = CanalMeshtastic.objects.create(nom='Fr_Balise', compagnon=compagnon)
        response = client.delete(reverse('canalmeshtastic-detail', args=[canal.id]))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert CanalMeshtastic.objects.filter(id=canal.id).exists()
