"""Partie publique « pour les copains » (28/11/2026) : ce qu'on montre sans connexion, et surtout
ce qu'on ne montre pas (core/carte_ouverte.py)."""
import datetime
import json
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, CompagnonMeshtastic, CompteurPaquetsMeshtastic, ContactMeshCore, ContactMeshtastic,
    CouvertureRadioSite, Institution, InstitutionType, MesureTelemetrieMeshtastic, NoeudPublicMeshCore, RelaisMeshCore,
)


@pytest.fixture(autouse=True)
def _vider_cache():
    cache.clear()
    yield
    cache.clear()


def _public(cle, nom, role="repeater", lon=2.35, lat=48.85, vu=None):
    return NoeudPublicMeshCore.objects.create(instance="https://exemple.test", pubkey_hex=cle * 32, nom=nom, role=role,
                                              location=Point(lon, lat, srid=4326), dernier_vu=vu or timezone.now(),
                                              relais_actif=True, date_import=timezone.now())


@pytest.mark.django_db
class TestRadioPublique:
    def test_repeteurs_et_rooms_seulement_sans_connexion(self, create_user):
        _public("aa", "Relais du Pilat")
        _public("bb", "Room du club", role="room")
        _public("cc", "🚫 Ne pas afficher")
        _public("dd", "Vieux relais", vu=timezone.now() - datetime.timedelta(days=60))
        compagnon = CompagnonMeshCore.objects.create(nom="Passerelle du PC")
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex="ee" * 32, type_contact="REPEATER", nom="Relais entendu",
                                       location=Point(4.3, 45.4, srid=4326), dernier_advert=timezone.now())
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex="ff" * 32, type_contact="COMPANION", nom="Téléphone de Léa",
                                       location=Point(4.31, 45.41, srid=4326), dernier_advert=timezone.now())
        # Le même répéteur entendu ET dans la cartographie : une seule fois.
        ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex="aa" * 32, type_contact="REPEATER", nom="Pilat (entendu)",
                                       location=Point(2.35, 48.85, srid=4326), dernier_advert=timezone.now())
        itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
        asso = Institution.objects.create(nom="Radio-club secret", type=itype)
        RelaisMeshCore.objects.create(nom="Relais du château d'eau", institution=asso, location=Point(4.4, 45.5, srid=4326),
                                      pubkey_hex="11" * 32, commentaire="clé de la porte chez M. X")
        mt = CompagnonMeshtastic.objects.create(nom="Pont", node_num=1)
        ContactMeshtastic.objects.create(compagnon=mt, node_num=42, long_name="Maison de Paul", location=Point(4.5, 45.5, srid=4326))

        r = APIClient().get(reverse("carte_ouverte_radio"))
        assert r.status_code == 200
        noms = sorted(f["properties"]["nom"] for f in r.data["features"])
        assert noms == ["Relais du Pilat", "Relais du château d'eau", "Relais entendu", "Room du club"]
        texte = json.dumps(r.data, ensure_ascii=False)
        for secret in ("Léa", "Paul", "Radio-club secret", "M. X", "Ne pas afficher", "Vieux relais"):
            assert secret not in texte

    def test_couverture_seulement_si_publiee(self, create_user):
        commun = dict(location=Point(4.4, 45.4, srid=4326), perte_environnement_db=12, statut="TERMINEE",
                      points=[[45.41, 4.41, 8.5, 1200]])
        cachee = CouvertureRadioSite.objects.create(nom="Toit de Paul (candidat)", **commun)
        publiee = CouvertureRadioSite.objects.create(nom="Relais du Pilat", publique=True, **commun)
        client = APIClient()
        assert [c["nom"] for c in client.get(reverse("carte_ouverte_couvertures")).data] == ["Relais du Pilat"]
        assert client.get(reverse("carte_ouverte_couverture_geojson", args=[cachee.id])).status_code == 404
        g = client.get(reverse("carte_ouverte_couverture_geojson", args=[publiee.id])).data
        assert g["features"][0]["properties"] == {"marge_db": 8.5}

    def test_publier_reserve_a_l_acces_radio_et_aux_couvertures_terminees(self, create_user):
        c = CouvertureRadioSite.objects.create(nom="Pilat", location=Point(4.4, 45.4, srid=4326), perte_environnement_db=12,
                                               statut="EN_COURS")
        anonyme = APIClient().post(f"/api/couvertures-radio/{c.id}/publier/", {"publique": True}, format="json")
        assert anonyme.status_code in (401, 403)
        admin = create_user(username="admin-radio@test.fr", email="admin-radio@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(admin)
        assert client.post(f"/api/couvertures-radio/{c.id}/publier/", {"publique": True}, format="json").status_code == 400
        c.statut = "TERMINEE"
        c.save()
        r = client.post(f"/api/couvertures-radio/{c.id}/publier/", {"publique": True}, format="json")
        assert r.status_code == 200 and r.data["publique"] is True


@pytest.mark.django_db
class TestSanteDuReseau:
    def test_agregee_sans_rien_qui_identifie(self):
        maintenant = timezone.now()
        for n, (nom, num, occupation) in enumerate((("Passerelle chez Paul", 101, 10.0), ("Passerelle du PC", 102, 20.0))):
            c = CompagnonMeshtastic.objects.create(nom=nom, node_num=num)
            MesureTelemetrieMeshtastic.objects.create(compagnon=c, node_num=num, horodatage=maintenant - datetime.timedelta(minutes=5),
                                                      occupation_canal=occupation, temps_antenne_tx=1.0)
            # Un voisin entendu par la passerelle : sa télémétrie ne compte pas.
            MesureTelemetrieMeshtastic.objects.create(compagnon=c, node_num=999, horodatage=maintenant - datetime.timedelta(minutes=5),
                                                      occupation_canal=90.0)
            CompteurPaquetsMeshtastic.objects.create(compagnon=c, heure=maintenant.replace(minute=0, second=0, microsecond=0),
                                                     type_paquet="TEXT_MESSAGE_APP", nombre=5 + n)
        r = APIClient().get(reverse("carte_ouverte_sante"))
        assert r.status_code == 200
        m = r.data["meshtastic"]
        assert m["passerelles"] == "plusieurs" and m["occupation_actuelle"] == 15.0
        assert m["par_type"] == [{"type": "TEXT_MESSAGE_APP", "nombre": 11}]
        texte = json.dumps(r.data, ensure_ascii=False)
        assert "Paul" not in texte and "101" not in texte and "PC" not in texte

    def test_resume_de_l_accueil(self):
        _public("aa", "Relais du Pilat")
        r = APIClient().get(reverse("carte_ouverte"))
        assert r.status_code == 200 and r.data["repeteurs"] == 1 and r.data["kp"] is None


@pytest.mark.django_db
class TestLiaisonOuverte:
    def _corps(self, **plus):
        corps = {"lat_a": 45.40, "lon_a": 4.40, "lat_b": 45.45, "lon_b": 4.45}
        corps.update(plus)
        return corps

    def test_sans_connexion_avec_verdict(self):
        with mock.patch("core.relief_radio.altitude_point", return_value=500.0), \
                mock.patch("core.relief_radio.altitudes_points", side_effect=lambda pts: [500.0] * len(pts)):
            r = APIClient().post(reverse("carte_ouverte_liaison"), self._corps(), format="json")
        assert r.status_code == 200, r.data
        assert r.data["verdict"] in ("passe", "passe de justesse", "ne passe pas")
        assert "parametres" in r.data and "calibre" in r.data["parametres"]

    def test_soixante_kilometres_au_plus(self):
        r = APIClient().post(reverse("carte_ouverte_liaison"), self._corps(lat_b=46.2), format="json")
        assert r.status_code == 400 and "60 km" in r.data["detail"]

    def test_nombre_de_calculs_limite(self):
        client = APIClient()
        codes = [client.post(reverse("carte_ouverte_liaison"), self._corps(lat_b=47.0), format="json").status_code
                 for _ in range(12)]
        assert codes[:10] == [400] * 10 and codes[-1] == 429
