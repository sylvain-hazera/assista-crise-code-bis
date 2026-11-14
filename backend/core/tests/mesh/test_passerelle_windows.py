"""Ce que la passerelle Windows (passerelle-windows/) demande au central, au-delà de ce qu'un
satellite Docker demandait déjà : le Bluetooth pour Meshtastic, et le retrait d'une radio.

L'enrôlement lui-même (jeton -> validation -> identifiants) est celui des satellites, déjà
couvert ailleurs : la passerelle Windows EST un satellite de profil GW."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core.canaux_locaux import est_isolee
from core.models import (
    CompagnonMeshCore, CompagnonMeshtastic, Institution, InstitutionType,
    MeshtasticConnexionType, ProfilSatellite, Satellite, StatutEnrolementSatellite, UserRole,
)


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie de la Passerelle", type=itype)


def _passerelle(create_user, institution, nom):
    compte = create_user(username=f"{nom}@service.test", email=f"{nom}@service.test",
                         type=UserRole.SIMPLE_USER)
    satellite = Satellite.objects.create(
        institution=institution, nom=nom, profil=ProfilSatellite.GW, compte_service=compte,
        statut_enrolement=StatutEnrolementSatellite.APPROUVE, environment="PROD")
    client = APIClient()
    client.force_authenticate(user=compte)
    return satellite, client


@pytest.fixture
def pc_accueil(create_user, mairie):
    return _passerelle(create_user, mairie, "pc-accueil")


class TestMeshtasticEnBluetooth:
    def test_la_passerelle_enregistre_une_radio_bluetooth(self, pc_accueil):
        satellite, client = pc_accueil

        reponse = client.post("/api/compagnons-meshtastic/enregistrer-depuis-satellite/", {
            "node_num": 0x0BADCAFE, "nom": "T-Echo", "connexion_type": "BLE",
            "ble_adresse": "AA:BB:CC:DD:EE:FF",
        }, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        radio = CompagnonMeshtastic.objects.get(node_num=0x0BADCAFE)
        assert radio.connexion_type == MeshtasticConnexionType.BLE
        assert radio.ble_adresse == "AA:BB:CC:DD:EE:FF"
        assert radio.satellite == satellite

    def test_elle_est_isolee_comme_toute_passerelle_locale(self, pc_accueil):
        """Règle du 14/11/2026 : locale = isolée par défaut, quel que soit le fil."""
        _, client = pc_accueil
        client.post("/api/compagnons-meshtastic/enregistrer-depuis-satellite/", {
            "node_num": 0x0BADCAFE, "connexion_type": "BLE", "ble_adresse": "AA:BB:CC:DD:EE:FF",
        }, format="json")

        assert est_isolee(CompagnonMeshtastic.objects.get(node_num=0x0BADCAFE))

    def test_son_pont_recoit_l_adresse_bluetooth(self, pc_accueil):
        _, client = pc_accueil
        client.post("/api/compagnons-meshtastic/enregistrer-depuis-satellite/", {
            "node_num": 0x0BADCAFE, "connexion_type": "BLE", "ble_adresse": "AA:BB:CC:DD:EE:FF",
        }, format="json")

        radios = client.get("/api/compagnons-meshtastic/actifs-avec-identifiants/").json()

        assert [(r["connexion_type"], r["ble_adresse"]) for r in radios] == [
            ("BLE", "AA:BB:CC:DD:EE:FF")]


class TestRetirerUneRadio:
    def _enregistrer(self, client):
        return client.post("/api/compagnons-meshtastic/enregistrer-depuis-satellite/", {
            "node_num": 0x0BADCAFE, "connexion_type": "SERIE", "serie_device": "COM5",
        }, format="json").json()["id"]

    def test_une_radio_retiree_n_est_plus_servie_au_pont(self, pc_accueil):
        """Sinon elle restait « active » sans personne pour l'ouvrir, et captait des messages."""
        _, client = pc_accueil
        identifiant = self._enregistrer(client)

        reponse = client.post(f"/api/compagnons-meshtastic/{identifiant}/retirer-du-satellite/")

        assert reponse.status_code == status.HTTP_200_OK
        assert client.get("/api/compagnons-meshtastic/actifs-avec-identifiants/").json() == []
        assert CompagnonMeshtastic.objects.get(pk=identifiant).actif is False

    def test_la_rebrancher_la_reactive(self, pc_accueil):
        _, client = pc_accueil
        identifiant = self._enregistrer(client)
        client.post(f"/api/compagnons-meshtastic/{identifiant}/retirer-du-satellite/")

        assert self._enregistrer(client) == identifiant
        assert CompagnonMeshtastic.objects.get(pk=identifiant).actif is True

    def test_on_ne_retire_pas_la_radio_d_une_autre_passerelle(self, pc_accueil, create_user, mairie):
        _, client = pc_accueil
        identifiant = self._enregistrer(client)
        _, autre = _passerelle(create_user, mairie, "pc-voisin")

        reponse = autre.post(f"/api/compagnons-meshtastic/{identifiant}/retirer-du-satellite/")

        assert reponse.status_code == status.HTTP_404_NOT_FOUND
        assert CompagnonMeshtastic.objects.get(pk=identifiant).actif is True

    def test_un_compte_ordinaire_ne_retire_rien(self, pc_accueil, create_user):
        _, client = pc_accueil
        identifiant = self._enregistrer(client)
        quidam = APIClient()
        quidam.force_authenticate(user=create_user(
            username="quidam@test.fr", email="quidam@test.fr", type=UserRole.SIMPLE_USER))

        reponse = quidam.post(f"/api/compagnons-meshtastic/{identifiant}/retirer-du-satellite/")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_meshcore_aussi(self, pc_accueil):
        _, client = pc_accueil
        identifiant = client.post("/api/compagnons-meshcore/enregistrer-depuis-satellite/", {
            "pubkey_hex": "ab" * 32, "nom": "Heltec", "connexion_type": "BLE",
            "ble_adresse": "11:22:33:44:55:66",
        }, format="json").json()["id"]
        assert CompagnonMeshCore.objects.get(pk=identifiant).ble_adresse == "11:22:33:44:55:66"

        reponse = client.post(f"/api/compagnons-meshcore/{identifiant}/retirer-du-satellite/")

        assert reponse.status_code == status.HTTP_200_OK
        assert CompagnonMeshCore.objects.get(pk=identifiant).actif is False
