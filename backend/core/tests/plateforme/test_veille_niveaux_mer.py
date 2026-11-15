"""Veille du territoire : niveau de la mer aux marégraphes et surcote estimée (15/11/2026).
Voir core/niveaux_mer.py. Aucun test n'appelle l'extérieur : la mer est fabriquée ici, comme
une somme d'ondes de marée connues, à laquelle on ajoute au besoin une surcote."""
import datetime
import math
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from core import niveaux_mer, sources_ouvertes
from core.models import Maregraphe

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
JOUR = datetime.timedelta(days=1)
MINUTE = datetime.timedelta(minutes=1)

BREST = {"shom_id": "3", "name": "BREST", "longitude": -4.495, "latitude": 48.383, "state": "OK", "reseau": "RONIM"}
GALETS = {"shom_id": "97", "name": "POINTE_DES_GALETS", "longitude": 55.28, "latitude": -20.93, "state": "ASYNC", "reseau": "RONIM"}
EN_PANNE = {"shom_id": "50", "name": "ROSCOFF", "longitude": -3.97, "latitude": 48.72, "state": "KO", "reseau": "RONIM"}

# Une marée de type atlantique : niveau moyen 4 m, grande onde semi-diurne lunaire, solaire, etc.
MAREE = {"M2": (2.05, 0.4), "S2": (0.75, 1.1), "N2": (0.41, 2.0), "K1": (0.06, 0.3), "O1": (0.07, 1.9), "M4": (0.05, 0.7)}


def _niveau(instant, surcote=0.0):
    heures = niveaux_mer._heures(instant)
    return 4.0 + surcote + sum(amplitude * math.cos(math.radians(niveaux_mer.ONDES[onde]) * heures - phase)
                               for onde, (amplitude, phase) in MAREE.items())


def _serie(debut, fin, pas_min=10, surcote=0.0, bruit=0.0):
    """Mesures de `debut` à `fin`. `bruit` : amplitude d'une houle régulière, en mètres."""
    mesures, instant, rang = [], debut, 0
    while instant <= fin:
        mesures.append((instant, _niveau(instant, surcote) + bruit * math.sin(rang * 1.7)))
        instant += pas_min * MINUTE
        rang += 1
    return mesures


def _corps(mesures):
    return {"data": [{"idstation": 3, "idsource": 1, "value": niveau,
                      "timestamp": instant.strftime("%Y/%m/%d %H:%M:%S")} for instant, niveau in mesures]}


@pytest.fixture(scope="module")
def ajustement():
    return niveaux_mer.ajuster(_serie(MAINTENANT - 120 * JOUR, MAINTENANT, bruit=0.05))


class TestLecture:

    def test_seuls_les_maregraphes_en_service_sont_gardes(self):
        stations = niveaux_mer.analyser_stations([BREST, GALETS, EN_PANNE, {"shom_id": "9", "state": "OK"}])

        assert set(stations) == {"3", "97"}
        assert stations["97"]["nom"] == "POINTE DES GALETS" and stations["97"]["latitude"] < -20

    def test_les_mesures_sont_lues_en_temps_universel_et_triees(self):
        mesures = niveaux_mer.analyser_observations({"data": [
            {"value": 5.69, "timestamp": "2026/11/15 19:30:00"}, {"value": 5.10, "timestamp": "2026/11/15 19:20:00"},
            {"value": 99.0, "timestamp": "2026/11/15 19:40:00"},          # sonde en défaut
            {"value": None, "timestamp": "2026/11/15 19:50:00"}, {"value": 5.0, "timestamp": "n'importe quoi"},
        ]})

        assert mesures == [(datetime.datetime(2026, 11, 15, 19, 20, tzinfo=UTC), 5.10),
                           (datetime.datetime(2026, 11, 15, 19, 30, tzinfo=UTC), 5.69)]
        assert niveaux_mer.analyser_observations({}) == []


