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


@pytest.mark.django_db
class TestDiagnosticGreleEtCumuls:

    def test_seuils_et_regroupement(self):
        assert orages.niveau_grele(None) is None and orages.niveau_grele(5) is None
        assert orages.niveau_grele(8.5) == "grêle possible" and orages.niveau_grele(13) == "grosse grêle possible"
        groupes = orages._regrouper([(0, 0, 1, 1), (0.5, 0.5, 2, 2), (5, 5, 6, 6)])
        assert sorted(len(g["membres"]) for g in groupes) == [1, 2]

    def test_le_diagnostic_est_le_plus_fort_sous_la_cellule(self):
        from django.contrib.gis.geos import Polygon
        from core.models import ImageRafales
        heure = datetime.datetime(2026, 11, 19, 20, 5, tzinfo=datetime.timezone.utc)
        ImageRafales.objects.create(echeance=heure, calcul=heure.replace(minute=0), image=b"", releve_le=heure)
        contour = Polygon.from_bbox((0.02, 44.02, 0.06, 44.06))
        contour.srid = 4326
        grille = numpy.zeros((20, 20))          # 0,01° par point, à partir de (0.0 ; 44.1)
        grille[5, 4] = 9.5                       # sous la cellule (0.04 ; 44.05)
        grille[15, 15] = 30.0                    # hors de la cellule : ignoré
        reponse = mock.Mock(status_code=200, content=b"II*\x00reste")
        with mock.patch.object(orages.meteo_france, "lire_cle", return_value="cle"), \
             mock.patch.object(orages.requests, "get", return_value=reponse) as appel, \
             mock.patch("core.rafales.lire_grille_tiff", return_value=(grille, 0.0, 44.1, 0.01)):
            (valeur,) = orages.diagnostic_grele([contour], heure)
        assert valeur == 9.5
        parametres = dict((k, v) for k, v in appel.call_args.kwargs["params"] if k != "subset")
        assert parametres["coverageid"] == "DIAG_GRELE__GROUND_OR_WATER_SURFACE___2026-11-19T20.00.00Z"
        assert ("subset", "time(2026-11-19T20:15:00Z)") in appel.call_args.kwargs["params"]

    def test_cumuls_par_commune(self, client):
        orages.IndexCommunes._cache = {}
        a = orages.lire(image_hdf5([(300, 300, 10, 2.0)], heure="190000"))      # 2 mm en 5 min
        creer_commune(a, "99001", "Arrosee", 150, 150)
        creer_commune(a, "99002", "Seche", 50, 250)
        orages.cumuler_pluie(a)
        b = orages.lire(image_hdf5([(300, 300, 10, 3.0)], heure="190500"))
        orages.cumuler_pluie(b)
        from core.models import CumulPluieCommune, PluieCommunesImage
        assert PluieCommunesImage.objects.count() == 2
        cumul = CumulPluieCommune.objects.get(commune_code="99001")
        assert cumul.mm_1h == pytest.approx(5.0, abs=0.2) and cumul.mm_24h == pytest.approx(5.0, abs=0.2)
        assert not CumulPluieCommune.objects.filter(commune_code="99002").exists()

        ImageRadarOrage.objects.create(heure=b.heure, largeur=1, hauteur=1, projdef=PROJDEF, x0=0, y0=0,
                                       grille=b"", images_par_fenetre={"1h": 2, "3h": 2, "24h": 2}, releve_le=b.heure)
        lon, lat = geo(b, 150, 150)
        r = client.get("/api/orages/", {"lat": lat, "lon": lon, "rayon_km": 20})
        cumuls = r.json()["cumuls"]
        assert [c["nom"] for c in cumuls["plus_arrosees"]] == ["Arrosee"]
        assert cumuls["fenetres"]["1h"] == 2 and cumuls["seuils_mm"]["3h"] == 50


@pytest.mark.django_db
def test_pluie_observee_en_image_pour_la_carte(client):
    """La dernière image, reprojetée pour la carte : coins plausibles, PNG transparent, une
    intensité forte peinte de la teinte de son palier."""
    import io as _io

    from PIL import Image

    from core import carte_radar
    carte_radar._IMAGES.clear()
    h0 = datetime.datetime(2026, 11, 19, 19, 0, tzinfo=datetime.timezone.utc)
    with mock.patch.object(orages, "heure_disponible", return_value=h0), \
         mock.patch.object(orages, "telecharger", return_value=image_hdf5([(300, 300, 10, 5.0)])):
        orages.relever(maintenant=h0 + datetime.timedelta(minutes=5))

    r = client.get("/api/orages/radar/")
    assert r.status_code == 200
    donnees = r.json()
    (ouest, nord), _, (est, sud), _ = donnees["coins"]
    assert ouest == pytest.approx(UL_LON, abs=0.05) and ouest < est and sud < nord
    assert donnees["legende"][0] == {"a_partir_de_mmh": 0.5, "couleur": "#bfdbfe"}

    image = client.get("/api/orages/radar/image/", {"heure": donnees["heure"]})
    assert image.status_code == 200 and image["Content-Type"] == "image/png"
    rgba = Image.open(_io.BytesIO(image.content)).convert("RGBA")
    couleurs = {c for _, c in rgba.getcolors(maxcolors=100000) if c[3] > 0}
    assert (220, 38, 38, carte_radar.OPACITE) in couleurs           # 60 mm/h : palier 50 mm/h
    assert rgba.getpixel((0, 0))[3] == 0                            # hors pluie : transparent
    assert client.get("/api/orages/radar/image/", {"heure": "2020-01-01T00:00:00Z"}).status_code == 404
