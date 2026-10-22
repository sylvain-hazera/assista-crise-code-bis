"""Adhésion d'un cadre au salon Matrix d'une équipe qu'il consulte sans en être membre
(matrix.assurer_membre_salon) -- incident du 22/10/2026 : le panneau de messagerie, rafraîchi
toutes les 8 s, réécrivait à chaque fois le nom affiché dans Synapse, qui republiait alors la
fiche de membre dans tous les salons de la personne, jusqu'à limiter le débit (429) et faire
tomber la messagerie unifiée en erreur 500."""
import pytest
import requests
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from core import matrix
from core.models import SalonMatrixEquipe, Team


class FauxSynapse:
    """Remplace les appels HTTP de core.matrix et note ceux qui sont faits."""

    def __init__(self, monkeypatch, nom_affiche="Sylvain Moi", compte_existe=True):
        self.appels = []
        self.nom_affiche = nom_affiche
        self.compte_existe = compte_existe
        monkeypatch.setattr(matrix, "_bot_headers", lambda: {})
        monkeypatch.setattr(matrix.requests, "get", self._get)
        monkeypatch.setattr(matrix.requests, "put", self._put)
        monkeypatch.setattr(matrix.requests, "post", self._post)

    def _reponse(self, code, data=None):
        reponse = requests.Response()
        reponse.status_code = code
        reponse._content = (__import__("json").dumps(data or {})).encode()
        return reponse

    def _get(self, url, **kwargs):
        self.appels.append("GET")
        return self._reponse(200, {"displayname": self.nom_affiche}) if self.compte_existe else self._reponse(404)

    def _put(self, url, **kwargs):
        self.appels.append(("PUT", kwargs.get("json", {}).get("displayname")))
        return self._reponse(200)

    def _post(self, url, **kwargs):
        self.appels.append("JOIN")
        return self._reponse(200)


@pytest.fixture(autouse=True)
def cache_vide():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestAdhesionSalon:

    def test_nom_inchange_jamais_reecrit(self, create_user, monkeypatch):
        synapse = FauxSynapse(monkeypatch, nom_affiche="Sylvain Moi")
        cadre = create_user(username="cadre@test.fr", email="cadre@test.fr", type="ADMIN")

        matrix.assurer_membre_salon(cadre, "!salon:test", displayname="Sylvain Moi")

        assert synapse.appels == ["GET", "JOIN"]

    def test_nom_change_reecrit_une_fois(self, create_user, monkeypatch):
        synapse = FauxSynapse(monkeypatch, nom_affiche="Ancien nom")
        cadre = create_user(username="cadre2@test.fr", email="cadre2@test.fr", type="ADMIN")

        matrix.assurer_membre_salon(cadre, "!salon:test", displayname="Sylvain Moi")

        assert synapse.appels == ["GET", ("PUT", "Sylvain Moi"), "JOIN"]

    def test_rafraichissements_suivants_sans_aucun_appel(self, create_user, monkeypatch):
        synapse = FauxSynapse(monkeypatch)
        cadre = create_user(username="cadre3@test.fr", email="cadre3@test.fr", type="ADMIN")

        for _ in range(10):                                  # 10 rafraîchissements de 8 s
            matrix.assurer_membre_salon(cadre, "!salon:test", displayname="Sylvain Moi")

        assert synapse.appels == ["GET", "JOIN"]

    def test_sans_compte_matrix_pas_de_creation_et_pas_de_relance_immediate(self, create_user, monkeypatch):
        synapse = FauxSynapse(monkeypatch, compte_existe=False)
        cadre = create_user(username="cadre4@test.fr", email="cadre4@test.fr", type="ADMIN")

        matrix.assurer_membre_salon(cadre, "!salon:test")
        matrix.assurer_membre_salon(cadre, "!salon:test")

        assert synapse.appels == ["GET"]                     # ni création, ni nouvel appel


@pytest.mark.django_db
def test_messagerie_affichee_meme_si_synapse_limite_le_debit(create_user, monkeypatch):
    cadre = create_user(username="cadre5@test.fr", email="cadre5@test.fr", type="ADMIN")
    equipe = Team.objects.create(name="Équipe Nord")
    SalonMatrixEquipe.objects.create(equipe=equipe, room_id="!salon:test")

    def limite(*args, **kwargs):
        reponse = requests.Response()
        reponse.status_code = 429
        raise requests.HTTPError("429 Client Error", response=reponse)

    monkeypatch.setattr(matrix, "assurer_membre_salon", limite)
    monkeypatch.setattr(matrix, "lister_messages_salon", lambda *a, **k: [])
    client = APIClient()
    client.force_authenticate(user=cadre)

    reponse = client.get(reverse('team-messagerie-unifiee', args=[equipe.id]))

    assert reponse.status_code == 200, getattr(reponse, "data", reponse)
