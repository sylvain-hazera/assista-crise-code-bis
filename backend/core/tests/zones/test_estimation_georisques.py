"""Estimation BAN du référencement des dégâts, filtrée sur les zones de débordement officielles
Géorisques (option `georisques`, demande utilisateur du 20/10/2026)."""
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Polygon
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Crisis, Habitation

ZONE = Polygon(((5.0, 45.0), (5.01, 45.0), (5.01, 45.01), (5.0, 45.01), (5.0, 45.0)), srid=4326)


def _adresse(n, lon, lat):
    return {"adresse": f"{n} rue Test", "lon": lon, "lat": lat, "parcelle_cadastrale": None, "ban_id": f"ban-{n}"}


def _scan_simule(commune_code, polygone_limite=None):
    # Même filtrage que scanner_ban_commune : seules les adresses dans le polygone sont gardées.
    from django.contrib.gis.geos import Point
    adresses = [_adresse(1, 5.005, 45.005), _adresse(2, 5.02, 45.005)]   # 1 dedans, 1 dehors
    if polygone_limite is not None:
        adresses = [a for a in adresses if polygone_limite.contains(Point(a["lon"], a["lat"], srid=4326))]
    return {"adresses": adresses, "voies_totales": 1, "voies_en_echec": 0, "erreur": None}


@pytest.fixture
def admin_client(create_user):
    admin = create_user(username="admin-geo@test.fr", email="admin-geo@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def crise():
    return Crisis.objects.create(name="Crue test", type="INONDATION", location="POINT (5.005 45.005)")


@pytest.mark.django_db
class TestEstimationGeorisques:

    def _post(self, client, crise, **extra):
        return client.post(reverse("habitation-estimation-ban"),
                           {"commune_code": "99020", "crise": str(crise.id), **extra}, format="json")

    def test_seules_les_adresses_en_zone_sont_referencees(self, admin_client, crise):
        with patch("core.habitations.scanner_ban_commune", side_effect=_scan_simule), \
             patch("core.habitations.zones_georisques", return_value={"polygone": ZONE, "erreur": None}):
            reponse = self._post(admin_client, crise, georisques="ALEA_SYNT_01_02MOY_FXX")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["creees"] == 1
        assert reponse.data["filtre_georisques"]
        assert list(Habitation.objects.values_list("ban_id", flat=True)) == ["ban-1"]

    def test_sans_filtre_toutes_les_adresses(self, admin_client, crise):
        with patch("core.habitations.scanner_ban_commune", side_effect=_scan_simule):
            reponse = self._post(admin_client, crise)
        assert reponse.status_code == 200
        assert reponse.data["creees"] == 2

    def test_commune_hors_tri_message_explicite(self, admin_client, crise):
        with patch("core.habitations.scanner_ban_commune", side_effect=_scan_simule), \
             patch("core.habitations.zones_georisques", return_value={"polygone": None, "erreur": None}):
            reponse = self._post(admin_client, crise, georisques="ALEA_SYNT_01_02MOY_FXX")
        assert reponse.status_code == 422
        assert "TRI" in reponse.data["error"]
        assert not Habitation.objects.exists()

    def test_scenario_inconnu_refuse(self, admin_client, crise):
        reponse = self._post(admin_client, crise, georisques="ALEA_SYNT_99")
        assert reponse.status_code == 400


@pytest.mark.django_db
class TestCarteGeorisques:

    def test_geometrie_renvoyee_et_mise_en_cache(self, admin_client):
        from django.core.cache import cache
        cache.clear()
        with patch("core.habitations.zones_georisques", return_value={"polygone": ZONE, "erreur": None}) as zones:
            url = reverse("simulation_inondation_georisques", args=["99030"])
            r1 = admin_client.get(url, {"couche": "ALEA_SYNT_01_02MOY_FXX"})
            r2 = admin_client.get(url, {"couche": "ALEA_SYNT_01_02MOY_FXX"})
        assert r1.status_code == 200
        assert r1.data["geometrie"]["type"] == "Polygon"
        assert r2.data["geometrie"] == r1.data["geometrie"]
        assert zones.call_count == 1   # 2e appel servi par le cache

    def test_hors_tri_geometrie_nulle(self, admin_client):
        from django.core.cache import cache
        cache.clear()
        with patch("core.habitations.zones_georisques", return_value={"polygone": None, "erreur": None}):
            r = admin_client.get(reverse("simulation_inondation_georisques", args=["99031"]), {"couche": "ALEA_SYNT_03_02MOY_FXX"})
        assert r.status_code == 200
        assert r.data["geometrie"] is None

    def test_couche_inconnue(self, admin_client):
        r = admin_client.get(reverse("simulation_inondation_georisques", args=["99032"]), {"couche": "XYZ"})
        assert r.status_code == 400
