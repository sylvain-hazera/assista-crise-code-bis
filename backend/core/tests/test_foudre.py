"""Foudre vue par le satellite MTG (core/foudre.py, 19/11/2026).

Le produit est fabriqué avec la structure relevée sur un vrai produit « LI Lightning Flashes »
le 19/11/2026 : archive ZIP, NetCDF-4 avec `latitude`/`longitude` en entiers (scale_factor
0,0027, _FillValue -32767), `flash_time` en secondes depuis 2000, `flash_duration`, `radiance`."""
import datetime
import io
import zipfile
from unittest import mock

import numpy
import pytest
from django.contrib.gis.geos import Point, Polygon
from django.utils import timezone

from core import foudre, sources_ouvertes
from core.models import ImpactFoudre, ProduitFoudre

ECHELLE = 0.0027


def produit(eclairs, nom="W_XX-EUMETSAT-Darmstadt,LI-2-LFL--FD--CHK-BODY_0001.nc"):
    """[(lat, lon, instant)] -> archive ZIP comme celle du Data Store."""
    import h5py
    tampon = io.BytesIO()
    with h5py.File(tampon, "w") as h:
        lat = numpy.array([round(e[0] / ECHELLE) if e[0] is not None else -32767 for e in eclairs], dtype="int16")
        lon = numpy.array([round(e[1] / ECHELLE) if e[1] is not None else -32767 for e in eclairs], dtype="int16")
        for nom_var, valeurs in (("latitude", lat), ("longitude", lon)):
            v = h.create_dataset(nom_var, data=valeurs)
            v.attrs["scale_factor"] = numpy.array([ECHELLE], dtype="float32")
            v.attrs["add_offset"] = numpy.array([0.0], dtype="float32")
            v.attrs["_FillValue"] = numpy.array([-32767], dtype="int16")
        h.create_dataset("flash_time", data=numpy.array(
            [(e[2] - foudre.EPOQUE).total_seconds() for e in eclairs], dtype="float64"))
        h.create_dataset("flash_duration", data=numpy.full(len(eclairs), 120, dtype="uint16"))
        h.create_dataset("radiance", data=numpy.full(len(eclairs), 900, dtype="uint16"))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(nom, tampon.getvalue())
        z.writestr("manifest.xml", "<manifest/>")
    return archive.getvalue()


T0 = datetime.datetime(2026, 11, 19, 20, 50, tzinfo=datetime.timezone.utc)


def test_seuls_les_eclairs_de_nos_emprises_sont_gardes():
    eclairs = foudre.lire_eclairs(produit([
        (45.64, -1.55, T0), (47.25, -3.67, T0 + datetime.timedelta(seconds=30)),
        (10.0, 20.0, T0),                    # Afrique : hors emprise
        (None, None, T0),                    # valeur manquante
    ]))
    assert [(e["latitude"], e["longitude"]) for e in eclairs] == [
        (pytest.approx(45.64, abs=0.003), pytest.approx(-1.55, abs=0.003)),
        (pytest.approx(47.25, abs=0.003), pytest.approx(-3.67, abs=0.003))]
    assert eclairs[1]["instant"] == T0 + datetime.timedelta(seconds=30)
    assert eclairs[0]["duree_ms"] == 120


def test_les_eclairs_de_la_reunion_sont_gardes():
    eclairs = foudre.lire_eclairs(produit([
        (-21.10, 55.50, T0),                 # sur l'île
        (-21.90, 54.80, T0),                 # en mer, l'orage arrive
        (-20.20, 57.50, T0),                 # Maurice : hors emprise
    ]))
    assert [(round(e["latitude"], 1), round(e["longitude"], 1)) for e in eclairs] == [(-21.1, 55.5), (-21.9, 54.8)]


def _reponses(produits):
    """Faux Data Store : jeton, recherche, téléchargements."""
    def get(url, headers=None, timeout=None, params=None):
        if url == foudre.URL_RECHERCHE:
            return mock.Mock(status_code=200, raise_for_status=lambda: None, json=lambda: {"features": [
                {"id": ident, "properties": {"date": f"{debut:%Y-%m-%dT%H:%M:%SZ}/{fin:%Y-%m-%dT%H:%M:%SZ}",
                                             "links": {"data": [{"href": f"https://exemple.invalide/{ident}"}]}}}
                for ident, debut, fin, _ in produits]})
        ident = url.rsplit("/", 1)[-1]
        contenu = next(p[3] for p in produits if p[0] == ident)
        return mock.Mock(status_code=200, raise_for_status=lambda: None, content=contenu)
    poste = mock.Mock(return_value=mock.Mock(raise_for_status=lambda: None, json=lambda: {"access_token": "x"}))
    return get, poste


