"""Veille du territoire : antennes mobiles déclarées en panne ou en maintenance (Arcep,
15/11/2026), avec le filtre des six mois. Voir core/antennes_mobiles.py.

Aucun test n'appelle l'extérieur : le fichier est un extrait réel réduit."""
import datetime
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from core import antennes_mobiles, sources_ouvertes
from core.models import AntenneIndisponible

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
JOUR = datetime.timedelta(days=1)


def _site(operateur="Orange", station="0692290587", commune="Lyon", voix="HS", data="HS",
          raison="INT", debut="2026-11-14 08:50:00", position=(4.8425, 45.7553), **technologies):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(position)},
            "properties": {"operateur": operateur, "station_anfr": station, "commune": commune,
                           "code_insee": "69123", "voix": voix, "data": data, "raison": raison,
                           "debut": debut, **technologies}}


def _fichier(*sites):
    return {"type": "FeatureCollection", "features": list(sites)}


FICHIER = _fichier(
    _site(voix4g="HS", data4g="HS", data5g="HS", voix2g="OK"),
    _site("SFR", "0692290587", voix="OK", data="HS", raison="MAINT", debut="2026-11-10 23:00:00"),
    _site("Bouygues Telecom", "0012750001", commune="La Boisse", debut="2022-01-11 09:52:30", position=(5.034, 45.826)),
    _site("Free", None, commune="Bron", voix=None, data="OK", debut=None, position=(4.91, 45.73)),
)


def _service(par_jour):
    """Faux dépôt de l'Arcep : `par_jour` associe une date (AAAA-MM-JJ) à un fichier."""
    appels = []

    def repondre(adresse, **_options):
        appels.append(adresse)
        jour = next((jour for jour in par_jour if f"/{jour}/" in adresse), None)
        if jour is None:
            return mock.Mock(status_code=404, content=b"", raise_for_status=lambda: None)
        contenu = par_jour[jour]
        return mock.Mock(status_code=200, content=b"{}", json=lambda: contenu, raise_for_status=lambda: None)

    repondre.appels = appels
    return repondre


class TestAnalyse:

    def test_un_site_est_lu_avec_ses_services_et_son_debut_a_l_heure_de_paris(self):
        site = antennes_mobiles.analyser(FICHIER)["Orange|0692290587"]

        assert site["commune"] == "Lyon" and site["voix_hs"] is True and site["donnees_hs"] is True
        assert site["motif"] == "INCIDENT"
        assert site["technologies"] == {"voix4g": "HS", "data4g": "HS", "data5g": "HS", "voix2g": "OK"}
        assert site["debut"] == datetime.datetime(2026, 11, 14, 7, 50, tzinfo=UTC)       # 8 h 50 à Paris

    def test_deux_operateurs_sur_le_meme_pylone_restent_deux_sites(self):
        sites = antennes_mobiles.analyser(FICHIER)

        assert {"Orange|0692290587", "SFR|0692290587"} <= set(sites)
        assert sites["SFR|0692290587"]["motif"] == "MAINTENANCE" and sites["SFR|0692290587"]["voix_hs"] is False

    def test_un_site_sans_numero_de_station_est_garde_par_sa_position(self):
        sites = antennes_mobiles.analyser(FICHIER)

        libre = sites["Free|@45.73000,4.91000"]
        assert libre["voix_hs"] is None and libre["donnees_hs"] is False and libre["debut"] is None

    def test_une_ligne_sans_operateur_ou_sans_position_est_ignoree(self):
        sites = antennes_mobiles.analyser(_fichier(
            _site(operateur=""), {"type": "Feature", "geometry": None, "properties": {"operateur": "Orange"}},
            _site(position=(400, 45))))

        assert sites == {}