class TestMareeCalculee:

    def test_la_maree_ajustee_retrouve_la_mer_des_jours_suivants(self, ajustement):
        """LE test de ce module : ce que l'ajustement n'a pas vu, il doit le prédire."""
        suite = _serie(MAINTENANT, MAINTENANT + 10 * JOUR, pas_min=30)

        calculee = niveaux_mer.maree_attendue(ajustement, [instant for instant, _niveau_ in suite])

        ecart_max = max(abs(c - niveau) for c, (_instant, niveau) in zip(calculee, suite))
        assert ecart_max < 0.05                       # moins de cinq centimètres, dix jours plus tard
        assert ajustement["incertitude_cm"] < 6 and ajustement["jours"] == 120

    def test_l_ajustement_garde_le_plus_haut_niveau_mesure(self, ajustement):
        assert 6.5 < ajustement["maximum_m"] < 7.6
        assert ajustement["maximum_le"].startswith("2026-")

    def test_un_historique_trop_court_ou_trop_troue_n_est_pas_ajuste(self):
        """Trente jours ne séparent pas les ondes voisines : la prédiction divergerait."""
        assert niveaux_mer.ajuster(_serie(MAINTENANT - 30 * JOUR, MAINTENANT)) is None
        assert niveaux_mer.ajuster(_serie(MAINTENANT - 120 * JOUR, MAINTENANT, pas_min=360)) is None
        assert niveaux_mer.ajuster([]) is None

    def test_une_mer_que_la_maree_n_explique_pas_n_est_pas_ajustee(self):
        """Station d'estuaire ou sonde capricieuse : mieux vaut pas d'estimation qu'une fausse."""
        capricieuse = [(instant, niveau + 0.9 * math.sin(rang * rang * 0.37))
                       for rang, (instant, niveau) in enumerate(_serie(MAINTENANT - 120 * JOUR, MAINTENANT))]

        assert niveaux_mer.ajuster(capricieuse) is None

    def test_la_surcote_est_l_ecart_a_la_maree_calculee(self, ajustement):
        recentes = _serie(MAINTENANT - 3 * 60 * MINUTE, MAINTENANT, surcote=0.62, bruit=0.05)

        estimation = niveaux_mer.estimer(ajustement, recentes, MAINTENANT)

        assert 57 <= estimation["surcote_cm"] <= 67
        assert abs(estimation["maree_attendue_m"] - _niveau(MAINTENANT)) < 0.05

    def test_une_vague_isolee_ne_fait_pas_sauter_la_surcote(self, ajustement):
        recentes = _serie(MAINTENANT - 3 * 60 * MINUTE, MAINTENANT)
        recentes[-1] = (recentes[-1][0], recentes[-1][1] + 1.5)

        assert abs(niveaux_mer.estimer(ajustement, recentes, MAINTENANT)["surcote_cm"]) <= 3

    def test_la_prochaine_pleine_mer_porte_la_surcote_du_moment(self, ajustement):
        recentes = _serie(MAINTENANT - 3 * 60 * MINUTE, MAINTENANT, surcote=0.40)

        estimation = niveaux_mer.estimer(ajustement, recentes, MAINTENANT)

        pleine_mer = estimation["pleine_mer_le"]
        assert MAINTENANT < pleine_mer <= MAINTENANT + niveaux_mer.HORIZON_PLEINE_MER
        # C'est bien un sommet de la marée : la mer est plus basse une heure avant et après.
        assert _niveau(pleine_mer) > _niveau(pleine_mer - 60 * MINUTE) and _niveau(pleine_mer) > _niveau(pleine_mer + 60 * MINUTE)
        assert abs(estimation["pleine_mer_niveau_m"] - (_niveau(pleine_mer) + 0.40)) < 0.06

    def test_sans_ajustement_il_n_y_a_pas_d_estimation(self):
        assert niveaux_mer.estimer({}, _serie(MAINTENANT - 60 * MINUTE, MAINTENANT), MAINTENANT) is None
        assert niveaux_mer.estimer({"coefficients": [0.0] * 45}, [], MAINTENANT) is None


class TestEtat:

    def _station(self, surcote, incertitude=12.0, **champs):
        valeurs = dict(code="3", niveau_m=5.0, niveau_le=MAINTENANT - 10 * MINUTE, surcote_cm=surcote,
                       ajustement={"incertitude_cm": incertitude, "coefficients": [0.0]}, referentiel_le=MAINTENANT)
        valeurs.update(champs)
        return Maregraphe(**valeurs)

    def test_les_paliers_tiennent_compte_de_l_incertitude_de_la_station(self):
        assert niveaux_mer.etat(self._station(20), MAINTENANT) == "NORMALE"
        assert niveaux_mer.etat(self._station(35), MAINTENANT) == "MARQUEE"
        assert niveaux_mer.etat(self._station(60), MAINTENANT) == "FORTE"
        # Une station moins fidèle doit montrer davantage avant d'être signalée.
        assert niveaux_mer.etat(self._station(35, incertitude=20.0), MAINTENANT) == "NORMALE"
        assert niveaux_mer.etat(self._station(60, incertitude=20.0), MAINTENANT) == "MARQUEE"
        # Une décote (mer plus basse que prévu) n'est pas un danger de submersion.
        assert niveaux_mer.etat(self._station(-70), MAINTENANT) == "NORMALE"

    def test_sans_mesure_recente_ni_ajustement_l_etat_est_inconnu(self):
        assert niveaux_mer.etat(self._station(60, niveau_le=MAINTENANT - 5 * 60 * MINUTE), MAINTENANT) == "INCONNUE"
        assert niveaux_mer.etat(self._station(None), MAINTENANT) == "INCONNUE"
        assert niveaux_mer.etat(self._station(60, ajustement={}), MAINTENANT) == "INCONNUE"


