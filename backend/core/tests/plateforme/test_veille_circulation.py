"""Veille du territoire : circulation sur le réseau routier national (15/11/2026) -- vitesses et
débits des stations de comptage, état du trafic des agglomérations. Voir core/circulation.py.

Aucun test n'appelle l'extérieur : les réponses sont des extraits réels réduits."""
import datetime
import random
from unittest import mock

import pytest
import requests
from django.urls import reverse
from django.utils import timezone

from core import circulation, sources_ouvertes
from core.models import StationCirculation

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 18, 35, tzinfo=UTC)

# L'en-tête annonce `code_insee_commune`, que les lignes ne portent pas : tel que publié.
ENTETE = ("code_pme;source;source_2;code_insee_commune;axe;pr_debut;abscisse_debut;pr_fin;abscisse_fin;"
          "sens_gestionnaire;sens_cardinal;sens_migratoire;sens_giratoire;longueur;nb_voies;"
          "x_deb;y_deb;x_fin;y_fin;code_traficolor")
# A47 à Saint-Étienne : les deux sens portent les mêmes deux bouts.
A47_VERS_L_OUEST = "MYL42.a1;DIRCE;824242123;A47;42PR20D;300;42PR22D;400;1;EST_OUEST;Y;;1750;0;823248.2;6491877.0;822210.5;6490471.5;ST42"
A47_VERS_L_EST = "MYL42.a2;DIRCE;824242123;A47;42PR20G;300;42PR22G;400;1;OUEST_EST;W;;1750;0;823248.2;6491877.0;822210.5;6490471.5;ST42"
SANS_COORDONNEES = "MB333.G5;DIRA;0;A630;33PR1D;0;33PR2D;0;1;;;;0;0;;;;;BX33"
ROCADE = "MUM76.h1;DIRNO;237676517;A28;76PR91D;800;76PR94D;840;1;NORD_SUD;Y;;3035;0;569981.6;6938140.0;568217.6;6935783.5;RO76"


def _referentiel(*lignes):
    return "\n".join((ENTETE,) + (lignes or (A47_VERS_L_OUEST, A47_VERS_L_EST, SANS_COORDONNEES, ROCADE))) + "\n"


def _site(code, heure, interieur):
    return (f'<siteMeasurements><measurementSiteReference targetClass="MeasurementSiteRecord" id="{code}" version="1.0"/>'
            f"<measurementTimeDefault>{heure}</measurementTimeDefault>{interieur}</siteMeasurements>")


def _publication(*sites):
    return ('<?xml version="1.0" encoding="UTF-8"?><d2LogicalModel modelBaseVersion="2" '
            'xmlns="http://datex2.eu/schema/2/2_0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<payloadPublication xsi:type="MeasuredDataPublication" lang="fr">'
            + "".join(sites) + "</payloadPublication></d2LogicalModel>").encode()


def _mesure(code, vitesse, debit, heure="2026-11-15T19:24:00.000+01:00"):
    return _site(code, heure, (
        '<measuredValue index="0"><measuredValue><basicData xsi:type="TrafficFlow"><vehicleFlow>'
        f"<vehicleFlowRate>{debit}</vehicleFlowRate></vehicleFlow></basicData></measuredValue></measuredValue>"
        '<measuredValue index="0"><measuredValue><basicData xsi:type="TrafficSpeed"><averageVehicleSpeed>'
        f"<speed>{vitesse}</speed></averageVehicleSpeed></basicData></measuredValue></measuredValue>"))


def _etat(code, valeur, heure="2026-11-15T19:30:00+01:00"):
    return _site(code, heure, (
        '<measuredValue index="0"><measuredValue><basicData xsi:type="TrafficStatus"><trafficStatus>'
        f"<trafficStatusValue>{valeur}</trafficStatusValue></trafficStatus></basicData></measuredValue></measuredValue>"))


INDEX_AGGLOMERATIONS = ('<a href="?C=N;O=D">Name</a> <a href="/publication/">Parent Directory</a> '
                        '<a href="TraficHyrondelle/">TraficHyrondelle/</a> <a href="TraficRouen/">TraficRouen/</a>')


def _index(dossier, *heures):
    return " ".join(f'<a href="{dossier}_1_DataTRT_20261115_{heure}.xml">x</a>' for heure in heures)


