"""Propagation radio (28/11/2026) : ondes courtes d'après la NOAA (core/propagation.py), conduits
troposphériques estimés sur le profil ARPEGE (core/tropo.py). Aucun appel réseau."""
import datetime

import numpy
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import propagation, tropo
from core.models import PropagationTropo, ReleveEspace

MAINTENANT = datetime.datetime(2026, 11, 28, 9, 0, tzinfo=datetime.timezone.utc)

# Extraits réels de services.swpc.noaa.gov du 28/11/2026, raccourcis.
BRUT = {
    "echelles": {
        "-1": {"DateStamp": "2026-11-27", "R": {"Scale": "0"}, "S": {"Scale": "0"}, "G": {"Scale": "0"}},
        "0": {"DateStamp": "2026-11-28", "TimeStamp": "08:23:00", "R": {"Scale": "0", "Text": "none"},
              "S": {"Scale": "0", "Text": "none"}, "G": {"Scale": "0", "Text": "none"}},
        "1": {"DateStamp": "2026-11-28", "R": {"Scale": None, "MinorProb": "1", "MajorProb": "1"}, "G": {"Scale": "0"}},
        "2": {"DateStamp": "2026-11-29", "R": {"Scale": None, "MinorProb": "5", "MajorProb": "1"}, "G": {"Scale": "1"}},
        "3": {"DateStamp": "2026-11-30", "R": {"Scale": None, "MinorProb": "5", "MajorProb": "1"}, "G": {"Scale": "0"}},
    },
    "kp": [{"time_tag": "2026-11-28T00:00:00", "Kp": 2.0}, {"time_tag": "2026-11-28T03:00:00", "Kp": 2.67}],
    "kp_prevu": [{"time_tag": "2026-11-28T03:00:00", "kp": 2.67, "observed": "observed"},
                 {"time_tag": "2026-11-29T00:00:00", "kp": 4.33, "observed": "predicted"},
                 {"time_tag": "2026-11-30T00:00:00", "kp": 1.67, "observed": "predicted"}],
    "flux": [{"flux": 91, "time_tag": "2026-11-27T20:00:00"}],
    "eruptions": [
        {"max_time": "2026-11-28T06:41:00Z", "max_class": "B9.7"},
        {"max_time": "2026-11-27T22:10:00Z", "max_class": "C2.1"},
        {"max_time": "2026-11-25T10:00:00Z", "max_class": "M3.0"},          # plus de 24 h : ignorée
    ],
}


class TestEchelles:
    def test_kp_vers_g(self):
        assert [propagation.kp_vers_g(k) for k in (2.67, 5, 6.33, 7, 8, 9)] == [0, 1, 2, 3, 4, 5]

    def test_classe_vers_r(self):
        assert [propagation.classe_vers_r(c) for c in ("C9.9", "M1.0", "M5.2", "X1.0", "X12", "X25")] == [0, 1, 2, 3, 4, 5]


class TestResume:
    def test_les_valeurs_de_la_noaa_telles_quelles(self):
        r = propagation.resumer(BRUT, MAINTENANT)
        assert r["kp"] == 2.67 and r["kp_max_prevu_3j"] == 4.33 and r["flux_10cm"] == 91
        assert r["eruption_max_24h"]["classe"] == "C2.1"
        assert r["g"] == 0 and r["r"] == 0 and r["effet_r"].startswith("Pas de coupure")
        assert [p["g"] for p in r["prevision"]] == [0, 1, 0]
        assert r["prevision"][1]["r_mineur_pct"] == 5

    def test_sans_echelle_officielle_on_deduit_des_mesures(self):
        brut = dict(BRUT, echelles={}, kp=[{"time_tag": "x", "Kp": 7.0}],
                    eruptions=[{"max_time": "2026-11-28T08:00:00Z", "max_class": "X2.0"}])
        r = propagation.resumer(brut, MAINTENANT)
        assert r["g"] == 3 and r["r"] == 3 and "intermittente" in r["effet_g"]


class _Reponse:
    def __init__(self, donnees):
        self.donnees = donnees

    def raise_for_status(self):
        pass

    def json(self):
        return self.donnees


