"""Synchronisation du domaine mesh entre un satellite et le central (06/11/2026).

Deux sens, deux mécanismes différents, et c'est volontaire :

- **Montant** : la file sortante générique (`core/sync_outbox.py`), élargie aux canaux, aux trois
  modèles de message manquants et aux alertes SOS. Un satellite observe du trafic radio que le
  central ne voit jamais — il peut être à l'autre bout du pays, voire à La Réunion.
- **Descendant** : un canal dédié avec accusé (`SatelliteViewSet.mesh_a_emettre` / `mesh_emis`),
  parce que la file montante ne suit que les CRÉATIONS : un `EN_ATTENTE -> ENVOYE` n'y remonterait
  jamais, alors qu'un opérateur du central doit savoir si son message est parti.

Aucun pont MQTT entre les brokers : décision du 06/11/2026, voir la docstring de
`core/management/commands/synchroniser_mesh.py`.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.management.commands.synchroniser_mesh import Command as CommandeSyncMesh
from core.models import (
    CanalMeshtastic, CompagnonMeshtastic, DirectionMessageMesh, EvenementSynchronisation,
    Institution, InstitutionType, MessageCanalMeshtastic, MessageMeshtasticLog, ModeleSynchronisable,
    Satellite, StatutEnrolementSatellite, StatutMessageMesh,
)


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Mesh", type=itype, commune_code="97411")


@pytest.fixture
def satellite(create_user, institution):
    compte = create_user(
        username="sat-mesh@service.fr", email="sat-mesh@service.fr",
        type="UTIL_SIMPLE", institution=institution,
    )
    return Satellite.objects.create(
        institution=institution, nom="Sat La Réunion", profil="FULL",
        statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte,
    )


@pytest.fixture
def satellite_client(satellite):
    client = APIClient()
    client.force_authenticate(user=satellite.compte_service)
    return client


@pytest.fixture
def compagnon_du_satellite(institution, satellite):
    return CompagnonMeshtastic.objects.create(
        nom="Radio du satellite", node_num=777001, institution=institution, satellite=satellite,
    )


@pytest.fixture
def canal(institution, compagnon_du_satellite):
    return CanalMeshtastic.objects.create(
        nom="EquipeCAI", institution=institution, psk_hex="ab" * 16,
        compagnon=compagnon_du_satellite,
    )


class TestPerimetreMontant:
    """Le périmètre de la file sortante, et la cohérence des trois endroits qu'il faut tenir
    alignés : l'énumération, les listes de champs et les signaux."""

    def test_les_modeles_mesh_sont_tous_declares(self):
        from core.sync_outbox import APPEND_ONLY, CHAMPS_PAR_MODELE

        attendus = {
            "MessageMeshLog", "CanalMeshCore", "CanalMeshtastic", "MessageCanalMeshCore",
            "MessageMeshtasticLog", "MessageCanalMeshtastic", "AlerteMeshSOS",
        }
        assert attendus <= set(ModeleSynchronisable.values)
        assert attendus <= set(CHAMPS_PAR_MODELE)
        assert attendus <= APPEND_ONLY, "le trafic observé ne se réédite pas : append-only"

    def test_chaque_modele_synchronisable_a_un_signal_connecte(self):
        """Garde-fou : déclarer un modèle sans connecter son signal le rendrait silencieusement
        non synchronisé — aucune erreur, juste de la donnée qui ne remonte jamais."""
        from django.db.models.signals import post_save

        from core.sync_outbox import MODELES_SYNCHRONISABLES, enregistrer_evenement

        connectes = {
            r[1]().__name__ for r in post_save.receivers
            if r[1]() is not None and getattr(r[1](), '__name__', '') == 'enregistrer_evenement'
        }
        # post_save.receivers ne donne pas directement le sender : on vérifie via dispatch_uid.
        uids = {str(r[0][0]) for r in post_save.receivers}
        manquants = [
            m for m in MODELES_SYNCHRONISABLES
            if f"sync_outbox_{m}" not in uids
        ]
        assert manquants == [], f"signal post_save non connecté pour : {manquants}"
        assert enregistrer_evenement is not None and connectes is not None

    def test_les_champs_declares_existent_vraiment(self):
        """Un champ mal orthographié dans CHAMPS_PAR_MODELE ne casse qu'à l'exécution, sur le
        satellite, en crise. On le détecte ici."""
        from django.apps import apps as django_apps

        from core.sync_outbox import CHAMPS_PAR_MODELE

        erreurs = []
        for nom_modele, champs in CHAMPS_PAR_MODELE.items():
            Modele = django_apps.get_model('core', nom_modele)
            concrets = {f.name for f in Modele._meta.get_fields()}
            concrets |= {f"{f.name}_id" for f in Modele._meta.get_fields() if f.many_to_one or f.one_to_one}
            for champ in champs:
                if champ not in concrets:
                    erreurs.append(f"{nom_modele}.{champ}")
        assert erreurs == [], f"champs inexistants : {erreurs}"


