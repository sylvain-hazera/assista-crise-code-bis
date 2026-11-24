"""Un point d'eau se trouve sur le terrain par son adresse la plus proche, ses coordonnées GPS et
Lambert 93 (demande du 24/11/2026)."""
import pytest
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.utils import timezone

from core import circuit_eau, points_eau
from core.models import AdresseBAN, Commune, PointEauIncendie

CACHE_LOCAL = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "pei-localisation"}}


@pytest.fixture
def borne(db):
    return PointEauIncendie.objects.create(source="OSM", ref_source="node/1", departement_code="43", insee="43157",
                                           type_pei="PI", ref_terrain="12", location=Point(3.88580, 45.04340, srid=4326),
                                           releve_le=timezone.now())


@override_settings(CACHES=CACHE_LOCAL)
def test_lambert_93_au_metre(borne):
    x, y = points_eau.lambert93(borne.location)
    # Le Puy-en-Velay : environ X 770 km, Y 6 437 km en Lambert 93.
    assert 765_000 < x < 775_000 and 6_430_000 < y < 6_445_000


@override_settings(CACHES=CACHE_LOCAL)
def test_l_adresse_la_plus_proche_et_le_nom_verbeux(borne):
    AdresseBAN.objects.create(ban_id="43157_0001_00012", commune_code="43157", commune_nom="Le Puy-en-Velay",
                              code_postal="43000", numero="12", voie="Rue de la Gare",
                              location=Point(3.88620, 45.04340, srid=4326), modifie_le=timezone.now())
    loc = points_eau.localisation(borne.location, borne.insee)
    assert loc["adresse"].startswith("à 3") and "12 Rue de la Gare, 43000 Le Puy-en-Velay" in loc["adresse"]
    assert loc["gps"] == "45.04340, 3.88580" and set(loc["lambert93"]) == {"x", "y"}
    assert circuit_eau.nom_du_point(borne).startswith("Poteau d'incendie n° 12 — à 3")
    donnees = points_eau.en_dict(borne, 0.3, avec_localisation=True)
    assert donnees["nom"] == "Poteau d'incendie n° 12" and donnees["adresse"] == loc["adresse"]


@override_settings(CACHES=CACHE_LOCAL)
def test_sans_adresse_proche_la_commune(db):
    Commune.objects.update_or_create(code="43999", defaults={"nom": "Commune d'essai", "centre_latitude": 45.2, "centre_longitude": 3.7})
    citerne = PointEauIncendie.objects.create(source="SDIS", ref_source="43-9", departement_code="43", insee="43999",
                                              type_pei="CI", location=Point(3.70001, 45.20001, srid=4326), releve_le=timezone.now())
    assert points_eau.localisation(citerne.location, "43999")["adresse"] == "Commune d'essai (43999)"
    assert points_eau.nom_du_point(citerne) == "Citerne ou réserve n° 43-9"
