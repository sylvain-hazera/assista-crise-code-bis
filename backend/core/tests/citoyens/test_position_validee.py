"""Une position illisible est refusée comme une erreur de saisie, pas par une erreur 500.

18/11/2026 : un objet GeoJSON envoyé à la place du texte attendu faisait planter le dépôt d'une
information (`Cannot set Information SpatialProxy (POINT) with value of type: dict`)."""
import pytest
from rest_framework import serializers

from core.serializers import InformationSerializer, OfferSerializer, PositionValideeMixin, RequestSerializer

valider = PositionValideeMixin().validate_location


def test_les_trois_depots_publics_valident_leur_position():
    for classe in (RequestSerializer, OfferSerializer, InformationSerializer):
        assert issubclass(classe, PositionValideeMixin)


@pytest.mark.parametrize("valeur", [
    "POINT(4.6172 45.5291)",
    "SRID=4326;POINT(4.6172 45.5291)",
    '{"type": "Point", "coordinates": [4.6172, 45.5291]}',
    {"type": "Point", "coordinates": [4.6172, 45.5291]},
])
def test_ce_qui_se_lit_comme_un_point_est_accepte(valeur):
    point = valider(valeur)
    assert (round(point.x, 4), round(point.y, 4), point.srid) == (4.6172, 45.5291, 4326)


@pytest.mark.parametrize("valeur", [
    {"latitude": 45.5, "longitude": 4.6}, "n'importe quoi", 12, ["4.6", "45.5"],
    "LINESTRING(0 0, 1 1)", "POINT(445.0 45.5)",
])
def test_le_reste_est_une_erreur_de_saisie(valeur):
    with pytest.raises(serializers.ValidationError):
        valider(valeur)


def test_une_position_absente_reste_absente():
    assert valider(None) is None and valider("") is None