class TestGraviteEtAge:

    def _antenne(self, **champs):
        valeurs = dict(cle="Orange|1", operateur="Orange", voix_hs=True, donnees_hs=True, technologies={},
                       debut=MAINTENANT - 3 * JOUR, premiere_vue_le=MAINTENANT - JOUR)
        valeurs.update(champs)
        return AntenneIndisponible(**valeurs)

    def test_la_gravite_dit_ce_qui_est_coupe(self):
        assert antennes_mobiles.gravite(self._antenne()) == "TOTALE"
        assert antennes_mobiles.gravite(self._antenne(voix_hs=False)) == "PARTIELLE"
        assert antennes_mobiles.gravite(self._antenne(voix_hs=None, donnees_hs=None, technologies={"data5g": "HS"})) == "PARTIELLE"
        assert antennes_mobiles.gravite(self._antenne(voix_hs=False, donnees_hs=False, technologies={"voix4g": "OK"})) == "DECLAREE"

    def test_une_panne_de_plus_de_six_mois_est_ecartee(self):
        """Décision du 15/11/2026 : au-delà de six mois ce n'est plus une panne, c'est une
        déclaration oubliée."""
        assert antennes_mobiles.trop_ancienne(self._antenne(debut=MAINTENANT - 184 * JOUR), MAINTENANT) is True
        assert antennes_mobiles.trop_ancienne(self._antenne(debut=MAINTENANT - 182 * JOUR), MAINTENANT) is False
        assert antennes_mobiles.trop_ancienne(self._antenne(debut=datetime.datetime(2022, 1, 11, tzinfo=UTC)), MAINTENANT) is True

    def test_sans_debut_declare_l_age_se_compte_depuis_notre_premiere_vue(self):
        recente = self._antenne(debut=None, premiere_vue_le=MAINTENANT - 20 * JOUR)
        oubliee = self._antenne(debut=None, premiere_vue_le=MAINTENANT - 200 * JOUR)

        assert antennes_mobiles.depuis(recente) == MAINTENANT - 20 * JOUR
        assert antennes_mobiles.trop_ancienne(recente, MAINTENANT) is False
        assert antennes_mobiles.trop_ancienne(oubliee, MAINTENANT) is True


@pytest.mark.django_db
class TestReleve:

    def test_la_source_est_inscrite_au_releve_planifie(self):
        source = sources_ouvertes.SOURCES["ANTENNES_MOBILES"]

        assert source.relever is antennes_mobiles.relever and "Arcep" in source.attribution

    def test_le_dernier_fichier_paru_est_pris_meme_s_il_date_de_quelques_jours(self):
        """Aucun fichier le 13 ni le 14/11/2026 : celui du 12 doit être trouvé."""
        service = _service({"2026-11-12": FICHIER})
        with mock.patch("core.antennes_mobiles.requests.get", side_effect=service):
            assert antennes_mobiles.relever(MAINTENANT) == 4

        assert [adresse[-18:-8] for adresse in service.appels] == ["2026-11-15", "2026-11-14", "2026-11-13", "2026-11-12"]
        assert all(adresse.startswith("https://arcep.s3.rbx.io.cloud.ovh.net/sites-indisponibles/") for adresse in service.appels)
        lyon = AntenneIndisponible.objects.get(pk="Orange|0692290587")
        assert lyon.jour_du_fichier == datetime.date(2026, 11, 12) and lyon.premiere_vue_le == MAINTENANT
        assert lyon.voix_hs is True and 45.7 < lyon.location.y < 45.8

    def test_sans_aucun_fichier_recent_le_releve_est_en_echec(self):
        with mock.patch("core.antennes_mobiles.requests.get", side_effect=_service({})):
            with pytest.raises(ValueError, match="aucun fichier"):
                antennes_mobiles.relever(MAINTENANT)
        with mock.patch("core.antennes_mobiles.requests.get", side_effect=requests.ConnectionError("refusée")):
            with pytest.raises(requests.ConnectionError):
                antennes_mobiles.relever(MAINTENANT)

    def test_la_premiere_vue_est_gardee_et_un_site_retabli_disparait(self):
        with mock.patch("core.antennes_mobiles.requests.get", side_effect=_service({"2026-11-15": FICHIER})):
            antennes_mobiles.relever(MAINTENANT)
        lendemain = _fichier(_site(voix="OK"))          # Orange a rétabli la voix, les autres sont réparés
        with mock.patch("core.antennes_mobiles.requests.get", side_effect=_service({"2026-11-16": lendemain})):
            assert antennes_mobiles.relever(MAINTENANT + JOUR) == 1

        lyon = AntenneIndisponible.objects.get()
        assert lyon.cle == "Orange|0692290587" and lyon.voix_hs is False
        assert lyon.premiere_vue_le == MAINTENANT and lyon.jour_du_fichier == datetime.date(2026, 11, 16)


