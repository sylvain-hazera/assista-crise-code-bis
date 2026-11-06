"""Analyse des liaisons radio Meshtastic (core/analyse_liaisons.py).

Porté de `asymetrie.js` de carte-live-meshtastic. Ce qui a de la valeur dans son travail, ce ne
sont pas les formules — ce sont les précautions, qui évitent de conclure à tort. Chaque test
ci-dessous verrouille l'une d'elles, parce que sans elles l'analyse produirait des diagnostics
faux et crédibles : désigner un relais comme sourd envoie quelqu'un sur un point haut.
"""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from core.analyse_liaisons import PLAFOND_VOISINAGE, SEUIL_SOURD_DB, analyser
from core.models import (
    CompagnonMeshtastic, ContactMeshtastic, LiaisonMeshtastic, SourceLiaisonMeshtastic,
)

MAINTENANT = None  # posé par la fixture


@pytest.fixture
def compagnon(db):
    return CompagnonMeshtastic.objects.create(nom="Passerelle", node_num=1000)


@pytest.fixture
def noeud(compagnon):
    """Fabrique un nœud vu récemment, avec position."""
    def _creer(num, lat=44.84, lon=-0.57, vu_il_y_a_heures=1):
        return ContactMeshtastic.objects.create(
            compagnon=compagnon, node_num=num, long_name=f"Noeud {num}",
            location=Point(lon, lat, srid=4326),
            dernier_advert=timezone.now() - datetime.timedelta(hours=vu_il_y_a_heures),
        )
    return _creer


@pytest.fixture
def liaison(db):
    """Fabrique une liaison orientée : `recepteur` a entendu `emetteur`."""
    def _creer(emetteur, recepteur, snr=None, source=SourceLiaisonMeshtastic.RF,
               nombre=5, vu_il_y_a_heures=1):
        return LiaisonMeshtastic.objects.create(
            emetteur=emetteur, recepteur=recepteur, source=source, snr=snr, nombre=nombre,
            dernier_vu=timezone.now() - datetime.timedelta(hours=vu_il_y_a_heures),
        )
    return _creer


@pytest.mark.django_db
class TestLiaisonsASensUnique:

    def test_detecte_b_entend_a_mais_a_n_entend_jamais_b(self, noeud, liaison):
        noeud(10); noeud(20); noeud(99)
        # 10 est bien un RAPPORTEUR : il entend 99 et le dit. Sans ça, son silence sur 20 ne
        # prouverait rien — c'est la précaution centrale du portage.
        liaison(99, 10, snr=2.0)
        # 20 entend 10 régulièrement ; 10 n'entend jamais 20.
        liaison(10, 20, snr=5.0)
        resultat = analyser("PROD")
        assert len(resultat["sens_unique"]) == 1
        cas = resultat["sens_unique"][0]
        assert cas["entend"] == 20 and cas["entendu"] == 10
        assert cas["preuve"] == "passerelle"

    def test_une_observation_isolee_ne_conclut_pas(self, noeud, liaison):
        """Sa précaution : il faut de la régularité. Un seul paquet peut être un rebond."""
        noeud(10); noeud(20)
        liaison(10, 20, snr=5.0, nombre=2)
        assert analyser("PROD")["sens_unique"] == []

    def test_un_saut_de_traceroute_ne_prouve_pas_qu_un_noeud_rapporte(self, noeud, liaison):
        """LA précaution centrale. Un relais qui ne rapporte rien ferait passer pour « à sens
        unique » tout ce qu'il entend sans le dire."""
        noeud(10); noeud(20)
        liaison(10, 20, snr=5.0, source=SourceLiaisonMeshtastic.TRACEROUTE)
        assert analyser("PROD")["sens_unique"] == []

    def test_un_voisinage_plein_n_est_pas_une_preuve_d_absence(self, noeud, liaison):
        """Un rapport NeighborInfo ne porte que 10 voisins : si la liste est pleine, l'absence
        d'un voisin ne prouve rien."""
        noeud(100)
        for i in range(PLAFOND_VOISINAGE):
            noeud(200 + i)
            liaison(200 + i, 100, snr=3.0, source=SourceLiaisonMeshtastic.VOISINAGE)
        # 100 déclare 10 voisins (liste pleine) et aucun ne le déclare en retour.
        assert analyser("PROD")["sens_unique"] == []

    def test_une_liaison_trop_lointaine_est_ecartee(self, noeud, liaison):
        """Au-delà de 120 km, c'est une erreur de position, pas une liaison directe."""
        noeud(10, lat=44.84, lon=-0.57)
        noeud(20, lat=48.85, lon=2.35)      # Bordeaux -> Paris
        liaison(10, 20, snr=5.0)
        assert analyser("PROD")["sens_unique"] == []

    def test_un_emetteur_inactif_n_est_pas_signale(self, noeud, liaison):
        """Si B ne s'est pas annoncé depuis 24 h, il est peut-être simplement éteint."""
        noeud(10, vu_il_y_a_heures=72)
        noeud(20)
        liaison(10, 20, snr=5.0)
        assert analyser("PROD")["sens_unique"] == []


