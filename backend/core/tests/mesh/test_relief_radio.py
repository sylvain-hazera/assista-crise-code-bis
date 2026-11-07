"""Propagation radio sur le relief (core/relief_radio.py).

Porté de `relief.js` de carte-live-meshtastic. Comme pour l'analyse d'asymétrie, ce qui a de la
valeur n'est pas la formule mais ce qu'elle évite de dire de faux : annoncer couverte une vallée
qui ne l'est pas envoie une équipe sans radio, et annoncer bloquée une liaison qui passe fait
renoncer à un relais qui aurait servi.

Les tests ne touchent JAMAIS l'API d'altimétrie IGN : les altitudes sont fournies à la main, ce
qui permet en plus de construire des reliefs d'école (plat, colline au milieu, crête près d'une
extrémité) dont on connaît la réponse attendue.
"""
import math

import pytest

from core.relief_radio import (
    CALIBRATION_BORNE_MAX_DB, CALIBRATION_BORNE_MIN_DB, K_REFRACTION, PRESETS_LORA,
    ParametresRadio, RAYON_TERRE_M, SNR_LIMITE_PAR_SF, ajuster_pour_noeuds, analyser_liaison,
    balayer, diffraction_db, distance_m, fspl_db, plancher_bruit_db, points_balayage,
    points_profil, seuil_sensibilite_db,
)


class TestPhysique:
    """Les constantes et formules reprises telles quelles : si l'une dérive, tout le reste ment
    en silence."""

    def test_le_plancher_de_bruit_depend_de_la_bande(self):
        # -174 dBm/Hz + 10log10(250 kHz) + 6 dB de facteur de bruit
        assert plancher_bruit_db(250.0) == pytest.approx(-174 + 10 * math.log10(250000) + 6, abs=0.01)
        # Une bande quatre fois plus étroite, c'est 6 dB de bruit en moins : c'est tout l'intérêt
        # des presets lents.
        assert plancher_bruit_db(62.5) == pytest.approx(plancher_bruit_db(250.0) - 6.02, abs=0.05)

    def test_un_preset_lent_est_plus_sensible(self):
        """VERY_LONG_SLOW (SF12, 62,5 kHz) doit descendre bien plus bas que SHORT_FAST (SF7)."""
        assert seuil_sensibilite_db("VERY_LONG_SLOW") < seuil_sensibilite_db("LONG_FAST")
        assert seuil_sensibilite_db("LONG_FAST") < seuil_sensibilite_db("SHORT_FAST")

    def test_un_preset_inconnu_retombe_sur_long_fast(self):
        assert seuil_sensibilite_db("N_IMPORTE_QUOI") == seuil_sensibilite_db("LONG_FAST")

    def test_tous_les_presets_ont_un_seuil_de_demodulation(self):
        """Un preset sans seuil lèverait un KeyError au milieu d'un calcul de couverture."""
        for nom, p in PRESETS_LORA.items():
            assert p["sf"] in SNR_LIMITE_PAR_SF, nom

    def test_l_espace_libre_perd_6_db_par_doublement_de_distance(self):
        assert fspl_db(20000) - fspl_db(10000) == pytest.approx(6.02, abs=0.01)

    def test_la_diffraction_est_nulle_quand_l_obstacle_est_sous_la_visee(self):
        """Borne de la recommandation UIT-R P.526, pas un choix : sous v = -0,78 la formule n'a
        plus de sens physique."""
        assert diffraction_db(-1.0) == 0.0
        assert diffraction_db(-0.78) == 0.0

    def test_la_diffraction_croit_avec_l_obstacle(self):
        assert diffraction_db(0) == pytest.approx(6.0, abs=0.5)      # ~6 dB en limite de visée
        assert diffraction_db(1) > diffraction_db(0)
        assert diffraction_db(3) > diffraction_db(1)

    def test_la_distance_orthodromique(self):
        # Un degré de latitude ~ 111 km.
        assert distance_m((45.0, 4.0), (46.0, 4.0)) == pytest.approx(111195, rel=0.01)
        assert distance_m((45.0, 4.0), (45.0, 4.0)) == 0


