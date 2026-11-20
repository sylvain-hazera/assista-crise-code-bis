"""Le radar de La Réunion à côté de celui de la métropole (core/orages.ZONES, 20/11/2026).

L'image de La Réunion est fabriquée avec la projection et le coin de la vraie mosaïque REUNION
(Mercator, coin haut gauche 51° E 16° S, relevés sur une image réelle le 20/11/2026), recadrée
pour rester légère. Ce qui compte : les deux mosaïques vivent côte à côte sans s'écraser, et
chaque demande reçoit celle de l'endroit qu'elle regarde."""
import datetime
import io
from unittest import mock

import numpy
import pytest

from core import orages, sources_ouvertes
from core.models import (CelluleOrage, Commune, CumulPluieCommune, ImageRadarEstimee, ImageRadarOrage,
                         PluieCommunesImage)
from core.tests.test_orages import image_hdf5

PROJDEF_REUNION = ("+proj=merc +lat_0=0 +lon_0=0 +lat_ts=-20.387 +ellps=WGS84 +datum=WGS84 "
                   "+x_0=-5323837.27 +y_0=2681326.18 ")
UL_LON, UL_LAT = 51.0, -16.0
# 1400 × 1100 points de 500 m : 700 km vers le sud, 550 km vers l'est, l'île comprise.
LIGNES, COLONNES = 1400, 1100
H0 = datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)


def image_reunion(cellules=(), heure="190000"):
    """[(lon, lat, rayon en points de 500 m, mm en 5 min)] -> lame d'eau REUNION synthétique."""
    import h5py
    from django.contrib.gis.gdal import CoordTransform, SpatialReference
    from django.contrib.gis.geos import Point
    coin = Point(UL_LON, UL_LAT, srid=4326)
    coin.transform(CoordTransform(SpatialReference(4326), SpatialReference(PROJDEF_REUNION)))
    donnees = numpy.full((LIGNES, COLONNES), 65534, dtype=numpy.uint16)
    l, c = numpy.mgrid[0:LIGNES, 0:COLONNES]
    for lon, lat, rayon, mm in cellules:
        p = Point(lon, lat, srid=4326)
        p.transform(CoordTransform(SpatialReference(4326), SpatialReference(PROJDEF_REUNION)))
        ligne, colonne = (coin.y - p.y) / 500, (p.x - coin.x) / 500
        donnees[(l - ligne) ** 2 + (c - colonne) ** 2 <= rayon ** 2] = int(mm / 0.01)
    tampon = io.BytesIO()
    with h5py.File(tampon, "w") as h:
        h.create_group("what").attrs.update({"date": b"20261119", "time": heure.encode(), "object": b"COMP"})
        h.create_group("where").attrs.update({"projdef": PROJDEF_REUNION.encode(), "xscale": 500.0, "yscale": 500.0,
                                              "xsize": COLONNES, "ysize": LIGNES, "UL_lon": UL_LON, "UL_lat": UL_LAT})
        h.create_group("how").attrs.update({"nodes": b"WMO:61978,WMO:61979"})
        d = h.create_group("dataset1/data1")
        d.create_dataset("data", data=donnees)
        d.create_group("what").attrs.update({"gain": 0.01, "offset": 0.0, "nodata": 65535.0, "undetect": 65534.0,
                                             "quantity": b"ACRR"})
    return tampon.getvalue()


def relever(octets, heure, zone):
    with mock.patch.object(orages, "heure_disponible", return_value=heure) as fiche, \
         mock.patch.object(orages, "telecharger", return_value=octets) as fichier:
        nombre = orages.relever(maintenant=heure + datetime.timedelta(minutes=5), zone=zone)
    if fichier.called:
        assert fichier.call_args.args == (zone,)
    assert fiche.call_args.args == (zone,)
    return nombre


def test_la_reunion_a_sa_mosaique_et_son_releve():
    assert orages.url_zone("REUNION").endswith("/mosaiques/REUNION/observations/LAME_D_EAU")
    assert orages.URL == orages.url_zone("METROPOLE")
    assert "ORAGES_RADAR_REUNION" in sources_ouvertes.SOURCES
    assert "ORAGES_RADAR_REUNION" in sources_ouvertes.SOURCES_EN_CONTINU
    assert sources_ouvertes.SOURCES["ORAGES_RADAR_REUNION"].relever == orages.relever_reunion


