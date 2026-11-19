"""Orages selon les relevés radar (core/orages.py, 19/11/2026).

Les images sont fabriquées ici avec la même structure que la lame d'eau de Météo-France
(HDF5 ODIM : `dataset1/data1/data`, gain, nodata, undetect, `where/projdef`, coins, radars),
relevée sur une image réelle le 19/11/2026. Une image synthétique permet de connaître d'avance
ce que l'analyse doit trouver : où est la cellule, à quelle vitesse elle va."""
import datetime
import io
import math
from unittest import mock

import numpy
import pytest
from django.utils import timezone

from core import orages, sources_ouvertes
from core.models import CelluleOrage, Commune, ImageRadarOrage, ObservationMeteo

PROJDEF = ("+proj=stere +lat_0=90 +lon_0=0 +lat_ts=45 +ellps=WGS84 "
           "+x_0=619652.07 +y_0=5262818.34 +datum=WGS84")
# Coin haut gauche de la vraie mosaïque métropole.
UL_LON, UL_LAT = -9.965, 53.67
TAILLE = 600          # points de 500 m : 300 km de côté, assez pour tout ce qu'on teste


def image_hdf5(cellules=(), heure="190000", absents=b"WMO:07714"):
    """Une lame d'eau synthétique : [(ligne, colonne, rayon, mm_en_5min)] en points de 500 m."""
    import h5py
    donnees = numpy.full((TAILLE, TAILLE), 65534, dtype=numpy.uint16)     # non détecté
    donnees[:, :20] = 65535                                               # bande sans radar
    l, c = numpy.mgrid[0:TAILLE, 0:TAILLE]
    for ligne, colonne, rayon, mm in cellules:
        donnees[(l - ligne) ** 2 + (c - colonne) ** 2 <= rayon ** 2] = int(mm / 0.01)
    tampon = io.BytesIO()
    with h5py.File(tampon, "w") as h:
        h.create_group("what").attrs.update({"date": b"20261119", "time": heure.encode(), "object": b"COMP"})
        h.create_group("where").attrs.update({"projdef": PROJDEF.encode(), "xscale": 500.0, "yscale": 500.0,
                                              "xsize": TAILLE, "ysize": TAILLE, "UL_lon": UL_LON, "UL_lat": UL_LAT})
        h.create_group("how").attrs.update({"nodes": b"WMO:07255,WMO:07714", "missing_nodes": absents})
        d = h.create_group("dataset1/data1")
        d.create_dataset("data", data=donnees)
        d.create_group("what").attrs.update({"gain": 0.01, "offset": 0.0, "nodata": 65535.0, "undetect": 65534.0,
                                             "quantity": b"ACRR"})
    return tampon.getvalue()


def geo(grille, ligne, colonne):
    """(lon, lat) d'un point de la grille à 1 km."""
    return grille.vers_geo([ligne], [colonne])[0]


@pytest.mark.django_db
class TestLecture:

    def test_intensite_et_geolocalisation(self):
        g = orages.lire(image_hdf5([(200, 200, 6, 5.0)]))          # 5 mm en 5 min = 60 mm/h
        assert g.forme == (TAILLE // 2, TAILLE // 2)
        assert numpy.nanmax(g.taux) == pytest.approx(60.0)
        assert g.heure == datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)
        assert g.absents == ["WMO:07714"] and len(g.radars) == 2
        # Le coin haut gauche retombe sur celui du fichier (à un demi-point près).
        lon, lat = geo(g, -0.5, -0.5)
        assert (lon, lat) == (pytest.approx(UL_LON, abs=0.01), pytest.approx(UL_LAT, abs=0.01))
        # Aller-retour géographique.
        (r,), (c,) = g.depuis_geo(*zip(geo(g, 100, 120)))
        assert (r, c) == (pytest.approx(100, abs=0.01), pytest.approx(120, abs=0.01))

    def test_sans_donnee_et_non_detecte_ne_se_confondent_pas(self):
        g = orages.lire(image_hdf5())
        assert numpy.isnan(g.taux[50, 0])          # bande sans radar : inconnu
        assert g.taux[50, 100] == 0                # non détecté : pas de pluie


@pytest.mark.django_db
class TestCellulesEtDeplacement:

    def test_une_cellule_et_son_intensite(self):
        g = orages.lire(image_hdf5([(200, 200, 8, 5.0), (400, 400, 1, 9.0)]))   # la seconde est trop petite
        trouvees, _ = orages.cellules(g)
        assert len(trouvees) == 1
        assert trouvees[0]["max_mmh"] == pytest.approx(60)
        assert trouvees[0]["centre"] == (pytest.approx(100, abs=0.6), pytest.approx(100, abs=0.6))

    def test_le_deplacement_est_retrouve(self):
        """La cellule avance de 4 km vers l'est et 3 km vers le nord en 5 minutes : 60 km/h,
        cap 53° (nord-est)."""
        a = orages.lire(image_hdf5([(300, 300, 10, 5.0), (330, 280, 6, 4.0)]))
        b = orages.lire(image_hdf5([(294, 308, 10, 5.0), (324, 288, 6, 4.0)]))
        v = orages.deplacement(a.taux, b.taux, (150, 150), 5)
        assert v is not None
        cap, kmh = orages.cap_et_vitesse(v)
        assert kmh == pytest.approx(60, abs=6)
        assert cap == pytest.approx(53, abs=8)
        assert orages.vers(cap) == "le nord-est"

    def test_une_correlation_floue_ne_donne_pas_de_vitesse(self):
        a = orages.lire(image_hdf5([(300, 300, 10, 5.0)]))
        b = orages.lire(image_hdf5())
        assert orages.deplacement(a.taux, b.taux, (150, 150), 5) is None