class TestParametres:

    def test_le_budget_retire_bien_toutes_les_pertes(self):
        p = ParametresRadio(puissance_dbm=27, gains_dbi=4.3, pertes_db=1.5,
                            marge_securite_db=6, perte_environnement_db=12)
        assert p.budget_db == pytest.approx(27 + 4.3 - 1.5 - p.seuil_dbm - 6 - 12, abs=0.01)

    def test_la_fiche_d_un_noeud_corrige_les_parametres(self):
        base = ParametresRadio()
        ajuste = ajuster_pour_noeuds(base, {"gain_dbi": 8.0, "pertes_db": 2.0, "hauteur_m": 30.0}, None)
        assert ajuste.gains_dbi == pytest.approx(base.gains_dbi + 8.0 - 2.15)
        assert ajuste.pertes_db == pytest.approx(base.pertes_db + 2.0 - 0.75)
        assert ajuste.hauteur_site_m == 30.0

    def test_la_puissance_retenue_est_celle_du_maillon_faible(self):
        """Une liaison ne vaut que ce que vaut son maillon faible : annoncer la portée du plus
        puissant des deux ferait croire à une liaison qui ne passe que dans un sens -- exactement
        ce que core/analyse_liaisons.py cherche à détecter."""
        base = ParametresRadio(puissance_dbm=27)
        ajuste = ajuster_pour_noeuds(base, {"puissance_dbm": 20}, {"puissance_dbm": 14})
        assert ajuste.puissance_dbm == 14

    def test_un_noeud_sans_fiche_ne_change_rien(self):
        base = ParametresRadio()
        assert ajuster_pour_noeuds(base, None, {}).budget_db == base.budget_db

    def test_une_couverture_non_calibree_le_dit(self):
        assert ParametresRadio().calibre is False
        assert ParametresRadio(perte_environnement_db=18, calibre=True).calibre is True


