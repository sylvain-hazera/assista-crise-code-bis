"""Prévision immédiate par pysteps (core/prevision_immediate.py, 19/11/2026).

pysteps et OpenCV ne sont installés que dans l'image du service `orages` : ces essais tournent
dans cette image et sont sautés ailleurs."""
import datetime
from unittest import mock

import numpy
import pytest

from core import orages, prevision_immediate
from core.models import CelluleOrage, PrevisionPluieCommune
from core.tests.test_orages import creer_commune, image_hdf5

pytestmark = pytest.mark.skipif(not prevision_immediate.disponible(), reason="pysteps absent de cette image")


def bulle(decalage, forme=(300, 300)):
    g = numpy.zeros(forme)
    l, c = numpy.mgrid[0:forme[0], 0:forme[1]]
    g[(l - 150) ** 2 + (c - 100 - decalage) ** 2 <= 15 ** 2] = 60.0
    g[(l - 150) ** 2 + (c - 100 - decalage) ** 2 <= 6 ** 2] = 90.0
    return g


def test_le_flux_optique_retrouve_le_deplacement():
    champ = prevision_immediate.champ_de_deplacement([bulle(0), bulle(5), bulle(10)])
    l, c = numpy.nonzero(bulle(10) > 0)
    vitesse = prevision_immediate.vitesse_sous(champ, l, c)          # (lignes, colonnes) par minute
    cap, kmh = orages.cap_et_vitesse(vitesse)
    assert kmh == pytest.approx(60, abs=15)                           # 5 km par 5 minutes
    assert orages.vers(cap) == "l'est"


def test_l_extrapolation_avance_la_pluie():
    champ = prevision_immediate.champ_de_deplacement([bulle(0), bulle(5), bulle(10)])
    prevue = prevision_immediate.extrapoler(bulle(10), champ, pas=6)
    assert prevue.shape == (6, 300, 300)
    colonnes = numpy.nonzero(prevue[-1] > 30)[1]
    assert colonnes.mean() > 120                                      # partie de la colonne 110


@pytest.mark.django_db
def test_releve_complet_sur_trois_images():
    orages.IndexCommunes._cache = {}
    h0 = datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)
    images = [image_hdf5([(300, 300 + 10 * k, 12, 5.0)], heure=f"19{5 * k:02d}00") for k in range(3)]
    g = orages.lire(images[-1])
    creer_commune(g, "99010", "Plus-a-l-est", 150, 185)               # 25 km devant la cellule
    for k, octets in enumerate(images):
        heure = h0 + datetime.timedelta(minutes=5 * k)
        with mock.patch.object(orages, "heure_disponible", return_value=heure), \
             mock.patch.object(orages, "telecharger", return_value=octets):
            orages.relever(maintenant=heure + datetime.timedelta(minutes=5))
    cellule = CelluleOrage.objects.get()
    assert cellule.vitesse_kmh == pytest.approx(60, abs=20) and orages.vers(cellule.cap_deg) == "l'est"
    prevue = PrevisionPluieCommune.objects.get(commune_code="99010")
    assert prevue.dans_min_intense is not None and 10 <= prevue.dans_min_intense <= 45
    assert prevue.cumul_mm > 0