@pytest.mark.django_db
class TestLiaisonsDesequilibrees:

    def test_un_ecart_de_plus_de_dix_db_est_signale(self, noeud, liaison):
        noeud(10); noeud(20)
        liaison(10, 20, snr=8.0)      # 20 entend 10 fort
        liaison(20, 10, snr=-5.0)     # 10 entend 20 faiblement
        resultat = analyser("PROD")
        assert len(resultat["desequilibrees"]) == 1
        assert resultat["desequilibrees"][0]["ecart_db"] == 13.0
        # Une liaison réciproque n'est jamais « à sens unique ».
        assert resultat["sens_unique"] == []

    def test_un_ecart_normal_n_est_pas_signale(self, noeud, liaison):
        noeud(10); noeud(20)
        liaison(10, 20, snr=5.0)
        liaison(20, 10, snr=2.0)
        assert analyser("PROD")["desequilibrees"] == []

    def test_une_paire_n_est_signalee_qu_une_fois(self, noeud, liaison):
        """Les deux sens existent : sans garde, la paire apparaîtrait deux fois."""
        noeud(10); noeud(20)
        liaison(10, 20, snr=9.0)
        liaison(20, 10, snr=-6.0)
        assert len(analyser("PROD")["desequilibrees"]) == 1


@pytest.mark.django_db
class TestNoeudsInaudibles:

    def test_un_noeud_qui_entend_mais_que_personne_n_entend(self, noeud, liaison):
        """Typiquement une antenne en réception seulement, ou une émission en panne."""
        noeud(10); noeud(20); noeud(30)
        liaison(20, 10, snr=4.0)
        liaison(30, 10, snr=4.0)
        resultat = analyser("PROD")
        inaudibles = [x["node_num"] for x in resultat["inaudibles"]]
        assert inaudibles == [10]

    def test_un_seul_voisin_ne_suffit_pas(self, noeud, liaison):
        noeud(10); noeud(20)
        liaison(20, 10, snr=4.0)
        assert analyser("PROD")["inaudibles"] == []


