"""Tableaux de situation du pilotage (23/11/2026, core/pilotage_situation.py)."""
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Crisis, Habitation, PointOperationnel, PointType, RegistrePresence, Team, User


@pytest.mark.django_db
def test_les_blocs_de_situation_lisent_les_tables_existantes():
    crise = Crisis.objects.create(name="Crue situation", type="INONDATION", location=Point(4.6, 45.5, srid=4326), radius=5)
    hebergement, _ = PointType.objects.get_or_create(code="HEBERGEMENT", defaults={"libelle": "Centre d'accueil"})
    centre = PointOperationnel.objects.create(nom="Gymnase", type=hebergement, crise=crise, capacite_accueil=80,
                                              location=Point(4.6, 45.5, srid=4326))
    RegistrePresence.objects.create(point=centre, type_personne="EVACUE", nombre=12)
    for statut in ("DEGATS_FORTS", "DETRUITE", "PAS_DE_DEGATS"):
        Habitation.objects.create(crise=crise, adresse="x", commune_code="42186", statut_evaluation=statut,
                                  location=Point(4.6, 45.5, srid=4326))
    Team.objects.create(name="Equipe radio").assigned_crises.add(crise)
    pc = User.objects.create_user(username="pc-sit@test.fr", email="pc-sit@test.fr", password="x", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=pc)
    with mock.patch("core.geo_lookup.commune_code_from_point", return_value="42186"):
        r = client.get(reverse("pilotage-situation"), {"crise": str(crise.id)})
    assert r.status_code == 200, r.data
    assert r.data["accueil"]["centres"] == [{"nom": "Gymnase", "capacite": 80, "presents": 12}]
    assert r.data["degats"]["par_statut"]["DETRUITE"] == 1 and r.data["degats"]["evalues"] == 3
    assert r.data["radio"]["equipes"][0] == {"nom": "Equipe radio", "indicatif": None, "transmissions": False,
                                             "meshtastic": False, "meshcore": False, "dernier_message_radio": None}
    assert r.data["radio"]["canal_crise"] == {"meshtastic": None, "meshcore": None} and r.data["radio"]["a_trier"] == 0
    assert "vigilance_meteo" in r.data["veille"] and "renforts_24h" in r.data["moyens"]


@pytest.mark.django_db
def test_reserve_au_poste_de_commandement():
    crise = Crisis.objects.create(name="Crue sit 2", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    benevole = User.objects.create_user(username="ben-sit@test.fr", email="ben-sit@test.fr", password="x", type="UTIL_SIMPLE")
    client = APIClient()
    client.force_authenticate(user=benevole)
    assert client.get(reverse("pilotage-situation"), {"crise": str(crise.id)}).status_code == 403
