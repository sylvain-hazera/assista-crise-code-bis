import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, CommandeMeshCore, ContactInstitution, Institution, InstitutionType,
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

    def test_bridge_can_mark_message_sent_via_patch(self, api_client, compagnon, create_user):
        """Régression : statut/erreur/date_envoi étaient marqués read_only sur le serializer,
        rendant le PATCH du pont (DjangoClient.marquer_message, après une tentative d'envoi)
        silencieusement sans effet — un message restait EN_ATTENTE indéfiniment, réessayé en
        boucle par boucle_envoi, jamais marqué en échec ni en envoyé."""
        bridge_user = create_user(username='bridge-mesh6@test.fr', email='bridge-mesh6@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        message = MessageMeshLog.objects.create(
            compagnon=compagnon, direction='SORTANT', statut='EN_ATTENTE',
            contact_pubkey_hex='ee', contenu='à envoyer',
        )

        response = api_client.patch(
            reverse('messagemeshlog-detail', args=[message.id]), {'statut': 'ENVOYE'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        message.refresh_from_db()
        assert message.statut == 'ENVOYE'

    def test_bridge_can_mark_message_failed_with_erreur_via_patch(self, api_client, compagnon, create_user):
        bridge_user = create_user(username='bridge-mesh7@test.fr', email='bridge-mesh7@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        message = MessageMeshLog.objects.create(
            compagnon=compagnon, direction='SORTANT', statut='EN_ATTENTE',
            contact_pubkey_hex='ff', contenu='à envoyer',
        )

        response = api_client.patch(
            reverse('messagemeshlog-detail', args=[message.id]),
            {'statut': 'ECHEC', 'erreur': "{'reason': 'no_event_received'}"}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        message.refresh_from_db()
        assert message.statut == 'ECHEC'
        assert message.erreur == "{'reason': 'no_event_received'}"
        # Un message marqué ECHEC ne doit plus jamais réapparaître dans la file d'attente.
        response = api_client.get(reverse('messagemeshlog-a-envoyer'), {'compagnon': str(compagnon.id)})
        assert response.data == []


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

    def test_message_entrant_avec_prefixe_seul_resout_et_normalise_la_cle(self, api_client, compagnon, create_user, institution_a):
        """Le pont ne transmet qu'un préfixe de clé publique (ce que la trame radio
        CONTACT_MSG_RECV porte réellement — voir bridge.py, `_sur_message`), jamais la clé
        complète. Le message doit malgré tout être rattaché au bon nœud, ET stocker la clé
        COMPLÈTE (pas le préfixe reçu) pour que le filtre `contact_pubkey_hex` du fil de
        discussion (qui compare à NoeudMeshUtilisateur.pubkey_hex, toujours complet côté
        front) le retrouve ensuite."""
        from core.models import NoeudMeshUtilisateur, Team
        bridge_user = create_user(username='bridge-prefixe@test.fr', email='bridge-prefixe@test.fr', type='UTIL_SIMPLE')
        terrain_user = create_user(username='terrain-prefixe@test.fr', email='terrain-prefixe@test.fr', type='UTIL_SIMPLE')
        equipe = Team.objects.create(name='Équipe préfixe test', institution=institution_a)
        equipe.members.add(terrain_user)
        cle_complete = '1b35564956a504311b888d53c0fba492a54e480bdab23ced45b10a271909c361'
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain_user, pubkey_hex=cle_complete, actif=True)

        api_client.force_authenticate(user=bridge_user)
        response = api_client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'ENTRANT',
            'contact_pubkey_hex': '1b35564956a5', 'contenu': 'fghj',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        message = MessageMeshLog.objects.get(id=response.data['id'])
        assert message.expediteur == terrain_user
        assert message.equipe == equipe
        assert message.contact_pubkey_hex == cle_complete

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

    def test_filters_by_contact_pubkey_hex_for_a_single_thread(self, create_user, institution_a, compagnon):
        """Fil de discussion avec UNE personne précise — distinct du filtre équipe, qui
        mélangerait les messages de tous les membres équipés d'une même équipe."""
        admin = create_user(username='admin-thread@test.fr', email='admin-thread@test.fr', type='ADMIN')
        MessageMeshLog.objects.create(compagnon=compagnon, direction='ENTRANT', statut='RECU', contact_pubkey_hex='pers-a', contenu='De A')
        MessageMeshLog.objects.create(compagnon=compagnon, direction='SORTANT', statut='ENVOYE', contact_pubkey_hex='pers-a', contenu='Vers A')
        MessageMeshLog.objects.create(compagnon=compagnon, direction='ENTRANT', statut='RECU', contact_pubkey_hex='pers-b', contenu='De B')

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('messagemeshlog-list'), {'contact_pubkey_hex': 'pers-a'})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        assert all(m['contact_pubkey_hex'] == 'pers-a' for m in response.data)


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

    def test_synchroniser_contacts_auto_importe_repeteur_detecte(self, api_client, compagnon, institution_a, create_user):
        """Avant ce correctif, importer un répéteur détecté nécessitait un clic manuel côté
        front, sans protection anti-doublon — voir la migration 0145 qui a dû dédupliquer des
        répéteurs importés jusqu'à 9 fois en base. Désormais automatique dès la synchro."""
        from core.models import RelaisMeshCore
        bridge_user = create_user(username='bridge-relais1@test.fr', email='bridge-relais1@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [{'pubkey_hex': 'repeat-aa', 'nom': 'Relais Clocher', 'type_contact': 'REPEATER', 'latitude': 45.75, 'longitude': 4.85}]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        relais = RelaisMeshCore.objects.get(pubkey_hex='repeat-aa')
        assert relais.nom == 'Relais Clocher'
        assert relais.location is not None
        assert relais.institution_id == institution_a.id

    def test_synchroniser_contacts_repeteur_ne_duplique_jamais(self, api_client, compagnon, create_user):
        from core.models import RelaisMeshCore
        bridge_user = create_user(username='bridge-relais2@test.fr', email='bridge-relais2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        payload = {'contacts': [{'pubkey_hex': 'repeat-bb', 'nom': 'Relais Mairie', 'type_contact': 'REPEATER', 'latitude': 45.1, 'longitude': 5.2}]}
        for _ in range(3):
            api_client.post(reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]), payload, format='json')

        assert RelaisMeshCore.objects.filter(pubkey_hex='repeat-bb').count() == 1

    def test_synchroniser_contacts_repeteur_position_suit_les_mises_a_jour(self, api_client, compagnon, create_user):
        from core.models import RelaisMeshCore
        bridge_user = create_user(username='bridge-relais3@test.fr', email='bridge-relais3@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [{'pubkey_hex': 'repeat-cc', 'nom': 'Relais Mobile', 'type_contact': 'REPEATER', 'latitude': 45.1, 'longitude': 5.2}]},
            format='json',
        )
        api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [{'pubkey_hex': 'repeat-cc', 'nom': 'Relais Mobile', 'type_contact': 'REPEATER', 'latitude': 46.2, 'longitude': 6.3}]},
            format='json',
        )

        relais = RelaisMeshCore.objects.get(pubkey_hex='repeat-cc')
        assert relais.location.y == pytest.approx(46.2)
        assert relais.location.x == pytest.approx(6.3)

    def test_synchroniser_contacts_ne_cree_pas_de_relais_pour_un_companion(self, api_client, compagnon, create_user):
        from core.models import RelaisMeshCore
        bridge_user = create_user(username='bridge-relais4@test.fr', email='bridge-relais4@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [{'pubkey_hex': 'not-a-repeater', 'nom': 'Alice', 'type_contact': 'COMPANION', 'latitude': 45.1, 'longitude': 5.2}]},
            format='json',
        )

        assert not RelaisMeshCore.objects.filter(pubkey_hex='not-a-repeater').exists()

    def test_synchroniser_contacts_est_idempotent(self, api_client, compagnon, create_user):
        from core.models import ContactMeshCore
        bridge_user = create_user(username='bridge-contacts2@test.fr', email='bridge-contacts2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        payload = {'contacts': [{'pubkey_hex': 'cc33', 'nom': 'Bob', 'type_contact': 'COMPANION'}]}
        api_client.post(reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]), payload, format='json')
        api_client.post(reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]), payload, format='json')

        assert ContactMeshCore.objects.filter(compagnon=compagnon, pubkey_hex='cc33').count() == 1

    def test_synchroniser_contacts_position_only_preserves_nom_et_type(self, api_client, compagnon, create_user):
        """Régression : un rafraîchissement de position seule (pubkey_hex/latitude/longitude,
        sans nom ni type_contact — voir la boucle de suivi actif pendant une mission côté
        pont) ne doit jamais écraser le nom/type déjà connus de ce contact."""
        from core.models import ContactMeshCore
        bridge_user = create_user(username='bridge-contacts3@test.fr', email='bridge-contacts3@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [{'pubkey_hex': 'gg77', 'nom': 'Alice Terrain', 'type_contact': 'COMPANION'}]},
            format='json',
        )

        api_client.post(
            reverse('compagnonmeshcore-synchroniser-contacts', args=[compagnon.id]),
            {'contacts': [{'pubkey_hex': 'gg77', 'latitude': 45.75, 'longitude': 4.85}]},
            format='json',
        )

        contact = ContactMeshCore.objects.get(compagnon=compagnon, pubkey_hex='gg77')
        assert contact.nom == 'Alice Terrain'
        assert contact.type_contact == 'COMPANION'
        assert contact.location is not None

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


