"""Veille du territoire : neige, verglas et grêle prévus (15/11/2026) -- le type de précipitation
de la prévision immédiate, peint par ce serveur. Voir core/precipitations_hiver.py.

Aucun test n'appelle l'extérieur : les grilles sont fabriquées ici (voir test_veille_rafales)."""
import datetime
import io
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from core import pluie, precipitations_hiver, rafales, sources_ouvertes
from core.models import ImagePrecipitationHiver, ImageRafales
from core.tests.plateforme.test_veille_rafales import (
    _colonne, _grille, _ligne, _reponse_grille, _reponse_refus, _tiff,
)

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 9, 30, tzinfo=UTC)


@pytest.fixture
def cle_meteo(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("a.b.c")
    monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
    monkeypatch.setattr(pluie, "PAUSE_ENTRE_IMAGES_S", 0)


def _bandes(*codes):
    """Grille découpée en bandes verticales de 100 colonnes, une par code."""
    grille = _grille(0.0)
    for rang, code in enumerate(codes):
        grille[:, rang * 100:(rang + 1) * 100] = code
    return grille


def _au_milieu_de_la_bande(png, rang):
    return precipitations_hiver.famille_au_point(png, 46.0, rafales.OUEST + (rang * 100 + 50) * rafales.PAS_DEGRES)


class TestPeinture:

    def test_chaque_code_va_dans_sa_famille(self):
        png = precipitations_hiver.peindre(_bandes(3, 12, 5, 6, 7, 8, 9, 10))

        familles = [_au_milieu_de_la_bande(png, rang) for rang in range(8)]
        assert familles == ["VERGLAS", "VERGLAS", "NEIGE", "NEIGE_HUMIDE", "NEIGE_HUMIDE", "GRESIL", "GRESIL", "GRELE"]

    def test_la_pluie_et_la_bruine_ne_sont_pas_peintes(self):
        """La pluie a son propre calque : celui-ci ne montre que ce qui change la conduite à tenir."""
        png = precipitations_hiver.peindre(_bandes(1, 11, 201, 0))

        assert [_au_milieu_de_la_bande(png, rang) for rang in range(4)] == ["", "", "", ""]

    def test_les_variantes_en_deux_cents_rejoignent_leur_type(self):
        """Déduction du 15/11/2026 : 205, 206 et 207 se trouvent en montagne au contact de la
        neige, 201 partout comme la pluie."""
        png = precipitations_hiver.peindre(_bandes(205, 206, 207, 203, 210))

        familles = [_au_milieu_de_la_bande(png, rang) for rang in range(5)]
        assert familles == ["NEIGE", "NEIGE_HUMIDE", "NEIGE_HUMIDE", "VERGLAS", "GRELE"]

    def test_un_code_inconnu_ou_une_valeur_absurde_n_est_pas_peint(self):
        import numpy

        grille = _bandes(193, 213, 2, 4, 999, -5)
        grille[:, 600:700] = numpy.nan

        png = precipitations_hiver.peindre(grille)

        assert [_au_milieu_de_la_bande(png, rang) for rang in range(7)] == [""] * 7

    def test_les_teintes_sont_celles_de_la_legende(self):
        from PIL import Image

        image = Image.open(io.BytesIO(precipitations_hiver.peindre(_bandes(3, 5, 6, 8, 10)))).convert("RGBA")
        milieu = image.height // 2

        for rang, (_cle, _libelle, teinte, _codes) in enumerate(precipitations_hiver.FAMILLES):
            assert image.getpixel((rang * 100 + 50, milieu)) == teinte + (255,)
        assert image.getpixel((900, milieu))[3] == 0
        legende = precipitations_hiver.legende()
        assert [famille["cle"] for famille in legende] == ["VERGLAS", "NEIGE", "NEIGE_HUMIDE", "GRESIL", "GRELE"]
        assert legende[1] == {"cle": "NEIGE", "libelle": "Neige", "couleur": "#38bdf8"}

    def test_une_chute_de_neige_se_retrouve_a_sa_place_sur_la_carte(self):
        grille = _grille(0.0)
        grille[_ligne(45.6):_ligne(45.2), _colonne(6.0):_colonne(7.0)] = 5       # les Alpes

        png = precipitations_hiver.peindre(grille)

        assert precipitations_hiver.famille_au_point(png, 45.4, 6.5) == "NEIGE"
        assert precipitations_hiver.famille_au_point(png, 45.8, 6.5) == ""
        assert precipitations_hiver.famille_au_point(png, 45.4, 7.4) == ""
        assert precipitations_hiver.famille_au_point(png, -21.1, 55.5) is None  # La Réunion


class TestTelechargement:

    def test_la_demande_vise_le_type_de_precipitation_sans_hauteur_ni_serie(self, cle_meteo):
        contenu = _tiff(_grille(0.0))
        calcul = datetime.datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(contenu)) as appel:
            assert precipitations_hiver.telecharger_grille(calcul, MAINTENANT) == contenu

        params = appel.call_args.kwargs["params"]
        assert ("coverageid", "SEVERE_PRECIPITATION_TYPE_15_MIN__GROUND_OR_WATER_SURFACE"
                              "___2026-11-15T09.00.00Z") in params
        assert [valeur for nom, valeur in params if nom == "subset"] == [
            "time(2026-11-15T09:30:00Z)", "lat(41.0,51.5)", "long(-5.5,10.0)"]

    def test_les_rafales_gardent_leur_serie_et_leur_hauteur(self, cle_meteo):
        """Les deux champs passent par le même téléchargement : l'un ne doit pas déteindre sur l'autre."""
        with mock.patch("core.rafales.requests.get", return_value=_reponse_refus()) as appel:
            assert rafales.telecharger_grille(MAINTENANT, MAINTENANT) is None

        params = appel.call_args.kwargs["params"]
        assert dict(params)["coverageid"].endswith("_PT15M") and ("subset", "height(10)") in params


