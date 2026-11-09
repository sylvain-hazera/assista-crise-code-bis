"""Routage Meshtastic (core/routage_meshtastic.py) : quelle passerelle a entendu ce nœud, et par
où passer pour le joindre.

Chaque test verrouille une des raisons pour lesquelles ces deux questions ne se confondent pas.
Les confondre produit une réponse crédible et fausse — « il est joignable » alors que personne ne
peut l'atteindre, ce qui est le pire résultat possible en gestion de crise.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshtastic, ContactMeshtastic, LiaisonMeshtastic, SourceLiaisonMeshtastic,
)
from core.routage_meshtastic import HOP_LIMIT_DEFAUT, router


@pytest.fixture
def compagnon(db):
    """Notre connexion MQTT, dont le node_num est celui de NOTRE passerelle."""
    return CompagnonMeshtastic.objects.create(
        nom="Gaulix", node_num=1000, broker_host="mqtt.gaulix.fr", broker_port=1883)


@pytest.fixture
def noeud(compagnon):
    def _creer(num, vu_il_y_a_heures=1, sur=None):
        return ContactMeshtastic.objects.create(
            compagnon=sur or compagnon, node_num=num, long_name=f"Noeud {num}",
            dernier_advert=timezone.now() - datetime.timedelta(hours=vu_il_y_a_heures),
        )
    return _creer


@pytest.fixture
def institutionnel(create_user, db):
    from core.models import Institution, InstitutionType
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom="Mairie Routage", type=itype)
    user = create_user(username="secours-routage@x.fr", email="secours-routage@x.fr",
                       type="SECOURS", institution=institution)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def citoyen(create_user, db):
    client = APIClient()
    client.force_authenticate(user=create_user(username="citoyen-routage@x.fr",
                                               email="citoyen-routage@x.fr"))
    return client


@pytest.fixture
def liaison(db):
    """« recepteur a entendu emetteur », une observation orientée."""
    def _creer(emetteur, recepteur, snr=5.0, source=SourceLiaisonMeshtastic.RF,
               nombre=5, vu_il_y_a_heures=1):
        return LiaisonMeshtastic.objects.create(
            emetteur=emetteur, recepteur=recepteur, source=source, snr=snr, nombre=nombre,
            dernier_vu=timezone.now() - datetime.timedelta(hours=vu_il_y_a_heures),
        )
    return _creer


def route(resultat, num):
    return next(r for r in resultat["routes"] if r["node_num"] == num)


@pytest.mark.django_db
class TestPasserelleQuiAEntendu:

    def test_un_noeud_entendu_directement_est_a_un_saut_de_sa_passerelle(self, noeud, liaison):
        noeud(1000); noeud(42)
        liaison(42, 1000, snr=-7.5)
        r = route(router("PROD"), 42)
        assert r["sauts"] == 1
        assert [p["node_num"] for p in r["passerelles"]] == [1000]
        assert r["passerelles"][0]["snr"] == -7.5

    def test_notre_passerelle_est_distinguee_de_celle_d_un_tiers(self, noeud, liaison):
        """Sur un broker partagé la plupart des passerelles ne sont pas à nous. On voit alors le
        nœud sans rien maîtriser du dernier saut : son `downlink_enabled` nous est inconnu."""
        noeud(1000); noeud(7777); noeud(42)
        liaison(42, 1000)            # notre passerelle (node_num du companion)
        liaison(42, 7777)            # passerelle d'un tiers sur le même broker
        r = route(router("PROD"), 42)
        par_num = {p["node_num"]: p["nous"] for p in r["passerelles"]}
        assert par_num == {1000: True, 7777: False}
        assert r["passerelles_a_nous"] == 1

    def test_une_seule_passerelle_est_signalee_comme_panne_unique(self, noeud, liaison):
        noeud(1000); noeud(42)
        liaison(42, 1000)
        assert "si elle tombe" in route(router("PROD"), 42)["raison"]

    def test_le_meilleur_snr_est_propose_en_premier(self, noeud, liaison):
        noeud(1000); noeud(2000); noeud(42)
        liaison(42, 1000, snr=-15.0)
        liaison(42, 2000, snr=3.0)
        r = route(router("PROD"), 42)
        assert [p["node_num"] for p in r["passerelles"]] == [2000, 1000]

    def test_un_noeud_que_personne_n_entend_ne_promet_rien(self, noeud):
        noeud(42)
        r = route(router("PROD"), 42)
        assert r["sauts"] is None
        assert r["passerelles"] == []
        assert "rien ne permet d'affirmer qu'on peut l'atteindre" in r["raison"]

    def test_une_passerelle_est_a_zero_saut_d_elle_meme(self, noeud, liaison):
        """Le nœud qui publie sur MQTT n'a besoin d'aucun relais : sans ce cas, il s'affichait
        « à 0 sauts de la passerelle "une passerelle" »."""
        noeud(1000); noeud(42)
        liaison(42, 1000)
        r = route(router("PROD"), 1000)
        assert r["sauts"] == 0
        assert r["hop_limit_suffisant"] is True
        assert "lui-même une passerelle" in r["raison"]

    def test_une_liaison_hors_fenetre_ne_compte_plus(self, noeud, liaison):
        noeud(1000); noeud(42)
        liaison(42, 1000, vu_il_y_a_heures=24 * 8)
        assert route(router("PROD"), 42)["sauts"] is None


@pytest.mark.django_db
class TestBrokerCloisonne:

    def test_le_companion_a_employer_est_celui_qui_a_vu_le_noeud(self, compagnon, noeud, liaison):
        """Publier sur un autre broker n'atteint pas ce nœud : les deux réseaux ne communiquent
        pas. C'est la première raison pour laquelle « entendu » ne vaut pas « joignable »."""
        autre = CompagnonMeshtastic.objects.create(
            nom="Local", node_num=2000, broker_host="mosquitto", broker_port=1883)
        noeud(42, sur=autre)
        liaison(42, 2000)
        r = route(router("PROD"), 42)
        assert r["compagnon_id"] == str(autre.id)
        assert r["compagnon_nom"] == "Local"
        assert r["broker"] == "mosquitto:1883"
        assert "Local" in r["raison"]

    def test_vu_par_deux_brokers_le_plus_recent_gagne(self, compagnon, noeud):
        """Le trafic d'un nœud passe par le broker où on l'a entendu le plus récemment : un
        companion qui l'a vu la semaine dernière ne dit rien de l'état actuel du réseau."""
        autre = CompagnonMeshtastic.objects.create(nom="Local", node_num=2000)
        noeud(42, sur=compagnon, vu_il_y_a_heures=40)
        noeud(42, sur=autre, vu_il_y_a_heures=2)
        assert route(router("PROD"), 42)["compagnon_nom"] == "Local"


