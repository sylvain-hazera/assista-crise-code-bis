"""Potentiel d'orage de feu (core/orages_de_feu.py, 20/11/2026) : C-Haines et seuil de puissance
d'un pyrocumulonimbus (PFT) calculés sur le profil vertical d'ARPEGE -- nos estimations.

Les deux profils sont de vrais profils au-dessus de Saumos (Gironde), tirés de l'archive des
modèles : le 24/07/2026 à 15 h TU, une heure avant l'orage de feu (air brûlant et très sec), et
le lendemain à la même heure (air humide, orages ordinaires). Aucun test n'appelle l'extérieur."""
import datetime
from unittest import mock

import numpy
import pytest
from django.utils import timezone

from core import orages_de_feu, sources_ouvertes
from core.models import PotentielOrageFeu

UTC = datetime.timezone.utc

SAUMOS_24_JUILLET = (
    {"ps": 100460, "t2": 36.4, "hr2": 14, "vent10": 2.3, "blh": 2115.0},
    {1000: (34.8, 13, 76.0, 0.92), 950: (30.1, 17, 535.0, 2.05), 925: (27.9, 18, 772.0, 2.46),
     900: (25.7, 20, 1013.0, 2.67), 850: (20.9, 25, 1511.0, 2.43), 800: (15.9, 32, 2029.0, 1.76),
     700: (9.0, 39, 3149.0, 8.79), 600: (-1.1, 35, 4401.0, 14.73), 500: (-11.7, 46, 5825.0, 20.01),
     400: (-22.3, 18, 7498.77, 22.41), 300: (-39.0, 36, 9541.94, 25.7), 250: (-47.5, 47, 10767.62, 27.18)},
)
SAUMOS_25_JUILLET = (
    {"ps": 100650, "t2": 25.4, "hr2": 60, "vent10": 3.61, "blh": 1015.0},
    {1000: (24.1, 58, 91.0, 5.47), 950: (19.6, 70, 537.0, 5.06), 925: (17.8, 75, 766.0, 3.75),
     900: (15.8, 82, 1000.0, 2.14), 850: (12.9, 85, 1484.0, 4.36), 800: (10.2, 67, 1992.0, 8.82),
     700: (3.0, 67, 3092.0, 2.89), 600: (-6.4, 61, 4319.0, 3.44), 500: (-15.6, 21, 5717.0, 3.07),
     400: (-26.7, 53, 7362.96, 1.8), 300: (-41.0, 52, 9367.74, 8.03), 250: (-42.5, 11, 10603.81, 5.96)},
)


def grilles(*profils, altitude=36.0):
    """(sol, niveaux) d'une grille d'une ligne, une colonne par profil, au format d'ARPEGE."""
    sol = {nom: numpy.array([[p[0][nom] for p in profils]], float) for nom in ("ps", "t2", "hr2", "vent10", "blh")}
    sol["zsol"] = numpy.full((1, len(profils)), altitude)
    niveaux = {}
    for niveau in profils[0][1]:
        valeurs = [p[1][niveau] for p in profils]
        niveaux[niveau] = {
            "t": numpy.array([[v[0] for v in valeurs]]), "hr": numpy.array([[v[1] for v in valeurs]], float),
            "geo": numpy.array([[v[2] * orages_de_feu.GRAVITE for v in valeurs]]),
            "vent": numpy.array([[v[3] for v in valeurs]]),
        }
    return sol, niveaux


