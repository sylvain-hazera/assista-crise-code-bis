"""Copie central -> satellite du référentiel d'adresses (lot B, core/sync_adresses.py)."""
import datetime
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core import sync_adresses
from core.models import AdresseBAN, Commune, Institution, InstitutionType, Satellite, StatutEnrolementSatellite

UTC = datetime.timezone.utc
T = [datetime.datetime(2026, 11, 20, h, tzinfo=UTC) for h in range(24)]
COMMUNE = "42218"


@pytest.fixture
def institution(db):
    Commune.objects.create(code=COMMUNE, nom="Saint-Étienne", departement_code="42", epci_code="244200770")
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom="Mairie Adresses", type=itype, commune_code=COMMUNE)
    Institution.objects.filter(pk=institution.pk).update(secteur_niveau_effectif="commune")
    institution.refresh_from_db()
    return institution


def _satellite(create_user, institution, profil="FULL"):
    compte = create_user(username=f"sat-adr-{profil}@service.assista-crise.local",
                         email=f"sat-adr-{profil}@service.assista-crise.local", type="UTIL_SIMPLE", institution=institution)
    return Satellite.objects.create(institution=institution, nom=f"Sat {profil}", profil=profil,
                                    statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte)


def _adresse(ban_id, commune=COMMUNE, modifie_le=T[1], retiree_le=None, voie="Rue du Puits"):
    return AdresseBAN.objects.create(ban_id=ban_id, commune_code=commune, voie=voie, numero="1",
                                     location=Point(4.39, 45.43, srid=4326), modifie_le=modifie_le, retiree_le=retiree_le)


