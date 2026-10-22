"""Chaque companion Meshtastic n'est servi qu'au pont qui peut l'ouvrir (22/10/2026) : la radio
série d'un satellite à son seul pont, les companions du central (MQTT, TCP) au seul pont du
central. Avant, le central réessayait sans fin /dev/ttyACM0 du satellite de la Loire, et ce
satellite ouvrait la connexion MQTT du central avec ses identifiants."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import CompagnonMeshtastic, Institution, InstitutionType, Satellite, StatutEnrolementSatellite


@pytest.fixture
def satellite(create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom="Mairie Pont", type=itype)
    compte = create_user(username="sat-pont@service.assista-crise.local", email="sat-pont@service.assista-crise.local",
                         type="UTIL_SIMPLE", institution=institution)
    return Satellite.objects.create(institution=institution, nom="poste-loire", profil="FULL",
                                    statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte)


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _noms(reponse):
    assert reponse.status_code == 200, reponse.data
    return sorted(c["nom"] for c in reponse.data)


@pytest.mark.django_db
def test_chaque_pont_ne_recoit_que_ses_companions(create_user, satellite):
    CompagnonMeshtastic.objects.create(nom="Assista-Crise-Bridge", node_num=1, connexion_type="MQTT")
    _client(satellite.compte_service).post(
        reverse('compagnonmeshtastic-enregistrer-depuis-satellite'),
        {"node_num": 2, "serie_device": "/dev/ttyACM0"}, format="json",
    )
    assert CompagnonMeshtastic.objects.get(node_num=2).satellite == satellite

    pont_central = create_user(username="pont-central@assista-crise.local", email="pont-central@assista-crise.local", type="ADMIN")
    url = reverse('compagnonmeshtastic-actifs-avec-identifiants')

    assert _noms(_client(satellite.compte_service).get(url)) == ["Satellite poste-loire"]
    assert _noms(_client(pont_central).get(url)) == ["Assista-Crise-Bridge"]
