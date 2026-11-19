"""Veille du territoire : rafales de vent prévues (15/11/2026), peintes par ce serveur à partir
des valeurs de la prévision immédiate de Météo-France -- voir core/rafales.py.

Aucun test n'appelle l'extérieur : le fichier TIFF est fabriqué ici, tel que le service le rend
(nombres à virgule de 64 bits, sans compression, une bande par ligne)."""
import datetime
import io
import struct
from unittest import mock

import numpy
import pytest
from django.urls import reverse
from django.utils import timezone

from core import pluie, rafales, sources_ouvertes
from core.models import ImageRafales

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 9, 30, tzinfo=UTC)


def _tiff(grille, compression=1, ancrage=(-5.5, 51.5), pas=0.01, nature=3, ecart=0, desordre=False):
    """Fichier TIFF minimal portant `grille`, dans la forme observée le 15/11/2026.
    `ecart` : octets de bourrage entre deux bandes ; `desordre` : bandes rangées dans le fichier
    de la dernière à la première (forme observée le 19/11/2026, « bandes dispersées »)."""
    hauteur, largeur = grille.shape
    taille_ligne = largeur * 8
    lignes = [grille[i].astype("<f8").tobytes() for i in range(hauteur)]
    ordre_physique = list(range(hauteur))[::-1] if desordre else list(range(hauteur))
    donnees = b"".join(lignes[i] + b"\x00" * ecart for i in ordre_physique)
    rang_physique = {ligne: rang for rang, ligne in enumerate(ordre_physique)}
    etiquettes = []                     # (numéro, genre, valeurs)
    etiquettes.append((256, 3, [largeur]))
    etiquettes.append((257, 3, [hauteur]))
    etiquettes.append((258, 3, [64]))
    etiquettes.append((259, 3, [compression]))
    etiquettes.append((273, 4, None))   # positions des bandes, remplies plus bas
    etiquettes.append((278, 3, [1]))
    etiquettes.append((279, 4, [taille_ligne] * hauteur))
    etiquettes.append((339, 3, [nature]))
    etiquettes.append((33550, 12, [pas, pas, 0.0]))
    etiquettes.append((33922, 12, [0.0, 0.0, 0.0, ancrage[0], ancrage[1], 0.0]))

    codes = {3: "H", 4: "I", 12: "d"}
    debut_repertoire = 8
    fin_repertoire = debut_repertoire + 2 + 12 * len(etiquettes) + 4
    # Les valeurs trop longues pour tenir dans l'entrée sont rangées après le répertoire.
    annexes, position = [], fin_repertoire
    tailles = {}
    for numero, genre, valeurs in etiquettes:
        combien = hauteur if valeurs is None else len(valeurs)
        taille = struct.calcsize("<" + codes[genre]) * combien
        tailles[numero] = (combien, taille, position if taille > 4 else None)
        if taille > 4:
            position += taille
    debut_donnees = position
    entrees = b""
    for numero, genre, valeurs in etiquettes:
        combien, taille, ou = tailles[numero]
        if valeurs is None:
            valeurs = [debut_donnees + rang_physique[i] * (taille_ligne + ecart) for i in range(hauteur)]
        brut = struct.pack("<" + codes[genre] * combien, *valeurs)
        if ou is None:
            entrees += struct.pack("<HHI", numero, genre, combien) + brut.ljust(4, b"\x00")
        else:
            entrees += struct.pack("<HHII", numero, genre, combien, ou)
            annexes.append(brut)
    return (b"II*\x00" + struct.pack("<I", debut_repertoire) + struct.pack("<H", len(etiquettes))
            + entrees + struct.pack("<I", 0) + b"".join(annexes) + donnees)


def _grille(vitesse_ms=5.0):
    return numpy.full((rafales.HAUTEUR, rafales.LARGEUR), vitesse_ms, dtype="float64")


def _ligne(latitude):
    """Rang de la ligne de la grille qui porte cette latitude (la première est au nord)."""
    return round((rafales.NORD - latitude) / rafales.PAS_DEGRES)


def _colonne(longitude):
    return round((longitude - rafales.OUEST) / rafales.PAS_DEGRES)


@pytest.fixture(scope="module")
def tiff_calme():
    return _tiff(_grille())


