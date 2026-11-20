"""Feux en cours suivis par le satellite MTG (core/feux_mtg.py, 20/11/2026).

Les listes de pixels sont fabriquées ici avec l'en-tête exact des fichiers du LSA SAF
(LSA-509, constaté le 20/11/2026). Aucun test n'appelle l'extérieur."""
import datetime
import gzip
import io
from unittest import mock

import pytest
from django.contrib.gis.geos import Point, Polygon
from django.utils import timezone

from core import feux_mtg, orages_de_feu, sources_ouvertes
from core.models import CelluleOrage, DetectionFeuMTG, FeuSuivi, FoyerActif, ImpactFoudre, PotentielOrageFeu, ProduitFeuMTG

UTC = datetime.timezone.utc
EN_TETE = ("BW_SIZE,BW_NUMPIX,BW_BT_MIR,BW_BTD,RAD_BCK,STD_BCK,FIRE_CONFIDENCE,BT_MIR,BT_TIR,RAD_PIX,"
           "PIXEL_VZA,PIXEL_SZA,PIXEL_SIZE,ACQTIME,ABS_LINE,ABS_SAMP,LONGITUDE,LATITUDE,LONGITUDE_PARALLAX,"
           "LATITUDE_PARALLAX,FRP,ERR_FRP_COEFF,ERR_ATM_TRANS,ERR_RADIOMETRIC,ERR_BACKGROUND,ERR_VERT_COMP,"
           "FRP_UNCERTAINTY,PIXEL_ATM_TRANS")
SAUMOS = (44.87, -0.98)


def liste(pixels):
    """Fichier .csv.gz du LSA SAF : pixels = [(instant, lat, lon, MW, confiance)]."""
    lignes = [EN_TETE]
    for instant, lat, lon, mw, conf in pixels:
        lignes.append(f"5,16,300,10,0.3,0.01,{conf},320,300,0.5,50,30,2.0,{instant:%Y%m%d%H%M%S},1,1,"
                      f"{lon},{lat},{lon},{lat},{mw},0.1,0.02,0.2,0.1,0.01,{mw * 0.05},0.7")
    tampon = io.BytesIO()
    with gzip.GzipFile(fileobj=tampon, mode="wb") as f:
        f.write("\n".join(lignes).encode("ascii"))
    return tampon.getvalue()


def detection(creneau, lat, lon, mw):
    return {"creneau": creneau, "instant": creneau + datetime.timedelta(minutes=8), "latitude": lat,
            "longitude": lon, "puissance_mw": mw}


