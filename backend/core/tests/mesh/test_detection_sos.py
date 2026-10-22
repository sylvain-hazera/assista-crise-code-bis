"""Détection de messages d'urgence sur le réseau mesh (22/10/2026) : coupée pour Meshtastic
(faux positifs des canaux communautaires), et jamais déclenchée par l'écho de nos propres
diffusions (alertes séisme réentendues par nos autres companions)."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import AlerteMeshSOS, CanalMeshCore, CanalMeshtastic, MessageCanalMeshCore


@pytest.fixture
def pont(create_user):
    compte = create_user(username="pont-sos@assista-crise.local", email="pont-sos@assista-crise.local", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=compte)
    return client


def _recevoir(client, nom_url, canal, contenu):
    reponse = client.post(reverse(nom_url), {"canal": str(canal.id), "direction": "ENTRANT", "contenu": contenu}, format="json")
    assert reponse.status_code == 201, reponse.data


@pytest.mark.django_db
class TestDetectionSOS:

    def test_meshtastic_coupee_par_defaut(self, pont):
        canal = CanalMeshtastic.objects.create(nom="Fr_EMCOM")
        _recevoir(pont, "messagecanalmeshtastic-list", canal, "SOS blessé grave route du Pilat")
        assert AlerteMeshSOS.objects.count() == 0

    def test_meshtastic_reactivable_par_reglage(self, pont, settings):
        settings.DETECTION_SOS_MESHTASTIC = True
        canal = CanalMeshtastic.objects.create(nom="LongFast")
        _recevoir(pont, "messagecanalmeshtastic-list", canal, "SOS blessé grave route du Pilat")
        assert AlerteMeshSOS.objects.filter(protocole="MESHTASTIC").count() == 1

    def test_meshcore_ignore_l_echo_de_nos_diffusions(self, pont):
        canal = CanalMeshCore.objects.create(nom="#emcom")
        MessageCanalMeshCore.objects.create(canal=canal, direction="SORTANT", contenu="Seisme M3.0 pres de France.")
        _recevoir(pont, "messagecanalmeshcore-list", canal, "Assista-Crise : Seisme M3.0 pres de France.")
        assert AlerteMeshSOS.objects.count() == 0

    def test_meshcore_detecte_toujours_un_vrai_appel(self, pont):
        canal = CanalMeshCore.objects.create(nom="#emcom")
        MessageCanalMeshCore.objects.create(canal=canal, direction="SORTANT", contenu="Seisme M3.0 pres de France.")
        _recevoir(pont, "messagecanalmeshcore-list", canal, "Jeanne : au secours, maison inondée")
        assert AlerteMeshSOS.objects.filter(protocole="MESHCORE").count() == 1