@pytest.mark.django_db
class TestFileSortanteMesh:

    def test_un_message_de_canal_cree_localement_peuple_la_file(self, settings, canal):
        """Sur un satellite (INSTANCE_SATELLITE_LOCALE), un message observé sur la radio doit
        apparaître dans la file sortante. Avant le 06/11/2026, seuls les DM MeshCore le faisaient."""
        settings.INSTANCE_SATELLITE_LOCALE = True
        message = MessageCanalMeshtastic.objects.create(
            canal=canal, direction=DirectionMessageMesh.ENTRANT, contenu="recu sur la radio",
        )
        evenement = EvenementSynchronisation.objects.filter(
            modele="MessageCanalMeshtastic", objet_id=message.id,
        ).first()
        assert evenement is not None
        # Le contenu part en clair dans le payload (HTTPS) : le central doit pouvoir le lire, et
        # il le rechiffre avec SA clé en base.
        assert evenement.payload["contenu"] == "recu sur la radio"
        assert evenement.payload["canal_id"] == str(canal.id)

    def test_le_central_ne_peuple_jamais_la_file(self, settings, canal):
        """Le central ne se synchronise pas vers lui-même : sans ce garde, il se renverrait sa
        propre donnée."""
        settings.INSTANCE_SATELLITE_LOCALE = False
        MessageCanalMeshtastic.objects.create(
            canal=canal, direction=DirectionMessageMesh.ENTRANT, contenu="cote central",
        )
        assert not EvenementSynchronisation.objects.exists()


