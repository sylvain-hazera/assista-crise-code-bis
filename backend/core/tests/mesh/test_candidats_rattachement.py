"""Trouver SON nœud pour le rattacher à son compte.

`/api/noeuds-meshcore/candidats/` et `/api/noeuds-meshtastic/candidats/`.

Ce que ces tests verrouillent, et qui est un piège de conception vérifié le 11/11/2026 :

**la liste est ouverte à tout compte connecté, parce que rattacher son nœud est ce qui OUVRE le
droit radio.** Depuis que les endpoints radio sont passés derrière `PeutAccederRadio`, mettre la
liste de découverte derrière ce même droit formait un cercle : il faut le droit pour trouver la
clé qui donne le droit. La conséquence concrète était qu'un utilisateur devait recopier
64 caractères hexadécimaux à la main — et une faute de frappe rattache un nœud qui n'est pas le
sien.

L'ouverture est payée par une charge **minimale** : de quoi reconnaître son appareil, rien de
plus. Pas de position — celle d'un companion est très souvent un domicile — pas de télémétrie,
pas de voisinage. C'est pour cela que ces actions vivent sur les vues de rattachement et ne sont
pas un assouplissement de `ContactMeshCoreViewSet`, qui sert tout l'état du réseau.
"""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, CompagnonMeshtastic, ContactMeshCore, ContactMeshtastic,
    NoeudMeshUtilisateur, NoeudUtilisateurMeshtastic, TypeContactMeshCore,
)

URL_MESHCORE = "/api/noeuds-meshcore/candidats/"
URL_MESHTASTIC = "/api/noeuds-meshtastic/candidats/"

CLE_A = "a1" * 32
CLE_B = "b2" * 32
CLE_REPETEUR = "c3" * 32


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def sans_droit_radio(create_user, db):
    """Un compte qui vient d'acheter un boîtier : aucun nœud, aucune institution, aucun droit
    radio. C'est EXACTEMENT celui qui a besoin de la liste."""
    return create_user(username="neuf-radio@x.fr", email="neuf-radio@x.fr", type="UTIL_SIMPLE")


@pytest.fixture
def passerelle(db):
    return CompagnonMeshCore.objects.create(nom="Passerelle A", connexion_type="TCP",
                                            tcp_host="127.0.0.1", tcp_port=5050)


@pytest.fixture
def autre_passerelle(db):
    return CompagnonMeshCore.objects.create(nom="Passerelle B", connexion_type="TCP",
                                            tcp_host="127.0.0.1", tcp_port=5051)


@pytest.fixture
def contacts_meshcore(passerelle):
    ContactMeshCore.objects.create(
        compagnon=passerelle, pubkey_hex=CLE_A, nom="Talkie Jean",
        type_contact=TypeContactMeshCore.COMPANION, dernier_advert=timezone.now(),
        location=Point(2.35, 48.85), niveau_batterie_pct=87)
    ContactMeshCore.objects.create(
        compagnon=passerelle, pubkey_hex=CLE_B, nom="Talkie Marie",
        type_contact=TypeContactMeshCore.COMPANION, dernier_advert=timezone.now())
    # Un répéteur : il ne se réclame PAS ici, il passe par RattachementNoeudRadio avec preuve.
    ContactMeshCore.objects.create(
        compagnon=passerelle, pubkey_hex=CLE_REPETEUR, nom="Relais du Pilat",
        type_contact=TypeContactMeshCore.REPEATER, dernier_advert=timezone.now())


