"""Veille du territoire : champ de vent pour l'animation de la carte (modèle ARPEGE de
Météo-France, 15/11/2026). Voir core/vent.py. Aucun test n'appelle l'extérieur."""
import base64
import datetime
from unittest import mock

import numpy
import pytest
import requests
from django.urls import reverse
from django.utils import timezone

from core import vent, sources_ouvertes
from core.models import ChampVent
from core.tests.plateforme.test_veille_rafales import _tiff

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 21, 20, tzinfo=UTC)
HEURE = datetime.timedelta(hours=1)
LARGEUR, HAUTEUR = 231, 141              # l'emprise au dixième de degré, bornes comprises


def _grille(valeur):
    return numpy.full((HAUTEUR, LARGEUR), float(valeur))


def _fichier(valeur, **options):
    options.setdefault("ancrage", (-10.0, 53.0))
    options.setdefault("pas", 0.1)
    return _tiff(_grille(valeur), **options)


def _reponse(contenu):
    return mock.Mock(status_code=200, content=contenu, raise_for_status=lambda: None)


def _refus():
    return mock.Mock(status_code=404, content=b"<mw:fault/>", raise_for_status=lambda: None)


def _service(calculs_parus=("T12.00.00Z",), u=12.0, v=-5.0, pannes=()):
    """Faux service : rend u ou v selon le champ demandé, pour les seuls calculs parus."""
    appels = []

    def repondre(_adresse, params=None, **_options):
        demande = dict((nom, valeur) for nom, valeur in params if nom != "subset")
        temps = next(valeur for nom, valeur in params if nom == "subset" and valeur.startswith("time("))
        appels.append((demande["coverageid"], temps))
        if any(panne in temps for panne in pannes):
            raise requests.ConnectionError("refusée")
        if not any(calcul in demande["coverageid"] for calcul in calculs_parus):
            return _refus()
        return _reponse(_fichier(u if demande["coverageid"].startswith("U_") else v))

    repondre.appels = appels
    return repondre