@pytest.mark.django_db
class TestRelaisSourds:

    def _paire_desequilibree(self, noeud, liaison, sourd, partenaire, ecart):
        """Le partenaire entend le sourd correctement, le sourd l'entend `ecart` dB moins bien."""
        noeud(partenaire)
        liaison(sourd, partenaire, snr=5.0)
        liaison(partenaire, sourd, snr=5.0 - ecart)

    def test_un_ecart_median_anormal_sur_plusieurs_voisins(self, noeud, liaison):
        noeud(10)
        for p in (21, 22, 23):
            self._paire_desequilibree(noeud, liaison, 10, p, ecart=12.0)
        resultat = analyser("PROD")
        assert [s["node_num"] for s in resultat["sourds"]] == [10]
        assert resultat["sourds"][0]["ecart_db"] == 12.0
        assert resultat["sourds"][0]["nb_voisins"] == 3

    def test_un_seul_voisin_ne_prouve_rien(self, noeud, liaison):
        """Sa précaution : une mesure isolée peut venir du partenaire, pas du nœud examiné."""
        noeud(10)
        self._paire_desequilibree(noeud, liaison, 10, 21, ecart=15.0)
        assert analyser("PROD")["sourds"] == []

    def test_la_mediane_resiste_a_un_voisin_aberrant(self, noeud, liaison):
        """Trois voisins normaux et un aberrant ne doivent pas faire un sourd : c'est tout
        l'intérêt de la médiane plutôt que d'une moyenne."""
        noeud(10)
        for p in (21, 22, 23):
            self._paire_desequilibree(noeud, liaison, 10, p, ecart=1.0)
        self._paire_desequilibree(noeud, liaison, 10, 24, ecart=25.0)
        assert analyser("PROD")["sourds"] == []

    def test_il_faut_au_moins_une_mesure_reciproque(self, noeud, liaison):
        """Des bornes basses seules ne prouvent rien : le partenaire peut simplement émettre très
        fort. Ici deux voisins entendent 10 très fort sans que 10 ne les rapporte jamais."""
        noeud(10)
        # 10 rapporte bien quelque chose (sinon il n'est pas « rapporteur ») mais pas ces deux-là.
        noeud(99); liaison(99, 10, snr=1.0)
        for p in (21, 22):
            noeud(p)
            liaison(10, p, snr=5.0)
        resultat = analyser("PROD")
        assert resultat["sourds"] == []

    def test_le_resultat_signale_que_la_puissance_est_inconnue(self, noeud, liaison):
        """Limite propre à Assista-Crise : sans la puissance d'émission des nœuds, un nœud qui
        émet plus fort que ses voisins peut passer pour sourd. L'interface doit pouvoir le dire."""
        noeud(10)
        for p in (21, 22):
            self._paire_desequilibree(noeud, liaison, 10, p, ecart=SEUIL_SOURD_DB + 2)
        resultat = analyser("PROD")
        assert resultat["puissance_connue"] is False
        assert resultat["sourds"][0]["puissance_connue"] is False


@pytest.mark.django_db
class TestCloisonnementDesZones:

    def test_une_liaison_de_demo_n_apparait_pas_en_production(self, compagnon, liaison):
        ContactMeshtastic.objects.create(
            compagnon=compagnon, node_num=10, location=Point(-0.57, 44.84, srid=4326),
            dernier_advert=timezone.now(), environment="DEMO",
        )
        LiaisonMeshtastic.objects.create(
            emetteur=10, recepteur=20, source=SourceLiaisonMeshtastic.RF, snr=5.0, nombre=5,
            dernier_vu=timezone.now(), environment="DEMO",
        )
        assert analyser("PROD")["sens_unique"] == []