@pytest.mark.django_db
class TestReleve:

    @pytest.fixture(autouse=True)
    def _peinture_rapide(self, monkeypatch):
        monkeypatch.setattr(precipitations_hiver, "preparer", lambda octets: b"png")

    def test_la_source_est_inscrite_avant_les_rafales_qui_ferment_la_marche(self):
        source = sources_ouvertes.SOURCES["PRECIPITATIONS_HIVER"]

        assert source.relever is precipitations_hiver.relever and source.attribution == "Météo-France"
        assert list(sources_ouvertes.SOURCES)[-2:] == ["PRECIPITATIONS_HIVER", "RAFALES_PREVISION"]

    def test_treize_echeances_sont_copiees_sans_toucher_aux_rafales(self, cle_meteo):
        ImageRafales.objects.create(echeance=MAINTENANT, calcul=MAINTENANT, image=b"rafales", releve_le=MAINTENANT)
        contenu = _tiff(_grille(0.0))
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(contenu)):
            assert precipitations_hiver.relever(MAINTENANT + datetime.timedelta(hours=2)) == 13

        assert ImagePrecipitationHiver.objects.count() == 13 and ImageRafales.objects.count() == 1


@pytest.mark.django_db
class TestLectures:

    def _image(self, echeance, grille):
        return ImagePrecipitationHiver.objects.create(
            echeance=echeance, calcul=echeance - datetime.timedelta(hours=1),
            image=precipitations_hiver.peindre(grille), releve_le=timezone.now())

    def test_la_liste_donne_les_echeances_les_coins_et_la_legende(self, api_client):
        echeance = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._image(echeance, _grille(5.0))

        with mock.patch("core.rafales.requests.get") as appel:
            liste = api_client.get(reverse("precipitations_hiver")).json()
            image = api_client.get(reverse("precipitations_hiver_image"), {"echeance": liste["echeances"][0]})
            absente = api_client.get(reverse("precipitations_hiver_image"), {"echeance": "2020-01-01T00:00:00Z"})

        appel.assert_not_called()
        assert liste["coins"][0] == [-5.505, 51.505] and len(liste["echeances"]) == 1
        assert [famille["cle"] for famille in liste["legende"]][:2] == ["VERGLAS", "NEIGE"]
        assert liste["ici"] is None and liste["source"] == "Météo-France"
        assert image.status_code == 200 and image.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert absente.status_code == 404

    def test_un_point_donne_recoit_ce_qui_y_est_prevu_et_le_pire(self, api_client):
        debut = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._image(debut, _grille(1.0))                                        # pluie : rien
        self._image(debut + datetime.timedelta(minutes=15), _grille(6.0))       # neige humide
        self._image(debut + datetime.timedelta(minutes=30), _grille(3.0))       # pluie verglaçante

        ici = api_client.get(reverse("precipitations_hiver"), {"lat": 45.44, "lon": 4.39}).json()["ici"]

        assert [f["famille"] for f in ici["familles"]] == ["", "NEIGE_HUMIDE", "VERGLAS"]
        assert ici["pire"] == "VERGLAS" and ici["couvert"] is True

    def test_un_point_au_sec_et_un_point_hors_de_la_metropole(self, api_client):
        self._image(timezone.now().replace(minute=0, second=0, microsecond=0), _grille(1.0))

        sec = api_client.get(reverse("precipitations_hiver"), {"lat": 45.44, "lon": 4.39}).json()["ici"]
        loin = api_client.get(reverse("precipitations_hiver"), {"lat": -21.1, "lon": 55.5}).json()["ici"]

        assert sec["pire"] == "" and sec["couvert"] is True
        assert loin["couvert"] is False and loin["familles"][0]["famille"] is None