def _reponse_grille(contenu):
    # Le service annonce « wmo-grib » même quand il envoie un TIFF.
    return mock.Mock(status_code=200, headers={"content-type": "application/wmo-grib"},
                     content=contenu, raise_for_status=lambda: None)


def _reponse_refus():
    return mock.Mock(status_code=404, headers={"content-type": "application/xml"},
                     content=b"<mw:fault/>", raise_for_status=lambda: None)


@pytest.fixture
def cle_meteo(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("a.b.c")
    monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
    monkeypatch.setattr(pluie, "PAUSE_ENTRE_IMAGES_S", 0)


class TestLectureDeLaGrille:

    def test_les_valeurs_sont_relues_ligne_par_ligne_du_nord_au_sud(self):
        grille = _grille()
        grille[0, 0], grille[-1, -1], grille[_ligne(45.0), _colonne(4.0)] = 31.5, 2.25, 27.0

        lue = rafales.lire_tiff(_tiff(grille))

        assert lue.shape == (rafales.HAUTEUR, rafales.LARGEUR)
        assert lue[0, 0] == 31.5 and lue[-1, -1] == 2.25
        assert lue[_ligne(45.0), _colonne(4.0)] == 27.0 and lue[10, 10] == 5.0

    def test_ce_qui_n_est_pas_un_tiff_est_refuse(self):
        with pytest.raises(ValueError, match="pas un fichier TIFF"):
            rafales.lire_tiff(b"<?xml version='1.0'?><mw:fault/>")

    def test_un_fichier_tronque_est_refuse_sans_planter(self, tiff_calme):
        with pytest.raises(ValueError):
            rafales.lire_tiff(tiff_calme[:60])

    def test_un_format_non_prevu_est_refuse_plutot_que_mal_lu(self):
        """Compression, entiers, grille d'une autre taille ou posée ailleurs : mieux vaut un
        relevé en échec qu'une carte fausse."""
        petite = numpy.zeros((10, 10))
        with pytest.raises(ValueError, match="compressé"):
            rafales.lire_tiff(_tiff(_grille(), compression=5))
        with pytest.raises(ValueError, match="nombres à virgule"):
            rafales.lire_tiff(_tiff(_grille(), nature=1))
        with pytest.raises(ValueError, match="10 x 10"):
            rafales.lire_tiff(_tiff(petite))
        with pytest.raises(ValueError, match="posée ailleurs"):
            rafales.lire_tiff(_tiff(_grille(), ancrage=(-12.0, 55.4)))
        with pytest.raises(ValueError, match="posée ailleurs"):
            rafales.lire_tiff(_tiff(_grille(), pas=0.025))


class TestPeinture:

    def _image(self, grille):
        from PIL import Image

        return Image.open(io.BytesIO(rafales.peindre(grille)))

    def test_le_vent_ordinaire_ne_dessine_rien(self):
        image = self._image(_grille(10.0))              # 36 km/h

        assert image.convert("RGBA").getextrema()[3] == (0, 0)

    def test_chaque_palier_a_sa_teinte_en_km_h(self):
        """Les valeurs arrivent en m/s : 25 m/s font 90 km/h, palier « 80 et plus »."""
        grille = _grille(0.0)
        for rang, vitesse_kmh in enumerate((45, 65, 90, 105, 125, 160)):
            grille[:, rang * 200:(rang + 1) * 200] = vitesse_kmh / 3.6
        image = self._image(grille).convert("RGBA")
        milieu = image.height // 2

        for rang, teinte in enumerate(rafales.TEINTES):
            assert image.getpixel((rang * 200 + 100, milieu))[:3] == teinte
        # Le premier palier reste à demi transparent, les suivants sont pleins.
        assert image.getpixel((100, milieu))[3] == rafales.OPACITES[0] < 255
        assert image.getpixel((500, milieu))[3] == 255
        assert image.getpixel((1400, milieu))[3] == 0           # au-delà des bandes : calme

    def test_un_seuil_est_atteint_a_la_valeur_exacte(self):
        grille = _grille(0.0)
        grille[:, :500] = 60 / 3.6 + 1e-9
        grille[:, 500:1000] = 59.9 / 3.6

        png = rafales.peindre(grille)

        assert rafales.palier_au_point(png, 46.0, -3.0) == 60
        assert rafales.palier_au_point(png, 46.0, 2.0) == 40

    def test_une_valeur_absente_ou_absurde_n_est_pas_peinte(self):
        grille = _grille(30.0)
        grille[:, :500] = numpy.nan
        grille[:, 500:1000] = 9999.0                    # valeur de remplissage
        grille[:, 1000:1200] = -1.0

        png = rafales.peindre(grille)

        assert rafales.palier_au_point(png, 46.0, -3.0) == 0
        assert rafales.palier_au_point(png, 46.0, 2.0) == 0
        assert rafales.palier_au_point(png, 46.0, 5.5) == 0
        assert rafales.palier_au_point(png, 46.0, 9.0) == 100   # 108 km/h

    def test_une_rafale_se_retrouve_a_sa_latitude_sur_la_carte(self):
        """La grille est régulière en latitude, la carte en Mercator : une bande de vent à
        45° ne doit pas glisser en passant de l'une à l'autre."""
        grille = _grille(0.0)
        grille[_ligne(45.2):_ligne(44.8), :] = 25.0     # bande de 0,4° centrée sur 45°

        png = rafales.peindre(grille)

        assert rafales.palier_au_point(png, 45.0, 2.0) == 80
        assert rafales.palier_au_point(png, 45.15, 2.0) == 80
        assert rafales.palier_au_point(png, 45.3, 2.0) == 0
        assert rafales.palier_au_point(png, 44.7, 2.0) == 0
        # Et l'image est bien plus haute que la grille : la Mercator étire le nord.
        assert self._image(grille).height > rafales.HAUTEUR

    def test_hors_de_l_image_il_n_y_a_pas_de_palier(self):
        png = rafales.peindre(_grille(30.0))

        assert rafales.palier_au_point(png, 52.5, 2.0) is None          # au nord
        assert rafales.palier_au_point(png, -21.1, 55.5) is None        # La Réunion
        assert rafales.palier_au_point(png, 51.5, 10.0) == 100          # le coin compte

    def test_la_legende_suit_les_paliers_peints(self):
        legende = rafales.legende()

        assert [palier["a_partir_de_kmh"] for palier in legende] == [40, 60, 80, 100, 120, 140]
        assert legende[0]["couleur"] == "#d6c6f2" and len({p["couleur"] for p in legende}) == 6
        assert len(rafales.TEINTES) == len(rafales.OPACITES) == len(rafales.SEUILS_KMH)


class TestTelechargement:

    def test_la_demande_porte_le_calcul_l_echeance_et_l_emprise_nationale(self, cle_meteo, tiff_calme):
        calcul = datetime.datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(tiff_calme)) as appel:
            contenu = rafales.telecharger_grille(calcul, MAINTENANT)

        options = appel.call_args.kwargs
        assert contenu == tiff_calme
        assert options["headers"] == {"apikey": "a.b.c"}
        assert ("coverageid", "WIND_SPEED_GUST_15MIN__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND"
                              "___2026-11-15T09.00.00Z_PT15M") in options["params"]
        decoupes = [valeur for nom, valeur in options["params"] if nom == "subset"]
        assert decoupes == ["time(2026-11-15T09:30:00Z)", "lat(41.0,51.5)", "long(-5.5,10.0)", "height(10)"]
        assert not any("a.b.c" in str(valeur) for _nom, valeur in options["params"])

    def test_un_calcul_pas_encore_paru_vaut_pas_de_grille(self, cle_meteo):
        with mock.patch("core.rafales.requests.get", return_value=_reponse_refus()):
            assert rafales.telecharger_grille(MAINTENANT, MAINTENANT) is None

    def test_une_reponse_qui_n_est_pas_un_tiff_vaut_pas_de_grille(self, cle_meteo):
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(b"<ExceptionReport/>")):
            assert rafales.telecharger_grille(MAINTENANT, MAINTENANT) is None

    def test_sans_cle_rien_ne_part(self, monkeypatch, tmp_path):
        from core import meteo_france

        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(tmp_path / "absente"))
        with mock.patch("core.rafales.requests.get") as appel:
            with pytest.raises(meteo_france.CleAbsente):
                rafales.telecharger_grille(MAINTENANT, MAINTENANT)
        appel.assert_not_called()