class _Client:
    def __init__(self):
        self.headers = {}
        self.appels = []

    def get(self, url, timeout):
        self.appels.append(url)
        cle = next(c for c, chemin in propagation.FICHIERS.items() if url.endswith(chemin))
        return _Reponse(BRUT[cle])


@pytest.mark.django_db
def test_releve_et_point_d_acces_public():
    client = _Client()
    assert propagation.relever(MAINTENANT, client=client) == 1
    assert len(client.appels) == 5 and all(u.startswith("https://services.swpc.noaa.gov/") for u in client.appels)
    assert client.headers["User-Agent"] == "client-meteo"
    assert ReleveEspace.objects.get().donnees["kp"] == 2.67
    r = APIClient().get(reverse("carte_ouverte_propagation"))
    assert r.status_code == 200 and r.data["hf"]["flux_10cm"] == 91
    assert r.data["tropo"]["nos_estimations"] is True and r.data["tropo"]["echeances"] == []


def _profil(inversion):
    """Une colonne 1 × 1 : sol à 0 m, 1013 hPa ; avec `inversion`, air chaud et sec à 300 m
    au-dessus d'air frais et humide (le cas classique du conduit)."""
    un = lambda v: numpy.array([[v]], dtype=float)  # noqa: E731
    sol = {"ps": un(101300.0), "zsol": un(0.0), "t2": un(12.0), "hr2": un(95.0 if inversion else 70.0)}
    if inversion:
        niveaux = {1000: {"t": un(20.0), "hr": un(15.0), "geo": un(110 * 9.80665)},
                   975: {"t": un(19.0), "hr": un(15.0), "geo": un(320 * 9.80665)},
                   950: {"t": un(17.0), "hr": un(15.0), "geo": un(540 * 9.80665)}}
    else:
        # Atmosphère standard : −6,5 °C/km, humidité modérée.
        niveaux = {1000: {"t": un(11.3), "hr": un(68.0), "geo": un(110 * 9.80665)},
                   950: {"t": un(8.5), "hr": un(65.0), "geo": un(540 * 9.80665)},
                   900: {"t": un(5.3), "hr": un(60.0), "geo": un(990 * 9.80665)}}
    return sol, niveaux


class TestTropo:
    def test_inversion_donne_un_conduit(self):
        g = tropo.calculer(*_profil(True))
        assert g["gradient"][0, 0] <= tropo.CONDUIT and g["rang"][0, 0] == 2

    def test_atmosphere_standard_rien_a_peindre(self):
        g = tropo.calculer(*_profil(False))
        assert -79 < g["gradient"][0, 0] < 0 and g["rang"][0, 0] == 0

    def test_niveau_sous_le_relief_ignore(self):
        sol, niveaux = _profil(True)
        sol["ps"] = numpy.array([[90000.0]])          # en montagne : 1000 à 950 hPa sont sous le sol
        sol["zsol"] = numpy.array([[1000.0]])
        g = tropo.calculer(sol, niveaux)
        assert numpy.isnan(g["gradient"][0, 0]) and g["rang"][0, 0] == 0

    def test_coder_decoder(self):
        g = tropo.calculer(*_profil(True))
        relu = tropo.decoder(tropo.coder(g), 1, 1)
        assert relu["rang"][0, 0] == 2 and abs(relu["gradient"][0, 0] - round(g["gradient"][0, 0])) < 1

    @pytest.mark.django_db
    def test_enregistre_et_sert_l_image(self):
        sol, niveaux = _profil(True)
        echeance = timezone.now().replace(minute=0, second=0, microsecond=0)
        tropo.enregistrer(echeance, echeance - datetime.timedelta(hours=6), sol, niveaux, 2.0, 48.0)
        assert PropagationTropo.objects.count() == 1
        client = APIClient()
        d = client.get(reverse("carte_ouverte_propagation")).data
        assert d["tropo"]["echeances"][0]["classe_max"] == 2
        image = client.get(reverse("carte_ouverte_tropo_image"), {"echeance": echeance.isoformat()})
        assert image.status_code == 200 and image["Content-Type"] == "image/png"