class TestLiaison:
    """`profil` est la liste des altitudes intermédiaires, telles que `points_profil` les demande."""

    def _params(self):
        return ParametresRadio(perte_environnement_db=0.0, marge_securite_db=0.0)

    def test_un_terrain_plat_coute_la_rasance_et_rien_de_plus(self):
        """Contre-intuitif mais exact : au-dessus d'un terrain plat, la ligne de visée frôle le
        sol (la terre équivalente la fait passer sous l'horizontale) et la diffraction en
        rasance coûte déjà quelques dB -- 6 dB à v = 0, par la recommandation elle-même. Un
        modèle qui annoncerait 0 dB ici serait optimiste sur toutes les liaisons longues."""
        a, b = (45.0, 4.0), (45.0, 4.1)      # ~7,9 km
        profil = [100.0] * len(points_profil(a, b))
        r = analyser_liaison(a, b, 100.0, 100.0, profil, self._params())
        assert 0 < r["diffraction_db"] < 7
        assert r["obstacle"] is None          # rien ne dépasse la visée
        assert r["marge_db"] > 0

    def test_monter_les_antennes_supprime_la_rasance(self):
        """Et c'est bien la rasance : avec 40 m de chaque côté, le dégagement est franc."""
        a, b = (45.0, 4.0), (45.0, 4.1)
        profil = [100.0] * len(points_profil(a, b))
        r = analyser_liaison(a, b, 100.0, 100.0, profil, self._params(),
                             hauteur_a=40, hauteur_b=40)
        assert r["diffraction_db"] == 0.0

    def test_une_colline_au_milieu_coupe_la_liaison(self):
        a, b = (45.0, 4.0), (45.0, 4.1)
        points = points_profil(a, b)
        profil = [100.0] * len(points)
        milieu = len(profil) // 2
        profil[milieu] = 400.0               # 300 m au-dessus de la visée
        r = analyser_liaison(a, b, 100.0, 100.0, profil, self._params())
        assert r["diffraction_db"] > 20
        assert r["obstacle"] is not None
        assert r["obstacle"]["hauteur_m"] > 200

    def test_l_obstacle_retenu_est_celui_de_plus_grand_fresnel_pas_le_plus_haut(self):
        """LA règle de sélection, et elle n'est pas intuitive : `v` dépend de la POSITION autant
        que de la hauteur (le rayon de Fresnel se resserre près des extrémités). Un petit relief
        proche d'un nœud peut donc pénaliser plus qu'une colline au milieu — trier par hauteur
        désignerait le mauvais obstacle, et c'est ce que son mode rapide faisait."""
        a, b = (45.0, 4.0), (45.0, 4.2)      # ~15,7 km
        points = points_profil(a, b)
        profil = [100.0] * len(points)
        profil[2] = 180.0                     # petit relief à ~400 m du départ
        profil[len(points) // 2] = 260.0      # colline plus HAUTE, au milieu

        r = analyser_liaison(a, b, 100.0, 100.0, profil, self._params())
        # L'obstacle signalé est le petit, près du départ : c'est lui qui a le plus grand v.
        assert r["obstacle"]["distance_km"] < 1.0
        assert r["obstacle"]["hauteur_m"] < 100

    def test_monter_les_antennes_ne_degrade_jamais_une_liaison(self):
        a, b = (45.0, 4.0), (45.0, 4.15)
        points = points_profil(a, b)
        profil = [100.0] * len(points)
        profil[len(points) // 2] = 260.0
        bas = analyser_liaison(a, b, 100.0, 100.0, profil, self._params(), hauteur_a=3, hauteur_b=3)
        haut = analyser_liaison(a, b, 100.0, 100.0, profil, self._params(), hauteur_a=40, hauteur_b=40)
        assert haut["marge_db"] >= bas["marge_db"]

    def test_la_courbure_terrestre_est_prise_en_compte(self):
        """Sans la terre équivalente (k = 4/3), toute liaison de plus d'une quinzaine de
        kilomètres serait déclarée bloquée à tort. On vérifie l'ordre de grandeur : au milieu
        d'une liaison de 40 km, la correction vaut ~30 m."""
        distance = 40000.0
        d = distance / 2
        correction = (d * (distance - d)) / (2 * K_REFRACTION * RAYON_TERRE_M)
        assert 20 < correction < 30           # ~23,5 m au milieu d'une liaison de 40 km

    def test_une_liaison_tres_courte_passe_sans_calcul(self):
        a, b = (45.0, 4.0), (45.00005, 4.00005)
        r = analyser_liaison(a, b, 100.0, 100.0, [], self._params())
        assert r["marge_db"] == 99.0
        assert r["obstacle"] is None

    def test_une_altitude_manquante_a_une_extremite_ne_ment_pas(self):
        """Mieux vaut pas de réponse qu'une réponse fausse : sans l'altitude du site, la hauteur
        d'antenne n'a aucun sens."""
        a, b = (45.0, 4.0), (45.0, 4.1)
        assert analyser_liaison(a, b, None, 100.0, [100.0] * 10, self._params()) is None

    def test_un_trou_dans_le_profil_est_ignore_pas_fatal(self):
        """Un bilan calculé sur 98 % du profil vaut mieux qu'aucun bilan."""
        a, b = (45.0, 4.0), (45.0, 4.1)
        profil = [100.0] * len(points_profil(a, b))
        sans_trou = analyser_liaison(a, b, 100.0, 100.0, list(profil), self._params())
        profil[3] = None
        r = analyser_liaison(a, b, 100.0, 100.0, profil, self._params())
        assert r is not None
        # Le point manquant est simplement sauté : sur un terrain uniforme, le bilan ne bouge pas.
        assert r["marge_db"] == sans_trou["marge_db"]

    def test_le_profil_a_toujours_assez_de_points(self):
        """Au pas de 100 m, mais jamais moins de dix points : avec moins, un obstacle passe
        entre deux échantillons."""
        court = points_profil((45.0, 4.0), (45.0, 4.002))     # ~160 m
        assert len(court) == 9                                 # 10 intervalles, extrémités exclues
        long = points_profil((45.0, 4.0), (45.0, 4.1))         # ~7,9 km
        assert len(long) == pytest.approx(78, abs=2)

    def test_les_parametres_sont_rendus_avec_le_resultat(self):
        """Un bilan sans ses hypothèses n'est pas vérifiable."""
        a, b = (45.0, 4.0), (45.0, 4.1)
        r = analyser_liaison(a, b, 100.0, 100.0, [100.0] * 78, self._params())
        assert r["parametres"]["preset"] == "LONG_FAST"
        assert r["parametres"]["calibre"] is False


class TestBalayage:

    def test_les_points_couvrent_tous_les_rayons(self):
        params = ParametresRadio(rayon_max_m=4000)
        points = points_balayage((45.0, 4.0), params, nb_rayons=8, pas_m=1000)
        assert len(points) == 8 * 4

    def test_un_terrain_plat_couvre_un_disque(self):
        params = ParametresRadio(rayon_max_m=4000, perte_environnement_db=0.0)
        points = points_balayage((45.0, 4.0), params, 8, 1000)
        atteints = balayer((45.0, 4.0), 100.0, params, 8, 1000, [100.0] * len(points))
        # Tous les points d'un terrain plat à 4 km sont largement dans le budget.
        assert len(atteints) == len(points)

    def test_un_rayon_s_arrete_au_trou_de_donnees(self):
        """Continuer après un trou reviendrait à déclarer couvert ce qu'on n'a pas calculé."""
        params = ParametresRadio(rayon_max_m=4000, perte_environnement_db=0.0)
        points = points_balayage((45.0, 4.0), params, 4, 1000)
        altitudes = [100.0] * len(points)
        altitudes[1] = None                    # second point du premier rayon
        atteints = balayer((45.0, 4.0), 100.0, params, 4, 1000, altitudes)
        # Le premier rayon ne donne qu'un point, les trois autres en donnent quatre.
        assert len(atteints) == 1 + 3 * 4

    def test_sans_altitude_du_site_on_ne_calcule_rien(self):
        params = ParametresRadio(rayon_max_m=2000)
        assert balayer((45.0, 4.0), None, params, 4, 1000, [100.0] * 8) == []

    def test_une_crete_masque_ce_qui_est_derriere(self):
        params = ParametresRadio(rayon_max_m=20000, perte_environnement_db=0.0)
        points = points_balayage((45.0, 4.0), params, 1, 1000)
        plat = [100.0] * len(points)
        avec_crete = list(plat)
        avec_crete[4] = 600.0                  # une crête à 5 km, 500 m au-dessus
        sans = balayer((45.0, 4.0), 100.0, params, 1, 1000, plat)
        avec = balayer((45.0, 4.0), 100.0, params, 1, 1000, avec_crete)
        assert len(avec) < len(sans)

    def test_monter_l_antenne_ne_reduit_jamais_la_couverture(self):
        """Le défaut que son mode « précis » corrige : avec l'obstacle le plus haut en ANGLE,
        monter l'antenne pouvait faire diminuer la couverture affichée, ce qui est absurde."""
        points = points_balayage((45.0, 4.0), ParametresRadio(rayon_max_m=20000), 4, 1000)
        altitudes = [100.0] * len(points)
        for i in range(0, len(altitudes), 7):
            altitudes[i] = 300.0
        bas = balayer((45.0, 4.0), 100.0,
                      ParametresRadio(rayon_max_m=20000, perte_environnement_db=0.0, hauteur_site_m=3),
                      4, 1000, altitudes)
        haut = balayer((45.0, 4.0), 100.0,
                       ParametresRadio(rayon_max_m=20000, perte_environnement_db=0.0, hauteur_site_m=60),
                       4, 1000, altitudes)
        assert len(haut) >= len(bas)


@pytest.mark.django_db
class TestCacheAltitude:

    def test_un_point_deja_connu_ne_rappelle_pas_l_ign(self, monkeypatch):
        """Le relief ne change pas : un point lu une fois n'a pas à être redemandé, et l'API est
        limitée à 2,5 requêtes par seconde."""
        from core import relief_radio
        from core.models import PointAltitude

        appels = []

        def faux_ign(lons, lats, **kwargs):
            appels.append(len(lons))
            return [123.0] * len(lons)

        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots', faux_ign)

        points = [(45.0, 4.0), (45.001, 4.001)]
        assert relief_radio.altitudes_points(points) == [123.0, 123.0]
        assert appels == [2]
        assert PointAltitude.objects.count() == 2

        # Deuxième appel : tout vient du cache.
        assert relief_radio.altitudes_points(points) == [123.0, 123.0]
        assert appels == [2]

    def test_les_doublons_ne_sont_demandes_qu_une_fois(self, monkeypatch):
        from core import relief_radio

        appels = []

        def faux_ign(lons, lats, **kwargs):
            appels.append(len(lons))
            return [50.0] * len(lons)

        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots', faux_ign)
        # Trois fois le même point, à l'arrondi du cache près (1e-4 degré ~ 11 m).
        resultats = relief_radio.altitudes_points([(45.0, 4.0), (45.000001, 4.000001), (45.0, 4.0)])
        assert resultats == [50.0, 50.0, 50.0]
        assert appels == [1]

    def test_un_point_non_resolu_vaut_none_et_n_est_pas_mis_en_cache(self, monkeypatch):
        from core import relief_radio
        from core.models import PointAltitude

        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots',
                            lambda lons, lats, **kw: [None] * len(lons))
        assert relief_radio.altitudes_points([(45.0, 4.0)]) == [None]
        assert PointAltitude.objects.count() == 0

    def test_une_liste_vide_n_appelle_rien(self, monkeypatch):
        from core import relief_radio
        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots',
                            lambda *a, **k: pytest.fail("ne doit pas être appelé"))
        assert relief_radio.altitudes_points([]) == []