class TestLecture:
    def test_la_page_du_dossier_donne_les_listes_par_creneau(self):
        page = ('<a href="/PRODUCTS/MTG/MTFRPPixel/NATIVE/2026/07/22/LSA-509_MTG_MTFRPPIXEL-ListProduct_MTG-FD_202607221050.csv.gz">'
                '<a href="/PRODUCTS/MTG/MTFRPPixel/NATIVE/2026/07/22/LSA-509_MTG_MTFRPPIXEL-ListProduct_MTG-FD_202607221040.csv.gz">'
                '<a href="/PRODUCTS/MTG/MTFRPPixel/NATIVE/2026/07/22/LSA-509_MTG_MTFRPPIXEL_MTG-FD_202607221040.nc">')
        trouves = feux_mtg.lister(page)
        assert [c.strftime("%H:%M") for c, _ in trouves] == ["10:40", "10:50"]

    def test_seuls_les_pixels_de_l_emprise_sont_gardes(self):
        instant = datetime.datetime(2026, 7, 22, 10, 48, 48, tzinfo=UTC)
        pixels = feux_mtg.lire(liste([(instant, *SAUMOS, 8.4, 0.83), (instant, 52.7, -8.1, 6.5, 0.79)]))
        assert len(pixels) == 1
        assert pixels[0]["instant"] == instant and pixels[0]["puissance_mw"] == pytest.approx(8.4)

    def test_une_page_de_connexion_au_lieu_du_fichier_est_une_erreur(self):
        with pytest.raises(ValueError, match="identifiants"):
            feux_mtg.lire(b"<!DOCTYPE html><title>LSA SAF Data Service</title>Invalid Credentials")

    def test_les_identifiants_viennent_du_secret(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LSASAF_IDENTIFIANTS_FILE", str(tmp_path / "absent"))
        with pytest.raises(feux_mtg.IdentifiantsAbsents):
            feux_mtg.lire_identifiants()
        (tmp_path / "lsa").write_text("compte:mot:de:passe\n")
        monkeypatch.setenv("LSASAF_IDENTIFIANTS_FILE", str(tmp_path / "lsa"))
        assert feux_mtg.lire_identifiants() == ("compte", "mot:de:passe")


class TestRegroupement:
    T0 = datetime.datetime(2026, 7, 22, 10, 40, tzinfo=UTC)

    def test_les_pixels_voisins_font_un_feu_les_lointains_un_autre(self):
        detections = [detection(self.T0, 44.87, -0.98, 10), detection(self.T0, 44.90, -1.02, 20),
                      detection(self.T0, 46.0, 3.0, 5)]
        groupes = feux_mtg.regrouper(detections)
        assert sorted(len(g) for g in groupes) == [1, 2]

    def test_la_courbe_la_puissance_et_la_confirmation(self):
        t1 = self.T0 + datetime.timedelta(minutes=10)
        groupe = [detection(self.T0, 44.87, -0.98, 8.4), detection(t1, 44.87, -0.98, 50), detection(t1, 44.89, -1.0, 65)]
        feu = feux_mtg.decrire(groupe, t1)
        assert feu["puissance_mw"] == pytest.approx(115) and feu["pixels"] == 2
        assert feu["puissance_max_mw"] == pytest.approx(115) and feu["instant_max"] == t1
        assert feu["confirme"] is True
        assert [p for _c, p, _n in feu["courbe"]] == [8.4, 115.0]
        assert feu["premier_vu"] == self.T0 + datetime.timedelta(minutes=8)
        seul = feux_mtg.decrire([detection(self.T0, 44.87, -0.98, 8.4)], self.T0)
        assert seul["confirme"] is False

    def test_les_sources_fixes(self):
        feu = feux_mtg.decrire([detection(self.T0, 44.87, -0.98, 40)], self.T0)
        maille = feu["mailles"][0]
        assert feux_mtg.est_source_fixe(feu, [(44.88, -0.99)], {})                # source fixe de FIRMS à 1 km
        jours = {datetime.date(2026, 7, d) for d in range(16, 23)}
        assert feux_mtg.est_source_fixe(feu, [], {maille: (jours, 60.0)})         # tous les jours, faible
        assert not feux_mtg.est_source_fixe(feu, [], {maille: (jours, 3300.0)})   # un grand feu qui dure
        assert not feux_mtg.est_source_fixe(feu, [], {maille: ({datetime.date(2026, 7, 22)}, 60.0)})


@pytest.mark.django_db
class TestContexte:
    MAINTENANT = datetime.datetime(2026, 7, 24, 17, 0, tzinfo=UTC)

    def _feu(self, puissances, statut="actif"):
        creneaux = [self.MAINTENANT - datetime.timedelta(minutes=10 * (len(puissances) - 1 - i)) for i in range(len(puissances))]
        feu = feux_mtg.decrire([detection(c, 44.66, -1.04, p) for c, p in zip(creneaux, puissances)], self.MAINTENANT)
        feu["statut"] = statut
        return feu

    def _cellule(self):
        return CelluleOrage.objects.create(
            identifiant="c1", heure_image=self.MAINTENANT, centre=Point(-1.04, 44.66, srid=4326),
            contour=Polygon.from_bbox((-1.1, 44.6, -0.98, 44.72)), ligne=0, colonne=0, max_mmh=40, moyenne_mmh=20, surface_km2=150, releve_le=self.MAINTENANT,
            eclairs=0, doppler_divergence={"delta_v_ms": 22})

    def test_un_orage_au_dessus_d_un_feu_qui_faiblit_le_masque(self):
        cellule = self._cellule()
        feu = self._feu([13000, 12200, 7500, 6100])
        ctx = feux_mtg.contexte(feu, [cellule], [(44.67, -1.03)], None, self.MAINTENANT)
        assert ctx["orage"]["au_dessus"] is True and ctx["orage"]["rafale_descendante"] is True
        assert ctx["eclairs_30_min"] == 1
        assert ctx["masque_par_nuage"] is True

    def test_sans_orage_une_baisse_n_est_pas_un_masque(self):
        ctx = feux_mtg.contexte(self._feu([13000, 6100]), [], [], None, self.MAINTENANT)
        assert ctx["orage"] is None and ctx["masque_par_nuage"] is False

    def test_le_feu_est_compare_au_seuil_de_son_endroit(self):
        valeurs = {"pft_gw": 213, "c_haines": 9.8, "palier": 2, "potentiel": "élevé"}
        ctx = feux_mtg.contexte(self._feu([25000]), [], [], (self.MAINTENANT, valeurs), self.MAINTENANT)
        assert ctx["potentiel"]["puissance_estimee_gw"] == [125, 250]
        assert ctx["potentiel"]["atteint_le_seuil"] is True
        ctx = feux_mtg.contexte(self._feu([5000]), [], [], (self.MAINTENANT, valeurs), self.MAINTENANT)
        assert ctx["potentiel"]["atteint_le_seuil"] is False


@pytest.mark.django_db
class TestReleve:
    MAINTENANT = datetime.datetime(2026, 7, 22, 11, 10, tzinfo=UTC)

    @pytest.fixture(autouse=True)
    def identifiants(self, monkeypatch, tmp_path):
        (tmp_path / "lsa").write_text("compte:secret")
        monkeypatch.setenv("LSASAF_IDENTIFIANTS_FILE", str(tmp_path / "lsa"))

    def _serveur(self, fichiers):
        """fichiers : {créneau: octets}. Rend (fichiers_disponibles, session.get) simulés."""
        chemins = {c: f"/PRODUCTS/x/LSA-509_MTG_MTFRPPIXEL-ListProduct_MTG-FD_{c:%Y%m%d%H%M}.csv.gz" for c in fichiers}

        def get(url, timeout=None):
            for c, chemin in chemins.items():
                if url.endswith(chemin):
                    return mock.Mock(status_code=200, content=fichiers[c], raise_for_status=lambda: None)
            raise AssertionError(url)
        return [(c, chemins[c]) for c in sorted(fichiers)], get

    def test_la_source_tourne_avec_les_orages(self):
        assert "FEUX_MTG" in sources_ouvertes.SOURCES_EN_CONTINU

    def test_sans_identifiants_rien_ne_part(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LSASAF_IDENTIFIANTS_FILE", str(tmp_path / "absent"))
        assert sources_ouvertes.relever_source("FEUX_MTG", forcer=True) == "échec"
        assert sources_ouvertes.etat("FEUX_MTG").erreur == "aucune clé sur cette machine"

    def test_le_depart_du_feu_de_saumos(self):
        t1, t2 = datetime.datetime(2026, 7, 22, 10, 40, tzinfo=UTC), datetime.datetime(2026, 7, 22, 10, 50, tzinfo=UTC)
        fichiers = {
            t1: liste([(t1 + datetime.timedelta(minutes=8), *SAUMOS, 8.4, 0.83)]),
            t2: liste([(t2 + datetime.timedelta(minutes=8), 44.87, -0.98, 51.6, 0.99),
                       (t2 + datetime.timedelta(minutes=8), 44.89, -1.0, 63.5, 0.97),
                       (t2 + datetime.timedelta(minutes=8), 47.0, 2.0, 30.0, 0.9)]),
        }
        disponibles, get = self._serveur(fichiers)
        with mock.patch.object(feux_mtg, "fichiers_disponibles", return_value=disponibles), \
             mock.patch("requests.Session.get", side_effect=get):
            assert feux_mtg.relever(self.MAINTENANT) == 2
            # Deuxième passage : rien de nouveau à lire.
            assert feux_mtg.relever(self.MAINTENANT) == 2
        assert ProduitFeuMTG.objects.count() == 2 and DetectionFeuMTG.objects.count() == 4
        saumos = FeuSuivi.objects.get(pixels=2)
        assert saumos.confirme and saumos.statut == "actif"
        assert saumos.puissance_mw == pytest.approx(115.1)
        assert [p for _c, p, _n in saumos.courbe] == [8.4, 115.1]
        autre = FeuSuivi.objects.exclude(pk=saumos.pk).get()
        assert not autre.confirme

    def test_un_feu_proche_d_une_usine_est_une_source_fixe(self):
        FoyerActif.objects.create(reference="f1", date=self.MAINTENANT, location=Point(2.0, 47.0, srid=4326),
                                  source_fixe=True, releve_le=self.MAINTENANT)
        t1 = datetime.datetime(2026, 7, 22, 10, 50, tzinfo=UTC)
        disponibles, get = self._serveur({t1: liste([(t1, 47.0, 2.0, 30.0, 0.9)])})
        with mock.patch.object(feux_mtg, "fichiers_disponibles", return_value=disponibles), \
             mock.patch("requests.Session.get", side_effect=get):
            feux_mtg.relever(self.MAINTENANT)
        assert FeuSuivi.objects.get().source_fixe is True

    def test_les_detections_d_il_y_a_plus_d_une_semaine_sont_retirees(self):
        vieux = self.MAINTENANT - datetime.timedelta(days=8)
        ProduitFeuMTG.objects.create(creneau=vieux, releve_le=vieux)
        DetectionFeuMTG.objects.create(creneau=vieux, instant=vieux, location=Point(0, 45, srid=4326), puissance_mw=5)
        with mock.patch.object(feux_mtg, "fichiers_disponibles", return_value=[]):
            feux_mtg.relever(self.MAINTENANT)
        assert not DetectionFeuMTG.objects.exists() and not ProduitFeuMTG.objects.exists()

    def test_le_potentiel_et_la_foudre_entrent_dans_la_fiche(self):
        from core.tests.test_orages_de_feu import SAUMOS_24_JUILLET, grilles

        resultat = orages_de_feu.calculer(*grilles(SAUMOS_24_JUILLET))
        PotentielOrageFeu.objects.create(echeance=self.MAINTENANT, calcul=self.MAINTENANT, largeur=1, hauteur=1,
                                         ouest=-0.98, nord=44.87, grilles=orages_de_feu.coder(resultat), image=b"",
                                         releve_le=self.MAINTENANT)
        ImpactFoudre.objects.create(instant=self.MAINTENANT - datetime.timedelta(minutes=5),
                                    location=Point(-0.97, 44.88, srid=4326))
        t1 = datetime.datetime(2026, 7, 22, 11, 0, tzinfo=UTC)
        disponibles, get = self._serveur({t1: liste([(t1, *SAUMOS, 3000.0, 1.0)])})
        with mock.patch.object(feux_mtg, "fichiers_disponibles", return_value=disponibles), \
             mock.patch("requests.Session.get", side_effect=get):
            feux_mtg.relever(self.MAINTENANT)
        ctx = FeuSuivi.objects.get().contexte
        assert ctx["eclairs_30_min"] == 1
        assert ctx["potentiel"]["pft_gw"] > 0 and ctx["potentiel"]["puissance_estimee_gw"] == [15, 30]


@pytest.mark.django_db
class TestAPI:
    def _feu(self, identifiant, lat, lon, mw, fixe=False, statut="actif"):
        maintenant = timezone.now()
        return FeuSuivi.objects.create(
            identifiant=identifiant, premier_vu=maintenant, dernier_vu=maintenant, centre=Point(lon, lat, srid=4326),
            statut=statut, puissance_mw=mw, puissance_max_mw=mw, instant_max=maintenant, pixels=3, confirme=True,
            source_fixe=fixe, courbe=[[maintenant.isoformat(), mw, 3]], contexte={}, calcule_le=maintenant)

    def test_la_france_entiere_sans_les_sources_fixes(self, client):
        self._feu("a", 44.87, -0.98, 3300)
        self._feu("b", 46.0, 3.0, 50, statut="plus vu")
        self._feu("c", 47.0, 2.0, 400)
        self._feu("usine", 51.0, 2.3, 70, fixe=True)
        r = client.get("/api/feux-suivis/", {"france": 1}).json()
        assert [f["identifiant"] for f in r["resultats"]] == ["a", "c", "b"]      # actifs d'abord
        assert r["sources_fixes"] == 1 and r["source"] == feux_mtg.ATTRIBUTION
        r = client.get("/api/feux-suivis/", {"france": 1, "fixes": 1}).json()
        assert "usine" in [f["identifiant"] for f in r["resultats"]]

    def test_autour_d_un_point(self, client):
        self._feu("a", 44.87, -0.98, 3300)
        self._feu("c", 47.0, 2.0, 400)
        r = client.get("/api/feux-suivis/", {"lat": 44.8, "lon": -1.0, "rayon_km": 30}).json()
        assert [f["identifiant"] for f in r["resultats"]] == ["a"]
        assert r["resultats"][0]["distance_km"] == pytest.approx(7.8, abs=0.5)
