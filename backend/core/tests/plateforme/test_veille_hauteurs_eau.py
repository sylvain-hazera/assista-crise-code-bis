"""Veille du territoire : hauteurs d'eau et débits mesurés en rivière (Hub'Eau, 15/11/2026).
Voir core/hauteurs_eau.py. Aucun test n'appelle l'extérieur."""
import datetime
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from core import hauteurs_eau, sources_ouvertes
from core.models import StationHydrometrique

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 19, 30, tzinfo=UTC)
HEURE = datetime.timedelta(hours=1)
MINUTE = datetime.timedelta(minutes=1)

ONDAINE = {"code_station": "K058000101", "libelle_station": "L'Ondaine à Unieux - Le Pertuiset",
           "libelle_cours_eau": "l'Ondaine", "longitude_station": 4.252086421,
           "latitude_station": 45.408578412, "code_departement": "42"}
GOYAVES = {"code_station": "1011000101", "libelle_station": "La Grande Rivière à Goyaves à Petit-Bourg",
           "libelle_cours_eau": "Grande Rivière à Goyaves", "longitude_station": -61.658989597,
           "latitude_station": 16.189402471, "code_departement": "971"}


def _obs(code, instant, valeur, grandeur="H"):
    return {"code_station": code, "date_obs": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resultat_obs": valeur, "grandeur_hydro": grandeur}


def _reponse(lignes, suivante=None):
    return mock.Mock(status_code=200, raise_for_status=lambda: None,
                     json=lambda: {"count": len(lignes), "data": lignes, "next": suivante})


def _service(observations, stations=(ONDAINE, GOYAVES)):
    """Faux Hub'Eau : rend le référentiel ou les observations selon l'adresse, note les appels."""
    appels = []

    def repondre(adresse, params=None, **_options):
        appels.append((adresse, params))
        return _reponse(list(stations) if adresse == hauteurs_eau.URL_STATIONS else list(observations))

    repondre.appels = appels
    return repondre


class TestAnalyse:

    def test_les_stations_sont_lues_outre_mer_compris(self):
        stations = hauteurs_eau.analyser_stations([ONDAINE, GOYAVES, {"code_station": "SANS", "libelle_station": "x"}])

        assert set(stations) == {"K058000101", "1011000101"}
        assert stations["1011000101"]["departement"] == "971" and stations["1011000101"]["longitude"] < -61
        assert stations["K058000101"]["cours_eau"] == "l'Ondaine"

    def test_hauteurs_et_debit_sont_ranges_par_station(self):
        mesures = hauteurs_eau.analyser_observations([
            _obs("K1", MAINTENANT, 320.0), _obs("K1", MAINTENANT - 30 * MINUTE, 301.0),
            _obs("K1", MAINTENANT - 10 * MINUTE, 1390.0, "Q"), _obs("K1", MAINTENANT - 40 * MINUTE, 1200.0, "Q"),
            _obs("K2", MAINTENANT, None), {"code_station": "K3", "date_obs": "pas une date", "resultat_obs": 1.0},
        ])

        assert list(mesures) == ["K1"]
        assert mesures["K1"]["hauteurs"] == [(MAINTENANT - 30 * MINUTE, 301.0), (MAINTENANT, 320.0)]
        assert mesures["K1"]["debit"] == (MAINTENANT - 10 * MINUTE, 1390.0)        # le plus récent


class TestHistoriqueEtTendance:

    def test_l_historique_s_allonge_s_eclaircit_et_oublie_le_passe(self):
        ancien = [[(MAINTENANT - 8 * HEURE).isoformat(), 100.0], [(MAINTENANT - 2 * HEURE).isoformat(), 200.0]]
        nouvelles = [(MAINTENANT - 20 * MINUTE, 230.0), (MAINTENANT - 17 * MINUTE, 232.0),
                     (MAINTENANT - 5 * MINUTE, 240.0), (MAINTENANT, 245.0)]

        historique = hauteurs_eau.fusionner_historique(ancien, nouvelles, MAINTENANT)

        # Parti : le point de huit heures. Éclairci : - 17 min (trop près de - 20 min). La
        # dernière mesure remplace sa voisine de cinq minutes plutôt que d'être perdue.
        assert [mm for _instant, mm in historique] == [200.0, 230.0, 245.0]
        assert historique[-1][0] == MAINTENANT.isoformat()

    def test_une_mesure_relue_ne_double_pas_l_historique(self):
        mesures = [(MAINTENANT - 30 * MINUTE, 300.0), (MAINTENANT, 320.0)]
        une_fois = hauteurs_eau.fusionner_historique([], mesures, MAINTENANT)

        assert hauteurs_eau.fusionner_historique(une_fois, mesures, MAINTENANT) == une_fois

    def test_la_variation_compare_a_la_mesure_la_plus_proche_d_il_y_a_une_heure(self):
        historique = [[(MAINTENANT - 185 * MINUTE).isoformat(), 1000.0], [(MAINTENANT - 65 * MINUTE).isoformat(), 1180.0],
                      [(MAINTENANT - 30 * MINUTE).isoformat(), 1300.0], [MAINTENANT.isoformat(), 1420.0]]

        assert hauteurs_eau.variation_cm(historique, HEURE, hauteurs_eau.TOLERANCE_1H) == 24.0
        assert hauteurs_eau.variation_cm(historique, 3 * HEURE, hauteurs_eau.TOLERANCE_3H) == 42.0

    def test_pas_de_variation_sans_point_de_comparaison_assez_proche(self):
        recent = [[(MAINTENANT - 10 * MINUTE).isoformat(), 300.0], [MAINTENANT.isoformat(), 320.0]]

        assert hauteurs_eau.variation_cm(recent, HEURE, hauteurs_eau.TOLERANCE_1H) is None
        assert hauteurs_eau.variation_cm([[MAINTENANT.isoformat(), 320.0]], HEURE, hauteurs_eau.TOLERANCE_1H) is None
        assert hauteurs_eau.variation_cm([], HEURE, hauteurs_eau.TOLERANCE_1H) is None

    def test_un_saut_impossible_est_un_defaut_de_sonde(self):
        sonde = [[(MAINTENANT - HEURE).isoformat(), 300.0], [MAINTENANT.isoformat(), 99999.0]]

        assert hauteurs_eau.variation_cm(sonde, HEURE, hauteurs_eau.TOLERANCE_1H) is None

    def _station(self, **champs):
        valeurs = dict(code="K1", hauteur_m=1.2, hauteur_le=MAINTENANT - 10 * MINUTE,
                       variation_1h_cm=0.0, variation_3h_cm=None, referentiel_le=MAINTENANT)
        valeurs.update(champs)
        return StationHydrometrique(**valeurs)

    def test_les_paliers_de_tendance(self):
        palier = lambda **champs: hauteurs_eau.tendance(self._station(**champs), MAINTENANT)

        assert palier(variation_1h_cm=35.0) == "HAUSSE_RAPIDE"
        assert palier(variation_1h_cm=12.0) == "HAUSSE"
        assert palier(variation_1h_cm=3.0) == "STABLE"
        assert palier(variation_1h_cm=-15.0) == "BAISSE"
        # Sans variation sur une heure, celle sur trois heures, ramenée à l'heure.
        assert palier(variation_1h_cm=None, variation_3h_cm=96.0) == "HAUSSE_RAPIDE"
        assert palier(variation_1h_cm=None, variation_3h_cm=None) == "INCONNUE"

    def test_une_mesure_ancienne_n_a_plus_de_tendance(self):
        ancienne = self._station(variation_1h_cm=40.0, hauteur_le=MAINTENANT - 5 * HEURE)

        assert hauteurs_eau.tendance(ancienne, MAINTENANT) == "INCONNUE"
        assert hauteurs_eau.tendance(self._station(hauteur_le=None), MAINTENANT) == "INCONNUE"


@pytest.mark.django_db
class TestReleve:

    OBSERVATIONS = (
        _obs("K058000101", MAINTENANT - 60 * MINUTE, 301.0), _obs("K058000101", MAINTENANT - 30 * MINUTE, 420.0),
        _obs("K058000101", MAINTENANT, 660.0), _obs("K058000101", MAINTENANT - 5 * MINUTE, 1390.0, "Q"),
        _obs("INCONNUE", MAINTENANT, 100.0),
    )

    def test_la_source_est_inscrite_au_releve_planifie(self):
        source = sources_ouvertes.SOURCES["HAUTEURS_EAU"]

        assert source.relever is hauteurs_eau.relever and "Hub'Eau" in source.attribution

    def test_stations_et_mesures_sont_copiees_avec_leur_tendance(self):
        service = _service(self.OBSERVATIONS)
        with mock.patch("core.hauteurs_eau.requests.get", side_effect=service):
            assert hauteurs_eau.relever(MAINTENANT) == 1

        assert StationHydrometrique.objects.count() == 2
        ondaine = StationHydrometrique.objects.get(pk="K058000101")
        assert ondaine.hauteur_m == 0.66 and ondaine.hauteur_le == MAINTENANT
        assert ondaine.debit_m3s == 1.39 and ondaine.variation_1h_cm == 35.9
        assert hauteurs_eau.tendance(ondaine, MAINTENANT) == "HAUSSE_RAPIDE"
        assert StationHydrometrique.objects.get(pk="1011000101").hauteur_m is None
        # Une seule question nationale, bornée dans le temps : rien ne désigne un lieu.
        adresse, params = service.appels[-1]
        assert adresse == hauteurs_eau.URL_OBSERVATIONS
        assert params["date_debut_obs"] == "2026-11-15T18:30:00" and "bbox" not in params

    def test_le_referentiel_n_est_relu_qu_une_fois_par_jour(self):
        service = _service(self.OBSERVATIONS)
        with mock.patch("core.hauteurs_eau.requests.get", side_effect=service):
            hauteurs_eau.relever(MAINTENANT)
            hauteurs_eau.relever(MAINTENANT + 20 * MINUTE)
            hauteurs_eau.relever(MAINTENANT + 25 * HEURE)

        assert [adresse for adresse, _params in service.appels].count(hauteurs_eau.URL_STATIONS) == 2

    def test_la_tendance_se_construit_de_passage_en_passage(self):
        """L'historique est gardé chez nous : la variation sur trois heures apparaît sans jamais
        redemander trois heures de mesures."""
        instants = [MAINTENANT - 3 * HEURE, MAINTENANT - 2 * HEURE, MAINTENANT - HEURE, MAINTENANT]
        for rang, instant in enumerate(instants):
            observations = [_obs("K058000101", instant, 300.0 + 100 * rang)]
            with mock.patch("core.hauteurs_eau.requests.get", side_effect=_service(observations)):
                hauteurs_eau.relever(instant)

        ondaine = StationHydrometrique.objects.get(pk="K058000101")
        assert ondaine.variation_1h_cm == 10.0 and ondaine.variation_3h_cm == 30.0
        assert len(ondaine.historique) == 4

    def test_les_pages_suivantes_sont_lues(self):
        pages = {None: _reponse([_obs("K058000101", MAINTENANT - 30 * MINUTE, 300.0)], suivante="https://hubeau.eaufrance.fr/suite"),
                 "suite": _reponse([_obs("K058000101", MAINTENANT, 330.0)])}

        def service(adresse, params=None, **_options):
            if adresse == hauteurs_eau.URL_STATIONS:
                return _reponse([ONDAINE])
            return pages["suite"] if adresse.endswith("/suite") else pages[None]

        with mock.patch("core.hauteurs_eau.requests.get", side_effect=service):
            hauteurs_eau.relever(MAINTENANT)

        assert StationHydrometrique.objects.get(pk="K058000101").hauteur_m == 0.33

    def test_une_lecture_vide_ou_en_panne_est_un_echec(self):
        with mock.patch("core.hauteurs_eau.requests.get", side_effect=_service([])):
            with pytest.raises(ValueError, match="aucune mesure"):
                hauteurs_eau.relever(MAINTENANT)
        with mock.patch("core.hauteurs_eau.requests.get", side_effect=requests.ConnectionError("refusée")):
            with pytest.raises(requests.ConnectionError):
                hauteurs_eau.relever(MAINTENANT + 25 * HEURE)

    def test_une_station_retiree_du_service_disparait(self):
        with mock.patch("core.hauteurs_eau.requests.get", side_effect=_service(self.OBSERVATIONS)):
            hauteurs_eau.relever(MAINTENANT)
        with mock.patch("core.hauteurs_eau.requests.get", side_effect=_service(self.OBSERVATIONS, stations=(ONDAINE,))):
            hauteurs_eau.relever(MAINTENANT + 25 * HEURE)

        assert list(StationHydrometrique.objects.values_list("code", flat=True)) == ["K058000101"]


@pytest.mark.django_db
class TestLecture:

    def _station(self, code, nom, longitude, latitude, variation, **champs):
        valeurs = dict(code=code, nom=nom, cours_eau="l'Ondaine", departement="42",
                       location=Point(longitude, latitude, srid=4326), referentiel_le=timezone.now(),
                       hauteur_m=0.66, hauteur_le=timezone.now() - 10 * MINUTE, debit_m3s=1.39,
                       debit_le=timezone.now() - 10 * MINUTE, variation_1h_cm=variation)
        valeurs.update(champs)
        return StationHydrometrique.objects.create(**valeurs)

    def test_ce_qui_monte_vient_d_abord(self, api_client):
        self._station("K1", "L'Ondaine à Unieux", 4.252, 45.409, 2.0)
        self._station("K2", "Le Furan à Andrézieux", 4.27, 45.52, 35.9)
        self._station("K3", "Le Gier à Rive-de-Gier", 4.61, 45.53, 14.0)
        self._station("K4", "Sonde muette", 4.30, 45.45, 50.0, hauteur_le=timezone.now() - 6 * HEURE)

        with mock.patch("core.hauteurs_eau.requests.get") as appel:
            reponse = api_client.get(reverse("hauteurs_eau"), {"lat": 45.44, "lon": 4.39, "rayon_km": 30}).json()

        appel.assert_not_called()
        assert reponse["source"].startswith("Hub'Eau")
        assert [ligne["code"] for ligne in reponse["resultats"]] == ["K2", "K3", "K1", "K4"]
        assert reponse["bilan"] == {"HAUSSE_RAPIDE": 1, "HAUSSE": 1, "STABLE": 1, "BAISSE": 0, "INCONNUE": 1}
        rapide, muette = reponse["resultats"][0], reponse["resultats"][3]
        assert rapide["tendance"] == "HAUSSE_RAPIDE" and rapide["variation_1h_cm"] == 35.9
        assert rapide["hauteur_m"] == 0.66 and rapide["debit_m3s"] == 1.39 and rapide["distance_km"] > 5
        # Une mesure de six heures n'est plus montrée comme la hauteur de l'eau.
        assert muette["tendance"] == "INCONNUE" and muette["hauteur_m"] is None and muette["variation_1h_cm"] is None

    def test_on_peut_ne_demander_que_les_hausses(self, api_client):
        self._station("K1", "L'Ondaine à Unieux", 4.252, 45.409, 2.0)
        self._station("K2", "Le Furan à Andrézieux", 4.27, 45.52, 35.9)

        reponse = api_client.get(reverse("hauteurs_eau"), {"bbox": "4.0,45.2,4.9,45.7", "en_hausse": 1}).json()

        assert [ligne["code"] for ligne in reponse["resultats"]] == ["K2"]
        assert reponse["bilan"]["STABLE"] == 1            # le bilan compte tout, la liste filtre

    def test_sans_emprise_la_liste_est_vide(self, api_client):
        self._station("K1", "L'Ondaine à Unieux", 4.252, 45.409, 2.0)

        reponse = api_client.get(reverse("hauteurs_eau")).json()

        assert reponse["resultats"] == [] and reponse["emprise_connue"] is False