def _service(mesures, etats=None, referentiel=None, pannes=()):
    """Faux serveur de fichiers : rend ce qui est demandé selon l'adresse, et note les appels."""
    etats = etats if etats is not None else {"TraficHyrondelle/": _publication(), "TraficRouen/": _publication()}
    appels = []

    def repondre(adresse, **_options):
        appels.append(adresse)
        if any(panne in adresse for panne in pannes):
            raise requests.ConnectionError("refusée")
        reponse = mock.Mock(status_code=200, raise_for_status=lambda: None)
        if adresse == circulation.URL_REFERENTIEL:
            reponse.content = (referentiel or _referentiel()).encode()
        elif adresse == circulation.URL_MESURES:
            reponse.content = mesures
        elif adresse == circulation.URL_ETATS:
            reponse.text, reponse.content = INDEX_AGGLOMERATIONS, b""
        else:
            dossier = next(nom for nom in etats if nom in adresse)
            if adresse.endswith("/"):
                reponse.text, reponse.content = _index(dossier.rstrip("/"), "192740", "193040", "190040"), b""
            else:
                assert adresse.endswith("_193040.xml"), "ce n'est pas le fichier le plus récent"
                reponse.content = etats[dossier]
        return reponse

    repondre.appels = appels
    return repondre


@pytest.fixture(autouse=True)
def _sans_pause(monkeypatch):
    monkeypatch.setattr(circulation, "PAUSE_ENTRE_FICHIERS_S", 0)


class TestReferentiel:

    def test_l_en_tete_decale_d_une_colonne_est_rattrape(self):
        stations = circulation.analyser_referentiel(_referentiel())

        a47 = stations["MYL42.a1"]
        assert a47["axe"] == "A47" and a47["sens"] == "EST_OUEST" and a47["gestionnaire"] == "DIRCE"
        assert a47["longueur_m"] == 1750 and a47["agglomeration"] == "ST42"
        assert a47["debut"] == (823248.2, 6491877.0) and a47["fin"] == (822210.5, 6490471.5)

    def test_un_en_tete_corrige_a_la_source_reste_lu(self):
        entete = ENTETE.replace("code_insee_commune;", "")
        stations = circulation.analyser_referentiel("\n".join((entete, A47_VERS_L_OUEST)))

        assert stations["MYL42.a1"]["axe"] == "A47"

    def test_une_station_sans_coordonnees_est_gardee_sans_trait(self):
        station = circulation.analyser_referentiel(_referentiel())["MB333.G5"]

        assert station["debut"] is None and station["axe"] == "A630"
        assert circulation.trace_d_une_station(station) is None
        assert circulation.cote_de_la_chaussee(station) == 0

    def test_le_trait_est_pose_en_longitude_latitude(self):
        station = circulation.analyser_referentiel(_referentiel())["MYL42.a1"]

        (lon1, lat1), (lon2, lat2) = circulation.trace_d_une_station(station).coords
        # Saint-Étienne, à l'est de la ville, et le trait va vers le sud-ouest.
        assert 4.40 < lon1 < 4.70 and 45.40 < lat1 < 45.60
        assert lon2 < lon1 and lat2 < lat1

    def test_les_deux_sens_d_une_route_ne_se_recouvrent_pas(self):
        """Mêmes deux bouts dans le référentiel : chaque sens est dessiné de son côté du trait."""
        stations = circulation.analyser_referentiel(_referentiel())

        # Le trait va vers l'ouest : le sens « EST_OUEST » le suit, il roule donc à sa droite.
        assert circulation.cote_de_la_chaussee(stations["MYL42.a1"]) == 1
        assert circulation.cote_de_la_chaussee(stations["MYL42.a2"]) == -1


