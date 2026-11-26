"""Matrix arrêté (26/11/2026) : les anciens points d'entrée du chat Matrix ne lèvent plus une
erreur 500 (et son courriel) quand Synapse ne répond pas ; ils répondent 503, proprement."""
import requests
from rest_framework.test import APIRequestFactory

from core.views import TeamViewSet, _sans_matrix


class _Vue:
    @_sans_matrix
    def appel(self, request):
        raise requests.exceptions.ConnectionError("Failed to resolve 'synapse'")


def test_synapse_injoignable_donne_503_et_pas_500():
    r = _Vue().appel(APIRequestFactory().get("/"))
    assert r.status_code == 503
    assert r.data["matrix_arrete"] is True


def test_les_points_d_entree_matrix_sont_gardes():
    for nom in ("salon_matrix_messages", "salon_matrix_reagir", "provisionner_salon_matrix"):
        assert getattr(TeamViewSet, nom).__wrapped__ is not None
