"""Veille du territoire : qualité de l'air estimée par modèle (OpenWeather, 15/11/2026). Voir
core/qualite_air.py. Aucun test n'appelle l'extérieur."""
import datetime
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from core import qualite_air, sources_ouvertes
from core.models import PointQualiteAir

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 21, 20, tzinfo=UTC)
HEURE = datetime.timedelta(hours=1)


def _pas(instant, indice, pm2_5=4.1):
    return {"main": {"aqi": indice}, "dt": int(instant.timestamp()),
            "components": {"co": 129.7, "no": 0, "no2": 1.8, "o3": 80.25, "so2": 0.36,
                           "pm2_5": pm2_5, "pm10": 6.04, "nh3": 0.47}}


def _corps(*indices, debut=None):
    """Une heure par indice, à partir de l'heure ronde en cours."""
    debut = debut or MAINTENANT.replace(minute=0)
    return {"coord": {"lon": 2.35, "lat": 48.86},
            "list": [_pas(debut + HEURE * rang, indice) for rang, indice in enumerate(indices)]}


def _reponse(corps):
    return mock.Mock(status_code=200, json=lambda: corps, raise_for_status=lambda: None)


@pytest.fixture
def cle(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("0123456789abcdef0123456789abcdef\n")
    monkeypatch.setenv("OPENWEATHERMAP_CLE_API_FILE", str(fichier))
    monkeypatch.setattr(qualite_air, "PAUSE_ENTRE_POINTS_S", 0)


class TestListeDesPoints:

    def test_la_liste_est_fixe_et_couvre_chaque_departement_outre_mer_compris(self):
        """C'est CETTE liste qui part vers OpenWeather, la même pour tous : aucune requête ne
        dit quelle commune utilise la plateforme."""
        departements = {point[2] for point in qualite_air.POINTS}

        assert len(qualite_air.POINTS) == len({point[0] for point in qualite_air.POINTS}) == 112
        assert {"01", "2A", "2B", "42", "75", "95", "971", "972", "973", "974", "976"} <= departements
        assert all(-90 <= latitude <= 90 and -180 <= longitude <= 180
                   for _code, _nom, _departement, latitude, longitude in qualite_air.POINTS)

    def test_les_grandes_villes_y_sont_meme_quand_elles_ne_sont_pas_les_premieres_de_leur_departement(self):
        noms = {(nom, departement) for _code, nom, departement, _lat, _lon in qualite_air.POINTS}

        assert {("Paris", "75"), ("Lyon", "69"), ("Villeurbanne", "69"), ("Saint-Étienne", "42")} <= noms


class TestAnalyse:

    def test_l_etat_courant_est_l_heure_la_plus_proche_et_la_suite_fait_la_prevision(self):
        etat = qualite_air.analyser(_corps(2, 2, 3, 4), MAINTENANT)

        assert etat["indice"] == 2 and etat["mesure_le"] == MAINTENANT.replace(minute=0)
        assert etat["composants"] == {"co": 129.7, "no2": 1.8, "o3": 80.2, "so2": 0.4, "pm2_5": 4.1, "pm10": 6.0}
        assert [indice for _instant, indice in etat["prevision"]] == [2, 3, 4]
        assert etat["prevision"][0][0] == "2026-11-15T22:00:00+00:00"

    def test_la_prevision_est_bornee_a_deux_jours(self):
        etat = qualite_air.analyser(_corps(*([2] * 96)), MAINTENANT)

        # De 22 h ce soir à 21 h après-demain : quarante-huit heures, pas quatre jours.
        assert len(etat["prevision"]) == 48 and etat["prevision"][-1][0] == "2026-11-17T21:00:00+00:00"

    def test_une_reponse_vide_ou_abimee_ne_donne_pas_d_etat(self):
        assert qualite_air.analyser({}, MAINTENANT) is None
        assert qualite_air.analyser({"list": [{"dt": "hier"}, {"main": {"aqi": 9}, "dt": 1794776400}]}, MAINTENANT) is None

    def test_le_pire_des_vingt_quatre_heures_et_sa_premiere_heure(self):
        etat = qualite_air.analyser(_corps(2, 2, 4, 3, 4, 2), MAINTENANT)

        pire, quand = qualite_air.pire_a_venir(etat["prevision"], MAINTENANT)

        assert pire == 4 and quand == datetime.datetime(2026, 11, 15, 23, 0, tzinfo=UTC)
        assert qualite_air.pire_a_venir([], MAINTENANT) == (None, None)
        # Une prévision entièrement passée ne prévoit plus rien.
        assert qualite_air.pire_a_venir(etat["prevision"], MAINTENANT + 30 * HEURE) == (None, None)


@pytest.mark.django_db
class TestReleve:

    def test_la_source_est_inscrite_avec_la_mention_obligatoire(self):
        source = sources_ouvertes.SOURCES["QUALITE_AIR"]

        assert source.relever is qualite_air.relever
        assert source.attribution == "Données météo fournies par OpenWeather"

    def test_seuls_les_points_de_la_liste_sont_demandes(self, cle):
        with mock.patch("core.qualite_air.requests.get", return_value=_reponse(_corps(2, 3))) as appel:
            assert qualite_air.relever(MAINTENANT) == 112

        demandes = {(a.kwargs["params"]["lat"], a.kwargs["params"]["lon"]) for a in appel.call_args_list}
        assert demandes == {(latitude, longitude) for _c, _n, _d, latitude, longitude in qualite_air.POINTS}
        assert all(a.args[0] == qualite_air.URL_PREVISION for a in appel.call_args_list)
        paris = PointQualiteAir.objects.get(pk="75056")
        assert paris.nom == "Paris" and paris.indice == 2 and paris.prevision[0][1] == 3
        assert 48.8 < paris.location.y < 48.9

    def test_un_point_en_panne_ne_fait_pas_perdre_les_autres_et_la_cle_ne_va_pas_au_journal(self, cle, caplog):
        appels = {"n": 0}

        def service(adresse, params=None, **_options):
            appels["n"] += 1
            if appels["n"] == 3:
                raise requests.HTTPError(f"401 pour {adresse}?appid={params['appid']}")
            return _reponse(_corps(2))

        with mock.patch("core.qualite_air.requests.get", side_effect=service), caplog.at_level("WARNING"):
            assert qualite_air.relever(MAINTENANT) == 111

        assert "0123456789abcdef" not in caplog.text and "HTTPError" in caplog.text

    def test_si_le_service_ne_repond_plus_le_releve_est_en_echec(self, cle):
        with mock.patch("core.qualite_air.requests.get", side_effect=requests.ConnectionError("refusée")):
            with pytest.raises(ValueError, match="112 points sur 112"):
                qualite_air.relever(MAINTENANT)

    def test_sans_cle_rien_ne_part(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENWEATHERMAP_CLE_API_FILE", str(tmp_path / "absente"))
        with mock.patch("core.qualite_air.requests.get") as appel:
            with pytest.raises(qualite_air.CleAbsente):
                qualite_air.relever(MAINTENANT)
        appel.assert_not_called()

    def test_rien_n_est_archive(self, cle):
        """La licence distingue l'usage des données de la constitution d'une base : une ligne
        par point, réécrite."""
        with mock.patch("core.qualite_air.requests.get", return_value=_reponse(_corps(2))):
            qualite_air.relever(MAINTENANT)
        with mock.patch("core.qualite_air.requests.get", return_value=_reponse(_corps(4, debut=MAINTENANT.replace(minute=0) + HEURE))):
            qualite_air.relever(MAINTENANT + HEURE)

        assert PointQualiteAir.objects.count() == 112
        assert set(PointQualiteAir.objects.values_list("indice", flat=True)) == {4}


@pytest.mark.django_db
class TestLecture:

    def _point(self, code, nom, longitude, latitude, indice, **champs):
        maintenant = timezone.now()
        valeurs = dict(code=code, nom=nom, departement=code[:2], location=Point(longitude, latitude, srid=4326),
                       indice=indice, composants={"pm2_5": 4.1, "no2": 12.0}, mesure_le=maintenant - 20 * datetime.timedelta(minutes=1),
                       prevision=[[(maintenant + HEURE * rang).isoformat(), valeur] for rang, valeur in enumerate((2, 4, 3), start=1)],
                       releve_le=maintenant)
        valeurs.update(champs)
        return PointQualiteAir.objects.create(**valeurs)

    def test_le_point_le_plus_proche_est_donne_avec_sa_distance_meme_hors_du_rayon(self, api_client):
        self._point("42218", "Saint-Étienne", 4.39, 45.44, 2)
        self._point("69123", "Lyon", 4.84, 45.76, 3)

        with mock.patch("core.qualite_air.requests.get") as appel:
            reponse = api_client.get(reverse("qualite_air"), {"lat": 45.61, "lon": 4.06, "rayon_km": 10}).json()

        appel.assert_not_called()
        assert reponse["source"] == "Données météo fournies par OpenWeather"
        assert reponse["resultats"] == []                       # aucune ville de la liste à moins de 10 km
        proche = reponse["plus_proche"]
        assert proche["nom"] == "Saint-Étienne" and 25 < proche["distance_km"] < 40
        assert proche["indice"] == 2 and proche["libelle"] == "correct"
        assert proche["pire_24h"] == 4 and proche["pire_24h_libelle"] == "mauvais"
        assert reponse["libelles"]["5"] == "très mauvais"

    def test_la_carte_recoit_les_points_de_son_emprise_les_pires_d_abord(self, api_client):
        self._point("42218", "Saint-Étienne", 4.39, 45.44, 2)
        self._point("69123", "Lyon", 4.84, 45.76, 4)
        self._point("75056", "Paris", 2.35, 48.86, 5)

        reponse = api_client.get(reverse("qualite_air"), {"bbox": "4.0,45.0,5.5,46.2"}).json()

        assert [ligne["nom"] for ligne in reponse["resultats"]] == ["Lyon", "Saint-Étienne"]
        assert reponse["plus_proche"] is None                   # pas de centre : pas de « plus proche »

    def test_une_estimation_ancienne_n_est_plus_donnee_comme_l_air_qu_il_fait(self, api_client):
        self._point("42218", "Saint-Étienne", 4.39, 45.44, 4, mesure_le=timezone.now() - 6 * HEURE)

        proche = api_client.get(reverse("qualite_air"), {"lat": 45.44, "lon": 4.39}).json()["plus_proche"]

        assert proche["indice"] is None and proche["libelle"] == "" and proche["composants"] == {}

    def test_sans_emprise_la_reponse_est_vide(self, api_client):
        self._point("42218", "Saint-Étienne", 4.39, 45.44, 2)

        reponse = api_client.get(reverse("qualite_air")).json()

        assert reponse["emprise_connue"] is False and reponse["plus_proche"] is None and reponse["resultats"] == []