class TestLectureDesFlux:

    def test_vitesse_et_debit_sont_lus_par_station(self):
        mesures = circulation.analyser_mesures(_publication(
            _mesure("MYL42.a1", 88.666664, 1420), _mesure("MYL42.a2", 8.0, 820)))

        assert mesures["MYL42.a1"]["vitesse_kmh"] == 88.7 and mesures["MYL42.a1"]["debit_veh_h"] == 1420
        assert mesures["MYL42.a2"]["mesure_le"] == datetime.datetime(2026, 11, 15, 18, 24, tzinfo=UTC)

    def test_une_vitesse_nulle_n_est_pas_un_bouchon(self):
        """Le flux note zéro pour une station qui ne mesure pas la vitesse : 1 420 véhicules
        par heure à 0 km/h, cela n'existe pas."""
        mesures = circulation.analyser_mesures(_publication(_mesure("MYL42.Y2", 0.0, 1420)))

        assert mesures["MYL42.Y2"]["vitesse_kmh"] is None and mesures["MYL42.Y2"]["debit_veh_h"] == 1420

    def test_les_etats_de_l_exploitant_sont_traduits_et_l_inconnu_n_est_pas_un_etat(self):
        etats = circulation.analyser_etats(_publication(
            _etat("A", "freeFlow"), _etat("B", "heavy"), _etat("C", "congested"),
            _etat("D", "impossible"), _etat("E", "unknown")))

        assert {code: etat for code, (etat, _heure) in etats.items()} == {
            "A": "FLUIDE", "B": "DENSE", "C": "SATURE", "D": "BLOQUE"}
        assert etats["C"][1] == datetime.datetime(2026, 11, 15, 18, 30, tzinfo=UTC)

    def test_les_dossiers_et_le_fichier_le_plus_recent_sont_reperes(self):
        assert circulation.dossiers_d_etats(INDEX_AGGLOMERATIONS) == ["TraficHyrondelle/", "TraficRouen/"]
        page = _index("TraficLyon", "150517", "193010", "192910") + ' <a href="20261114/">hier</a>'
        assert circulation.dernier_fichier(page) == "TraficLyon_1_DataTRT_20261115_193010.xml"
        assert circulation.dernier_fichier("<html>vide</html>") is None


class TestVitesseHabituelle:

    def test_l_habitude_se_pose_sur_la_vitesse_de_circulation_libre(self):
        """Une route qui roule à 90 la plupart du temps et s'encombre une mesure sur cinq :
        l'habitude apprise doit rester la vitesse libre, pas la moyenne."""
        hasard = random.Random(4)
        habituelle, comptees = None, 0
        for _ in range(4000):
            vitesse = hasard.gauss(25, 8) if hasard.random() < 0.2 else hasard.gauss(88, 5)
            habituelle, comptees = circulation.apprendre_vitesse(habituelle, comptees, max(3, vitesse), 1500)

        assert comptees == 4000 and 86 < habituelle < 97

    def test_une_mesure_sans_vitesse_ou_a_trafic_faible_n_apprend_rien(self):
        assert circulation.apprendre_vitesse(90.0, 500, None, 1500) == (90.0, 500)
        assert circulation.apprendre_vitesse(90.0, 500, 140.0, 40) == (90.0, 500)       # trois voitures la nuit
        assert circulation.apprendre_vitesse(None, 0, 72.0, 900) == (72.0, 1)


def _station(**champs):
    valeurs = dict(code="S1", axe="N88", sens="NORD_SUD", referentiel_le=MAINTENANT, vitesse_kmh=30.0,
                   debit_veh_h=1200, mesure_le=MAINTENANT - datetime.timedelta(minutes=8),
                   vitesse_habituelle_kmh=90.0, mesures_comptees=circulation.MESURES_POUR_ESTIMER)
    valeurs.update(champs)
    return StationCirculation(**valeurs)


class TestEtatAffiche:

    def test_l_etat_de_l_exploitant_prime_quand_il_est_recent(self):
        station = _station(etat="FLUIDE", etat_le=MAINTENANT - datetime.timedelta(minutes=5))

        assert circulation.etat_affiche(station, MAINTENANT) == ("FLUIDE", "OFFICIEL")

    def test_un_etat_ancien_laisse_la_place_a_l_estimation(self):
        station = _station(etat="FLUIDE", etat_le=MAINTENANT - datetime.timedelta(hours=2))

        assert circulation.etat_affiche(station, MAINTENANT) == ("SATURE", "ESTIME")       # 30 pour 90

    def test_l_estimation_compare_la_vitesse_a_l_habitude(self):
        assert circulation.etat_affiche(_station(vitesse_kmh=30.0), MAINTENANT) == ("SATURE", "ESTIME")
        assert circulation.etat_affiche(_station(vitesse_kmh=50.0), MAINTENANT) == ("DENSE", "ESTIME")
        assert circulation.etat_affiche(_station(vitesse_kmh=80.0), MAINTENANT) == ("FLUIDE", "ESTIME")

    def test_rien_n_est_estime_sans_habitude_apprise_ni_mesure_fiable(self):
        inconnu = ("INCONNU", "")
        assert circulation.etat_affiche(_station(mesures_comptees=30), MAINTENANT) == inconnu
        assert circulation.etat_affiche(_station(vitesse_habituelle_kmh=None), MAINTENANT) == inconnu
        assert circulation.etat_affiche(_station(vitesse_kmh=None), MAINTENANT) == inconnu
        assert circulation.etat_affiche(_station(debit_veh_h=40), MAINTENANT) == inconnu     # trois voitures
        ancienne = _station(mesure_le=MAINTENANT - datetime.timedelta(hours=1))
        assert circulation.etat_affiche(ancienne, MAINTENANT) == inconnu


