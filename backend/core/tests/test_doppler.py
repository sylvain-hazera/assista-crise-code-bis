"""Signatures Doppler (core/doppler.py, 19/11/2026), sur des balayages fabriqués : on sait
d'avance où est la rotation, la grêle, la divergence — et ce qui doit être refusé."""
import math

import numpy
import pytest
from django.contrib.gis.geos import Polygon

from core import doppler

RADAR = (45.0, 1.0)                          # latitude, longitude


def balayage(nature, elevation, valeurs, porte_m=1000.0):
    return doppler.Balayage(nature, elevation, 0.0, valeurs, porte_m, RADAR[0], RADAR[1], 100.0, 1500.0)


def vitesse_avec_rotation(vrot=20.0, azimut=90.0, distance_km=60):
    """Fond calme, et un couple « vers / depuis le radar » de part et d'autre de `azimut`."""
    v = numpy.full((360, 256), 2.0)
    i, j = int(azimut), distance_km
    for k in range(1, 4):
        v[i - k, j - 1:j + 2] = -vrot * (1 - 0.2 * (k - 1))
        v[i + k, j - 1:j + 2] = vrot * (1 - 0.2 * (k - 1))
    return v


def zone_autour(azimut=90.0, distance_km=60, demi=0.2):
    b = balayage("V", 0.5, numpy.zeros((360, 256)))
    lon, lat = doppler.position(b, azimut, distance_km * 1000)
    p = Polygon.from_bbox((lon - demi, lat - demi, lon + demi, lat + demi))
    p.srid = 4326
    return p


def test_une_rotation_sur_deux_elevations_est_detectee():
    zone = zone_autour()
    rot = doppler.rotation([balayage("V", 0.5, vitesse_avec_rotation()), balayage("V", 1.5, vitesse_avec_rotation())], zone)
    assert rot is not None and rot["vrot_ms"] == pytest.approx(20, abs=0.1)
    assert rot["elevations"] == [0.5, 1.5]


def test_une_rotation_sur_une_seule_elevation_ne_suffit_pas():
    zone = zone_autour()
    assert doppler.rotation([balayage("V", 0.5, vitesse_avec_rotation()),
                             balayage("V", 1.5, numpy.full((360, 256), 2.0))], zone) is None


def test_un_saut_brusque_n_est_pas_une_rotation():
    """Erreur de dépliement : la vitesse bascule d'un coup de −40 à +40 m/s."""
    v = numpy.full((360, 256), 2.0)
    v[85:90, 59:62] = -40.0
    v[90:95, 59:62] = 40.0
    zone = zone_autour()
    assert doppler.rotation([balayage("V", 0.5, v), balayage("V", 1.5, v)], zone) is None


def test_grele_selon_waldvogel():
    z = numpy.full((720, 256), numpy.nan)
    z[178:184, 55:65] = 55.0                                     # vers 90° (pas de 0,5°), 55-65 km
    zone = zone_autour()
    haut = doppler.grele([balayage("Z", 4.0, z)], zone)          # à 60 km et 4°, faisceau vers 4,5 km
    assert haut["probable"] is True and haut["z_max_dbz"] == 55.0
    bas = doppler.grele([balayage("Z", 0.4, z)], zone)           # faisceau vers 0,9 km : sous l'isotherme
    assert bas["probable"] is False


def test_divergence_pres_du_sol():
    v = numpy.full((360, 256), 0.0)
    v[85:96, 20:26] = numpy.linspace(-15, 15, 6)                 # 6 m/s par km : +24 m/s sur 4 km
    zone = zone_autour(distance_km=22, demi=0.15)
    assert doppler.divergence([balayage("V", 0.5, v)], zone) == pytest.approx(24, abs=0.5)


def test_lecture_d_un_message_decode():
    """Forme de la sortie de decbufr relevée sur un vrai balayage de vitesse (Bollène)."""
    texte = "\n".join([
        " 0  2 135       2.4000000            Antenna elevation",
        " 3  1  21      44.3230600   0  5   1 Latitude (high accuracy)",
        "                4.7622200   0  6   1 Longitude (high accuracy)",
        "              310.0000000   0  7   2 Height or altitude",
        "           256000.0000000   0  6 195 Portee de fin de traitement d'un site",
        " 0 30  21       2.0000000            Number of pixels per row",
        " 0 30  22       2.0000000            Number of pixels per column",
        " 0  2 134       0.0000000            Antenna beam azimuth",
        " 0 49 220    1700.0000000            Altitude de l'isotherme 0 degre du PVR",
        " 0 49 241     -60.2000000            Valeur minimale de la vitesse radiale en m/s",
        " 0 49 231       0.5000000            Ecart entre deux valeurs consecutives des vitesses radiales",
        " 0 31 192       4.0000000            Facteur super elargi de repetition differe du descripteur",
        " 0 30   1     120.0000000            Pixel value (4 bits)",
        "              255.0000000   0 30   1 Pixel value (4 bits)",
        "              140.0000000   0 30   1 Pixel value (4 bits)",
        "              100.0000000   0 30   1 Pixel value (4 bits)",
    ])
    b = doppler.lire_message(texte)
    assert b.nature == "V" and b.elevation == 2.4 and b.porte_m == 128000.0
    assert b.latitude == pytest.approx(44.32306) and b.isotherme0 == 1700.0
    # Météo-France compte la vitesse positive VERS le radar : retournée au décodage.
    assert b.valeurs[0, 0] == pytest.approx(0.2) and math.isnan(b.valeurs[0, 1])
    assert b.valeurs[1, 0] == pytest.approx(-9.8) and b.valeurs[1, 1] == pytest.approx(10.2)