@pytest.mark.django_db
class TestCentral:
    def test_les_communes_du_satellite_et_rien_d_autre(self, create_user, institution):
        satellite = _satellite(create_user, institution)
        _adresse("42218_1", modifie_le=T[1])
        _adresse("42218_2", modifie_le=T[2])
        _adresse("59350_1", commune="59350", modifie_le=T[3])          # une autre commune
        client = APIClient()
        client.force_authenticate(user=satellite.compte_service)
        url = f"/api/satellites/{satellite.id}/adresses/"

        assert client.get(url, {"communes_voulues": "1"}).data == {"communes": [COMMUNE]}
        tout = client.get(url).data
        assert [a["ban_id"] for a in tout["adresses"]] == ["42218_1", "42218_2"] and tout["suivant"] is None
        depuis = client.get(url, {"depuis": T[1].isoformat(), "apres": "42218_1"}).data
        assert [a["ban_id"] for a in depuis["adresses"]] == ["42218_2"]
        # Une commune demandée hors du territoire n'est pas servie.
        assert client.get(url, {"communes": "59350"}).data["adresses"] == []

    def test_par_pages_dans_l_ordre(self, create_user, institution):
        satellite = _satellite(create_user, institution)
        for i in range(5):
            _adresse(f"42218_{i}", modifie_le=T[1])                     # même horodatage : départagés par l'identifiant
        client = APIClient()
        client.force_authenticate(user=satellite.compte_service)
        url = f"/api/satellites/{satellite.id}/adresses/"
        with patch.object(sync_adresses, "TAILLE_PAGE", 2):
            premiere = client.get(url).data
            seconde = client.get(url, premiere["suivant"]).data
        assert [a["ban_id"] for a in premiere["adresses"]] == ["42218_0", "42218_1"]
        assert [a["ban_id"] for a in seconde["adresses"]] == ["42218_2", "42218_3"]

    def test_reserve_au_compte_de_service_d_un_satellite_complet(self, create_user, institution):
        satellite = _satellite(create_user, institution)
        passerelle = _satellite(create_user, institution, profil="GW")
        autre = create_user(username="curieux@test.fr", email="curieux@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=autre)
        assert client.get(f"/api/satellites/{satellite.id}/adresses/").status_code in (403, 404)
        client.force_authenticate(user=passerelle.compte_service)
        assert client.get(f"/api/satellites/{passerelle.id}/adresses/").status_code == 403


class CentralSimule:
    """Le central en mémoire : la même pagination que sync_adresses.page, sur une liste."""

    def __init__(self, communes, lignes):
        self.communes, self.lignes, self.appels = communes, lignes, []

    def __call__(self, params):
        self.appels.append(dict(params))
        if params.get("communes_voulues"):
            return {"communes": sorted(self.communes)}
        depuis, apres, communes = sync_adresses.lire_curseur(params)
        perimetre = set(communes) & self.communes if communes else self.communes
        lignes = sorted((l for l in self.lignes if l["commune_code"] in perimetre), key=lambda l: (l["modifie_le"], l["ban_id"]))
        if depuis is not None:
            lignes = [l for l in lignes if (l["modifie_le"], l["ban_id"]) > (depuis.isoformat(), apres)]
        page, suivant = lignes[:2], None
        if len(lignes) > 2:
            suivant = {"depuis": page[-1]["modifie_le"], "apres": page[-1]["ban_id"]}
        return {"adresses": page, "suivant": suivant}


def ligne(ban_id, commune, heure, retiree=None, voie="Rue du Puits"):
    return {"ban_id": ban_id, "commune_code": commune, "commune_nom": "", "code_postal": "", "numero": "1",
            "suffixe": "", "voie": voie, "lieu_dit": "", "type_position": "entrée", "parcelles": "",
            "lon": 4.39, "lat": 45.43, "retiree_le": retiree, "modifie_le": T[heure].isoformat()}


@pytest.mark.django_db
class TestSatellite:
    def test_premiere_copie_puis_seulement_les_changements(self):
        central = CentralSimule({"A"}, [ligne("A1", "A", 1), ligne("A2", "A", 1), ligne("A3", "A", 2)])
        assert sync_adresses.copier(central) == {"communes_nouvelles": 0, "ecrites": 3}
        assert AdresseBAN.objects.count() == 3
        assert AdresseBAN.objects.get(ban_id="A3").modifie_le == T[2]          # copié à l'identique
        assert sync_adresses.copier(central)["ecrites"] == 0                  # rien de neuf : rien d'écrit
        central.lignes[0] = ligne("A1", "A", 5, voie="Rue renommée")
        central.lignes[1] = ligne("A2", "A", 5, retiree=T[5].isoformat())
        assert sync_adresses.copier(central)["ecrites"] == 2
        assert AdresseBAN.objects.get(ban_id="A1").voie == "Rue renommée"
        assert AdresseBAN.objects.get(ban_id="A2").retiree_le == T[5]          # retirée, pas effacée

    def test_une_commune_chargee_depuis_longtemps_au_central_arrive_quand_meme(self):
        central = CentralSimule({"A"}, [ligne("A1", "A", 9)])
        sync_adresses.copier(central)
        # Une crise ouvre la commune B, chargée au central depuis longtemps (heure 1, avant le
        # curseur du satellite) ; et une adresse de A change entre-temps (heure 10).
        central.communes = {"A", "B"}
        central.lignes += [ligne("B1", "B", 1), ligne("B2", "B", 1), ligne("B3", "B", 1)]
        central.lignes[0] = ligne("A1", "A", 10, voie="Rue changée")
        resultat = sync_adresses.copier(central)
        assert resultat["communes_nouvelles"] == 1
        assert set(AdresseBAN.objects.values_list("ban_id", flat=True)) == {"A1", "B1", "B2", "B3"}
        assert AdresseBAN.objects.get(ban_id="A1").voie == "Rue changée"      # le changement plus ancien n'est pas perdu

    def test_la_synchronisation_entrante_copie_les_adresses(self, settings):
        from django.core.management import call_command

        settings.SATELLITE_CENTRAL_URL, settings.SATELLITE_ID = "https://central.test", "1"
        settings.SATELLITE_EMAIL, settings.SATELLITE_PASSWORD = "sat@test", "x"
        central = CentralSimule({"A"}, [ligne("A1", "A", 1)])

        class Reponse:
            def __init__(self, data): self._data = data
            def raise_for_status(self): pass
            def json(self): return self._data

        def faux_get(url, params=None, headers=None, **kwargs):
            if url.endswith("/adresses/"):
                return Reponse(central(params or {}))
            return Reponse({"institution": {}, "comptes": []} if url.endswith("/comptes/") else {})

        with patch("requests.post", return_value=Reponse({"access": "jeton"})), patch("requests.get", side_effect=faux_get), \
             patch("core.sync_comptes.appliquer_comptes", return_value={"crees": 0, "mis_a_jour": 0, "desactives": 0, "ignores": 0}):
            call_command("synchroniser_entrant")
        assert AdresseBAN.objects.filter(ban_id="A1").exists()