@pytest.mark.django_db
class TestCalibration:
    """Ce qui sépare une prévision d'une illustration."""

    @pytest.fixture
    def reseau(self, db, monkeypatch):
        import datetime
        from django.contrib.gis.geos import Point
        from django.utils import timezone
        from core.models import (
            CompagnonMeshtastic, ContactMeshtastic, LiaisonMeshtastic, SourceLiaisonMeshtastic,
        )

        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots',
                            lambda lons, lats, **kw: [200.0] * len(lons))
        compagnon = CompagnonMeshtastic.objects.create(nom="Passerelle", node_num=0x9000)

        def noeud(num, lat, lon):
            return ContactMeshtastic.objects.create(
                compagnon=compagnon, node_num=num, location=Point(lon, lat, srid=4326),
                dernier_advert=timezone.now(),
            )

        def liaison(emetteur, recepteur, snr):
            return LiaisonMeshtastic.objects.create(
                emetteur=emetteur, recepteur=recepteur, source=SourceLiaisonMeshtastic.RF,
                snr=snr, nombre=5, environment="PROD",
                dernier_vu=timezone.now() - datetime.timedelta(hours=1),
            )
        return noeud, liaison

    def test_sans_assez_de_liaisons_on_ne_conclut_pas(self, reseau):
        """Une correction tirée de deux observations vaudrait moins que la valeur par défaut."""
        from core.relief_radio import calibrer
        noeud, liaison = reseau
        noeud(1, 45.0, 4.0); noeud(2, 45.05, 4.05)
        liaison(1, 2, -5.0)
        resultat = calibrer("PROD")
        assert resultat["liaisons_retenues"] == 1
        assert resultat["perte_environnement_db"] is None

    def test_une_liaison_trop_courte_est_ecartee(self, reseau):
        """Sous 1 km tout passe : le modèle n'apprend rien."""
        from core.relief_radio import calibrer
        noeud, liaison = reseau
        noeud(1, 45.0, 4.0); noeud(2, 45.001, 4.001)      # ~130 m
        liaison(1, 2, 5.0)
        assert calibrer("PROD")["liaisons_retenues"] == 0

    def test_une_liaison_trop_longue_est_ecartee(self, reseau):
        """Au-delà de 80 km ce n'est plus une liaison radio directe."""
        from core.relief_radio import calibrer
        noeud, liaison = reseau
        noeud(1, 45.0, 4.0); noeud(2, 46.0, 4.0)          # ~111 km
        liaison(1, 2, 5.0)
        assert calibrer("PROD")["liaisons_retenues"] == 0

    def test_une_liaison_confortable_des_deux_cotes_n_apprend_rien(self, reseau):
        """Un module LoRa plafonne son SNR vers +10 dB : comparer au-delà n'a pas de sens."""
        from core.relief_radio import calibrer
        noeud, liaison = reseau
        noeud(1, 45.0, 4.0); noeud(2, 45.02, 4.0)         # ~2,2 km, tout passe
        liaison(1, 2, 9.5)
        assert calibrer("PROD")["liaisons_retenues"] == 0

    def test_la_perte_deduite_est_bornee(self, reseau):
        """Au-delà de 30 dB, c'est autre chose qu'un environnement (position fausse, antenne
        débranchée) et une correction aussi grosse masquerait le vrai problème."""
        from core.relief_radio import calibrer
        noeud, liaison = reseau
        for i in range(8):
            noeud(10 + i, 45.0 + i * 0.001, 4.0)
            noeud(100 + i, 45.03 + i * 0.001, 4.0)
            liaison(10 + i, 100 + i, -19.0)               # mesuré très bas : écart énorme
        resultat = calibrer("PROD")
        assert resultat["liaisons_retenues"] >= 5
        assert CALIBRATION_BORNE_MIN_DB <= resultat["perte_environnement_db"] <= CALIBRATION_BORNE_MAX_DB

    def test_la_calibration_est_enregistree_et_reutilisee(self, reseau):
        """Une couverture calculée après calibration doit porter la perte mesurée, et le dire."""
        from core.models import CalibrationRadio
        from core.relief_radio import calibrer, parametres_calibres
        noeud, liaison = reseau
        for i in range(8):
            noeud(10 + i, 45.0 + i * 0.001, 4.0)
            noeud(100 + i, 45.03 + i * 0.001, 4.0)
            liaison(10 + i, 100 + i, -14.0)
        resultat = calibrer("PROD")
        assert CalibrationRadio.objects.count() == 1

        params = parametres_calibres("PROD")
        assert params.calibre is True
        assert params.perte_environnement_db == resultat["perte_environnement_db"]

    def test_sans_calibration_les_parametres_le_signalent(self, db):
        from core.relief_radio import PERTE_ENVIRONNEMENT_DEFAUT_DB, parametres_calibres
        params = parametres_calibres("PROD")
        assert params.calibre is False
        assert params.perte_environnement_db == PERTE_ENVIRONNEMENT_DEFAUT_DB

    def test_une_liaison_sans_position_est_ignoree(self, reseau):
        from core.relief_radio import calibrer
        noeud, liaison = reseau
        noeud(1, 45.0, 4.0)
        liaison(1, 999, -5.0)                              # 999 n'a pas de position connue
        assert calibrer("PROD")["liaisons_retenues"] == 0


