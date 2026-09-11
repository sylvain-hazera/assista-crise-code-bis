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


@pytest.mark.django_db
class TestMessageMeshLogResolutionEtVisibilite:
    """L'expéditeur/l'équipe sont résolus côté serveur (jamais posés par le client), et la
    visibilité des DM est cloisonnée à l'équipe (leader/régulateur) — voir doc de conception
    « Maillage Terrain », principe « administrer un companion n'est pas lire les messages »."""

    def test_message_entrant_resout_expediteur_et_equipe(self, api_client, compagnon, create_user, institution_a):
        from core.models import NoeudMeshUtilisateur, Team
        bridge_user = create_user(username='bridge-resolve@test.fr', email='bridge-resolve@test.fr', type='UTIL_SIMPLE')
        terrain_user = create_user(username='terrain-resolve@test.fr', email='terrain-resolve@test.fr', type='UTIL_SIMPLE')
        equipe = Team.objects.create(name='Équipe résolution test', institution=institution_a)
        equipe.members.add(terrain_user)
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain_user, pubkey_hex='aabbccddeeff', actif=True)

        api_client.force_authenticate(user=bridge_user)
        response = api_client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'ENTRANT',
            'contact_pubkey_hex': 'aabbccddeeff', 'contenu': 'Statut RAS',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        message = MessageMeshLog.objects.get(id=response.data['id'])
        assert message.expediteur == terrain_user
        assert message.equipe == equipe

    def test_message_entrant_pubkey_inconnue_ne_resout_rien(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-inconnu@test.fr', email='bridge-inconnu@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        response = api_client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'ENTRANT',
            'contact_pubkey_hex': 'ffffffffffff', 'contenu': 'Inconnu',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        message = MessageMeshLog.objects.get(id=response.data['id'])
        assert message.expediteur is None
        assert message.equipe is None

    def test_message_sortant_expediteur_est_utilisateur_connecte(self, mairie_client, compagnon):
        client, regulateur = mairie_client
        response = client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'SORTANT',
            'contact_pubkey_hex': 'aabbccddeeff', 'contenu': 'Rentrez à la base',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        message = MessageMeshLog.objects.get(id=response.data['id'])
        assert message.expediteur == regulateur

    def test_leader_equipe_voit_les_messages_de_son_equipe(self, create_user, institution_a, compagnon):
        from core.models import NoeudMeshUtilisateur, Team
        leader = create_user(username='leader-visib@test.fr', email='leader-visib@test.fr', type='AUT_LOCALE')
        terrain_user = create_user(username='terrain-visib@test.fr', email='terrain-visib@test.fr', type='UTIL_SIMPLE')
        equipe = Team.objects.create(name='Équipe visibilité test', institution=institution_a, leader=leader)
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain_user, pubkey_hex='1234567890ab', actif=True)
        MessageMeshLog.objects.create(
            compagnon=compagnon, direction='ENTRANT', statut='RECU',
            contact_pubkey_hex='1234567890ab', contenu='RAS', expediteur=terrain_user, equipe=equipe,
        )

        client = APIClient()
        client.force_authenticate(user=leader)
        response = client.get(reverse('messagemeshlog-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['contenu'] == 'RAS'

    def test_regulateur_autre_equipe_ne_voit_pas(self, create_user, institution_a, compagnon):
        from core.models import NoeudMeshUtilisateur, Team
        leader = create_user(username='leader-autre@test.fr', email='leader-autre@test.fr', type='AUT_LOCALE')
        autre_regulateur = create_user(username='regulateur-autre@test.fr', email='regulateur-autre@test.fr', type='AUT_LOCALE')
        terrain_user = create_user(username='terrain-autre@test.fr', email='terrain-autre@test.fr', type='UTIL_SIMPLE')
        equipe = Team.objects.create(name='Équipe A cloisonnement', institution=institution_a, leader=leader)
        Team.objects.create(name='Équipe B cloisonnement', institution=institution_a, regulateur=autre_regulateur)
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain_user, pubkey_hex='deadbeefcafe', actif=True)
        MessageMeshLog.objects.create(
            compagnon=compagnon, direction='ENTRANT', statut='RECU',
            contact_pubkey_hex='deadbeefcafe', contenu='Confidentiel équipe A', expediteur=terrain_user, equipe=equipe,
        )

        client = APIClient()
        client.force_authenticate(user=autre_regulateur)
        response = client.get(reverse('messagemeshlog-list'))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_administrateur_voit_tout(self, create_user, institution_a, compagnon):
        from core.models import NoeudMeshUtilisateur, Team
        admin = create_user(username='admin-visib@test.fr', email='admin-visib@test.fr', type='ADMIN')
        leader = create_user(username='leader-admin-test@test.fr', email='leader-admin-test@test.fr', type='AUT_LOCALE')
        terrain_user = create_user(username='terrain-admin-test@test.fr', email='terrain-admin-test@test.fr', type='UTIL_SIMPLE')
        equipe = Team.objects.create(name='Équipe visible admin', institution=institution_a, leader=leader)
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain_user, pubkey_hex='0011223344aa', actif=True)
        MessageMeshLog.objects.create(
            compagnon=compagnon, direction='ENTRANT', statut='RECU',
            contact_pubkey_hex='0011223344aa', contenu='Visible admin', expediteur=terrain_user, equipe=equipe,
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('messagemeshlog-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1


@pytest.mark.django_db
class TestRelaisMeshCore:

    def test_institutional_actor_can_create(self, mairie_client, institution_a):
        client, _ = mairie_client
        response = client.post(reverse('relaismeshcore-list'), {
            'nom': 'Relais clocher', 'institution': str(institution_a.id),
            'latitude': 45.75, 'longitude': 4.85,
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['latitude'] == 45.75
        assert response.data['longitude'] == 4.85

    def test_non_institutional_cannot_create(self, create_user):
        user = create_user(username='simple-relais@test.fr', email='simple-relais@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(reverse('relaismeshcore-list'), {'nom': 'Relais refuse'}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCanalMeshCore:

    def test_institutional_actor_can_create_canal_and_post_message(self, mairie_client, institution_a):
        client, regulateur = mairie_client
        canal_response = client.post(reverse('canalmeshcore-list'), {
            'nom': 'Canal coordination générale', 'institution': str(institution_a.id),
            'cle_partagee_hex': 'secretcanal01',
        }, format='json')
        assert canal_response.status_code == status.HTTP_201_CREATED
        assert 'cle_partagee_hex' not in canal_response.data

        message_response = client.post(reverse('messagecanalmeshcore-list'), {
            'canal': canal_response.data['id'], 'direction': 'SORTANT', 'contenu': 'Point de situation général',
        }, format='json')
        assert message_response.status_code == status.HTTP_201_CREATED
        assert message_response.data['expediteur_nom']


@pytest.mark.django_db
class TestContactMeshCore:

    def test_synchroniser_contacts_upserts(self, api_client, compagnon, create_user):
        from core.models import ContactMeshCore
        bridge_user = create_user(username='bridge-contacts@test.fr', email='bridge-contacts@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [
                {'pubkey_hex': 'aa11', 'nom': 'Alice Terrain', 'type_contact': 'COMPANION'},
                {'pubkey_hex': 'bb22', 'nom': 'Relais Clocher', 'type_contact': 'REPEATER', 'latitude': 45.75, 'longitude': 4.85},
            ]}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['synchronises'] == 2
        assert ContactMeshCore.objects.filter(compagnon=compagnon, pubkey_hex='aa11', nom='Alice Terrain').exists()
        relais = ContactMeshCore.objects.get(compagnon=compagnon, pubkey_hex='bb22')
        assert relais.type_contact == 'REPEATER'
        assert relais.location is not None

    def test_synchroniser_contacts_est_idempotent(self, api_client, compagnon, create_user):
        from core.models import ContactMeshCore
        bridge_user = create_user(username='bridge-contacts2@test.fr', email='bridge-contacts2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        payload = {'contacts': [{'pubkey_hex': 'cc33', 'nom': 'Bob', 'type_contact': 'COMPANION'}]}
        api_client.post(reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]), payload, format='json')
        api_client.post(reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]), payload, format='json')

        assert ContactMeshCore.objects.filter(compagnon=compagnon, pubkey_hex='cc33').count() == 1

    def test_list_requires_institutional_actor(self, api_client, create_user):
        user = create_user(username='simple-contacts@test.fr', email='simple-contacts@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('contactmeshcore-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_deja_associe_reflects_noeud_utilisateur(self, mairie_client, compagnon, create_user):
        from core.models import ContactMeshCore, NoeudMeshUtilisateur
        client, _ = mairie_client
        terrain_user = create_user(username='terrain-contacts@test.fr', email='terrain-contacts@test.fr', type='UTIL_SIMPLE')
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain_user, pubkey_hex='dd44')
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex='dd44', nom='Déjà associé', type_contact='COMPANION')
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex='ee55', nom='Pas encore', type_contact='COMPANION')

        response = client.get(reverse('contactmeshcore-list'), {'compagnon': str(compagnon.id)})

        assert response.status_code == status.HTTP_200_OK
        par_pubkey = {c['pubkey_hex']: c['deja_associe'] for c in response.data}
        assert par_pubkey['dd44'] is True
        assert par_pubkey['ee55'] is False