@pytest.mark.django_db
class TestLiaisonOrientee:

    def test_le_sens_retour_non_observe_est_dit(self, noeud, liaison):
        """« La passerelle l'entend » n'implique pas « il entend la passerelle ». Un chemin dont
        le retour n'est pas prouvé est un chemin pour écouter, pas pour parler."""
        noeud(1000); noeud(42)
        liaison(42, 1000)
        r = route(router("PROD"), 42)
        assert r["passerelles"][0]["retour_prouve"] is False
        assert "rien ne prouve qu'il nous entende" in r["raison"]

    def test_le_retour_observe_est_reconnu(self, noeud, liaison):
        noeud(1000); noeud(42)
        liaison(42, 1000)
        liaison(1000, 42, source=SourceLiaisonMeshtastic.VOISINAGE)
        r = route(router("PROD"), 42)
        assert r["passerelles"][0]["retour_prouve"] is True
        assert r["retour_prouve"] is True
        assert "rien ne prouve" not in r["raison"]


@pytest.mark.django_db
class TestCheminEtSauts:

    def test_un_relais_intermediaire_donne_deux_sauts_et_un_chemin_nomme(self, noeud, liaison):
        """Le saut intermédiaire vient forcément du VOISINAGE : une observation de source RF
        signifierait que le relais a lui-même publié le paquet sur MQTT, donc qu'il est une
        passerelle — et le nœud serait alors à un seul saut."""
        noeud(1000); noeud(500); noeud(42)
        liaison(500, 1000)       # la passerelle entend le relais
        liaison(42, 500, source=SourceLiaisonMeshtastic.VOISINAGE)   # le relais entend le nœud
        r = route(router("PROD"), 42)
        assert r["sauts"] == 2
        assert [(e["de"], e["vers"]) for e in r["chemin"]] == [(42, 500), (500, 1000)]

    def test_un_unique_relais_intermediaire_est_un_point_de_panne(self, noeud, liaison):
        noeud(1000); noeud(500); noeud(42)
        liaison(500, 1000)
        liaison(42, 500, source=SourceLiaisonMeshtastic.VOISINAGE)
        r = route(router("PROD"), 42)
        assert r["relais_obligatoire"]["node_num"] == 500
        assert "point de panne unique" in r["raison"]

    def test_deux_relais_distincts_ne_sont_pas_un_point_de_panne(self, noeud, liaison):
        noeud(1000); noeud(500); noeud(600); noeud(42)
        liaison(500, 1000); liaison(600, 1000)
        liaison(42, 500, source=SourceLiaisonMeshtastic.VOISINAGE)
        liaison(42, 600, source=SourceLiaisonMeshtastic.VOISINAGE)
        assert route(router("PROD"), 42)["relais_obligatoire"] is None

    def test_au_dela_du_hop_limit_par_defaut_le_message_est_abandonne_sans_erreur(self, noeud, liaison):
        """Quatre sauts avec le réglage par défaut (3) : le paquet meurt en route et l'émetteur
        n'en sait rien. C'est la conclusion la plus actionnable de ce module."""
        chaine = [42, 40, 30, 20, 1000]
        for num in chaine:
            noeud(num)
        for emetteur, recepteur in zip(chaine, chaine[1:]):
            liaison(emetteur, recepteur, source=SourceLiaisonMeshtastic.VOISINAGE)
        liaison(20, 1000)        # c'est bien une passerelle (source RF)
        r = route(router("PROD"), 42)
        assert r["sauts"] == 4 > HOP_LIMIT_DEFAUT
        assert r["hop_limit_suffisant"] is False
        assert "abandonné en route" in r["raison"]

    def test_un_chemin_dans_le_hop_limit_est_declare_suffisant(self, noeud, liaison):
        noeud(1000); noeud(500); noeud(42)
        liaison(500, 1000)
        liaison(42, 500, source=SourceLiaisonMeshtastic.VOISINAGE)
        assert route(router("PROD"), 42)["hop_limit_suffisant"] is True