@pytest.mark.django_db
class TestReleve:

    MESURES = _publication(_mesure("MYL42.a1", 88.0, 1420), _mesure("MYL42.a2", 8.0, 820),
                           _mesure("MB333.G5", 24.2, 2400), _mesure("INCONNUE.1", 50.0, 500))
    ETATS = {"TraficHyrondelle/": _publication(_etat("MYL42.a1", "freeFlow"), _etat("MYL42.a2", "congested")),
             "TraficRouen/": _publication(_etat("MUM76.h1", "heavy"))}

    def test_la_source_est_inscrite_au_releve_planifie(self):
        source = sources_ouvertes.SOURCES["CIRCULATION"]

        assert source.relever is circulation.relever and "Bison Futé" in source.attribution
        assert list(sources_ouvertes.SOURCES)[-1] == "RAFALES_PREVISION"      # la source lente reste dernière

    def test_stations_mesures_et_etats_sont_copies(self):
        service = _service(self.MESURES, self.ETATS)
        with mock.patch("core.circulation.requests.get", side_effect=service):
            assert circulation.relever(MAINTENANT) == 3        # la station hors référentiel n'est pas créée

        assert StationCirculation.objects.count() == 4
        est = StationCirculation.objects.get(pk="MYL42.a2")
        assert (est.vitesse_kmh, est.debit_veh_h, est.etat, est.cote) == (8.0, 820, "SATURE", -1)
        assert est.trace is not None and 45.4 < est.location.y < 45.6
        assert est.vitesse_habituelle_kmh == 8.0 and est.mesures_comptees == 1
        rocade = StationCirculation.objects.get(pk="MUM76.h1")
        assert rocade.etat == "DENSE" and rocade.vitesse_kmh is None      # un état, pas de mesure
        sans_trait = StationCirculation.objects.get(pk="MB333.G5")
        assert sans_trait.trace is None and sans_trait.location is None and sans_trait.vitesse_kmh == 24.2
        # Tout vient du serveur de fichiers de Bison Futé, et rien d'autre.
        assert all(adresse.startswith(circulation.URL_BASE) for adresse in service.appels)

    def test_le_referentiel_n_est_relu_qu_une_fois_par_jour(self):
        service = _service(self.MESURES, self.ETATS)
        with mock.patch("core.circulation.requests.get", side_effect=service):
            circulation.relever(MAINTENANT)
            circulation.relever(MAINTENANT + datetime.timedelta(minutes=10))
            circulation.relever(MAINTENANT + datetime.timedelta(hours=25))

        assert service.appels.count(circulation.URL_REFERENTIEL) == 2
        assert service.appels.count(circulation.URL_MESURES) == 3

    def test_une_mesure_relue_ne_compte_pas_deux_fois_dans_l_habitude(self):
        with mock.patch("core.circulation.requests.get", side_effect=_service(self.MESURES, self.ETATS)):
            circulation.relever(MAINTENANT)
            circulation.relever(MAINTENANT + datetime.timedelta(minutes=3))       # flux pas encore republié
        assert StationCirculation.objects.get(pk="MYL42.a1").mesures_comptees == 1

        suivantes = _publication(_mesure("MYL42.a1", 95.0, 1500, heure="2026-11-15T19:30:00.000+01:00"))
        with mock.patch("core.circulation.requests.get", side_effect=_service(suivantes, self.ETATS)):
            circulation.relever(MAINTENANT + datetime.timedelta(minutes=10))

        ouest = StationCirculation.objects.get(pk="MYL42.a1")
        assert ouest.mesures_comptees == 2 and ouest.vitesse_kmh == 95.0
        assert ouest.vitesse_habituelle_kmh == pytest.approx(88.0 + 0.5 * 0.85)

    def test_une_agglomeration_en_panne_ne_fait_pas_perdre_les_autres(self):
        service = _service(self.MESURES, self.ETATS, pannes=("TraficHyrondelle/",))
        with mock.patch("core.circulation.requests.get", side_effect=service):
            assert circulation.relever(MAINTENANT) == 3

        assert StationCirculation.objects.get(pk="MUM76.h1").etat == "DENSE"
        assert StationCirculation.objects.get(pk="MYL42.a2").etat == ""
        assert StationCirculation.objects.get(pk="MYL42.a2").vitesse_kmh == 8.0

    def test_sans_les_etats_les_vitesses_sont_quand_meme_copiees(self):
        service = _service(self.MESURES, self.ETATS, pannes=("TRAFICOLOR-DIR",))
        with mock.patch("core.circulation.requests.get", side_effect=service):
            assert circulation.relever(MAINTENANT) == 3

        assert StationCirculation.objects.get(pk="MYL42.a1").vitesse_kmh == 88.0

    def test_un_flux_de_mesures_vide_est_un_echec(self):
        with mock.patch("core.circulation.requests.get", side_effect=_service(_publication(), self.ETATS)):
            with pytest.raises(ValueError, match="aucune mesure"):
                circulation.relever(MAINTENANT)

    def test_une_station_retiree_du_referentiel_disparait(self):
        with mock.patch("core.circulation.requests.get", side_effect=_service(self.MESURES, self.ETATS)):
            circulation.relever(MAINTENANT)
        reduit = _referentiel(A47_VERS_L_OUEST)
        with mock.patch("core.circulation.requests.get",
                        side_effect=_service(self.MESURES, self.ETATS, referentiel=reduit)):
            circulation.relever(MAINTENANT + datetime.timedelta(hours=25))

        assert list(StationCirculation.objects.values_list("code", flat=True)) == ["MYL42.a1"]
        # L'habitude déjà apprise n'est pas perdue à la relecture du référentiel.
        assert StationCirculation.objects.get(pk="MYL42.a1").mesures_comptees == 1