def _service(stations=(BREST, GALETS), surcote=0.0, pannes=()):
    """Faux service du Shom : la liste, ou les mesures de la période demandée."""
    appels = []

    def repondre(adresse, params=None, **_options):
        appels.append((adresse, params))
        if any(panne in adresse for panne in pannes):
            raise requests.ConnectionError("refusée")
        reponse = mock.Mock(status_code=200, raise_for_status=lambda: None)
        if adresse == niveaux_mer.URL_STATIONS:
            reponse.json = lambda: list(stations)
            return reponse
        debut = datetime.datetime.strptime(params["dtStart"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        fin = datetime.datetime.strptime(params["dtEnd"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        recent = fin - debut <= datetime.timedelta(hours=4)
        mesures = _serie(debut, fin, pas_min=params.get("interval") or 10, surcote=surcote if recent else 0.0)
        reponse.json = lambda: _corps(mesures)
        return reponse

    repondre.appels = appels
    return repondre


@pytest.fixture(autouse=True)
def _sans_pause(monkeypatch):
    monkeypatch.setattr(niveaux_mer, "PAUSE_ENTRE_STATIONS_S", 0)


@pytest.mark.django_db
class TestReleve:

    def test_la_source_est_inscrite_au_releve_planifie(self):
        source = sources_ouvertes.SOURCES["NIVEAUX_MER"]

        assert source.relever is niveaux_mer.relever and "Shom" in source.attribution

    def test_premier_passage_niveaux_copies_puis_maree_ajustee(self):
        service = _service()
        with mock.patch("core.niveaux_mer.requests.get", side_effect=service):
            assert niveaux_mer.relever(MAINTENANT) == 2

        brest = Maregraphe.objects.get(pk="3")
        assert brest.nom == "BREST" and brest.niveau_le == MAINTENANT
        assert abs(brest.niveau_m - _niveau(MAINTENANT)) < 0.01
        # Au premier passage la marée n'était pas encore ajustée : pas de surcote, mais
        # l'ajustement vient d'être fait pour le passage suivant.
        assert brest.surcote_cm is None and brest.ajustement["jours"] == 180 and brest.ajuste_le == MAINTENANT
        # Tout part vers le service du Shom, une station à la fois, sans rien qui désigne un lieu.
        assert all(adresse.startswith("https://services.data.shom.fr/maregraphie/") for adresse, _p in service.appels)

    def test_au_passage_suivant_la_surcote_est_estimee(self):
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service()):
            niveaux_mer.relever(MAINTENANT)
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service(surcote=0.55)) as appel:
            niveaux_mer.relever(MAINTENANT + 30 * MINUTE)

        brest = Maregraphe.objects.get(pk="3")
        assert 52 <= brest.surcote_cm <= 58 and niveaux_mer.etat(brest, MAINTENANT + 30 * MINUTE) == "FORTE"
        assert brest.pleine_mer_le > MAINTENANT + 30 * MINUTE
        # Déjà ajustées, les stations ne redemandent pas six mois d'historique : liste non
        # relue (moins d'un jour), une demande de mesures par station.
        assert appel.call_count == 2

    def test_l_ajustement_est_etale_sur_plusieurs_passages(self, monkeypatch):
        monkeypatch.setattr(niveaux_mer, "AJUSTEMENTS_PAR_PASSAGE", 1)
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service()):
            niveaux_mer.relever(MAINTENANT)
            assert Maregraphe.objects.exclude(ajuste_le=None).count() == 1
            niveaux_mer.relever(MAINTENANT + 30 * MINUTE)

        assert Maregraphe.objects.exclude(ajuste_le=None).count() == 2

    def test_un_maregraphe_en_panne_ne_fait_pas_perdre_les_autres(self):
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service(pannes=("/json/97",))):
            assert niveaux_mer.relever(MAINTENANT) == 1

        assert Maregraphe.objects.get(pk="3").niveau_m is not None
        assert Maregraphe.objects.get(pk="97").niveau_m is None

    def test_si_aucun_maregraphe_ne_repond_le_releve_est_en_echec(self):
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service(pannes=("/observation/",))):
            with pytest.raises(ValueError, match="aucun marégraphe"):
                niveaux_mer.relever(MAINTENANT)

    def test_un_maregraphe_sorti_du_service_disparait(self):
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service()):
            niveaux_mer.relever(MAINTENANT)
        with mock.patch("core.niveaux_mer.requests.get", side_effect=_service(stations=(BREST,))):
            niveaux_mer.relever(MAINTENANT + 25 * 60 * MINUTE)

        assert list(Maregraphe.objects.values_list("code", flat=True)) == ["3"]
        assert Maregraphe.objects.get(pk="3").ajustement        # l'ajustement survit à la relecture