@pytest.mark.django_db
def test_les_deux_mosaiques_vivent_cote_a_cote(client):
    orages.IndexCommunes._cache = {}
    Commune.objects.create(code="97415", nom="Saint-Paul", centre_latitude=-21.01, centre_longitude=55.27)
    Commune.objects.create(code="97411", nom="Saint-Denis", centre_latitude=-20.88, centre_longitude=55.45)

    # Une averse sur Saint-Paul (60 mm/h), à la même heure qu'une cellule en métropole.
    assert relever(image_reunion([(55.27, -21.01, 8, 5.0)]), H0, "REUNION") == 1
    assert relever(image_hdf5([(300, 300, 10, 5.0)]), H0, "METROPOLE") == 1
    assert set(ImageRadarOrage.objects.values_list("zone", "heure")) == {("REUNION", H0), ("METROPOLE", H0)}
    assert sorted(CelluleOrage.objects.values_list("zone", flat=True)) == ["METROPOLE", "REUNION"]
    (cellule,) = CelluleOrage.objects.filter(zone="REUNION")
    assert [c["nom"] for c in cellule.communes_touchees] == ["Saint-Paul"]
    # Rien de ce qu'AROME-PI prévoit en métropole n'est cherché sous une cellule réunionnaise.
    assert cellule.grele_prevue is False and cellule.rafale_prevue_kmh is None

    # L'image suivante de La Réunion ne touche pas aux cellules de la métropole.
    relever(image_reunion([(55.30, -21.01, 8, 5.0)], heure="190500"), H0 + datetime.timedelta(minutes=5), "REUNION")
    assert CelluleOrage.objects.filter(zone="METROPOLE").count() == 1
    assert ImageRadarOrage.objects.filter(zone="REUNION").count() == 2

    # Les cumuls : la ligne de l'heure garde les communes des deux mosaïques.
    assert "97415" in PluieCommunesImage.objects.get(heure=H0).valeurs
    assert CumulPluieCommune.objects.filter(commune_code="97415").exists()

    # La carte demande la mosaïque de l'endroit qu'elle regarde.
    r = client.get("/api/orages/radar/", {"lat": -21.1, "lon": 55.5})
    assert r.status_code == 200 and r.json()["zone"] == "REUNION"
    assert r.json()["heure"].startswith("2026-11-19T19:05")
    coins = r.json()["coins"]
    assert 51 <= coins[0][0] < 52 and -16.1 <= coins[0][1] <= -15.9
    assert client.get("/api/orages/radar/", {"lat": 45.0, "lon": 2.0}).json()["zone"] == "METROPOLE"
    assert client.get("/api/orages/radar/").json()["zone"] == "METROPOLE"
    image = client.get("/api/orages/radar/image/", {"heure": r.json()["heure"], "zone": "REUNION"})
    assert image.status_code == 200 and image["Content-Type"] == "image/png"
    assert client.get("/api/orages/radar/image/", {"heure": r.json()["heure"]}).status_code == 404
    assert client.get("/api/orages/radar/image/", {"heure": r.json()["heure"], "zone": "MARS"}).status_code == 404

    # La veille autour de Saint-Paul : la cellule de l'île, et le radar de l'île.
    veille = client.get("/api/orages/", {"lat": -21.01, "lon": 55.27}).json()
    assert veille["zone"] == "REUNION" and veille["radars"] == 2 and veille["couvert"] is True
    assert len(veille["cellules"]) == 1


@pytest.mark.django_db
def test_les_estimations_de_chaque_mosaique_restent_a_part():
    from core import prevision_immediate
    grille = orages.lire(image_reunion())
    prevision_immediate.enregistrer_images(grille, numpy.zeros((2, *grille.forme), dtype=numpy.float32), zone="REUNION")
    metropole = orages.lire(image_hdf5())
    prevision_immediate.enregistrer_images(metropole, numpy.zeros((3, *metropole.forme), dtype=numpy.float32))
    assert ImageRadarEstimee.objects.filter(zone="REUNION").count() == 2
    assert ImageRadarEstimee.objects.filter(zone="METROPOLE").count() == 3


@pytest.mark.django_db
def test_le_doppler_ne_regarde_que_la_metropole():
    from django.contrib.gis.geos import Point, Polygon
    from core import doppler
    from core.models import RadarMeteo
    RadarMeteo.objects.create(station=1, nom="Essai", tours=["A"], latitude=45.0, longitude=2.0, maj=H0)
    CelluleOrage.objects.create(identifiant="r1", zone="REUNION", heure_image=H0, centre=Point(55.25, -21.05),
                                contour=Polygon.from_bbox((55.2, -21.1, 55.3, -21.0)), ligne=0, colonne=0,
                                max_mmh=120, moyenne_mmh=60, surface_km2=50, releve_le=H0)
    with mock.patch.object(doppler, "mettre_a_jour_radars"):
        assert doppler.relever(H0) == 0      # aucune cellule de métropole : rien à examiner
