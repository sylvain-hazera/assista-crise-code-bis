"""Suivi des cellules par tobac (core/suivi_tobac.py, 20/11/2026).

Images synthétiques à 1 km, à cinq minutes d'intervalle : on sait d'avance ce que le suivi doit
trouver (une cellule qui avance et se renforce, deux cœurs dans une même zone de pluie)."""
import datetime

import numpy
import pytest

from core import suivi_tobac

avec_tobac = pytest.mark.skipif(not suivi_tobac.disponible(), reason="tobac absent de cette image")
T0 = datetime.datetime(2026, 11, 20, 6, 0, tzinfo=datetime.timezone.utc)


def disque(grille, ligne, colonne, rayon, mmh):
    l, c = numpy.mgrid[0:grille.shape[0], 0:grille.shape[1]]
    grille[(l - ligne) ** 2 + (c - colonne) ** 2 <= rayon ** 2] = mmh


def images(n, construire):
    grilles = []
    for i in range(n):
        g = numpy.zeros((200, 200), dtype="float32")
        g[:, :5] = numpy.nan                         # bande sans radar
        construire(g, i)
        grilles.append(g)
    return grilles, [T0 + datetime.timedelta(minutes=5 * i) for i in range(n)]


@avec_tobac
def test_une_cellule_qui_avance_et_se_renforce():
    # 2 km par image vers l'est ; le cœur passe de 40 à 70 mm/h et s'élargit.
    def construire(g, i):
        disque(g, 100, 40 + 2 * i, 6 + i, 35)
        disque(g, 100, 40 + 2 * i, 2 + i, 40 + 10 * i)
    grilles, heures = images(4, construire)
    noyaux = suivi_tobac.suivre(grilles, heures)
    assert noyaux, "aucun noyau"
    principal = max(noyaux, key=lambda n: (n["seuil"], n["surface_km2"]))
    assert principal["colonne"] == pytest.approx(46, abs=2) and principal["ligne"] == pytest.approx(100, abs=2)
    resume = suivi_tobac.resumer(noyaux)
    assert resume["suivie_depuis_min"] == 15
    assert resume["evolution"] == "renforcement"
    assert resume["max_10min_mmh"] >= 10


@avec_tobac
def test_deux_coeurs_dans_une_meme_zone():
    def construire(g, i):
        g[80:120, 40:120] = 35                        # une seule zone au-dessus de 30 mm/h
        disque(g, 100, 55 + i, 4, 70)
        disque(g, 100, 105 + i, 4, 65)
    grilles, heures = images(3, construire)
    resume = suivi_tobac.resumer(suivi_tobac.suivre(grilles, heures))
    assert resume["noyaux_intenses"] == 2


@avec_tobac
def test_sans_pluie_forte_rien():
    grilles, heures = images(3, lambda g, i: disque(g, 100, 100, 10, 12))
    assert suivi_tobac.suivre(grilles, heures) == []


@avec_tobac
def test_une_seule_image_donne_des_noyaux_sans_histoire():
    grilles, heures = images(1, lambda g, i: disque(g, 100, 100, 6, 60))
    (noyau, *_) = suivi_tobac.suivre(grilles, heures)
    assert noyau["age_min"] is None and noyau["max_10min_mmh"] is None
    assert suivi_tobac.resumer([noyau])["evolution"] is None


def test_resume_d_une_cellule():
    noyaux = [
        {"seuil": 50, "surface_km2": 20.0, "age_min": 25, "surface_10min_km2": -12.0, "max_10min_mmh": -15.0,
         "fusion": False, "division": True},
        {"seuil": 30, "surface_km2": 40.0, "age_min": None, "surface_10min_km2": None, "max_10min_mmh": None,
         "fusion": True, "division": False},
    ]
    assert suivi_tobac.resumer(noyaux) == {
        "suivie_depuis_min": 25, "noyaux": 2, "noyaux_intenses": 1, "surface_10min_km2": -12.0,
        "max_10min_mmh": -15.0, "evolution": "affaiblissement", "fusion": True, "division": True}
    assert suivi_tobac.resumer([]) is None


@avec_tobac
@pytest.mark.django_db
def test_le_releve_radar_porte_le_suivi(client):
    """Trois images de suite : la cellule de la veille dit depuis quand elle est suivie."""
    from unittest import mock

    from core import orages
    from django.contrib.gis.geos import Point

    from core.models import CelluleOrage, ImageRadarOrage
    from core.tests.test_orages import image_hdf5

    orages.IndexCommunes._cache = {}
    h0 = datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)
    for i in range(3):
        heure = h0 + datetime.timedelta(minutes=5 * i)
        # Points de 500 m : 4 km vers l'est par image, cœur de plus en plus fort.
        octets = image_hdf5([(300, 300 + 8 * i, 14, 3.0), (300, 300 + 8 * i, 5, 4.0 + 1.5 * i)],
                            heure=f"19{5 * i:02d}00")
        with mock.patch.object(orages, "heure_disponible", return_value=heure), \
             mock.patch.object(orages, "telecharger", return_value=octets):
            orages.relever(maintenant=heure + datetime.timedelta(minutes=5))
    assert ImageRadarOrage.objects.count() == 3
    (cellule,) = CelluleOrage.objects.all()
    assert cellule.suivi["suivie_depuis_min"] == 10
    assert cellule.suivi["evolution"] == "renforcement"
    # Les noyaux sont placés sur la carte, à l'intérieur de la cellule.
    (noyau, *_) = cellule.suivi["noyaux_positions"]
    assert cellule.contour.buffer(0.02).contains(Point(noyau["lon"], noyau["lat"], srid=4326))