class TestPhysique:
    def test_c_haines_de_saumos(self):
        # Instabilité (20,9 - 9,0)/2 - 2 = 3,95 ; sécheresse 20,8/3 - 1 = 5,93, adoucie au-delà de 5.
        assert float(orages_de_feu.c_haines(20.9, 0.1, 9.0)) == pytest.approx(9.42, abs=0.01)

    def test_le_seuil_de_saumos_le_jour_de_l_orage_de_feu(self):
        resultat = orages_de_feu.calculer(*grilles(SAUMOS_24_JUILLET))
        # Le prototype du rejeu (pas de 25 m, 13 niveaux) trouvait 255 GW.
        assert resultat["pft"][0, 0] == pytest.approx(255, rel=0.15)
        assert resultat["ch"][0, 0] == pytest.approx(9.4, abs=0.2)

    def test_par_temps_humide_le_seuil_est_bas_mais_pas_de_potentiel(self):
        resultat = orages_de_feu.calculer(*grilles(SAUMOS_24_JUILLET, SAUMOS_25_JUILLET))
        assert resultat["pft"][0, 1] < 30                 # les orages ordinaires se forment seuls
        assert resultat["rang"][0, 1] == 0                # air humide : rien n'est peint
        assert resultat["rang"][0, 0] in (1, 2)           # ≈ 250 GW, air sec : « modéré » à « élevé »

    def test_les_paliers_suivent_le_seuil_seulement_par_air_sec(self):
        pft_gw = numpy.array([[60.0, 200.0, 400.0, 900.0, numpy.nan, 60.0]])
        ch = numpy.array([[9, 9, 9, 9, 9, 6]])
        hr2 = numpy.array([[20, 20, 20, 20, 20, 20]])
        assert orages_de_feu.potentiel(pft_gw, ch, hr2).tolist() == [[3, 2, 1, 0, 0, 0]]
        assert orages_de_feu.potentiel(pft_gw, ch, hr2 + 30).tolist() == [[0, 0, 0, 0, 0, 0]]

    def test_pas_de_c_haines_en_montagne(self):
        sol, niveaux = grilles(SAUMOS_24_JUILLET, SAUMOS_24_JUILLET)
        sol["ps"][0, 1] = 84000                           # 850 hPa sous le relief
        resultat = orages_de_feu.calculer(sol, niveaux)
        assert numpy.isfinite(resultat["ch"][0, 0]) and numpy.isnan(resultat["ch"][0, 1])
        assert resultat["rang"][0, 1] == 0

    def test_les_niveaux_sous_le_relief_sont_ignores(self):
        sol, niveaux = grilles(SAUMOS_24_JUILLET, altitude=900.0)
        sol["ps"][:] = 91000                              # un plateau à 910 hPa
        P, Z, T, Q, V = orages_de_feu.profils(sol, niveaux)
        assert P[0, 0] == pytest.approx(910, abs=0.1)
        assert numpy.all(numpy.diff(P[0][Z[0] < 9500]) < 0)   # la pression ne fait que baisser


class TestStockage:
    def test_aller_retour_et_valeur_au_point(self):
        resultat = orages_de_feu.calculer(*grilles(SAUMOS_24_JUILLET, SAUMOS_25_JUILLET))
        octets = orages_de_feu.coder(resultat)
        relu = orages_de_feu.decoder(octets, 2, 1)
        assert relu["pft"][0, 0] == round(resultat["pft"][0, 0])
        assert relu["rang"].tolist() == resultat["rang"].tolist()
        grille = PotentielOrageFeu(largeur=2, hauteur=1, ouest=-1.0, nord=44.9, grilles=octets)
        ici = orages_de_feu.valeur_au_point(grille, 44.9, -1.0)
        assert ici["potentiel"] in ("modéré", "élevé") and ici["c_haines"] == pytest.approx(9.4, abs=0.2)
        assert orages_de_feu.valeur_au_point(grille, 60.0, 30.0) is None

    def test_aucun_orage_possible_est_garde_comme_tel(self):
        octets = orages_de_feu.coder({"pft": numpy.array([[numpy.nan]]), "ch": numpy.array([[3.0]]),
                                      "rang": numpy.zeros((1, 1), numpy.uint8)})
        assert numpy.isnan(orages_de_feu.decoder(octets, 1, 1)["pft"][0, 0])

    def test_l_image_est_un_png_transparent_hors_des_paliers(self):
        from io import BytesIO

        from PIL import Image

        rang = numpy.zeros((106, 156), numpy.uint8)
        rang[50:55, 70:75] = 3
        image = Image.open(BytesIO(orages_de_feu.peindre(rang)))
        assert image.format == "PNG" and image.width == 156 * 4
        assert sorted(set(image.tobytes())) == [0, 3]


