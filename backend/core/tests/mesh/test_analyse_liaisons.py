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


# ── Le même raisonnement, appliqué à MeshCore ────────────────────────────────

CLE_P = "aa" + "01" * 31      # la « passerelle » : celle qui rapporte
CLE_X = "bb" + "02" * 31
CLE_Y = "bb" + "03" * 31      # même PREMIER octet que CLE_X : collision sur 1 octet,
                              # mais pas sur 2 — c'est ce qui permet de tester les deux cas.
CLE_Z = "cc" + "04" * 31


@pytest.fixture
def noeud_meshcore(db):
    """Nœud MeshCore vu récemment, avec position."""
    from core.models import CompagnonMeshCore, ContactMeshCore, MeshCoreConnexionType

    compagnon = CompagnonMeshCore.objects.create(
        nom="Companion analyse", connexion_type=MeshCoreConnexionType.TCP, tcp_host="10.0.0.1",
    )

    def _creer(cle, nom=None, lat=-21.0, lon=55.5, vu_il_y_a_heures=1):
        return ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex=cle, nom=nom or cle[:8],
            location=Point(lon, lat, srid=4326),
            dernier_advert=timezone.now() - datetime.timedelta(hours=vu_il_y_a_heures),
        )
    return _creer


def _liaison_meshcore(prefixe, recepteur, snr=5.0, nombre=5, octets=1):
    from core.models import LiaisonMeshCore, SourceLiaisonMeshtastic as Source

    return LiaisonMeshCore.objects.create(
        emetteur_prefixe_hex=prefixe, prefixe_octets=octets, recepteur_pubkey_hex=recepteur,
        source=Source.VOISINAGE, snr=snr, nombre=nombre, dernier_vu=timezone.now(),
    )


def _releve(cle, total, recus):
    from core.models import ReleveVoisinageMeshCore

    return ReleveVoisinageMeshCore.objects.create(
        pubkey_hex=cle, total_annonce=total, recus=recus, date_releve=timezone.now(),
    )