@pytest.mark.django_db
def test_releve_sans_double_lecture(tmp_path, monkeypatch):
    secret = tmp_path / "eumetsat_api"
    secret.write_text("cle-essai:secret-essai")
    monkeypatch.setenv("EUMETSAT_API_FILE", str(secret))
    produits = [("P1", T0, T0 + datetime.timedelta(minutes=10), produit([(45.64, -1.55, T0)])),
                ("P2", T0, T0 + datetime.timedelta(minutes=10), produit([(47.25, -3.67, T0)]))]
    get, poste = _reponses(produits)
    maintenant = T0 + datetime.timedelta(minutes=20)
    with mock.patch.object(foudre.requests, "get", side_effect=get), mock.patch.object(foudre.requests, "post", poste):
        assert foudre.relever(maintenant) == 2
        assert foudre.relever(maintenant) == 0          # mêmes produits : pas relus
    assert ImpactFoudre.objects.count() == 2 and ProduitFoudre.objects.count() == 2
    assert poste.call_args.kwargs["auth"] == ("cle-essai", "secret-essai")
    with mock.patch.object(foudre.requests, "get", side_effect=get), mock.patch.object(foudre.requests, "post", poste):
        with pytest.raises(RuntimeError, match="récent"):
            foudre.relever(T0 + datetime.timedelta(hours=2))


def test_sans_identifiants(tmp_path, monkeypatch):
    monkeypatch.setenv("EUMETSAT_API_FILE", str(tmp_path / "absent"))
    with pytest.raises(foudre.IdentifiantsAbsents):
        foudre.lire_identifiants()


@pytest.mark.django_db
def test_vue_et_compte_sous_une_cellule(client):
    for i, (lat, lon) in enumerate([(45.64, -1.55), (45.65, -1.56), (48.0, 2.0)]):
        ImpactFoudre.objects.create(instant=T0 + datetime.timedelta(minutes=i), location=Point(lon, lat, srid=4326))
    r = client.get("/api/foudre/", {"minutes": 60})
    assert r.status_code == 200 and len(r.json()["features"]) == 3
    assert r.json()["features"][0]["properties"]["age_min"] == 0
    zone = Polygon.from_bbox((-1.6, 45.6, -1.5, 45.7))
    zone.srid = 4326
    assert foudre.eclairs_dans(zone, T0 - datetime.timedelta(minutes=5)).count() == 2


def test_la_foudre_est_relevee_par_le_service_et_non_par_le_cron():
    assert "FOUDRE_MTG" in sources_ouvertes.SOURCES_EN_CONTINU


# ── Blitzortung, à titre indicatif ────────────────────────────────────────────

def test_lecture_d_un_impact_blitzortung():
    import struct
    from core.management.commands.ecouter_blitzortung import lire_impact
    ns = int(T0.timestamp() * 1e9)
    instant, lat, lon = lire_impact(struct.pack("<ffq", 48.278, 6.352, ns))
    assert instant == T0 and lat == pytest.approx(48.278, abs=1e-4) and lon == pytest.approx(6.352, abs=1e-4)
    assert lire_impact(struct.pack("<ffq", 10.0, 20.0, ns)) is None        # hors emprise
    assert lire_impact(b"trop court") is None


@pytest.mark.django_db
def test_vue_blitzortung_porte_la_mention(client):
    from core.models import ImpactBlitzortung
    ImpactBlitzortung.objects.create(instant=timezone.now(), location=Point(2.35, 48.85, srid=4326))
    r = client.get("/api/blitzortung/", {"minutes": 30})
    assert r.status_code == 200 and len(r.json()["features"]) == 1
    assert r.json()["mention"] == "Informations Blitzortung données à titre indicatif"
    assert "FOUDRE_BLITZORTUNG" in sources_ouvertes.SOURCES_EN_CONTINU


@pytest.mark.django_db
def test_un_produit_cite_deux_fois_n_est_lu_qu_une_fois(tmp_path, monkeypatch):
    secret = tmp_path / "eumetsat_api"
    secret.write_text("cle-essai:secret-essai")
    monkeypatch.setenv("EUMETSAT_API_FILE", str(secret))
    archive = produit([(45.64, -1.55, T0)])
    double = [("P1", T0, T0 + datetime.timedelta(minutes=10), archive)] * 2
    get, poste = _reponses(double)
    with mock.patch.object(foudre.requests, "get", side_effect=get), mock.patch.object(foudre.requests, "post", poste):
        assert foudre.relever(T0 + datetime.timedelta(minutes=20)) == 1
    assert ImpactFoudre.objects.count() == 1 and ProduitFoudre.objects.count() == 1


@pytest.mark.django_db
def test_les_doublons_deja_en_base_sont_retires():
    for _ in range(3):
        ImpactFoudre.objects.create(instant=T0, location=Point(-1.55, 45.64, srid=4326))
    ImpactFoudre.objects.create(instant=T0, location=Point(-1.56, 45.64, srid=4326))
    assert foudre.supprimer_doublons() == 2
    assert ImpactFoudre.objects.count() == 2


@pytest.mark.django_db
def test_un_rattrapage_n_est_pas_une_panne(tmp_path, monkeypatch):
    """Service arrêté deux heures : les produits lus sont anciens, mais il en arrive."""
    secret = tmp_path / "eumetsat_api"
    secret.write_text("cle-essai:secret-essai")
    monkeypatch.setenv("EUMETSAT_API_FILE", str(secret))
    produits = [("P1", T0, T0 + datetime.timedelta(minutes=10), produit([(45.64, -1.55, T0)]))]
    get, poste = _reponses(produits)
    with mock.patch.object(foudre.requests, "get", side_effect=get), mock.patch.object(foudre.requests, "post", poste):
        assert foudre.relever(T0 + datetime.timedelta(hours=2)) == 1