def creer_commune(g, code, nom, ligne, colonne):
    lon, lat = geo(g, ligne, colonne)
    return Commune.objects.create(code=code, nom=nom, centre_latitude=lat, centre_longitude=lon)


@pytest.mark.django_db
class TestAnalyse:

    def test_communes_sous_la_pluie_et_estimees(self):
        orages.IndexCommunes._cache = {}
        a = orages.lire(image_hdf5([(300, 300, 10, 5.0)]))
        b = orages.lire(image_hdf5([(300, 310, 10, 5.0)], heure="190500"))     # 5 km vers l'est en 5 min
        creer_commune(b, "99001", "Sous-la-pluie", 150, 155)
        creer_commune(b, "99002", "Plus-a-l-est", 150, 175)                    # 20 km plus loin : ~20 min
        creer_commune(b, "99003", "A-l-ouest", 150, 120)
        ObservationMeteo.objects.create(station="99999001", nom="Station test", location=__import__(
            "django.contrib.gis.geos", fromlist=["Point"]).Point(*geo(b, 150, 155), srid=4326),
            rafale_kmh=97, mesure_le=b.heure, releve_le=timezone.now())
        (c,) = orages.analyser(b, a.taux, 5.0)
        assert c["vitesse_kmh"] == pytest.approx(60, abs=8) and orages.vers(c["cap_deg"]) == "l'est"
        assert [x["nom"] for x in c["communes_touchees"]] == ["Sous-la-pluie"]
        (estimee,) = c["communes_estimees"]
        assert estimee["nom"] == "Plus-a-l-est" and 10 <= estimee["dans_min"] <= 25
        assert c["rafale_mesuree"]["kmh"] == 97
        assert c["couloir"] is not None and c["couloir"].area > c["contour"].area

    def test_le_suivi_garde_l_identifiant(self):
        orages.IndexCommunes._cache = {}
        a = orages.lire(image_hdf5([(300, 300, 10, 5.0)]))
        (premiere,) = orages.analyser(a)
        b = orages.lire(image_hdf5([(300, 310, 10, 5.0)], heure="190500"))
        (seconde,) = orages.analyser(b, a.taux, 5.0, [premiere])
        assert seconde["identifiant"] == premiere["identifiant"]
        assert len(seconde["trace"]) == 2

    def test_une_ligne_de_grain(self):
        """Une bande de 100 km sur 6, qui avance perpendiculairement à sa longueur à 60 km/h."""
        import h5py  # noqa: F401 -- la fabrication de l'image en dépend
        orages.IndexCommunes._cache = {}

        def bande(decalage):
            octets = image_hdf5()
            g = orages.lire(octets)
            g.taux[:, :] = 0
            g.taux[100:200, 140 + decalage:146 + decalage] = 60
            return g
        a, b = bande(0), bande(5)
        b.heure = a.heure + datetime.timedelta(minutes=5)
        (c,) = orages.analyser(b, a.taux, 5.0)
        assert c["ligne_de_grain"] is True
        assert c["longueur_km"] >= 80


@pytest.mark.django_db
class TestReleveEtVue:

    def _relever(self, octets, heure):
        with mock.patch.object(orages, "heure_disponible", return_value=heure), \
             mock.patch.object(orages, "telecharger", return_value=octets):
            return orages.relever(maintenant=heure + datetime.timedelta(minutes=5))

    def test_releve_puis_vue_de_la_veille(self, client):
        orages.IndexCommunes._cache = {}
        h0 = datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)
        assert self._relever(image_hdf5([(300, 300, 10, 5.0)]), h0) == 1
        b = orages.lire(image_hdf5([(300, 310, 10, 5.0)], heure="190500"))
        creer_commune(b, "99001", "Sous-la-pluie", 150, 155)
        orages.IndexCommunes._cache = {}
        assert self._relever(image_hdf5([(300, 310, 10, 5.0)], heure="190500"), h0 + datetime.timedelta(minutes=5)) == 1
        # Image déjà analysée : rien ne change, le compte reste juste.
        assert self._relever(b"inutile", h0 + datetime.timedelta(minutes=5)) == 1
        assert ImageRadarOrage.objects.count() == 2

        lon, lat = geo(b, 150, 155)
        r = client.get("/api/orages/", {"lat": lat, "lon": lon})
        assert r.status_code == 200, r.content
        (cellule,) = r.json()["cellules"]
        assert cellule["releves"]["communes_sous_la_pluie"][0]["nom"] == "Sous-la-pluie"
        assert cellule["estimations"]["vers"] == "l'est"
        assert r.json()["couvert"] is True

        # Loin de tout : rien, et la couverture est dite.
        loin = client.get("/api/orages/", {"lat": 47.0, "lon": 2.0, "rayon_km": 10})
        assert loin.json()["cellules"] == []

    def test_une_image_figee_se_signale(self):
        # L'heure vient du fichier (19/11/2026 19:00 UTC) : l'essai ne dépend pas de l'heure qu'il est.
        h0 = datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)
        self._relever(image_hdf5([(300, 300, 10, 5.0)]), h0)
        with mock.patch.object(orages, "heure_disponible", return_value=h0), \
             mock.patch.object(orages, "telecharger", side_effect=AssertionError("ne doit pas télécharger")):
            assert orages.relever(maintenant=h0 + datetime.timedelta(minutes=10)) == 1     # encore frais
            with pytest.raises(RuntimeError, match="inchangée"):
                orages.relever(maintenant=h0 + datetime.timedelta(minutes=40))

    def test_le_cron_ne_releve_pas_le_radar(self):
        assert "ORAGES_RADAR" in sources_ouvertes.SOURCES
        assert "ORAGES_RADAR" in sources_ouvertes.SOURCES_EN_CONTINU