def test_decoupage_en_messages():
    m1 = b"BUFR" + (20).to_bytes(3, "big") + b"\x02" + b"x" * 8 + b"7777"
    m2 = b"BUFR" + (16).to_bytes(3, "big") + b"\x02" + b"y" * 4 + b"7777"
    assert doppler.messages(m1 + m2) == [m1, m2]


@pytest.mark.django_db
def test_releve_met_a_jour_la_cellule_avec_le_radar_proche():
    import datetime
    from unittest import mock
    from django.contrib.gis.geos import Point
    from django.utils import timezone
    from core.models import CelluleOrage, RadarMeteo

    maintenant = timezone.now()
    RadarMeteo.objects.create(station=99, nom="Essai", tours=["A", "B", "C"], latitude=RADAR[0], longitude=RADAR[1], maj=maintenant)
    for k in range(20):                                    # registre réputé frais
        RadarMeteo.objects.create(station=100 + k, nom=f"Loin {k}", tours=["A"], latitude=60, longitude=30, maj=maintenant)
    zone = zone_autour()
    CelluleOrage.objects.create(identifiant="c1", heure_image=maintenant, centre=zone.centroid, contour=zone,
                                ligne=0, colonne=0, max_mmh=70, moyenne_mmh=40, surface_km2=20, releve_le=maintenant)
    lus = [balayage("V", 0.5, vitesse_avec_rotation()), balayage("V", 1.5, vitesse_avec_rotation())]
    with mock.patch.object(doppler, "telecharger_balayage", return_value=b"x") as appel, \
         mock.patch.object(doppler, "decoder", return_value=lus):
        assert doppler.relever(maintenant) == 1
    assert {c.args[0] for c in appel.call_args_list} == {99}         # le radar lointain n'est pas lu
    cellule = CelluleOrage.objects.get()
    assert cellule.doppler_rotation["radar"] == "Essai" and cellule.doppler_radars == ["Essai"]


def _texte_pam(codes):
    entete = [" 0 30  21       2.0000000            Number of pixels per row",
              " 0 30  22       2.0000000            Number of pixels per column",
              " 0  2 135       0.8000000            Antenna elevation",
              " 0 31 192       4.0000000            Facteur super elargi de repetition differe du descripteur"]
    return "\n".join(entete + [f"              {c:.7f}   0 30   1 Pixel value (4 bits)" for c in codes])


def test_codages_de_la_double_polarisation():
    rho = doppler.lire_message(_texte_pam([69, 255, 0, 66]), "RHO")
    assert rho.nature == "RHO" and rho.valeurs[0, 0] == pytest.approx(0.995) and math.isnan(rho.valeurs[0, 1])
    zdr = doppler.lire_message(_texte_pam([100, 110, 90, 255]), "ZDR")
    assert zdr.valeurs[0, 0] == pytest.approx(0.05) and zdr.valeurs[0, 1] == pytest.approx(1.05)
    z = doppler.lire_message(_texte_pam([0, 1, 2, 60]), "Z")
    assert math.isnan(z.valeurs[0, 0]) and math.isnan(z.valeurs[0, 1]) and z.valeurs[1, 1] == pytest.approx(49.5)


def test_grele_et_debris_par_la_double_polarisation():
    forme = (720, 1066)
    z, rho, zdr = numpy.full(forme, 20.0), numpy.full(forme, 0.99), numpy.full(forme, 1.5)
    rangees = slice(178, 184)                       # vers 90°
    portes = slice(int(59000 / 240), int(61000 / 240))
    z[rangees, portes], rho[rangees, portes], zdr[rangees, portes] = 55.0, 0.93, 0.2
    lus = [balayage(n, 0.8, v, porte_m=240.0) for n, v in (("Z", z), ("RHO", rho), ("ZDR", zdr))]
    zone = zone_autour()
    resultat = doppler.polarimetrie(lus, zone)
    assert resultat["grele"] is True and resultat["portes_grele"] >= 5 and resultat["debris"] is False
    # Corrélation effondrée au cœur d'une rotation : signature de débris.
    rho[rangees, portes], z[rangees, portes] = 0.6, 45.0
    lus = [balayage(n, 0.8, v, porte_m=240.0) for n, v in (("Z", z), ("RHO", rho), ("ZDR", zdr))]
    centre = doppler.position(lus[0], 90.25, 60000)
    assert doppler.polarimetrie(lus, zone, centre)["debris"] is True
