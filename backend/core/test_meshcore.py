import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, ContactInstitution, Institution, InstitutionType,
    MessageMeshLog, NoeudMeshUtilisateur,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_MESHCORE', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test meshcore', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie MeshCore A')


@pytest.fixture
def mairie_client(create_user, institution_a):
    user = create_user(username='mairie-mesh@test.fr', email='mairie-mesh@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def compagnon(institution_a):
    return CompagnonMeshCore.objects.create(
        nom='Companion PC test', connexion_type='TCP', tcp_host='127.0.0.1', tcp_port=5000,
        institution=institution_a,
    )


@pytest.mark.django_db
class TestCompagnonMeshCore:

    def test_institutional_actor_can_create(self, mairie_client, institution_a):
        client, _ = mairie_client
        response = client.post(reverse('compagnonmeshcore-list'), {
            'nom': 'Companion test', 'connexion_type': 'TCP', 'tcp_host': '192.168.1.50', 'tcp_port': 5000,
            'institution': str(institution_a.id),
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['pubkey_hex'] is None

    def test_non_institutional_cannot_create(self, create_user):
        user = create_user(username='simple-mesh@test.fr', email='simple-mesh@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(reverse('compagnonmeshcore-list'), {
            'nom': 'Companion refuse', 'connexion_type': 'TCP',
        }, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_pubkey_and_status_fields_are_read_only_on_create(self, mairie_client, institution_a):
        client, _ = mairie_client
        response = client.post(reverse('compagnonmeshcore-list'), {
            'nom': 'Companion readonly test', 'connexion_type': 'SERIE', 'serie_device': '/dev/ttyUSB0',
            'institution': str(institution_a.id),
            'pubkey_hex': 'deadbeef', 'dernier_etat': 'CONNECTE',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['pubkey_hex'] is None
        assert response.data['dernier_etat'] is None

    def test_rapporter_etat_connecte_sets_pubkey_and_timestamp(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-mesh@test.fr', email='bridge-mesh@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.post(
            reverse('compagnonmeshcore-rapporter-etat', args=[compagnon.id]),
            {'etat': 'CONNECTE', 'pubkey_hex': 'a1b2c3d4e5f6'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        compagnon.refresh_from_db()
        assert compagnon.dernier_etat == 'CONNECTE'
        assert compagnon.pubkey_hex == 'a1b2c3d4e5f6'
        assert compagnon.derniere_connexion is not None

    def test_rapporter_etat_erreur_stores_message(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-mesh2@test.fr', email='bridge-mesh2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.post(
            reverse('compagnonmeshcore-rapporter-etat', args=[compagnon.id]),
            {'etat': 'ERREUR', 'erreur': 'Connexion refusée'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        compagnon.refresh_from_db()
        assert compagnon.dernier_etat == 'ERREUR'
        assert compagnon.derniere_erreur == 'Connexion refusée'

    def test_rapporter_etat_rejects_invalid_value(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-mesh3@test.fr', email='bridge-mesh3@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.post(
            reverse('compagnonmeshcore-rapporter-etat', args=[compagnon.id]),
            {'etat': 'PAS_UN_ETAT'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_requires_authentication(self, api_client, compagnon):
        response = api_client.post(reverse('compagnonmeshcore-rapporter-etat', args=[compagnon.id]), {'etat': 'CONNECTE'}, format='json')
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestNoeudMeshUtilisateur:

    def test_institutional_actor_can_associate_node(self, mairie_client, create_user):
        client, _ = mairie_client
        terrain_user = create_user(username='terrain-mesh@test.fr', email='terrain-mesh@test.fr', type='UTIL_SIMPLE')

        response = client.post(reverse('noeudmeshutilisateur-list'), {
            'utilisateur': str(terrain_user.id), 'pubkey_hex': 'ffeeddccbbaa', 'nom_noeud': 'Companion Alice',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['utilisateur_nom']

    def test_pubkey_must_be_unique(self, mairie_client, create_user):
        client, _ = mairie_client
        u1 = create_user(username='terrain-mesh1@test.fr', email='terrain-mesh1@test.fr', type='UTIL_SIMPLE')
        u2 = create_user(username='terrain-mesh2@test.fr', email='terrain-mesh2@test.fr', type='UTIL_SIMPLE')
        NoeudMeshUtilisateur.objects.create(utilisateur=u1, pubkey_hex='1122334455')

        response = client.post(reverse('noeudmeshutilisateur-list'), {
            'utilisateur': str(u2.id), 'pubkey_hex': '1122334455',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestMessageMeshLog:

    def test_bridge_can_log_incoming_message(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-mesh4@test.fr', email='bridge-mesh4@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'ENTRANT',
            'contact_pubkey_hex': '112233445566', 'contenu': 'Statut : RAS',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['statut'] == 'RECU'

    def test_a_envoyer_lists_only_pending_outgoing_for_this_compagnon(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-mesh5@test.fr', email='bridge-mesh5@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        autre_compagnon = CompagnonMeshCore.objects.create(nom='Autre companion', connexion_type='TCP')
        MessageMeshLog.objects.create(compagnon=compagnon, direction='SORTANT', statut='EN_ATTENTE', contact_pubkey_hex='aa', contenu='à envoyer')
        MessageMeshLog.objects.create(compagnon=compagnon, direction='SORTANT', statut='ENVOYE', contact_pubkey_hex='bb', contenu='déjà envoyé')
        MessageMeshLog.objects.create(compagnon=compagnon, direction='ENTRANT', statut='RECU', contact_pubkey_hex='cc', contenu='reçu')
        MessageMeshLog.objects.create(compagnon=autre_compagnon, direction='SORTANT', statut='EN_ATTENTE', contact_pubkey_hex='dd', contenu='autre companion')

        response = api_client.get(reverse('messagemeshlog-a-envoyer'), {'compagnon': str(compagnon.id)})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['contenu'] == 'à envoyer'

    def test_list_requires_institutional_actor(self, api_client, create_user):
        user = create_user(username='simple-mesh2@test.fr', email='simple-mesh2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('messagemeshlog-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN
