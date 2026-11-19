"""Le reste de ce que MeshCore permet (19/11/2026) : sur un répéteur joint par le nœud, et sur le
nœud local lui-même. Ce qui est verrouillé : qui peut quoi, et la forme des paramètres."""
import pytest
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, Institution, InstitutionType, MeshCoreConnexionType, MoyenAdminRadio,
    NoeudUtilisateurMeshtastic, RattachementNoeudRadio, StatutPreuveRadio, TacheAdminMeshCore,
)

URL = "/api/taches-admin-meshcore/"
CLE_REPETEUR = "cd" * 32
CLE_PASSERELLE = "ab" * 32


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def institution(db):
    t, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie radio", type=t)


@pytest.fixture
def autre_institution(db):
    t, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Autre mairie", type=t)


@pytest.fixture
def passerelle(institution):
    return CompagnonMeshCore.objects.create(
        nom="GW mairie", institution=institution, connexion_type=MeshCoreConnexionType.TCP,
        tcp_host="172.16.1.60", pubkey_hex=CLE_PASSERELLE)


def _agent(create_user, email, institution):
    u = create_user(username=email, email=email, type="SECOURS", institution=institution)
    NoeudUtilisateurMeshtastic.objects.create(utilisateur=u, node_num=hash(email) & 0xFFFFFF)
    return u


@pytest.fixture
def agent(create_user, institution, passerelle):
    return _agent(create_user, "agent-ops@x.fr", institution)


@pytest.fixture
def repeteur_prouve(institution, passerelle):
    return RattachementNoeudRadio.objects.create(
        pubkey_hex=CLE_REPETEUR, institution=institution, libelle="Piton",
        moyen_admin=MoyenAdminRadio.MOT_DE_PASSE, mot_de_passe="secret", compagnon_meshcore=passerelle,
        statut_preuve=StatutPreuveRadio.VERIFIEE)


def _poser(client, passerelle, type_tache, parametres=None, cible=CLE_REPETEUR):
    corps = {"compagnon": str(passerelle.id), "type_tache": type_tache}
    if cible:
        corps["pubkey_cible"] = cible
    if parametres is not None:
        corps["parametres"] = parametres
    return client.post(URL, corps, format="json")


@pytest.mark.django_db
class TestRepeteur:

    def test_relire_un_reglage_exige_la_preuve(self, agent, passerelle):
        refus = _poser(_client(agent), passerelle, "LIRE_REGLAGE", {"cle": "radio"})
        assert refus.status_code == 403        # pas de rattachement prouvé

    def test_relire_un_reglage_avec_la_preuve(self, agent, passerelle, repeteur_prouve):
        reponse = _poser(_client(agent), passerelle, "LIRE_REGLAGE", {"cle": "radio"})
        assert reponse.status_code == 201, reponse.data

    @pytest.mark.parametrize("cle", ["prv.key", "password", "guest.password", "Radio", "a b"])
    def test_un_reglage_secret_ou_mal_forme_n_est_pas_relu(self, agent, passerelle, repeteur_prouve, cle):
        assert _poser(_client(agent), passerelle, "LIRE_REGLAGE", {"cle": cle}).status_code == 400

    @pytest.mark.parametrize("type_tache", ["LIRE_VERSION", "LIRE_HORLOGE", "LIRE_ACL",
                                            "SYNCHRO_HORLOGE", "CONNEXION_ROOM", "DECONNECTER"])
    def test_les_operations_en_session_exigent_la_preuve(self, agent, passerelle, type_tache):
        assert _poser(_client(agent), passerelle, type_tache).status_code == 403

    def test_lire_le_proprietaire_est_une_lecture_ouverte(self, agent, passerelle):
        assert _poser(_client(agent), passerelle, "LIRE_PROPRIETAIRE").status_code == 201

    def test_l_horloge_remise_a_l_heure_est_une_ecriture(self, agent, passerelle, repeteur_prouve):
        reponse = _poser(_client(agent), passerelle, "SYNCHRO_HORLOGE")
        assert reponse.status_code == 201 and reponse.data["est_ecriture"] is True


@pytest.mark.django_db
class TestNoeudLocal:

    def test_la_cible_est_toujours_la_passerelle_elle_meme(self, agent, passerelle):
        reponse = _poser(_client(agent), passerelle, "LOCAL_STATISTIQUES", cible=CLE_REPETEUR)
        assert reponse.status_code == 201, reponse.data
        assert TacheAdminMeshCore.objects.get(pk=reponse.data["id"]).pubkey_cible == CLE_PASSERELLE

    def test_une_passerelle_sans_cle_connue_est_refusee(self, agent, passerelle):
        CompagnonMeshCore.objects.filter(pk=passerelle.pk).update(pubkey_hex="")
        assert _poser(_client(agent), passerelle, "LOCAL_REGLAGES", cible=None).status_code == 400

    def test_l_institution_regle_sa_passerelle_pas_une_autre(self, agent, create_user, passerelle, autre_institution):
        assert _poser(_client(agent), passerelle, "LOCAL_NOM", {"nom": "Mairie-GW"}, cible=None).status_code == 201
        etranger = _agent(create_user, "etranger-ops@x.fr", autre_institution)
        assert _poser(_client(etranger), passerelle, "LOCAL_NOM", {"nom": "Pirate"}, cible=None).status_code == 403

    def test_un_changement_radio_durable_exige_la_confirmation(self, agent, passerelle):
        radio = {"frequence_mhz": 869.525, "bande_khz": 250, "facteur_etalement": 11, "taux_codage": 5}
        refus = _poser(_client(agent), passerelle, "LOCAL_RADIO", radio, cible=None)
        assert refus.status_code == 400 and "confirme" in str(refus.data)
        assert _poser(_client(agent), passerelle, "LOCAL_RADIO", {**radio, "confirme": True},
                      cible=None).status_code == 201

    @pytest.mark.parametrize("type_tache,parametres", [
        ("LOCAL_NOM", {"nom": ""}),
        ("LOCAL_NOM", {"nom": "x" * 40}),
        ("LOCAL_POSITION", {"latitude": 95, "longitude": 3}),
        ("LOCAL_PUISSANCE", {"dbm": 40}),
        ("LOCAL_SUPPRIMER_CONTACT", {"pubkey": "zz"}),
    ])
    def test_les_parametres_mal_formes_sont_refuses(self, agent, passerelle, type_tache, parametres):
        assert _poser(_client(agent), passerelle, type_tache, parametres, cible=None).status_code == 400