@pytest.mark.django_db
class TestLecture:

    @pytest.fixture
    def releve(self):
        etats = {"TraficHyrondelle/": _publication(
            _etat("MYL42.a1", "freeFlow", heure=timezone.now().isoformat()),
            _etat("MYL42.a2", "congested", heure=timezone.now().isoformat())), "TraficRouen/": _publication()}
        mesures = _publication(
            _mesure("MYL42.a1", 88.0, 1420, heure=timezone.now().isoformat()),
            _mesure("MYL42.a2", 8.0, 820, heure=timezone.now().isoformat()))
        with mock.patch("core.circulation.requests.get", side_effect=_service(mesures, etats)):
            circulation.relever()

    def test_les_troncons_encombres_viennent_d_abord_avec_leur_origine(self, api_client, releve):
        with mock.patch("core.circulation.requests.get") as appel:
            reponse = api_client.get(reverse("circulation"), {"lat": 45.44, "lon": 4.39, "rayon_km": 30}).json()

        appel.assert_not_called()
        assert reponse["source"].startswith("Bison Futé") and reponse["emprise_connue"] is True
        assert reponse["bilan"] == {"BLOQUE": 0, "SATURE": 1, "DENSE": 0, "FLUIDE": 1, "INCONNU": 0}
        sature, fluide = reponse["resultats"]
        assert (sature["code"], sature["etat"], sature["origine"]) == ("MYL42.a2", "SATURE", "OFFICIEL")
        assert sature["vitesse_kmh"] == 8.0 and sature["axe"] == "A47" and sature["cote"] == -1
        assert sature["vitesse_habituelle_kmh"] is None        # pas encore apprise : pas de chiffre
        assert fluide["etat"] == "FLUIDE" and "trace" not in fluide and 10 < fluide["distance_km"] < 25

    def test_la_carte_recoit_le_trait_et_peut_ne_demander_que_les_ralentis(self, api_client, releve):
        reponse = api_client.get(reverse("circulation"), {
            "bbox": "4.0,45.2,4.9,45.7", "trace": 1, "ralentis": 1}).json()

        assert [ligne["code"] for ligne in reponse["resultats"]] == ["MYL42.a2"]
        assert reponse["bilan"]["FLUIDE"] == 1                  # le bilan compte tout, la liste filtre
        assert reponse["resultats"][0]["trace"]["type"] == "LineString"

    def test_ailleurs_ou_sans_emprise_la_liste_est_vide(self, api_client, releve):
        loin = api_client.get(reverse("circulation"), {"lat": 48.0, "lon": -4.0, "rayon_km": 10}).json()
        sans = api_client.get(reverse("circulation")).json()

        assert loin["resultats"] == [] and loin["emprise_connue"] is True
        assert sans["resultats"] == [] and sans["emprise_connue"] is False