@pytest.mark.django_db
class TestAnalyseMeshCore:
    """Le cœur de l'analyse est partagé : ces tests ne revérifient pas les seuils, ils
    verrouillent ce que MeshCore fait DIFFÉREMMENT."""

    def _scene_sens_unique(self, noeud_meshcore):
        """X rapporte (il entend Z), P entend X, mais X ne mentionne jamais P.

        Le sens est le piège de ce module : `_Sens(a, b)` signifie « b a entendu a », et la
        conclusion « à sens unique » porte sur **A**, celui qui rapporte sans mentionner B.
        C'est donc la complétude du relevé de **X** qui décide, pas celle de P."""
        noeud_meshcore(CLE_P, "Passerelle")
        noeud_meshcore(CLE_X, "Lointain")
        noeud_meshcore(CLE_Z, "Temoin")
        _liaison_meshcore(CLE_X[:2], CLE_P)      # P a entendu X
        _liaison_meshcore(CLE_Z[:2], CLE_X)      # X a entendu Z -> X rapporte

    def test_une_absence_ne_prouve_rien_tant_que_le_releve_est_incomplet(self, noeud_meshcore):
        """Sans relevé complet, on ne conclut pas « à sens unique » : la liste des voisins de X
        pouvait simplement s'arrêter avant P."""
        from core.analyse_liaisons import analyser_meshcore

        self._scene_sens_unique(noeud_meshcore)
        _releve(CLE_X, total=20, recus=3)        # page partielle

        resultat = analyser_meshcore("PROD")
        assert resultat["sens_unique"] == []

    def test_un_releve_complet_permet_de_conclure(self, noeud_meshcore):
        """C'est l'apport de MeshCore : il annonce son total, donc une absence PEUT être une
        preuve — ce qui n'est jamais le cas côté Meshtastic, dont le rapport est plafonné à 10
        sans le dire."""
        from core.analyse_liaisons import analyser_meshcore

        self._scene_sens_unique(noeud_meshcore)
        _releve(CLE_X, total=1, recus=1)

        resultat = analyser_meshcore("PROD")
        conclusions = [c for c in resultat["sens_unique"] if c["entendu"] == CLE_X]
        assert len(conclusions) == 1
        # « P entend X, X ne l'entend pas » : X est le côté sourd.
        assert conclusions[0]["entend"] == CLE_P
        assert conclusions[0]["nom_entend"] == "Passerelle"

    def test_un_prefixe_ambigu_est_ecarte_et_compte(self, noeud_meshcore):
        """Deux nœuds partagent le premier octet : on ne sait pas de qui parle la liaison.
        Conclure reviendrait à inventer, et une liaison fausse envoie quelqu'un sur un point
        haut."""
        from core.analyse_liaisons import analyser_meshcore

        noeud_meshcore(CLE_P, "Passerelle")
        noeud_meshcore(CLE_X, "X")
        noeud_meshcore(CLE_Y, "Y")
        _liaison_meshcore("bb", CLE_P)     # préfixe d'un octet : CLE_X et CLE_Y commencent par bb

        resultat = analyser_meshcore("PROD")
        assert resultat["sens_unique"] == []
        assert resultat["liaisons_ecartees"]["prefixe_ambigu"] == 1

    def test_un_prefixe_inconnu_est_ecarte_et_compte(self, noeud_meshcore):
        from core.analyse_liaisons import analyser_meshcore

        noeud_meshcore(CLE_P, "Passerelle")
        _liaison_meshcore("ff", CLE_P)
        _releve(CLE_P, total=1, recus=1)

        resultat = analyser_meshcore("PROD")
        assert resultat["liaisons_ecartees"]["prefixe_inconnu"] == 1

    def test_un_prefixe_plus_long_leve_l_ambiguite(self, noeud_meshcore):
        """Deux octets suffisent ici à distinguer CLE_X de CLE_Y : c'est exactement ce que
        `pubkey_prefix_length` achète."""
        from core.analyse_liaisons import analyser_meshcore

        noeud_meshcore(CLE_P, "Passerelle")
        noeud_meshcore(CLE_X, "X")
        noeud_meshcore(CLE_Y, "Y")
        noeud_meshcore(CLE_Z, "Temoin")
        _liaison_meshcore(CLE_X[:4], CLE_P, octets=2)
        _liaison_meshcore(CLE_Z[:2], CLE_X)
        _releve(CLE_X, total=1, recus=1)

        resultat = analyser_meshcore("PROD")
        # Deux octets suffisent à distinguer CLE_X de CLE_Y : rien n'est écarté, et la
        # conclusion devient possible.
        assert resultat["liaisons_ecartees"]["prefixe_ambigu"] == 0
        assert [c["entendu"] for c in resultat["sens_unique"]] == [CLE_X]

    def test_l_identite_rendue_est_la_cle_publique(self, noeud_meshcore):
        """Le frontend Meshtastic lit `node_num` ; MeshCore n'en a pas, et fabriquer un entier
        à partir d'une clé serait une identité inventée."""
        from core.analyse_liaisons import analyser_meshcore

        noeud_meshcore(CLE_P, "Passerelle")
        noeud_meshcore(CLE_Z, "Temoin")
        _liaison_meshcore(CLE_Z[:2], CLE_P)
        _releve(CLE_P, total=1, recus=1)

        resultat = analyser_meshcore("PROD")
        for inaudible in resultat["inaudibles"]:
            assert "pubkey" in inaudible and "node_num" not in inaudible

    def test_le_diagnostic_meshtastic_n_est_pas_pollue(self, noeud_meshcore, noeud, liaison):
        """Les deux réseaux sont analysés séparément : une liaison MeshCore ne doit jamais
        apparaître dans le diagnostic Meshtastic, et réciproquement."""
        noeud_meshcore(CLE_P, "Passerelle")
        noeud_meshcore(CLE_X, "X")
        _liaison_meshcore(CLE_X[:2], CLE_P)
        _releve(CLE_P, total=1, recus=1)

        resultat = analyser("PROD")   # Meshtastic
        assert resultat["sens_unique"] == []
        assert "liaisons_ecartees" not in resultat