@pytest.mark.django_db
class TestCandidatsMeshCore:

    def test_un_compte_sans_aucun_droit_radio_voit_la_liste(self, sans_droit_radio,
                                                            contacts_meshcore):
        """Le test qui porte toute la décision. Si celui-ci exigeait un droit, le rattachement
        serait un cercle : il faut un nœud rattaché pour avoir le droit radio, et il faudrait le
        droit radio pour trouver le nœud à rattacher."""
        reponse = _client(sans_droit_radio).get(URL_MESHCORE)
        assert reponse.status_code == 200
        assert {ligne['pubkey_hex'] for ligne in reponse.data} == {CLE_A, CLE_B}

    def test_mais_l_etat_du_reseau_lui_reste_fermé(self, sans_droit_radio, contacts_meshcore):
        """L'ouverture est une PORTE ÉTROITE, pas un trou dans le domaine radio : le même compte
        n'accède toujours pas à `/api/contacts-meshcore/`, qui sert tout l'état du réseau."""
        assert _client(sans_droit_radio).get("/api/contacts-meshcore/").status_code == 403

    def test_les_repeteurs_ne_sont_pas_proposes(self, sans_droit_radio, contacts_meshcore):
        """Un répéteur est une infrastructure dont d'autres dépendent : il se réclame par preuve
        (mot de passe ou appartenance à l'ACL), pas en cochant une liste."""
        reponse = _client(sans_droit_radio).get(URL_MESHCORE)
        assert CLE_REPETEUR not in {ligne['pubkey_hex'] for ligne in reponse.data}

    def test_ni_position_ni_telemetrie_ne_sont_servies(self, sans_droit_radio, contacts_meshcore):
        """Le prix de l'ouverture. Reconnaître « c'est le mien » n'a besoin ni de la position de
        l'appareil — souvent un domicile — ni de sa batterie."""
        ligne = next(l for l in _client(sans_droit_radio).get(URL_MESHCORE).data
                     if l['pubkey_hex'] == CLE_A)
        assert set(ligne) == {'pubkey_hex', 'nom', 'dernier_advert', 'deja_associe', 'a_moi'}

    def test_un_noeud_deja_pris_est_signale_sans_nommer_son_titulaire(self, sans_droit_radio,
                                                                     contacts_meshcore,
                                                                     create_user):
        """Savoir qu'une clé est prise suffit à comprendre pourquoi on ne peut pas la réclamer.
        Dire PAR QUI révélerait quel appareil appartient à quelle personne."""
        autre = create_user(username="autre-radio@x.fr", email="autre-radio@x.fr",
                            type="UTIL_SIMPLE")
        NoeudMeshUtilisateur.objects.create(utilisateur=autre, pubkey_hex=CLE_A)
        ligne = next(l for l in _client(sans_droit_radio).get(URL_MESHCORE).data
                     if l['pubkey_hex'] == CLE_A)
        assert ligne['deja_associe'] is True
        assert ligne['a_moi'] is False
        assert "autre-radio@x.fr" not in str(ligne)

    def test_mon_propre_noeud_est_distingue_de_celui_d_un_autre(self, sans_droit_radio,
                                                               contacts_meshcore):
        """« Pris » et « pris par vous » n'appellent pas la même action : le second se libère."""
        NoeudMeshUtilisateur.objects.create(utilisateur=sans_droit_radio, pubkey_hex=CLE_A)
        ligne = next(l for l in _client(sans_droit_radio).get(URL_MESHCORE).data
                     if l['pubkey_hex'] == CLE_A)
        assert ligne['deja_associe'] is True
        assert ligne['a_moi'] is True

    def test_un_noeud_entendu_par_deux_passerelles_n_apparait_qu_une_fois(
            self, sans_droit_radio, contacts_meshcore, autre_passerelle):
        """Le même appareil deux fois dans une liste de choix est une invitation à se tromper."""
        ContactMeshCore.objects.create(
            compagnon=autre_passerelle, pubkey_hex=CLE_A, nom="Talkie Jean",
            type_contact=TypeContactMeshCore.COMPANION, dernier_advert=timezone.now())
        reponse = _client(sans_droit_radio).get(URL_MESHCORE)
        assert [l['pubkey_hex'] for l in reponse.data].count(CLE_A) == 1

    def test_un_visiteur_non_connecte_ne_voit_rien(self, contacts_meshcore):
        """Ouvert à tout compte CONNECTÉ : la liste nomme des appareils, elle n'est pas publique."""
        assert APIClient().get(URL_MESHCORE).status_code in (401, 403)


@pytest.mark.django_db
class TestCandidatsMeshtastic:

    @pytest.fixture
    def contacts_meshtastic(self, db):
        compagnon = CompagnonMeshtastic.objects.create(
            nom="Pont Gaulix", node_num=1234, broker_host="mqtt.gaulix.fr")
        ContactMeshtastic.objects.create(
            compagnon=compagnon, node_num=0xA1B2C3D4, long_name="Talkie Jean",
            short_name="JEAN", hardware_model="HELTEC_V3", dernier_advert=timezone.now(),
            location=Point(2.35, 48.85))
        return compagnon

    def test_un_compte_sans_droit_radio_voit_la_liste(self, sans_droit_radio,
                                                      contacts_meshtastic):
        reponse = _client(sans_droit_radio).get(URL_MESHTASTIC)
        assert reponse.status_code == 200
        assert [l['node_num'] for l in reponse.data] == [0xA1B2C3D4]

    def test_l_identifiant_est_servi_sous_la_forme_que_l_appareil_affiche(
            self, sans_droit_radio, contacts_meshtastic):
        """`!a1b2c3d4`. Un entier décimal n'est reconnaissable par personne, et c'est pourtant
        la seule forme que le formulaire demandait jusqu'ici."""
        ligne = _client(sans_droit_radio).get(URL_MESHTASTIC).data[0]
        assert ligne['node_id'] == "!a1b2c3d4"

    def test_la_passerelle_qui_l_a_entendu_est_nommee(self, sans_droit_radio,
                                                      contacts_meshtastic):
        """Différence assumée avec MeshCore : `reclamer` a besoin de savoir par quel broker
        passer quand plusieurs ont entendu le nœud. Le dire ici évite un second choix à
        l'utilisateur."""
        ligne = _client(sans_droit_radio).get(URL_MESHTASTIC).data[0]
        assert ligne['compagnon_nom'] == "Pont Gaulix"
        assert ligne['compagnon_id']

    def test_aucune_position_n_est_servie(self, sans_droit_radio, contacts_meshtastic):
        ligne = _client(sans_droit_radio).get(URL_MESHTASTIC).data[0]
        assert 'latitude' not in ligne and 'location' not in ligne

    def test_mon_propre_noeud_est_distingue(self, sans_droit_radio, contacts_meshtastic):
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=sans_droit_radio,
                                                  node_num=0xA1B2C3D4)
        ligne = _client(sans_droit_radio).get(URL_MESHTASTIC).data[0]
        assert ligne['deja_associe'] is True and ligne['a_moi'] is True

    def test_mais_l_etat_du_reseau_lui_reste_fermé(self, sans_droit_radio, contacts_meshtastic):
        assert _client(sans_droit_radio).get("/api/contacts-meshtastic/").status_code == 403