@pytest.mark.django_db
class TestLectureParLesEcrans:

    def _station(self, code, nom, longitude, latitude, surcote, **champs):
        valeurs = dict(code=code, nom=nom, location=Point(longitude, latitude, srid=4326),
                       referentiel_le=timezone.now(), niveau_m=5.2, niveau_le=timezone.now() - 10 * MINUTE,
                       maree_attendue_m=4.8, surcote_cm=surcote, pleine_mer_le=timezone.now() + 180 * MINUTE,
                       pleine_mer_niveau_m=7.1, ajuste_le=timezone.now(),
                       ajustement={"coefficients": [0.0], "incertitude_cm": 12.0, "jours": 180,
                                   "maximum_m": 7.5, "maximum_le": "2026-09-29T17:40:00+00:00"})
        valeurs.update(champs)
        return Maregraphe.objects.create(**valeurs)

    def test_les_plus_fortes_surcotes_viennent_d_abord(self, api_client):
        self._station("3", "BREST", -4.495, 48.383, 12)
        self._station("5", "LE CONQUET", -4.78, 48.36, 58)
        self._station("7", "CONCARNEAU", -3.91, 47.87, 36)
        self._station("9", "SANS MAREE AJUSTEE", -4.4, 48.4, None, ajustement={}, maree_attendue_m=None)

        with mock.patch("core.niveaux_mer.requests.get") as appel:
            reponse = api_client.get(reverse("niveaux_mer"), {"lat": 48.39, "lon": -4.49, "rayon_km": 100}).json()

        appel.assert_not_called()
        assert reponse["source"].startswith("Shom")
        assert [ligne["code"] for ligne in reponse["resultats"]] == ["5", "7", "3", "9"]
        assert reponse["bilan"] == {"FORTE": 1, "MARQUEE": 1, "NORMALE": 1, "INCONNUE": 1}
        forte, sans_maree = reponse["resultats"][0], reponse["resultats"][3]
        assert forte["etat"] == "FORTE" and forte["surcote_cm"] == 58 and forte["incertitude_cm"] == 12.0
        assert forte["pleine_mer_niveau_m"] == 7.1 and forte["maximum_m"] == 7.5 and forte["jours_ajustes"] == 180
        # Sans marée ajustée : le niveau mesuré, et rien de ce que l'on ne sait pas calculer.
        assert sans_maree["niveau_m"] == 5.2 and sans_maree["surcote_cm"] is None and sans_maree["pleine_mer_le"] is None

    def test_une_mesure_ancienne_n_est_plus_montree_comme_le_niveau_de_la_mer(self, api_client):
        self._station("3", "BREST", -4.495, 48.383, 58, niveau_le=timezone.now() - 6 * 60 * MINUTE)

        ligne = api_client.get(reverse("niveaux_mer"), {"lat": 48.39, "lon": -4.49}).json()["resultats"][0]

        assert ligne["etat"] == "INCONNUE" and ligne["niveau_m"] is None and ligne["surcote_cm"] is None

    def test_loin_de_la_mer_ou_sans_emprise_la_liste_est_vide(self, api_client):
        self._station("3", "BREST", -4.495, 48.383, 12)

        assert api_client.get(reverse("niveaux_mer"), {"lat": 45.44, "lon": 4.39}).json()["resultats"] == []
        assert api_client.get(reverse("niveaux_mer")).json()["emprise_connue"] is False