@pytest.fixture
def cle_meteo(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("a.b.c")
    monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
    monkeypatch.setattr(vent, "PAUSE_ENTRE_GRILLES_S", 0)


class TestForme:

    def test_les_heures_voulues_vont_de_l_heure_en_cours_a_six_heures(self):
        heures = vent.echeances_voulues(MAINTENANT)

        assert heures[0] == datetime.datetime(2026, 11, 15, 21, 0, tzinfo=UTC) and len(heures) == 7
        assert heures[-1] == datetime.datetime(2026, 11, 16, 3, 0, tzinfo=UTC)

    def test_les_calculs_possibles_tombent_toutes_les_six_heures(self):
        calculs = vent.calculs_candidats(MAINTENANT)

        assert [calcul.strftime("%d %H") for calcul in calculs] == ["15 18", "15 12", "15 06", "15 00"]

    def test_le_codage_garde_le_vent_a_un_tiers_de_metre_par_seconde_pres(self):
        u, v = _grille(12.4), _grille(-7.9)
        u[0, 0], v[-1, -1] = 3.0, 31.0

        donnees = vent.coder(u, v)
        u2, v2 = vent.decoder(donnees, LARGEUR, HAUTEUR)

        assert len(donnees) == 2 * LARGEUR * HAUTEUR
        assert abs(u2[5, 5] - 12.4) < 0.17 and abs(v2[5, 5] + 7.9) < 0.17
        assert abs(u2[0, 0] - 3.0) < 0.17 and abs(v2[-1, -1] - 31.0) < 0.17      # les coins ne se mélangent pas

    def test_une_valeur_absente_vaut_le_calme_et_une_tempete_est_bornee(self):
        u, v = _grille(0.0), _grille(0.0)
        u[0, 0], u[0, 1], v[0, 2] = numpy.nan, 95.0, -95.0

        u2, v2 = vent.decoder(vent.coder(u, v), LARGEUR, HAUTEUR)

        assert abs(u2[0, 0]) < 0.17 and u2[0, 1] == 40.0 and v2[0, 2] == -40.0


class TestTelechargement:

    def test_la_demande_vise_le_modele_arpege_sur_toute_l_emprise(self, cle_meteo):
        calcul = datetime.datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
        with mock.patch("core.vent.requests.get", return_value=_reponse(_fichier(5.0))) as appel:
            vent.telecharger_composante(vent.COMPOSANTES[0], calcul, MAINTENANT.replace(minute=0))

        assert "MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WCS" in appel.call_args.args[0]
        assert appel.call_args.kwargs["headers"] == {"apikey": "a.b.c"}
        params = appel.call_args.kwargs["params"]
        assert ("coverageid", "U_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND___2026-11-15T12.00.00Z") in params
        assert [valeur for nom, valeur in params if nom == "subset"] == [
            "time(2026-11-15T21:00:00Z)", "lat(39.0,53.0)", "long(-10.0,13.0)", "height(10)"]

    def test_un_calcul_pas_encore_paru_vaut_pas_de_grille(self, cle_meteo):
        with mock.patch("core.vent.requests.get", return_value=_refus()):
            assert vent.telecharger_composante(vent.COMPOSANTES[0], MAINTENANT, MAINTENANT) is None


@pytest.mark.django_db
class TestReleve:

    def test_la_source_est_inscrite_au_releve_planifie(self):
        source = sources_ouvertes.SOURCES["VENT"]

        assert source.relever is vent.relever and source.attribution == "Météo-France"

    def test_sept_heures_sont_copiees_depuis_le_dernier_calcul_paru(self, cle_meteo):
        service = _service()
        with mock.patch("core.vent.requests.get", side_effect=service):
            assert vent.relever(MAINTENANT) == 7

        # Le calcul de 18 h n'est pas paru : une question (refusée), puis celui de 12 h.
        assert service.appels[0][0].endswith("T18.00.00Z") and service.appels[1][0].endswith("T12.00.00Z")
        champ = ChampVent.objects.order_by("echeance").first()
        assert champ.calcul == datetime.datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
        assert (champ.largeur, champ.hauteur, champ.ouest, champ.nord) == (LARGEUR, HAUTEUR, -10.0, 53.0)
        u, v = vent.decoder(bytes(champ.donnees), champ.largeur, champ.hauteur)
        assert abs(u[70, 100] - 12.0) < 0.17 and abs(v[70, 100] + 5.0) < 0.17

    def test_au_passage_suivant_rien_n_est_redemande_puis_seule_l_heure_nouvelle(self, cle_meteo):
        service = _service()
        with mock.patch("core.vent.requests.get", side_effect=service):
            vent.relever(MAINTENANT)
            premier_passage = len(service.appels)
            vent.relever(MAINTENANT + datetime.timedelta(minutes=20))
            meme_heure = len(service.appels)
            vent.relever(MAINTENANT + HEURE)

        # Même heure : la seule question est « le calcul de 18 h est-il paru ? » -- non.
        assert meme_heure == premier_passage + 1
        # Heure suivante : cette même question, puis les deux composantes de l'heure nouvelle.
        assert len(service.appels) == meme_heure + 3
        assert service.appels[-1][1] == "time(2026-11-16T04:00:00Z)"
        # L'heure passée est gardée soixante-dix minutes (on vient peut-être de la regarder) :
        # à 22 h 20, celle de 21 h est partie, et rien ne s'accumule.
        assert ChampVent.objects.count() == 7
        assert ChampVent.objects.order_by("echeance").first().echeance == datetime.datetime(2026, 11, 15, 22, 0, tzinfo=UTC)

    def test_un_nouveau_calcul_remplace_les_heures_deja_copiees(self, cle_meteo):
        with mock.patch("core.vent.requests.get", side_effect=_service()):
            vent.relever(MAINTENANT)
        with mock.patch("core.vent.requests.get", side_effect=_service(("T12.00.00Z", "T18.00.00Z"), u=20.0)):
            vent.relever(MAINTENANT + datetime.timedelta(minutes=20))

        assert set(ChampVent.objects.values_list("calcul", flat=True)) == {datetime.datetime(2026, 11, 15, 18, 0, tzinfo=UTC)}
        champ = ChampVent.objects.order_by("echeance").first()
        assert abs(vent.decoder(bytes(champ.donnees), champ.largeur, champ.hauteur)[0][0, 0] - 20.0) < 0.17

    def test_une_heure_en_panne_ne_fait_pas_perdre_les_autres(self, cle_meteo, monkeypatch):
        from core import meteo_france

        monkeypatch.setattr(meteo_france, "TENTATIVES_DE_CONNEXION", 1)
        with mock.patch("core.vent.requests.get", side_effect=_service(pannes=("T23:00:00Z",))):
            assert vent.relever(MAINTENANT) == 6

    def test_sans_aucun_calcul_le_releve_est_en_echec(self, cle_meteo):
        with mock.patch("core.vent.requests.get", side_effect=_service(calculs_parus=())):
            with pytest.raises(ValueError, match="aucun calcul"):
                vent.relever(MAINTENANT)

    def test_deux_composantes_sur_des_grilles_differentes_sont_refusees(self, cle_meteo):
        def service(_adresse, params=None, **_options):
            identifiant = dict((nom, valeur) for nom, valeur in params if nom != "subset")["coverageid"]
            return _reponse(_fichier(5.0) if identifiant.startswith("U_") else _fichier(5.0, ancrage=(-9.0, 53.0)))

        with mock.patch("core.vent.requests.get", side_effect=service):
            with pytest.raises(ValueError, match="même grille"):
                vent.relever(MAINTENANT)


@pytest.mark.django_db
class TestLecture:

    def _champ(self, echeance, u=12.0, v=-5.0):
        return ChampVent.objects.create(
            echeance=echeance, calcul=echeance - 6 * HEURE, largeur=4, hauteur=3, ouest=-10.0, nord=53.0,
            donnees=vent.coder(numpy.full((3, 4), u), numpy.full((3, 4), v)), releve_le=timezone.now())

    def test_la_liste_donne_les_heures_sans_les_valeurs(self, api_client):
        heure = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._champ(heure)
        self._champ(heure + HEURE)

        with mock.patch("core.vent.requests.get") as appel:
            reponse = api_client.get(reverse("vent_prevu")).json()

        appel.assert_not_called()
        assert len(reponse["echeances"]) == 2 and reponse["champ"] is None and reponse["source"] == "Météo-France"

    def test_une_heure_demandee_rend_son_champ_pour_l_animation(self, api_client):
        heure = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._champ(heure)

        champ = api_client.get(reverse("vent_prevu"), {"echeance": heure.isoformat()}).json()["champ"]

        assert (champ["largeur"], champ["hauteur"], champ["ouest"], champ["nord"], champ["pas"]) == (4, 3, -10.0, 53.0, 0.1)
        assert champ["vitesse_max_ms"] == 40.0
        octets = base64.b64decode(champ["donnees"])
        assert len(octets) == 24
        # Le navigateur décode ainsi : octet / 255 * 80 - 40.
        assert abs(octets[0] / 255 * 80 - 40 - 12.0) < 0.17 and abs(octets[12] / 255 * 80 - 40 + 5.0) < 0.17

    def test_une_heure_inconnue_ne_rend_pas_de_champ(self, api_client):
        self._champ(timezone.now().replace(minute=0, second=0, microsecond=0))

        assert api_client.get(reverse("vent_prevu"), {"echeance": "2020-01-01T00:00:00Z"}).json()["champ"] is None
        assert api_client.get(reverse("vent_prevu"), {"echeance": "pas une date"}).json()["champ"] is None