@pytest.mark.django_db
class TestSourcesDObservation:

    def test_un_saut_de_traceroute_compte_comme_chemin(self, noeud, liaison):
        """Un saut de traceroute prouve bien un saut radio direct — contrairement à ce qu'on peut
        en conclure sur « ce nœud rapporte ce qu'il entend » (voir core/analyse_liaisons.py)."""
        noeud(1000); noeud(500); noeud(42)
        liaison(500, 1000)
        liaison(42, 500, source=SourceLiaisonMeshtastic.TRACEROUTE)
        r = route(router("PROD"), 42)
        assert r["sauts"] == 2
        assert r["chemin"][0]["sources"] == ["TRACEROUTE"]

    def test_un_relais_traverse_par_traceroute_n_est_pas_une_passerelle(self, noeud, liaison):
        """Il ne publie pas forcément sur MQTT : le compter comme passerelle promettrait une
        arrivée du trafic qui n'existe pas."""
        noeud(500); noeud(42)
        liaison(42, 500, source=SourceLiaisonMeshtastic.TRACEROUTE)
        assert route(router("PROD"), 42)["sauts"] is None

    def test_le_voisinage_seul_ne_fait_pas_une_passerelle(self, noeud, liaison):
        noeud(500); noeud(42)
        liaison(42, 500, source=SourceLiaisonMeshtastic.VOISINAGE)
        assert route(router("PROD"), 42)["sauts"] is None


@pytest.mark.django_db
class TestCloisonnementEtApi:

    def test_une_liaison_de_l_autre_zone_n_influence_pas_le_routage(self, compagnon, noeud, liaison):
        noeud(1000); noeud(42)
        LiaisonMeshtastic.objects.create(
            emetteur=42, recepteur=1000, source=SourceLiaisonMeshtastic.RF,
            dernier_vu=timezone.now(), environment="DEMO")
        assert route(router("PROD"), 42)["sauts"] is None

    def test_node_num_restreint_la_reponse_sans_changer_la_conclusion(self, noeud, liaison):
        noeud(1000); noeud(42); noeud(43)
        liaison(42, 1000); liaison(43, 1000)
        resultat = router("PROD", node_num=42)
        assert [r["node_num"] for r in resultat["routes"]] == [42]
        assert resultat["routes"][0]["sauts"] == 1

    def test_l_endpoint_sert_le_routage(self, institutionnel, noeud, liaison):
        noeud(1000); noeud(42)
        liaison(42, 1000)
        reponse = institutionnel.get(reverse('contactmeshtastic-routage'))
        assert reponse.status_code == 200
        assert route(reponse.json(), 42)["sauts"] == 1

    def test_l_endpoint_refuse_un_node_num_non_entier(self, institutionnel):
        reponse = institutionnel.get(reverse('contactmeshtastic-routage'), {'node_num': 'abc'})
        assert reponse.status_code == 400

    def test_l_endpoint_est_ferme_a_un_citoyen(self, citoyen):
        reponse = citoyen.get(reverse('contactmeshtastic-routage'))
        assert reponse.status_code == 403
