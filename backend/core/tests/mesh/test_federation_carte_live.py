"""Fédération au format carte-live-meshtastic (core/federation_carte_live.py).

Les deux tests qui comptent vraiment sont ceux de confidentialité : l'endpoint est anonyme par
nature du format, donc ce qu'il publie est le seul garde-fou. Un COMPANION peut être le terminal
d'une personne (NoeudMeshUtilisateur rattache une clé publique à un compte) — publier sa position
publierait celle de quelqu'un.
"""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, ContactMeshCore, RelaisMeshCore, TypeContactMeshCore,
)


@pytest.fixture
def client_anonyme():
    return APIClient()


@pytest.fixture
def federation_active(settings):
    settings.FEDERATION_CARTE_LIVE = True
    settings.FEDERATION_CARTE_LIVE_NOM = "Assista-Crise Gironde"
    settings.FEDERATION_CARTE_LIVE_DEPARTEMENT = "33"
    return settings


@pytest.mark.django_db
class TestActivation:

    def test_desactivee_par_defaut(self, client_anonyme, settings):
        """Publier les positions des relais d'un réseau de secours est une décision
        d'exploitation : rien ne sort tant qu'elle n'est pas prise."""
        settings.FEDERATION_CARTE_LIVE = False
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert reponse.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_le_format_est_celui_attendu_par_leurs_cartes(self, client_anonyme, federation_active):
        """Leur consommateur refuse la réponse si `format` ne correspond pas exactement
        (« réponse inattendue (pas une carte live ?) »)."""
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["format"] == "carte-live-federation"
        assert reponse.data["version"] == 1
        assert isinstance(reponse.data["relais"], list)
        assert reponse.data["liens"] == []        # aucun modèle de liaison mesurée encore
        assert reponse.data["instance"]["nom"] == "Assista-Crise Gironde"
        assert reponse.data["instance"]["departement"] == "33"


@pytest.mark.django_db
class TestConfidentialite:

    def test_un_companion_entendu_n_est_jamais_publie(self, client_anonyme, federation_active):
        """Le test central : un COMPANION peut être le terminal d'une personne."""
        compagnon = CompagnonMeshCore.objects.create(nom="Passerelle bureau")
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex="aa" * 32, type_contact=TypeContactMeshCore.COMPANION,
            location=Point(-0.57, 44.84, srid=4326), dernier_advert=timezone.now(),
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert [r["id"] for r in reponse.data["relais"]] == []

    def test_un_capteur_n_est_pas_publie_non_plus(self, client_anonyme, federation_active):
        compagnon = CompagnonMeshCore.objects.create(nom="Passerelle")
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex="bb" * 32, type_contact=TypeContactMeshCore.SENSOR,
            location=Point(-0.57, 44.84, srid=4326), dernier_advert=timezone.now(),
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert reponse.data["relais"] == []

    def test_un_repeteur_est_publie(self, client_anonyme, federation_active):
        compagnon = CompagnonMeshCore.objects.create(nom="Passerelle")
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex="cc" * 32, type_contact=TypeContactMeshCore.REPEATER,
            location=Point(-0.57, 44.84, srid=4326), dernier_advert=timezone.now(),
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        entrees = [r for r in reponse.data["relais"] if r["id"] == "cc" * 32]
        assert len(entrees) == 1
        assert entrees[0]["role"] == "repeteur"
        assert entrees[0]["lat"] == pytest.approx(44.84)
        assert entrees[0]["lon"] == pytest.approx(-0.57)


@pytest.mark.django_db
class TestPerimetre:

    def test_un_repeteur_muet_depuis_plus_de_trois_jours_est_ecarte(
        self, client_anonyme, federation_active,
    ):
        """Même fenêtre que leur implémentation : un relais silencieux depuis trois jours
        donnerait une carte fausse au voisin qui la lit."""
        compagnon = CompagnonMeshCore.objects.create(nom="Passerelle")
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex="dd" * 32, type_contact=TypeContactMeshCore.REPEATER,
            location=Point(-0.57, 44.84, srid=4326),
            dernier_advert=timezone.now() - datetime.timedelta(days=4),
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert reponse.data["relais"] == []

    def test_un_relais_declare_est_publie_comme_infrastructure(
        self, client_anonyme, federation_active,
    ):
        RelaisMeshCore.objects.create(
            nom="Relais du château d'eau", location=Point(-0.6, 44.9, srid=4326),
            pubkey_hex="ee" * 32, actif=True,
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        entrees = [r for r in reponse.data["relais"] if r["id"] == "ee" * 32]
        assert len(entrees) == 1
        assert entrees[0]["nom"] == "Relais du château d'eau"
        assert entrees[0]["passerelle"] is False

    def test_un_relais_inactif_n_est_pas_publie(self, client_anonyme, federation_active):
        RelaisMeshCore.objects.create(
            nom="Démonté", location=Point(-0.6, 44.9, srid=4326), pubkey_hex="ff" * 32, actif=False,
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert reponse.data["relais"] == []

    def test_un_companion_de_l_institution_est_publie_comme_passerelle(
        self, client_anonyme, federation_active,
    ):
        CompagnonMeshCore.objects.create(
            nom="Passerelle du PC", location=Point(-0.58, 44.85, srid=4326),
            pubkey_hex="11" * 32, actif=True,
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        entrees = [r for r in reponse.data["relais"] if r["id"] == "11" * 32]
        assert len(entrees) == 1
        assert entrees[0]["passerelle"] is True

    def test_pas_de_doublon_entre_companion_et_contact_entendu(
        self, client_anonyme, federation_active,
    ):
        """Un companion de l'institution peut aussi être entendu par un autre companion : il ne
        doit apparaître qu'une fois, sinon le voisin compterait deux relais au même endroit."""
        compagnon = CompagnonMeshCore.objects.create(
            nom="Passerelle", location=Point(-0.58, 44.85, srid=4326),
            pubkey_hex="22" * 32, actif=True,
        )
        ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex="22" * 32, type_contact=TypeContactMeshCore.REPEATER,
            location=Point(-0.58, 44.85, srid=4326), dernier_advert=timezone.now(),
        )
        reponse = client_anonyme.get(reverse('federation_carte_live'))
        assert len([r for r in reponse.data["relais"] if r["id"] == "22" * 32]) == 1