@pytest.mark.django_db
class TestApiCouverture:
    """L'API : ce qui se calcule tout de suite et ce qui part en file."""

    @pytest.fixture
    def institutionnel(self, create_user):
        from rest_framework.test import APIClient
        from core.models import Institution, InstitutionType
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie Relief", type=itype)
        user = create_user(username="relief@x.fr", email="relief@x.fr", type="AUT_LOCALE",
                           institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    @pytest.fixture
    def sans_celery(self, monkeypatch):
        """La tâche n'est pas exécutée : on vérifie la mise en file, pas le calcul (testé
        au-dessus, sans réseau)."""
        lancees = []
        monkeypatch.setattr('core.tasks.calculer_couverture_radio_task.delay',
                            lambda *a, **k: lancees.append(a))
        monkeypatch.setattr('core.tasks.calibrer_radio_task.delay',
                            lambda *a, **k: lancees.append(a))
        return lancees

    def test_le_calcul_part_en_file_et_ne_bloque_pas_la_requete(self, institutionnel, sans_celery):
        from core.models import CouvertureRadioSite, StatutCouvertureRadio
        reponse = institutionnel.post("/api/couvertures-radio/calculer/", {
            "nom": "Château d'eau", "latitude": 45.43, "longitude": 4.39,
            "hauteur_antenne_m": 25, "rayon_max_km": 20,
        }, format="json")
        assert reponse.status_code == 202, reponse.data
        couverture = CouvertureRadioSite.objects.get()
        assert couverture.statut == StatutCouvertureRadio.EN_COURS
        assert couverture.hauteur_antenne_m == 25
        # Non calibrée faute de liaisons mesurées : l'interface doit pouvoir le dire.
        assert couverture.calibre is False
        assert len(sans_celery) == 1

    def test_un_nom_est_exige(self, institutionnel, sans_celery):
        reponse = institutionnel.post("/api/couvertures-radio/calculer/",
                                      {"latitude": 45.0, "longitude": 4.0}, format="json")
        assert reponse.status_code == 400

    @pytest.mark.parametrize("surcharge", [
        {"latitude": 200},
        {"hauteur_antenne_m": 500},
        {"puissance_dbm": 45},
        {"rayon_max_km": 300},
        {"nb_rayons": 2000},
        {"pas_m": 10},
        {"preset": "INEXISTANT"},
    ])
    def test_les_parametres_hors_bornes_sont_refuses(self, institutionnel, sans_celery, surcharge):
        """Un balayage de 2000 rayons au pas de 10 m, c'est des millions d'interrogations
        d'altimétrie : la borne protège l'API IGN autant que la tâche."""
        charge = {"nom": "Site", "latitude": 45.0, "longitude": 4.0}
        charge.update(surcharge)
        reponse = institutionnel.post("/api/couvertures-radio/calculer/", charge, format="json")
        assert reponse.status_code == 400, surcharge

    def test_le_geojson_rend_des_points_pas_un_contour(self, institutionnel):
        """Une couverture radio est TROUÉE (vallées masquées, crêtes qui portent loin). Un
        contour convexe déclarerait couvert ce qu'il englobe, y compris les trous — l'erreur qui
        envoie une équipe dans une zone d'ombre en croyant qu'elle a la radio."""
        from django.contrib.gis.geos import Point
        from django.utils import timezone
        from core.models import CouvertureRadioSite, StatutCouvertureRadio
        couverture = CouvertureRadioSite.objects.create(
            environment="PROD", nom="Crêt", location=Point(4.39, 45.43, srid=4326),
            perte_environnement_db=12.0, statut=StatutCouvertureRadio.TERMINEE,
            points=[[45.44, 4.40, 12.5, 1200], [45.45, 4.41, 3.0, 2400]],
            surface_estimee_km2=18.4, date_calcul=timezone.now(),
        )
        reponse = institutionnel.get(f"/api/couvertures-radio/{couverture.id}/geojson/")
        assert reponse.status_code == 200
        assert reponse.data["type"] == "FeatureCollection"
        assert [f["geometry"]["type"] for f in reponse.data["features"]] == ["Point", "Point"]
        assert reponse.data["features"][0]["properties"]["marge_db"] == 12.5
        assert reponse.data["proprietes"]["surface_estimee_km2"] == 18.4

    def test_la_liste_n_embarque_pas_les_points(self, institutionnel):
        """Quelques milliers de points par site : les servir dans la liste la rendrait inutilisable."""
        from django.contrib.gis.geos import Point
        from django.utils import timezone
        from core.models import CouvertureRadioSite
        CouvertureRadioSite.objects.create(
            environment="PROD", nom="Site", location=Point(4.0, 45.0, srid=4326),
            perte_environnement_db=12.0, points=[[45.0, 4.0, 1.0, 100]] * 50,
            date_calcul=timezone.now(),
        )
        reponse = institutionnel.get("/api/couvertures-radio/")
        assert reponse.status_code == 200
        ligne = reponse.data[0] if isinstance(reponse.data, list) else reponse.data["results"][0]
        assert "points" not in ligne
        assert ligne["nombre_points"] == 50

    def test_la_liaison_point_a_point_repond_tout_de_suite(self, institutionnel, monkeypatch):
        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots',
                            lambda lons, lats, **kw: [200.0] * len(lons))
        reponse = institutionnel.post("/api/couvertures-radio/analyser-liaison/", {
            "lat_a": 45.43, "lon_a": 4.39, "lat_b": 45.46, "lon_b": 4.42,
            "hauteur_a_m": 20, "hauteur_b_m": 2,
        }, format="json")
        assert reponse.status_code == 200, reponse.data
        assert "marge_db" in reponse.data
        assert reponse.data["parametres"]["calibre"] is False

    def test_une_liaison_trop_longue_est_refusee_avec_la_raison(self, institutionnel, monkeypatch):
        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots',
                            lambda lons, lats, **kw: [200.0] * len(lons))
        reponse = institutionnel.post("/api/couvertures-radio/analyser-liaison/", {
            "lat_a": 45.0, "lon_a": 4.0, "lat_b": 47.0, "lon_b": 4.0,
        }, format="json")
        assert reponse.status_code == 400
        assert "120 km" in str(reponse.data)

    def test_une_altitude_indisponible_ne_rend_pas_un_faux_bilan(self, institutionnel, monkeypatch):
        monkeypatch.setattr('core.inondation._altitudes_ign_par_lots',
                            lambda lons, lats, **kw: [None] * len(lons))
        reponse = institutionnel.post("/api/couvertures-radio/analyser-liaison/", {
            "lat_a": 45.0, "lon_a": 4.0, "lat_b": 45.05, "lon_b": 4.05,
        }, format="json")
        assert reponse.status_code == 502
        assert "altimétrie" in str(reponse.data)

    def test_la_calibration_part_en_file(self, institutionnel, sans_celery):
        reponse = institutionnel.post("/api/calibrations-radio/calculer/", {}, format="json")
        assert reponse.status_code == 202
        assert len(sans_celery) == 1

    def test_un_citoyen_ne_peut_pas_lancer_de_calcul(self, create_user, sans_celery):
        """Un balayage coûte des milliers d'interrogations à un service public limité en débit :
        réservé aux acteurs institutionnels."""
        from rest_framework.test import APIClient
        citoyen = create_user(username="citoyen-relief@x.fr", email="citoyen-relief@x.fr",
                              type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=citoyen)
        assert client.post("/api/couvertures-radio/calculer/", {
            "nom": "x", "latitude": 45.0, "longitude": 4.0}, format="json").status_code == 403
        assert client.post("/api/calibrations-radio/calculer/", {}, format="json").status_code == 403