@pytest.mark.django_db
class TestPositionsMissionEnCours:
    """Suivi de position pendant une mission : uniquement les nœuds d'utilisateurs membres
    d'une équipe dont la mission courante est EN_COURS, jamais en dehors — voir
    NoeudMeshUtilisateurViewSet.positions_en_mission et
    CompagnonMeshCoreViewSet.pubkeys_a_suivre."""

    def _equipe_en_mission(self, utilisateur, statut='EN_COURS'):
        from core.models import Mission, Team
        equipe = Team.objects.create(name=f"Equipe {utilisateur.email}", description='', color='#3b82f6')
        equipe.members.add(utilisateur)
        mission = Mission.objects.create(titre='Reconnaissance secteur nord', statut=statut)
        equipe.mission_active = mission
        equipe.save(update_fields=['mission_active'])
        return equipe, mission

    def test_pubkeys_a_suivre_only_returns_nodes_on_mission_en_cours(self, api_client, compagnon, create_user):
        from core.models import ContactMeshCore

        user_en_mission = create_user(username='terrain-mission@test.fr', email='terrain-mission@test.fr', type='UTIL_SIMPLE')
        self._equipe_en_mission(user_en_mission, statut='EN_COURS')
        NoeudMeshUtilisateur.objects.create(utilisateur=user_en_mission, pubkey_hex='mission-en-cours')
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex='mission-en-cours', type_contact='COMPANION')

        user_sans_mission = create_user(username='terrain-repos@test.fr', email='terrain-repos@test.fr', type='UTIL_SIMPLE')
        NoeudMeshUtilisateur.objects.create(utilisateur=user_sans_mission, pubkey_hex='sans-mission')
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex='sans-mission', type_contact='COMPANION')

        user_mission_terminee = create_user(username='terrain-fini@test.fr', email='terrain-fini@test.fr', type='UTIL_SIMPLE')
        self._equipe_en_mission(user_mission_terminee, statut='TERMINEE')
        NoeudMeshUtilisateur.objects.create(utilisateur=user_mission_terminee, pubkey_hex='mission-finie')
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex='mission-finie', type_contact='COMPANION')

        bridge_user = create_user(username='bridge-positions@test.fr', email='bridge-positions@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.get(reverse('compagnonmeshcore-pubkeys-a-suivre', args=[compagnon.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pubkeys'] == ['mission-en-cours']

    def test_pubkeys_a_suivre_ignores_contacts_unknown_to_this_compagnon(self, api_client, institution_a, create_user):
        """Le pont ne doit interroger que SES propres contacts connus — un nœud rattaché à un
        autre companion (institution différente) n'a pas de sens à suivre ici."""
        autre_compagnon = CompagnonMeshCore.objects.create(
            nom='Autre companion', connexion_type='TCP', tcp_host='127.0.0.1', tcp_port=5001, institution=institution_a,
        )
        compagnon_a_interroger = CompagnonMeshCore.objects.create(
            nom='Companion à interroger', connexion_type='TCP', tcp_host='127.0.0.1', tcp_port=5002, institution=institution_a,
        )
        user = create_user(username='terrain-autre-compagnon@test.fr', email='terrain-autre-compagnon@test.fr', type='UTIL_SIMPLE')
        self._equipe_en_mission(user, statut='EN_COURS')
        NoeudMeshUtilisateur.objects.create(utilisateur=user, pubkey_hex='vue-par-autre')

        from core.models import ContactMeshCore
        ContactMeshCore.objects.create(compagnon=autre_compagnon, pubkey_hex='vue-par-autre', type_contact='COMPANION')

        bridge_user = create_user(username='bridge-positions2@test.fr', email='bridge-positions2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)

        response = api_client.get(reverse('compagnonmeshcore-pubkeys-a-suivre', args=[compagnon_a_interroger.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pubkeys'] == []

    def test_positions_en_mission_returns_latest_known_location(self, mairie_client, compagnon, create_user):
        from core.models import ContactMeshCore

        client, _ = mairie_client
        user = create_user(username='terrain-position@test.fr', email='terrain-position@test.fr', type='UTIL_SIMPLE')
        equipe, mission = self._equipe_en_mission(user, statut='EN_COURS')
        NoeudMeshUtilisateur.objects.create(utilisateur=user, pubkey_hex='position-connue', nom_noeud='Radio Bob')
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex='position-connue', type_contact='COMPANION',
            location='POINT (5.72 45.18)',
        )

        response = client.get(reverse('noeudmeshutilisateur-positions-en-mission'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        resultat = response.data[0]
        assert resultat['pubkey_hex'] == 'position-connue'
        assert resultat['latitude'] == pytest.approx(45.18)
        assert resultat['longitude'] == pytest.approx(5.72)
        assert resultat['equipe_nom'] == equipe.name
        assert resultat['mission_titre'] == mission.titre

    def test_positions_en_mission_excludes_nodes_without_known_location(self, mairie_client, create_user):
        user = create_user(username='terrain-sans-position@test.fr', email='terrain-sans-position@test.fr', type='UTIL_SIMPLE')
        self._equipe_en_mission(user, statut='EN_COURS')
        NoeudMeshUtilisateur.objects.create(utilisateur=user, pubkey_hex='jamais-vu')

        client, _ = mairie_client
        response = client.get(reverse('noeudmeshutilisateur-positions-en-mission'))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_positions_en_mission_requires_institutional_actor(self, api_client, create_user):
        user = create_user(username='simple-positions@test.fr', email='simple-positions@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('noeudmeshutilisateur-positions-en-mission'))
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCanalMeshCoreEquipe:
    """Canal MeshCore privé d'une équipe — répond au problème de routage des DM
    (MessageMeshLog.equipe résolu via expediteur.teams.first(), arbitraire pour un
    utilisateur multi-équipes) : voir TeamViewSet.provisionner_canal_meshcore."""

    def test_provisionner_creates_canal_and_sends_dm_to_equipped_members(self, mairie_client, institution_a, compagnon, create_user):
        from core.models import CanalMeshCore, MessageMeshLog, Team
        client, _ = mairie_client
        equipe = Team.objects.create(name='Équipe canal', institution=institution_a)
        membre_equipe = create_user(username='membre-canal@test.fr', email='membre-canal@test.fr', type='UTIL_SIMPLE')
        equipe.members.add(membre_equipe)
        NoeudMeshUtilisateur.objects.create(utilisateur=membre_equipe, pubkey_hex='canal-aa')
        compagnon.principal = True
        compagnon.save(update_fields=['principal'])

        response = client.post(reverse('team-provisionner-canal-meshcore', args=[equipe.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['destinataires'] == 1
        canal = CanalMeshCore.objects.get(equipe=equipe)
        assert canal.cle_partagee_hex
        assert canal.nom
        dm = MessageMeshLog.objects.get(equipe=equipe, contact_pubkey_hex='canal-aa')
        assert canal.nom in dm.contenu
        assert canal.cle_partagee_hex in dm.contenu
        assert dm.statut == 'EN_ATTENTE'

    def test_provisionner_is_idempotent_without_regenerer(self, mairie_client, institution_a, compagnon):
        from core.models import CanalMeshCore, Team
        client, _ = mairie_client
        equipe = Team.objects.create(name='Équipe canal stable', institution=institution_a)

        client.post(reverse('team-provisionner-canal-meshcore', args=[equipe.id]))
        canal_avant = CanalMeshCore.objects.get(equipe=equipe)
        cle_avant = canal_avant.cle_partagee_hex

        client.post(reverse('team-provisionner-canal-meshcore', args=[equipe.id]))
        canal_apres = CanalMeshCore.objects.get(equipe=equipe)

        assert canal_apres.id == canal_avant.id
        assert canal_apres.cle_partagee_hex == cle_avant

    def test_regenerer_changes_key_and_resets_provisioning(self, mairie_client, institution_a, compagnon):
        from core.models import CanalMeshCore, Team
        client, _ = mairie_client
        equipe = Team.objects.create(name='Équipe canal révoquée', institution=institution_a)
        client.post(reverse('team-provisionner-canal-meshcore', args=[equipe.id]))
        canal = CanalMeshCore.objects.get(equipe=equipe)
        canal.canal_idx = 3
        canal.compagnon = compagnon
        canal.save(update_fields=['canal_idx', 'compagnon'])
        ancienne_cle = canal.cle_partagee_hex

        response = client.post(reverse('team-provisionner-canal-meshcore', args=[equipe.id]), {'regenerer': True}, format='json')

        assert response.status_code == status.HTTP_200_OK
        canal.refresh_from_db()
        assert canal.cle_partagee_hex != ancienne_cle
        assert canal.canal_idx is None
        assert canal.compagnon is None

    def test_provisionner_requires_belonging_to_team_institution(self, create_user, institution_a):
        from core.models import Team
        autre_institution = _make_institution(nom='Mairie canal B')
        autre_user = create_user(username='autre-canal@test.fr', email='autre-canal@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=autre_institution, utilisateur=autre_user, actif=True)
        client = APIClient()
        client.force_authenticate(user=autre_user)
        equipe = Team.objects.create(name='Équipe canal protégée', institution=institution_a)

        response = client.post(reverse('team-provisionner-canal-meshcore', args=[equipe.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_canaux_a_provisionner_excludes_already_provisioned_for_this_compagnon(self, api_client, compagnon, institution_a, create_user):
        from core.models import CanalMeshCore, Team
        equipe = Team.objects.create(name='Équipe canal provisionnement', institution=institution_a)
        canal_pret = CanalMeshCore.objects.create(equipe=equipe, nom='Prêt', cle_partagee_hex='aa' * 16, compagnon=compagnon, canal_idx=2)
        autre_equipe = Team.objects.create(name='Équipe canal à faire', institution=institution_a)
        canal_a_faire = CanalMeshCore.objects.create(equipe=autre_equipe, nom='À faire', cle_partagee_hex='bb' * 16)

        bridge_user = create_user(username='bridge-canal1@test.fr', email='bridge-canal1@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        response = api_client.get(reverse('compagnonmeshcore-canaux-a-provisionner', args=[compagnon.id]))

        assert response.status_code == status.HTTP_200_OK
        ids = {c['id'] for c in response.data}
        assert str(canal_pret.id) not in ids
        assert str(canal_a_faire.id) in ids
        entree = next(c for c in response.data if c['id'] == str(canal_a_faire.id))
        assert entree['cle_partagee_hex'] == 'bb' * 16

    def test_rapporter_canal_provisionne_updates_canal(self, api_client, compagnon, institution_a, create_user):
        from core.models import CanalMeshCore, Team
        equipe = Team.objects.create(name='Équipe canal rapportée', institution=institution_a)
        canal = CanalMeshCore.objects.create(equipe=equipe, nom='Test', cle_partagee_hex='cc' * 16)

        bridge_user = create_user(username='bridge-canal2@test.fr', email='bridge-canal2@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        response = api_client.post(
            reverse('compagnonmeshcore-rapporter-canal-provisionne', args=[compagnon.id]),
            {'canal_id': str(canal.id), 'canal_idx': 4}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        canal.refresh_from_db()
        assert canal.canal_idx == 4
        assert canal.compagnon_id == compagnon.id

    def test_bridge_can_mark_channel_message_sent_via_patch(self, api_client, compagnon, institution_a, create_user):
        """Même régression que MessageMeshLogSerializer, côté canal."""
        from core.models import CanalMeshCore, MessageCanalMeshCore, Team
        equipe = Team.objects.create(name='Équipe canal msg', institution=institution_a)
        canal = CanalMeshCore.objects.create(equipe=equipe, nom='Test msg', cle_partagee_hex='dd' * 16, compagnon=compagnon, canal_idx=1)
        message = MessageCanalMeshCore.objects.create(canal=canal, direction='SORTANT', statut='EN_ATTENTE', contenu='Salut équipe')

        bridge_user = create_user(username='bridge-canal3@test.fr', email='bridge-canal3@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        response = api_client.patch(reverse('messagecanalmeshcore-detail', args=[message.id]), {'statut': 'ENVOYE'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        message.refresh_from_db()
        assert message.statut == 'ENVOYE'

    def test_messages_canal_a_envoyer_exposes_canal_idx(self, api_client, compagnon, institution_a, create_user):
        from core.models import CanalMeshCore, MessageCanalMeshCore, Team
        equipe = Team.objects.create(name='Équipe canal idx', institution=institution_a)
        canal = CanalMeshCore.objects.create(equipe=equipe, nom='Test idx', cle_partagee_hex='ee' * 16, compagnon=compagnon, canal_idx=5)
        MessageCanalMeshCore.objects.create(canal=canal, direction='SORTANT', statut='EN_ATTENTE', contenu='Message')

        bridge_user = create_user(username='bridge-canal4@test.fr', email='bridge-canal4@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        response = api_client.get(reverse('messagecanalmeshcore-a-envoyer'))

        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]['canal_idx'] == 5


# ── Zone DEMO : nœuds/companions restent affectés, joignables et sur la carte, mais leur
# paramétrage/affectation n'est ni consultable ni modifiable — messages sortants systématiquement
# préfixés et raccourcis. Demande explicite du 14/09, suite à l'incident de fuite d'identité
# constaté en testant le déploiement .114. ──────────────────────────────────────────────────

def _institutional_demo_user(create_user, institution, **kwargs):
    """Un compte institutionnel ET habilité en DEMO (demo_role) — sans demo_role, le rôle
    EFFECTIF en zone DEMO (voir get_effective_role) n'est pas institutionnel du tout, et un 403
    ne prouverait rien de spécifique à DenyInDemo (voir test_user_demo_masking.py, même
    piège)."""
    defaults = {'type': 'AUT_LOCALE', 'demo_role': 'AUT_LOCALE'}
    defaults.update(kwargs)
    user = create_user(**defaults)
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    return user


@pytest.mark.django_db
class TestDemoZoneBlocksMeshCoreWrites:
    """DenyInDemo : create/update/destroy sur CompagnonMeshCore et NoeudMeshUtilisateur
    refusés en zone DEMO, même pour un compte par ailleurs institutionnel."""

    def test_create_compagnon_denied_in_demo(self, create_user, institution_a):
        user = _institutional_demo_user(create_user, institution_a, username='demo-create-compagnon@test.fr', email='demo-create-compagnon@test.fr')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.post(reverse('compagnonmeshcore-list'), {
            'nom': 'Companion demo', 'connexion_type': 'TCP', 'tcp_host': '10.0.0.1', 'tcp_port': 5000,
            'institution': str(institution_a.id),
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not CompagnonMeshCore.objects.filter(nom='Companion demo').exists()

    def test_update_compagnon_denied_in_demo(self, create_user, institution_a, compagnon):
        user = _institutional_demo_user(create_user, institution_a, username='demo-update-compagnon@test.fr', email='demo-update-compagnon@test.fr')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.patch(reverse('compagnonmeshcore-detail', args=[compagnon.id]), {'nom': 'Renommé depuis la démo'}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        compagnon.refresh_from_db()
        assert compagnon.nom != 'Renommé depuis la démo'

    def test_create_compagnon_allowed_in_prod(self, mairie_client, institution_a):
        client, _ = mairie_client
        response = client.post(reverse('compagnonmeshcore-list'), {
            'nom': 'Companion prod', 'connexion_type': 'TCP', 'tcp_host': '10.0.0.2', 'tcp_port': 5000,
            'institution': str(institution_a.id),
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_noeud_denied_in_demo(self, create_user, institution_a):
        user = _institutional_demo_user(create_user, institution_a, username='demo-create-noeud@test.fr', email='demo-create-noeud@test.fr')
        terrain = create_user(username='terrain-demo-noeud@test.fr', email='terrain-demo-noeud@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.post(reverse('noeudmeshutilisateur-list'), {
            'utilisateur': str(terrain.id), 'pubkey_hex': 'demo-write-blocked',
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not NoeudMeshUtilisateur.objects.filter(pubkey_hex='demo-write-blocked').exists()

    def test_destroy_noeud_denied_in_demo(self, create_user, institution_a):
        user = _institutional_demo_user(create_user, institution_a, username='demo-destroy-noeud@test.fr', email='demo-destroy-noeud@test.fr')
        terrain = create_user(username='terrain-demo-destroy@test.fr', email='terrain-demo-destroy@test.fr', type='UTIL_SIMPLE')
        noeud = NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='demo-destroy-target')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.delete(reverse('noeudmeshutilisateur-detail', args=[noeud.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert NoeudMeshUtilisateur.objects.filter(id=noeud.id).exists()


@pytest.mark.django_db
class TestDemoZoneRedactsMeshCoreReads:
    """La LECTURE (list/retrieve) reste volontairement accessible en zone DEMO — sans ça, la
    messagerie d'équipe (EquipeMessagerieMeshComponent) casserait — mais les champs qui
    révèlent la vraie identité/topologie réseau sont masqués à l'affichage, jamais en base."""

    def test_compagnon_network_config_masked_in_demo(self, create_user, institution_a, compagnon):
        user = _institutional_demo_user(create_user, institution_a, username='demo-read-compagnon@test.fr', email='demo-read-compagnon@test.fr')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.get(reverse('compagnonmeshcore-detail', args=[compagnon.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['tcp_host'] is None
        assert response.data['tcp_port'] is None
        assert response.data['nom'] == compagnon.nom

    def test_compagnon_network_config_visible_in_prod(self, mairie_client, compagnon):
        client, _ = mairie_client
        response = client.get(reverse('compagnonmeshcore-detail', args=[compagnon.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['tcp_host'] == compagnon.tcp_host

    def test_noeud_identity_masked_in_demo(self, create_user, institution_a):
        user = _institutional_demo_user(create_user, institution_a, username='demo-read-noeud@test.fr', email='demo-read-noeud@test.fr')
        terrain = create_user(
            username='terrain-redact@test.fr', email='terrain-redact@test.fr', type='UTIL_SIMPLE',
            first_name='Alice', last_name='Terrain',
        )
        noeud = NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='redactme123', nom_noeud='Radio Alice')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.get(reverse('noeudmeshutilisateur-detail', args=[noeud.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['utilisateur'] is None
        assert response.data['utilisateur_nom'] == 'Nœud de terrain'
        assert 'Alice' not in response.data['utilisateur_nom']
        # Le pubkey reste présent : sans lui, le nœud ne serait plus adressable par message.
        assert response.data['pubkey_hex'] == 'redactme123'

    def test_noeud_identity_visible_in_prod(self, mairie_client, create_user):
        client, _ = mairie_client
        terrain = create_user(
            username='terrain-visible@test.fr', email='terrain-visible@test.fr', type='UTIL_SIMPLE',
            first_name='Bob', last_name='Terrain',
        )
        noeud = NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='visible123')

        response = client.get(reverse('noeudmeshutilisateur-detail', args=[noeud.id]))

        assert response.status_code == status.HTTP_200_OK
        assert str(response.data['utilisateur']) == str(terrain.id)
        assert 'Bob' in response.data['utilisateur_nom']


@pytest.mark.django_db
class TestDemoZoneMinimalEndpoints:
    """envoyables()/messageables() : résumés minimaux utilisés par la messagerie d'équipe pour
    composer un DM sans jamais passer par la lecture complète — fonctionnent aussi bien en
    zone DEMO (anonymisés) qu'en PROD (identité réelle)."""

    def test_envoyables_hides_network_config(self, mairie_client, compagnon):
        client, _ = mairie_client
        response = client.get(reverse('compagnonmeshcore-envoyables'))
        assert response.status_code == status.HTTP_200_OK
        entry = next(c for c in response.data if c['id'] == str(compagnon.id))
        assert set(entry.keys()) == {'id', 'nom', 'principal'}

    def test_envoyables_excludes_inactive(self, mairie_client, compagnon):
        compagnon.actif = False
        compagnon.save(update_fields=['actif'])
        client, _ = mairie_client
        response = client.get(reverse('compagnonmeshcore-envoyables'))
        assert response.data == []

    def test_messageables_requires_equipe_param(self, mairie_client):
        client, _ = mairie_client
        response = client.get(reverse('noeudmeshutilisateur-messageables'))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_messageables_anonymizes_in_demo_keeps_pubkey(self, create_user, institution_a):
        from core.models import Team

        user = _institutional_demo_user(create_user, institution_a, username='demo-messageables@test.fr', email='demo-messageables@test.fr')
        terrain = create_user(
            username='terrain-messageables@test.fr', email='terrain-messageables@test.fr', type='UTIL_SIMPLE',
            first_name='Carole', last_name='Terrain',
        )
        equipe = Team.objects.create(name='Équipe messageables', institution=institution_a)
        equipe.members.add(terrain)
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='messageable-pubkey', nom_noeud='Radio Carole')

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.get(reverse('noeudmeshutilisateur-messageables'), {'equipe': str(equipe.id)})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['pubkey_hex'] == 'messageable-pubkey'
        assert response.data[0]['utilisateur_nom'] == 'Nœud de terrain'
        assert 'Carole' not in response.data[0]['utilisateur_nom']

    def test_messageables_shows_real_name_in_prod(self, mairie_client, create_user, institution_a):
        from core.models import Team

        client, _ = mairie_client
        terrain = create_user(
            username='terrain-messageables-prod@test.fr', email='terrain-messageables-prod@test.fr', type='UTIL_SIMPLE',
            first_name='Denis', last_name='Terrain',
        )
        equipe = Team.objects.create(name='Équipe messageables prod', institution=institution_a)
        equipe.members.add(terrain)
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='messageable-prod-pubkey')

        response = client.get(reverse('noeudmeshutilisateur-messageables'), {'equipe': str(equipe.id)})

        assert response.status_code == status.HTTP_200_OK
        assert 'Denis' in response.data[0]['utilisateur_nom']


@pytest.mark.django_db
class TestDemoZonePositionsEnMissionRedaction:
    """positions_en_mission (carte) : même anonymisation que messageables en zone DEMO, la
    position elle-même reste exposée (voir NoeudMeshUtilisateurViewSet)."""

    def _equipe_en_mission(self, utilisateur, institution, statut='EN_COURS'):
        from core.models import Mission, Team
        equipe = Team.objects.create(name=f"Equipe demo {utilisateur.email}", institution=institution)
        equipe.members.add(utilisateur)
        mission = Mission.objects.create(titre='Reconnaissance démo', statut=statut)
        equipe.mission_active = mission
        equipe.save(update_fields=['mission_active'])
        return equipe, mission

    def test_position_anonymized_in_demo(self, create_user, institution_a, compagnon):
        from core.models import ContactMeshCore

        user = _institutional_demo_user(create_user, institution_a, username='demo-position@test.fr', email='demo-position@test.fr')
        terrain = create_user(
            username='terrain-position-demo@test.fr', email='terrain-position-demo@test.fr', type='UTIL_SIMPLE',
            first_name='Eve', last_name='Terrain',
        )
        equipe, mission = self._equipe_en_mission(terrain, institution_a, statut='EN_COURS')
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='position-demo', nom_noeud='Radio Eve')
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex='position-demo', type_contact='COMPANION',
            location='POINT (5.72 45.18)',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.get(reverse('noeudmeshutilisateur-positions-en-mission'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        resultat = response.data[0]
        # La position/le pubkey restent exposés : c'est ce qui fait apparaître le nœud sur la
        # carte et le garde joignable par message.
        assert resultat['pubkey_hex'] == 'position-demo'
        assert resultat['latitude'] == pytest.approx(45.18)
        assert resultat['longitude'] == pytest.approx(5.72)
        # L'identité réelle et le contexte équipe/mission, eux, sont masqués.
        assert resultat['utilisateur_id'] is None
        assert resultat['utilisateur_nom'] == 'Nœud de terrain'
        assert resultat['equipe_id'] is None
        assert resultat['equipe_nom'] is None
        assert resultat['mission_titre'] is None

    def test_position_shows_real_identity_in_prod(self, mairie_client, create_user, institution_a, compagnon):
        from core.models import ContactMeshCore

        client, _ = mairie_client
        terrain = create_user(
            username='terrain-position-prod@test.fr', email='terrain-position-prod@test.fr', type='UTIL_SIMPLE',
            first_name='Farid', last_name='Terrain',
        )
        equipe, mission = self._equipe_en_mission(terrain, institution_a, statut='EN_COURS')
        NoeudMeshUtilisateur.objects.create(utilisateur=terrain, pubkey_hex='position-prod')
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex='position-prod', type_contact='COMPANION',
            location='POINT (5.72 45.18)',
        )

        response = client.get(reverse('noeudmeshutilisateur-positions-en-mission'))

        assert response.status_code == status.HTTP_200_OK
        resultat = response.data[0]
        assert 'Farid' in resultat['utilisateur_nom']
        assert resultat['utilisateur_id'] == str(terrain.id)
        assert resultat['equipe_nom'] == equipe.name
        assert resultat['mission_titre'] == mission.titre


@pytest.mark.django_db
class TestDemoZoneMessageContent:
    """Un message MeshCore sortant composé depuis la zone DEMO part vers du vrai matériel radio
    tenu par de vraies personnes : toujours préfixé "[démo] " et raccourci — voir
    _contenu_message_mesh_demo dans views.py."""

    def test_dm_sortant_prefixed_and_truncated_in_demo(self, create_user, institution_a, compagnon):
        user = _institutional_demo_user(create_user, institution_a, username='demo-dm-send@test.fr', email='demo-dm-send@test.fr')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        contenu_long = 'x' * 200
        response = client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'SORTANT',
            'contact_pubkey_hex': 'demo-dm-target', 'contenu': contenu_long,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['contenu'].startswith('[démo] ')
        assert len(response.data['contenu']) <= 100

    def test_dm_sortant_not_double_prefixed_in_demo(self, create_user, institution_a, compagnon):
        user = _institutional_demo_user(create_user, institution_a, username='demo-dm-doubleprefix@test.fr', email='demo-dm-doubleprefix@test.fr')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'SORTANT',
            'contact_pubkey_hex': 'demo-dm-target2', 'contenu': '[démo] déjà préfixé',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['contenu'] == '[démo] déjà préfixé'
        assert response.data['contenu'].count('[démo]') == 1

    def test_dm_sortant_not_prefixed_in_prod(self, mairie_client, compagnon):
        client, _ = mairie_client
        response = client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'SORTANT',
            'contact_pubkey_hex': 'prod-dm-target', 'contenu': 'Message de production, pas raccourci du tout',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['contenu'] == 'Message de production, pas raccourci du tout'

    def test_dm_entrant_never_altered_in_demo(self, api_client, compagnon, create_user):
        """Un message ENTRANT (déposé par le pont, jamais composé par un humain) ne doit
        jamais être réécrit, même si le pont tourne avec X-Environment: DEMO (ne devrait pas
        arriver en pratique, mais la fonction ne doit s'appliquer qu'à SORTANT)."""
        bridge_user = create_user(username='bridge-demo-entrant@test.fr', email='bridge-demo-entrant@test.fr', type='UTIL_SIMPLE')
        api_client.force_authenticate(user=bridge_user)
        api_client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = api_client.post(reverse('messagemeshlog-list'), {
            'compagnon': str(compagnon.id), 'direction': 'ENTRANT',
            'contact_pubkey_hex': 'entrant-demo', 'contenu': 'Message entrant réel, inchangé',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['contenu'] == 'Message entrant réel, inchangé'

    def test_canal_message_prefixed_in_demo(self, create_user, institution_a, compagnon):
        from core.models import CanalMeshCore, Team

        user = _institutional_demo_user(create_user, institution_a, username='demo-canal-send@test.fr', email='demo-canal-send@test.fr')
        equipe = Team.objects.create(name='Équipe canal démo', institution=institution_a)
        canal = CanalMeshCore.objects.create(equipe=equipe, nom='Canal démo', cle_partagee_hex='ab' * 16, compagnon=compagnon, canal_idx=2)

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.post(reverse('messagecanalmeshcore-list'), {
            'canal': str(canal.id), 'direction': 'SORTANT', 'contenu': 'y' * 200,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['contenu'].startswith('[démo] ')
        assert len(response.data['contenu']) <= 100


@pytest.mark.django_db
class TestReclamerLibererMeshCore:
    """Auto-service page Paramètres du compte : réclamer/libérer SON PROPRE nœud, ouvert à
    n'importe quel utilisateur authentifié (pas besoin d'être acteur institutionnel)."""

    def test_simple_user_can_claim_own_node(self, create_user, compagnon):
        user = create_user(username='benevole@test.fr', email='benevole@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(reverse('noeudmeshutilisateur-reclamer'), {
            'pubkey_hex': 'AA' * 32, 'nom_noeud': 'Mon talkie',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        noeud = NoeudMeshUtilisateur.objects.get(pubkey_hex='aa' * 32)
        assert noeud.utilisateur_id == user.id
        assert noeud.nom_noeud == 'Mon talkie'

    def test_claim_sends_welcome_message(self, create_user, compagnon):
        user = create_user(username='b2@test.fr', email='b2@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(reverse('noeudmeshutilisateur-reclamer'), {'pubkey_hex': 'bb' * 32}, format='json')
        message = MessageMeshLog.objects.get(contact_pubkey_hex='bb' * 32)
        assert message.contenu == 'Bienvenue dans assista-crise !'
        assert message.compagnon_id == compagnon.id

    def test_cannot_claim_node_owned_by_someone_else(self, create_user, compagnon):
        owner = create_user(username='owner@test.fr', email='owner@test.fr', type='UTIL_SIMPLE')
        NoeudMeshUtilisateur.objects.create(utilisateur=owner, pubkey_hex='cc' * 32)
        other = create_user(username='other@test.fr', email='other@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=other)
        response = client.post(reverse('noeudmeshutilisateur-reclamer'), {'pubkey_hex': 'cc' * 32}, format='json')
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_claim_idempotent_for_owner_no_duplicate_welcome(self, create_user, compagnon):
        user = create_user(username='b3@test.fr', email='b3@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(reverse('noeudmeshutilisateur-reclamer'), {'pubkey_hex': 'dd' * 32}, format='json')
        response = client.post(reverse('noeudmeshutilisateur-reclamer'), {'pubkey_hex': 'dd' * 32}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert MessageMeshLog.objects.filter(contact_pubkey_hex='dd' * 32).count() == 1

    def test_release_own_node(self, create_user, compagnon):
        user = create_user(username='b4@test.fr', email='b4@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(reverse('noeudmeshutilisateur-reclamer'), {'pubkey_hex': 'ee' * 32}, format='json')
        response = client.post(reverse('noeudmeshutilisateur-liberer'), {'pubkey_hex': 'ee' * 32}, format='json')
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not NoeudMeshUtilisateur.objects.filter(pubkey_hex='ee' * 32).exists()

    def test_cannot_release_someone_elses_node(self, create_user, compagnon):
        owner = create_user(username='owner2@test.fr', email='owner2@test.fr', type='UTIL_SIMPLE')
        NoeudMeshUtilisateur.objects.create(utilisateur=owner, pubkey_hex='ff' * 32)
        other = create_user(username='other2@test.fr', email='other2@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=other)
        response = client.post(reverse('noeudmeshutilisateur-liberer'), {'pubkey_hex': 'ff' * 32}, format='json')
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert NoeudMeshUtilisateur.objects.filter(pubkey_hex='ff' * 32).exists()

    def test_mes_noeuds_returns_only_own(self, create_user, compagnon):
        user = create_user(username='b5@test.fr', email='b5@test.fr', type='UTIL_SIMPLE')
        other = create_user(username='other3@test.fr', email='other3@test.fr', type='UTIL_SIMPLE')
        NoeudMeshUtilisateur.objects.create(utilisateur=user, pubkey_hex='11' * 32)
        NoeudMeshUtilisateur.objects.create(utilisateur=other, pubkey_hex='22' * 32)
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse('noeudmeshutilisateur-mes-noeuds'))
        assert response.status_code == status.HTTP_200_OK
        assert [n['pubkey_hex'] for n in response.data] == ['11' * 32]

    def test_claim_blocked_in_demo(self, create_user, compagnon):
        user = create_user(username='b6@test.fr', email='b6@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.post(reverse('noeudmeshutilisateur-reclamer'), {'pubkey_hex': '33' * 32}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCommandeMeshCore:
    """Advert/flood advert : l'institutionnel programme une commande via l'action dédiée,
    jamais un create() direct exposé sur CommandeMeshCoreViewSet (voir sa docstring). Le
    service-pont l'exécute ensuite via a_executer/PATCH — même principe de file d'attente
    que MessageMeshLog."""

    def test_envoyer_advert_creates_commande(self, mairie_client, compagnon):
        client, _ = mairie_client
        response = client.post(reverse('compagnonmeshcore-envoyer-advert', args=[compagnon.id]), {}, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        commande = CommandeMeshCore.objects.get(compagnon=compagnon)
        assert commande.type_commande == 'ADVERT'
        assert commande.statut == 'EN_ATTENTE'

    def test_envoyer_flood_advert_creates_commande(self, mairie_client, compagnon):
        client, _ = mairie_client
        response = client.post(reverse('compagnonmeshcore-envoyer-advert', args=[compagnon.id]), {'flood': True}, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        commande = CommandeMeshCore.objects.get(compagnon=compagnon)
        assert commande.type_commande == 'FLOOD_ADVERT'

    def test_envoyer_advert_denied_in_demo(self, create_user, institution_a, compagnon):
        user = _institutional_demo_user(create_user, institution_a, username='demo-advert@test.fr', email='demo-advert@test.fr')
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')

        response = client.post(reverse('compagnonmeshcore-envoyer-advert', args=[compagnon.id]), {}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not CommandeMeshCore.objects.filter(compagnon=compagnon).exists()

    def test_requires_institutional_actor(self, create_user, compagnon):
        user = create_user(username='simple-advert@test.fr', email='simple-advert@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('compagnonmeshcore-envoyer-advert', args=[compagnon.id]), {}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_executer_returns_only_pending_for_compagnon(self, mairie_client, compagnon, institution_a):
        client, _ = mairie_client
        autre_compagnon = CompagnonMeshCore.objects.create(nom='Autre companion advert', connexion_type='TCP', institution=institution_a)
        cmd_attente = CommandeMeshCore.objects.create(compagnon=compagnon, type_commande='ADVERT')
        CommandeMeshCore.objects.create(compagnon=compagnon, type_commande='ADVERT', statut='EXECUTEE')
        CommandeMeshCore.objects.create(compagnon=autre_compagnon, type_commande='ADVERT')

        response = client.get(reverse('commandemeshcore-a-executer'), {'compagnon': str(compagnon.id)})

        assert response.status_code == status.HTTP_200_OK
        assert [c['id'] for c in response.data] == [str(cmd_attente.id)]

    def test_bridge_can_mark_commande_executed(self, compagnon):
        commande = CommandeMeshCore.objects.create(compagnon=compagnon, type_commande='ADVERT')
        from core.models import User
        pont = User.objects.create_user(username='pont-test@test.fr', email='pont-test@test.fr', type='UTIL_SIMPLE')
        client = APIClient()
        client.force_authenticate(user=pont)

        response = client.patch(reverse('commandemeshcore-detail', args=[commande.id]), {'statut': 'EXECUTEE'}, format='json')

        assert response.status_code == status.HTTP_200_OK, response.data
        commande.refresh_from_db()
        assert commande.statut == 'EXECUTEE'
        assert commande.date_execution is not None