@pytest.mark.django_db
class TestReleve:
    MAINTENANT = datetime.datetime(2026, 7, 24, 11, 0, tzinfo=UTC)

    def test_la_source_est_inscrite_parmi_les_sources_lentes(self):
        assert "POTENTIEL_ORAGE_FEU" in sources_ouvertes.SOURCES
        assert "POTENTIEL_ORAGE_FEU" not in sources_ouvertes.SOURCES_EN_CONTINU
        assert list(sources_ouvertes.SOURCES)[-1] == "RAFALES_PREVISION"

    def test_les_heures_de_l_apres_midi_d_aujourd_hui_et_demain(self):
        voulues = orages_de_feu.echeances_voulues(self.MAINTENANT)
        assert [e.strftime("%d %H") for e in voulues] == ["24 12", "24 15", "24 18", "25 12", "25 15", "25 18"]

    def test_le_releve_calcule_chaque_heure_une_fois_par_calcul(self):
        lu = (*grilles(SAUMOS_24_JUILLET), -1.0, 44.9)
        with mock.patch.object(orages_de_feu, "telecharger_echeance", return_value=lu) as appel:
            # Deux heures par relevé, au plus : trois relevés pour les six heures.
            assert [orages_de_feu.relever(self.MAINTENANT) for _ in range(3)] == [2, 4, 6]
            assert appel.call_count == 6
            appel.reset_mock()
            assert orages_de_feu.relever(self.MAINTENANT) == 6
            assert appel.call_count == 0                  # rien de nouveau : rien de redemandé
        assert PotentielOrageFeu.objects.first().calcul == datetime.datetime(2026, 7, 24, 6, tzinfo=UTC)

    def test_sans_calcul_disponible_le_releve_echoue(self):
        with mock.patch.object(orages_de_feu, "telecharger_echeance", return_value=None):
            with pytest.raises(ValueError):
                orages_de_feu.relever(self.MAINTENANT)

    def test_les_heures_passees_sont_retirees(self):
        PotentielOrageFeu.objects.create(echeance=self.MAINTENANT - datetime.timedelta(hours=5),
                                         calcul=self.MAINTENANT, largeur=1, hauteur=1, ouest=0, nord=0,
                                         grilles=b"", image=b"", releve_le=self.MAINTENANT)
        lu = (*grilles(SAUMOS_24_JUILLET), -1.0, 44.9)
        with mock.patch.object(orages_de_feu, "telecharger_echeance", return_value=lu):
            orages_de_feu.relever(self.MAINTENANT)
        assert not PotentielOrageFeu.objects.filter(echeance__lt=self.MAINTENANT - datetime.timedelta(hours=3)).exists()


@pytest.mark.django_db
class TestAPI:
    def _creer(self, echeance):
        resultat = orages_de_feu.calculer(*grilles(SAUMOS_24_JUILLET, SAUMOS_25_JUILLET))
        return PotentielOrageFeu.objects.create(
            echeance=echeance, calcul=echeance - datetime.timedelta(hours=9), largeur=2, hauteur=1,
            ouest=-1.0, nord=44.9, grilles=orages_de_feu.coder(resultat),
            image=orages_de_feu.peindre(resultat["rang"]), releve_le=timezone.now())

    def test_les_heures_la_legende_et_les_valeurs_ici(self, client):
        echeance = datetime.datetime(2026, 7, 24, 15, tzinfo=UTC)
        self._creer(echeance)
        r = client.get("/api/orages-de-feu/", {"lat": 44.9, "lon": -1.0}).json()
        assert r["nos_estimations"] is True
        assert [p["libelle"] for p in r["legende"]] == ["très élevé", "élevé", "modéré"]
        (heure,) = r["echeances"]
        assert heure["palier_max_france"] in (1, 2) and heure["palier_max_autour"] == heure["palier_max_france"]
        assert heure["ici"]["potentiel"] in ("modéré", "élevé") and 200 < heure["ici"]["pft_gw"] < 300

    def test_l_image_est_servie_sans_session(self, client):
        echeance = datetime.datetime(2026, 7, 24, 15, tzinfo=UTC)
        self._creer(echeance)
        r = client.get("/api/orages-de-feu/image/", {"echeance": echeance.isoformat()})
        assert r.status_code == 200 and r["Content-Type"] == "image/png"
        assert client.get("/api/orages-de-feu/image/", {"echeance": "2026-07-24T16:00:00Z"}).status_code == 404