@pytest.mark.django_db
class TestReleve:

    @pytest.fixture(autouse=True)
    def _peinture_rapide(self, monkeypatch):
        """Peindre treize grilles nationales prend plusieurs secondes : la peinture a ses
        propres tests, ici une image d'un octet suffit."""
        monkeypatch.setattr(rafales, "preparer", lambda octets: b"png")

    def test_la_source_est_inscrite_au_releve_planifie(self):
        source = sources_ouvertes.SOURCES["RAFALES_PREVISION"]

        assert source.relever is rafales.relever and source.attribution == "Météo-France"
        # En dernier : c'est la source la plus lente (treize grilles de 13 Mo), et les sources
        # sont relevées l'une après l'autre. Rien ne doit attendre derrière elle.
        assert list(sources_ouvertes.SOURCES)[-1] == "RAFALES_PREVISION"

    def test_treize_echeances_sont_copiees_depuis_le_dernier_calcul_paru(self, cle_meteo, tiff_calme):
        def service(_adresse, params=None, **_reste):
            # Le calcul de 9 h n'est pas encore paru ; celui de 8 h répond.
            identifiant = dict(params)["coverageid"]
            return _reponse_refus() if "T09.00.00Z" in identifiant else _reponse_grille(tiff_calme)

        with mock.patch("core.rafales.requests.get", side_effect=service):
            assert rafales.relever(MAINTENANT) == 13

        assert set(ImageRafales.objects.values_list("calcul", flat=True)) == {
            datetime.datetime(2026, 11, 15, 8, 0, tzinfo=UTC)}
        echeances = list(ImageRafales.objects.order_by("echeance").values_list("echeance", flat=True))
        assert echeances[0] == MAINTENANT and echeances[-1] == MAINTENANT + datetime.timedelta(hours=3)

    def test_un_calcul_deja_copie_n_est_pas_retelecharge(self, cle_meteo, tiff_calme):
        """13 Mo par grille : tant qu'aucun quart d'heure nouveau n'est à prendre, rien ne doit
        être téléchargé -- pas même pour vérifier que le calcul est toujours le bon."""
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(tiff_calme)) as appel:
            rafales.relever(MAINTENANT)
            premier_passage = appel.call_count
            rafales.relever(MAINTENANT + datetime.timedelta(minutes=10))
            deuxieme_passage = appel.call_count
            rafales.relever(MAINTENANT + datetime.timedelta(minutes=20))

        assert premier_passage == 13 and deuxieme_passage == 13
        # À 9 h 50, un quart d'heure nouveau (12 h 45) : une grille, une seule.
        assert appel.call_count == 14
        assert ("subset", "time(2026-11-15T12:45:00Z)") in appel.call_args.kwargs["params"]

    def test_tant_que_le_calcul_de_l_heure_n_est_pas_paru_la_question_ne_coute_rien(self, cle_meteo, tiff_calme):
        """À 10 h 05 le calcul de 10 h n'est pas encore paru : on le demande (un refus tient en
        quelques octets), puis on garde celui de 9 h sans le retélécharger."""
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(tiff_calme)):
            rafales.relever(MAINTENANT)                 # 9 h 30, calcul de 9 h, jusqu'à 12 h 30

        demandes = []

        def service(_adresse, params=None, **_reste):
            identifiant = dict(params)["coverageid"]
            demandes.append(identifiant[-15:])
            return _reponse_refus() if "T10.00.00Z" in identifiant else _reponse_grille(tiff_calme)

        with mock.patch("core.rafales.requests.get", side_effect=service):
            rafales.relever(MAINTENANT + datetime.timedelta(minutes=35))

        # Une question au calcul de 10 h, puis les deux quarts d'heure nouveaux (12 h 45 et 13 h)
        # pris dans celui de 9 h.
        assert demandes == ["10.00.00Z_PT15M", "09.00.00Z_PT15M", "09.00.00Z_PT15M"]

    def test_une_grille_en_panne_ne_fait_pas_perdre_les_autres(self, cle_meteo, tiff_calme):
        import requests

        appels = []

        def service(_adresse, params=None, **_reste):
            appels.append(params)
            if len(appels) in (4, 5, 6):                # trois essais de la même grille
                raise requests.ConnectionError("Connection refused")
            return _reponse_grille(tiff_calme)

        with mock.patch("core.rafales.requests.get", side_effect=service), \
                mock.patch("core.meteo_france.time.sleep"):
            assert rafales.relever(MAINTENANT) == 12

    def test_le_releve_des_rafales_ne_touche_pas_aux_images_de_pluie(self, cle_meteo, tiff_calme):
        from core.models import ImagePluie

        ImagePluie.objects.create(echeance=MAINTENANT, calcul=MAINTENANT, image=b"pluie", releve_le=MAINTENANT)
        with mock.patch("core.rafales.requests.get", return_value=_reponse_grille(tiff_calme)):
            rafales.relever(MAINTENANT + datetime.timedelta(hours=2))

        assert ImagePluie.objects.count() == 1          # la pluie a sa propre purge


