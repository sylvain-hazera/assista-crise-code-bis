"""Tableau radio MeshCore et états des observateurs (23/11/2026)."""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.ingestion_observateurs_meshcore import MessageObservateur, enregistrer_etat
from core.models import (
    CompteurPaquetsMeshCore, EtatObservateurMeshCore, LiaisonMeshCore, NoeudPublicMeshCore, UserRole,
)

OBS = "ab" * 32


@pytest.mark.django_db
def test_l_etat_d_un_observateur_garde_ses_valeurs_numeriques_seulement():
    message = MessageObservateur("BOD", OBS, "status", {
        "battery_mv": 4012, "noise_floor": -112, "uptime_secs": 3600, "origin": "33PORGE_OBS",
        "firmware": "v1.16", "drapeau": True,
    })
    enregistrer_etat(message)
    etat = EtatObservateurMeshCore.objects.get(pubkey_hex=OBS)
    assert {k: v for k, v in etat.mesures.items() if k != "_cles"} == {"battery_mv": 4012, "noise_floor": -112, "uptime_secs": 3600}
    # Les noms de tous les champs, jamais leurs valeurs textuelles.
    assert set(etat.mesures["_cles"]) == {"battery_mv", "noise_floor", "uptime_secs", "origin", "firmware", "drapeau"}
    assert (etat.origine, etat.iata) == ("33PORGE_OBS", "BOD")
    # Le suivant remplace le précédent : un seul état par observateur.
    enregistrer_etat(MessageObservateur("BOD", OBS, "status", {"battery_mv": 3900}))
    assert EtatObservateurMeshCore.objects.get(pubkey_hex=OBS).mesures == {"battery_mv": 3900, "_cles": ["battery_mv"]}


@pytest.mark.django_db
def test_valeurs_imbriquees_et_nombres_en_texte():
    """23/11/2026 : en production, aucun nombre au premier niveau des messages d'état."""
    from core.tableau_meshcore import _connues
    enregistrer_etat(MessageObservateur("BOD", OBS, "status", {
        "origin": "Obs", "status": "online", "stats": {"battery_mv": "4012", "noise_floor": -110, "radio": {"last_snr": 7.5}},
    }))
    mesures = EtatObservateurMeshCore.objects.get(pubkey_hex=OBS).mesures
    assert mesures["stats.battery_mv"] == 4012 and mesures["stats.radio.last_snr"] == 7.5
    assert "status" in mesures["_cles"] and "online" not in str(mesures)
    assert _connues(mesures) == {"battery_mv": 4012, "noise_floor": -110, "last_snr": 7.5}


@pytest.mark.django_db
def test_le_tableau_reunit_trafic_liaisons_relais_et_observateurs(create_user):
    maintenant = timezone.now()
    heure = maintenant.replace(minute=0, second=0, microsecond=0)
    CompteurPaquetsMeshCore.objects.create(recepteur_pubkey_hex=OBS, heure=heure, type_paquet="ADVERT", nombre=40)
    CompteurPaquetsMeshCore.objects.create(recepteur_pubkey_hex=OBS, heure=heure, type_paquet="GRP_TXT", nombre=10)
    CompteurPaquetsMeshCore.objects.create(recepteur_pubkey_hex=OBS, heure=heure - datetime.timedelta(days=3),
                                           type_paquet="ADVERT", nombre=999)       # hors fenêtre
    LiaisonMeshCore.objects.create(emetteur_prefixe_hex="cd", prefixe_octets=1, recepteur_pubkey_hex=OBS,
                                   source="RF", snr=4.0, dernier_vu=maintenant)
    LiaisonMeshCore.objects.create(emetteur_prefixe_hex="ef", prefixe_octets=1, recepteur_pubkey_hex=OBS,
                                   source="CHEMIN", dernier_vu=maintenant)
    NoeudPublicMeshCore.objects.create(instance="meshstats.test", pubkey_hex="cd" * 32, nom="Rep public", role="repeater",
                                       dernier_vu=maintenant, score_utilite=0.8, note_utilite="A", date_import=maintenant)
    enregistrer_etat(MessageObservateur("BOD", OBS, "status", {"battery_mv": 4012, "origin": "Obs Porge", "xyz": 1}))

    admin = create_user(username="tab-mc@test.fr", email="tab-mc@test.fr", type=UserRole.ADMINISTRATOR)
    client = APIClient()
    client.force_authenticate(user=admin)
    r = client.get(reverse("tableau-radio-meshcore"), {"fenetre": "24h"})
    assert r.status_code == 200, r.data
    assert r.data["trafic"]["total"] == 50
    assert r.data["trafic"]["par_type"][0] == {"type": "ADVERT", "trames": 40}
    assert r.data["trafic"]["recepteurs"][0]["nom"] == "Obs Porge" and r.data["trafic"]["recepteurs"][0]["trames"] == 50
    assert sum(p["trames"] for p in r.data["trafic"]["courbe"]) == 50
    assert (r.data["liaisons"]["reception_directe"], r.data["liaisons"]["chemins"]) == (1, 1)
    assert r.data["relais_publics"]["repeteurs_vus"] == 1 and r.data["relais_publics"]["instances"] == ["meshstats.test"]
    [obs] = r.data["observateurs"]
    assert obs["mesures"] == {"battery_mv": 4012} and obs["autres_mesures"] == 1 and not obs["silencieux"]


@pytest.mark.django_db
def test_un_citoyen_n_y_a_pas_acces(create_user):
    citoyen = create_user(username="cit-mc@test.fr", email="cit-mc@test.fr", type=UserRole.SIMPLE_USER)
    client = APIClient()
    client.force_authenticate(user=citoyen)
    assert client.get(reverse("tableau-radio-meshcore")).status_code == 403