@pytest.mark.django_db
class TestLecture:

    def _antenne(self, cle, longitude, latitude, depuis_jours, **champs):
        operateur = cle.split("|")[0]
        valeurs = dict(cle=cle, operateur=operateur, commune="Lyon", location=Point(longitude, latitude, srid=4326),
                       voix_hs=True, donnees_hs=True, technologies={"data4g": "HS"}, motif="INCIDENT",
                       debut=timezone.now() - depuis_jours * JOUR, premiere_vue_le=timezone.now(),
                       jour_du_fichier=timezone.now().date(), releve_le=timezone.now())
        valeurs.update(champs)
        return AntenneIndisponible.objects.create(**valeurs)

    def test_les_pannes_recentes_sont_rendues_les_anciennes_seulement_comptees(self, api_client):
        self._antenne("Orange|1", 4.84, 45.76, 1)
        self._antenne("SFR|2", 4.90, 45.74, 12, voix_hs=False)
        self._antenne("Bouygues Telecom|3", 4.86, 45.75, 1400)          # déclarée en janvier 2022
        self._antenne("Bouygues Telecom|4", 4.87, 45.77, 1410)
        self._antenne("Orange|5", 4.85, 45.76, 300)

        with mock.patch("core.antennes_mobiles.requests.get") as appel:
            reponse = api_client.get(reverse("antennes_indisponibles"), {"lat": 45.75, "lon": 4.85, "rayon_km": 30}).json()

        appel.assert_not_called()
        assert reponse["source"].startswith("Arcep") and reponse["jour_du_fichier"] == timezone.now().date().isoformat()
        assert [ligne["cle"] for ligne in reponse["resultats"]] == ["Orange|1", "SFR|2"]
        assert reponse["par_operateur"] == {"Orange": 1, "SFR": 1}
        # Ce que le filtre a écarté est dit, opérateur par opérateur.
        assert reponse["ecartees"] == 3
        assert reponse["ecartees_par_operateur"] == {"Bouygues Telecom": 2, "Orange": 1}
        totale, partielle = reponse["resultats"]
        assert totale["gravite"] == "TOTALE" and totale["motif"] == "INCIDENT" and totale["debut_declare"] is True
        assert partielle["gravite"] == "PARTIELLE" and partielle["distance_km"] > totale["distance_km"]

    def test_on_peut_ne_demander_qu_un_operateur_sans_fausser_le_bilan(self, api_client):
        self._antenne("Orange|1", 4.84, 45.76, 1)
        self._antenne("SFR|2", 4.90, 45.74, 12)

        reponse = api_client.get(reverse("antennes_indisponibles"), {"bbox": "4.5,45.5,5.2,46.0", "operateur": "SFR"}).json()

        assert [ligne["cle"] for ligne in reponse["resultats"]] == ["SFR|2"]
        assert reponse["par_operateur"] == {"Orange": 1, "SFR": 1}

    def test_sans_debut_declare_la_date_donnee_est_celle_de_notre_premiere_vue(self, api_client):
        vue = timezone.now() - 9 * JOUR
        self._antenne("Free|@45.73000,4.91000", 4.91, 45.73, 0, debut=None, premiere_vue_le=vue)

        ligne = api_client.get(reverse("antennes_indisponibles"), {"lat": 45.75, "lon": 4.85}).json()["resultats"][0]

        assert ligne["debut_declare"] is False and ligne["depuis"].startswith(vue.strftime("%Y-%m-%dT%H:%M"))

    def test_sans_emprise_la_liste_est_vide(self, api_client):
        self._antenne("Orange|1", 4.84, 45.76, 1)

        reponse = api_client.get(reverse("antennes_indisponibles")).json()

        assert reponse["resultats"] == [] and reponse["emprise_connue"] is False and reponse["ecartees"] == 0