@pytest.mark.django_db
class TestLectures:

    def _image(self, echeance, vitesse_ms):
        grille = _grille(vitesse_ms)
        return ImageRafales.objects.create(echeance=echeance, calcul=echeance - datetime.timedelta(hours=1),
                                           image=rafales.peindre(grille), releve_le=timezone.now())

    def test_la_liste_donne_les_echeances_les_coins_et_la_legende(self, api_client):
        echeance = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._image(echeance, 20.0)

        with mock.patch("core.rafales.requests.get") as appel:
            liste = api_client.get(reverse("rafales_prevues")).json()
            image = api_client.get(reverse("rafales_prevues_image"), {"echeance": liste["echeances"][0]})
            absente = api_client.get(reverse("rafales_prevues_image"), {"echeance": "2020-01-01T00:00:00Z"})

        appel.assert_not_called()
        # L'image déborde l'emprise d'un demi-pas : chaque valeur vaut pour le carré qui l'entoure.
        assert liste["coins"] == [[-5.505, 51.505], [10.005, 51.505], [10.005, 40.995], [-5.505, 40.995]]
        assert liste["source"] == "Météo-France" and len(liste["echeances"]) == 1
        assert [p["a_partir_de_kmh"] for p in liste["legende"]] == [40, 60, 80, 100, 120, 140]
        assert liste["ici"] is None
        assert image.status_code == 200 and image["Content-Type"] == "image/png"
        assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert absente.status_code == 404

    def test_un_point_donne_recoit_son_palier_echeance_par_echeance(self, api_client):
        debut = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._image(debut, 10.0)                                        # 36 km/h : rien
        self._image(debut + datetime.timedelta(minutes=15), 24.0)       # 86 km/h
        self._image(debut + datetime.timedelta(minutes=30), 18.0)       # 65 km/h

        ici = api_client.get(reverse("rafales_prevues"), {"lat": 45.44, "lon": 4.39}).json()["ici"]

        assert [p["a_partir_de_kmh"] for p in ici["paliers"]] == [0, 80, 60]
        assert ici["maximum_kmh"] == 80 and ici["couvert"] is True
        assert ici["latitude"] == 45.44

    def test_un_point_hors_de_la_metropole_est_dit_non_couvert(self, api_client):
        self._image(timezone.now().replace(minute=0, second=0, microsecond=0), 24.0)

        ici = api_client.get(reverse("rafales_prevues"), {"lat": -21.1, "lon": 55.5}).json()["ici"]

        assert ici["couvert"] is False and ici["maximum_kmh"] is None
        assert ici["paliers"][0]["a_partir_de_kmh"] is None

    def test_sans_position_ni_institution_il_n_y_a_pas_de_lecture_locale(self, api_client):
        self._image(timezone.now().replace(minute=0, second=0, microsecond=0), 24.0)

        assert api_client.get(reverse("rafales_prevues"), {"ici": 1}).json()["ici"] is None



class TestBandesDispersees:
    """19/11/2026 : les grilles de types de précipitation arrivent en bandes dispersées."""

    def test_des_bandes_espacees_et_dans_le_desordre_donnent_la_meme_grille(self):
        grille = numpy.arange(12, dtype="float64").reshape(3, 4)
        for ecart, desordre in ((0, False), (16, False), (0, True), (24, True)):
            valeurs, ouest, nord, pas = rafales.lire_grille_tiff(_tiff(grille, ecart=ecart, desordre=desordre))
            assert numpy.array_equal(valeurs, grille), (ecart, desordre)
            assert (ouest, nord, pas) == (-5.5, 51.5, 0.01)

    def test_un_fichier_tronque_est_refuse(self):
        import pytest
        grille = numpy.arange(12, dtype="float64").reshape(3, 4)
        with pytest.raises(ValueError):
            rafales.lire_grille_tiff(_tiff(grille, ecart=16)[:-40])