@pytest.fixture
def institutionnel(create_user, db):
    from core.models import Institution, InstitutionType
    from rest_framework.test import APIClient
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom="Mairie Liaisons", type=itype)
    user = create_user(username="secours-liaisons@x.fr", email="secours-liaisons@x.fr",
                       type="SECOURS", institution=institution)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestApiRapporterLiaisons:
    """Le pont rapporte ses observations par lot : un POST par paquet MQTT noierait l'API."""

    def _url(self, compagnon):
        return reverse('compagnonmeshtastic-rapporter-liaisons', args=[compagnon.id])

    def test_une_liaison_est_creee_puis_agregee(self, institutionnel, compagnon):
        corps = {"liaisons": [{"emetteur": 10, "recepteur": 20, "source": "RF", "snr": 3.0}]}
        r1 = institutionnel.post(self._url(compagnon), corps, format="json")
        assert r1.status_code == 200, r1.data
        assert r1.data == {"enregistrees": 1, "ignorees": 0}

        institutionnel.post(self._url(compagnon), corps, format="json")
        liaison = LiaisonMeshtastic.objects.get(emetteur=10, recepteur=20, source="RF")
        # Agrégée, pas dupliquée : une seule ligne par sens et par source.
        assert LiaisonMeshtastic.objects.count() == 1
        assert liaison.nombre == 2

    def test_seul_le_meilleur_snr_est_conserve(self, institutionnel, compagnon):
        """Une moyenne serait tirée vers le bas par les paquets en limite de portée et masquerait
        une liaison en réalité bonne. On garde ce dont la liaison est capable."""
        for snr in (3.0, 9.0, 1.0):
            institutionnel.post(
                self._url(compagnon),
                {"liaisons": [{"emetteur": 10, "recepteur": 20, "source": "RF", "snr": snr}]},
                format="json",
            )
        assert LiaisonMeshtastic.objects.get(emetteur=10, recepteur=20).snr == 9.0

    def test_une_entree_invalide_ne_bloque_pas_le_lot(self, institutionnel, compagnon):
        reponse = institutionnel.post(self._url(compagnon), {"liaisons": [
            {"emetteur": "pas-un-nombre", "recepteur": 20, "source": "RF"},
            {"emetteur": 10, "recepteur": 20, "source": "INVENTEE"},
            {"emetteur": 30, "recepteur": 30, "source": "RF"},          # un nœud ne s'entend pas
            {"emetteur": 10, "recepteur": 20, "source": "RF", "snr": 2.0},
        ]}, format="json")
        assert reponse.data == {"enregistrees": 1, "ignorees": 3}
        assert LiaisonMeshtastic.objects.count() == 1

    def test_un_anonyme_est_refuse(self, compagnon):
        from rest_framework.test import APIClient
        reponse = APIClient().post(self._url(compagnon), {"liaisons": []}, format="json")
        assert reponse.status_code in (401, 403)


@pytest.mark.django_db
class TestApiLectureEtGeojson:

    def test_le_geojson_ne_garde_que_les_liaisons_positionnees(self, institutionnel, noeud, liaison):
        noeud(10); noeud(20, lat=44.86, lon=-0.55)
        liaison(10, 20, snr=4.0)
        liaison(10, 999, snr=4.0)        # 999 n'a aucune position connue
        reponse = institutionnel.get(reverse('liaisonmeshtastic-geojson'))
        assert reponse.status_code == 200, reponse.data
        assert reponse.data["type"] == "FeatureCollection"
        assert len(reponse.data["features"]) == 1
        trait = reponse.data["features"][0]
        assert trait["geometry"]["type"] == "LineString"
        assert len(trait["geometry"]["coordinates"]) == 2
        assert trait["properties"]["snr"] == 4.0

    def test_le_geojson_ecarte_une_distance_impossible(self, institutionnel, noeud, liaison):
        noeud(10, lat=44.84, lon=-0.57)
        noeud(20, lat=48.85, lon=2.35)
        liaison(10, 20, snr=4.0)
        reponse = institutionnel.get(reverse('liaisonmeshtastic-geojson'))
        assert reponse.data["features"] == []

    def test_la_fenetre_est_bornee_meme_si_on_demande_l_impossible(self, institutionnel, noeud, liaison):
        """Sans borne, un réseau départemental rapatrierait des dizaines de milliers de segments."""
        noeud(10); noeud(20, lat=44.86, lon=-0.55)
        liaison(10, 20, snr=4.0, vu_il_y_a_heures=24 * 60)     # vieux de 60 jours
        reponse = institutionnel.get(reverse('liaisonmeshtastic-geojson'), {"depuis_heures": "999999"})
        assert reponse.data["features"] == []                   # borné à 30 jours

    def test_l_analyse_est_exposee(self, institutionnel, noeud, liaison):
        noeud(10); noeud(20); noeud(99)
        liaison(99, 10, snr=2.0)
        liaison(10, 20, snr=5.0)
        reponse = institutionnel.get(reverse('contactmeshtastic-analyse-liaisons'))
        assert reponse.status_code == 200, reponse.data
        assert [c["entendu"] for c in reponse.data["sens_unique"]] == [10]
        assert reponse.data["puissance_connue"] is False