@pytest.mark.django_db
class TestDescenteDesOrdresDEnvoi:

    def _url(self, satellite, action):
        return reverse(f'satellite-{action}', args=[satellite.id])

    def test_le_satellite_recoit_ses_messages_en_attente_et_leurs_canaux(
        self, satellite, satellite_client, canal, compagnon_du_satellite,
    ):
        message = MessageCanalMeshtastic.objects.create(
            canal=canal, compagnon=compagnon_du_satellite,
            direction=DirectionMessageMesh.SORTANT, contenu="ordre du central",
        )
        reponse = satellite_client.get(self._url(satellite, 'mesh-a-emettre'))

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert [m["id"] for m in reponse.data["messages"]] == [str(message.id)]
        assert reponse.data["messages"][0]["contenu"] == "ordre du central"
        # Le canal accompagne le message : le satellite ne le reçoit par aucun autre chemin, et
        # sans lui la FK serait introuvable chez lui.
        assert [c["id"] for c in reponse.data["canaux"]] == [str(canal.id)]
        assert reponse.data["canaux"][0]["psk_hex"] == "ab" * 16

    def test_un_message_deja_envoye_n_est_plus_propose(
        self, satellite, satellite_client, canal, compagnon_du_satellite,
    ):
        MessageCanalMeshtastic.objects.create(
            canal=canal, compagnon=compagnon_du_satellite, direction=DirectionMessageMesh.SORTANT,
            contenu="deja parti", statut=StatutMessageMesh.ENVOYE,
        )
        reponse = satellite_client.get(self._url(satellite, 'mesh-a-emettre'))
        assert reponse.data["messages"] == []

    def test_un_message_d_un_autre_satellite_n_est_jamais_propose(
        self, satellite, satellite_client, institution, canal,
    ):
        """Cloisonnement : un satellite ne doit voir que SES ordres d'envoi."""
        autre_satellite = Satellite.objects.create(
            institution=institution, nom="Autre sat", profil="FULL",
            statut_enrolement=StatutEnrolementSatellite.APPROUVE,
        )
        autre_compagnon = CompagnonMeshtastic.objects.create(
            nom="Radio ailleurs", node_num=777002, institution=institution, satellite=autre_satellite,
        )
        MessageCanalMeshtastic.objects.create(
            canal=canal, compagnon=autre_compagnon, direction=DirectionMessageMesh.SORTANT,
            contenu="pas pour moi",
        )
        reponse = satellite_client.get(self._url(satellite, 'mesh-a-emettre'))
        assert reponse.data["messages"] == []

    def test_un_message_sans_companion_designe_n_est_pas_propose(
        self, satellite, satellite_client, canal,
    ):
        """Sans companion, on ne sait pas à quel satellite le message appartient : il relève des
        companions du central."""
        MessageCanalMeshtastic.objects.create(
            canal=canal, compagnon=None, direction=DirectionMessageMesh.SORTANT, contenu="orphelin",
        )
        reponse = satellite_client.get(self._url(satellite, 'mesh-a-emettre'))
        assert reponse.data["messages"] == []

    def test_l_accuse_met_a_jour_le_statut_et_la_date(
        self, satellite, satellite_client, canal, compagnon_du_satellite,
    ):
        message = MessageMeshtasticLog.objects.create(
            compagnon=compagnon_du_satellite, canal=canal, contact_node_num=999,
            direction=DirectionMessageMesh.SORTANT, contenu="a emettre",
        )
        reponse = satellite_client.post(
            self._url(satellite, 'mesh-emis'),
            {"rapports": [{"modele": "MessageMeshtasticLog", "id": str(message.id),
                           "statut": StatutMessageMesh.ENVOYE}]},
            format="json",
        )
        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data["resultats"][0]["resultat"] == "applique"
        message.refresh_from_db()
        assert message.statut == StatutMessageMesh.ENVOYE
        assert message.date_envoi is not None

    def test_un_satellite_ne_peut_pas_rapporter_pour_un_autre(
        self, satellite, satellite_client, institution, canal,
    ):
        autre_satellite = Satellite.objects.create(
            institution=institution, nom="Autre sat 2", profil="FULL",
            statut_enrolement=StatutEnrolementSatellite.APPROUVE,
        )
        autre_compagnon = CompagnonMeshtastic.objects.create(
            nom="Radio ailleurs 2", node_num=777003, institution=institution, satellite=autre_satellite,
        )
        message = MessageCanalMeshtastic.objects.create(
            canal=canal, compagnon=autre_compagnon, direction=DirectionMessageMesh.SORTANT,
            contenu="pas a moi",
        )
        reponse = satellite_client.post(
            self._url(satellite, 'mesh-emis'),
            {"rapports": [{"modele": "MessageCanalMeshtastic", "id": str(message.id),
                           "statut": StatutMessageMesh.ENVOYE}]},
            format="json",
        )
        assert reponse.data["resultats"][0]["resultat"] == "inconnu"
        message.refresh_from_db()
        assert message.statut == StatutMessageMesh.EN_ATTENTE

    def test_un_rapport_invalide_ne_bloque_pas_le_lot(
        self, satellite, satellite_client, canal, compagnon_du_satellite,
    ):
        bon = MessageCanalMeshtastic.objects.create(
            canal=canal, compagnon=compagnon_du_satellite,
            direction=DirectionMessageMesh.SORTANT, contenu="bon",
        )
        reponse = satellite_client.post(
            self._url(satellite, 'mesh-emis'),
            {"rapports": [
                {"modele": "Inconnu", "id": str(bon.id), "statut": StatutMessageMesh.ENVOYE},
                {"modele": "MessageCanalMeshtastic", "id": str(bon.id), "statut": "PAS_UN_STATUT"},
                {"modele": "MessageCanalMeshtastic", "id": str(bon.id), "statut": StatutMessageMesh.ENVOYE},
            ]},
            format="json",
        )
        resultats = reponse.data["resultats"]
        assert [r["resultat"] for r in resultats] == ["erreur", "erreur", "applique"]
        bon.refresh_from_db()
        assert bon.statut == StatutMessageMesh.ENVOYE

    def test_un_compte_etranger_est_refuse(self, satellite, create_user, institution):
        intrus = create_user(
            username="intrus@x.fr", email="intrus@x.fr", type="UTIL_SIMPLE", institution=institution,
        )
        client = APIClient()
        client.force_authenticate(user=intrus)
        assert client.get(self._url(satellite, 'mesh-a-emettre')).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCreationLocaleSansEcho:
    """Le point le plus facile à casser : une création venue du central ne doit PAS repartir vers
    lui. Sans le marqueur `_synchronisation_entrante`, chaque descente provoquerait une remontée
    du même objet, indéfiniment."""

    def test_la_creation_locale_ne_peuple_pas_la_file_sortante(self, settings, institution):
        settings.INSTANCE_SATELLITE_LOCALE = True
        compagnon = CompagnonMeshtastic.objects.create(
            nom="Radio locale", node_num=777004, institution=institution,
        )
        EvenementSynchronisation.objects.all().delete()   # on ne mesure que ce qui suit

        CommandeSyncMesh._creer_sans_echo(
            CanalMeshtastic, "11111111-1111-1111-1111-111111111111",
            {"nom": "DepuisCentral", "psk_hex": "cd" * 16, "compagnon_id": compagnon.id,
             "institution_id": institution.id, "crise_id": None, "equipe_id": None,
             "principal": False, "actif": True},
        )

        assert CanalMeshtastic.objects.filter(nom="DepuisCentral").exists()
        assert not EvenementSynchronisation.objects.exists(), (
            "une création venue du central a été renvoyée au central : boucle d'écho"
        )

    def test_sans_le_marqueur_la_file_serait_peuplee(self, settings, institution):
        """Preuve que le test précédent mesure bien quelque chose : la même création SANS le
        marqueur peuple la file."""
        settings.INSTANCE_SATELLITE_LOCALE = True
        EvenementSynchronisation.objects.all().delete()
        CanalMeshtastic.objects.create(nom="EcritLocalement", psk_hex="ef" * 16)
        assert EvenementSynchronisation.objects.filter(modele="CanalMeshtastic").exists()
