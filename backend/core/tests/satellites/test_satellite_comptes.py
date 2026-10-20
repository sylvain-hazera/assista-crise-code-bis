"""Comptes de l'institution copiés sur un satellite FULL (SatelliteViewSet.comptes côté central,
core/sync_comptes.py côté satellite) : connexion locale sans internet avec ses identifiants
habituels (demande utilisateur du 20/10/2026)."""
import pytest
from django.contrib.auth import authenticate
from django.urls import reverse
from rest_framework.test import APIClient

from core.crypto_fields import blind_index
from core.models import ContactInstitution, Institution, InstitutionType, Satellite, User
from core.sync_comptes import appliquer_comptes


@pytest.fixture
def institution():
    itype, _ = InstitutionType.objects.get_or_create(code="TEST_TYPE_SAT_COMPTES", defaults={"libelle": "Test"})
    return Institution.objects.create(nom="Mairie Satellite Comptes", type=itype)


def _satellite_valide(create_user, institution, profil="FULL"):
    maire = create_user(username="maire-sat@test.fr", email="maire-sat@test.fr", type="AUT_LOCALE", institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=maire, actif=True)
    satellite = Satellite.objects.create(institution=institution, nom="Satellite C", profil=profil)
    client = APIClient()
    client.force_authenticate(user=maire)
    identifiants = client.post(reverse("satellite-valider", args=[satellite.id]), {}, format="json").data
    compte_service = User.objects.get(email_bidx=blind_index(identifiants["identifiants_compte_service"]["email"]))
    service = APIClient()
    service.force_authenticate(user=compte_service)
    return satellite, service, maire


@pytest.mark.django_db
class TestComptesCentral:

    def test_renvoie_les_comptes_de_l_institution_avec_hash(self, create_user, institution):
        satellite, service, maire = _satellite_valide(create_user, institution)
        agent = create_user(username="agent-sat@test.fr", email="agent-sat@test.fr", type="AUT_LOCALE", institution=institution)
        create_user(username="ailleurs@test.fr", email="ailleurs@test.fr", type="AUT_LOCALE")   # autre institution

        r = service.get(reverse("satellite-comptes", args=[satellite.id]))

        assert r.status_code == 200, r.data
        emails = {c["email"] for c in r.data["comptes"]}
        assert {"maire-sat@test.fr", "agent-sat@test.fr"} <= emails
        assert "ailleurs@test.fr" not in emails
        assert not any(e.endswith(".assista-crise.local") for e in emails)   # comptes de service exclus
        compte = next(c for c in r.data["comptes"] if c["email"] == "agent-sat@test.fr")
        assert compte["password"] == agent.password and not compte["password"].startswith("password")
        assert r.data["institution"]["id"] == str(institution.id)

    def test_refuse_un_satellite_gw(self, create_user, institution):
        satellite, service, _ = _satellite_valide(create_user, institution, profil="GW")
        assert service.get(reverse("satellite-comptes", args=[satellite.id])).status_code == 403

    def test_refuse_un_utilisateur_ordinaire(self, create_user, institution):
        satellite, _, maire = _satellite_valide(create_user, institution)
        client = APIClient()
        client.force_authenticate(user=maire)
        assert client.get(reverse("satellite-comptes", args=[satellite.id])).status_code == 403


@pytest.mark.django_db
class TestComptesSatellite:
    """Côté satellite : simulé dans la même base, avec des ids neufs (comme une base vierge)."""

    def _donnees(self, comptes, institution_id="11111111-2222-3333-4444-555555555555"):
        return {
            "institution": {
                "id": institution_id, "nom": "Mairie copiée", "type_code": "TEST_TYPE_COPIE",
                "type_libelle": "Copie", "commune_code": "42207", "commune_nom": "Saint-Chamond",
                "epci_code": None, "departement_code": "42", "region_code": "84",
                "secteur_niveau_effectif": "commune", "secteur_nom": "Saint-Chamond", "environment": "PROD",
            },
            "comptes": comptes,
        }

    def _compte(self, uid, email, mot_de_passe):
        from django.contrib.auth.hashers import make_password
        return {"id": uid, "username": email, "email": email, "first_name": "Ana", "last_name": "Terrain",
                "type": "AUT_LOCALE", "password": make_password(mot_de_passe)}

    def test_connexion_locale_avec_le_mot_de_passe_habituel(self):
        compte = self._compte("aaaaaaaa-0000-0000-0000-000000000001", "ana@mairie.fr", "Mot-de-passe-habituel-42")
        resultat = appliquer_comptes(self._donnees([compte]))

        assert resultat["crees"] == 1
        assert authenticate(username="ana@mairie.fr", password="Mot-de-passe-habituel-42") is not None
        assert Institution.objects.get(pk="11111111-2222-3333-4444-555555555555").departement_code == "42"

    def test_mise_a_jour_puis_desactivation_du_compte_parti(self):
        a = self._compte("aaaaaaaa-0000-0000-0000-000000000002", "a@mairie.fr", "x-1")
        b = self._compte("aaaaaaaa-0000-0000-0000-000000000003", "b@mairie.fr", "x-2")
        appliquer_comptes(self._donnees([a, b]))
        a["last_name"] = "Renommée"
        resultat = appliquer_comptes(self._donnees([a]))

        assert resultat == {"crees": 0, "mis_a_jour": 1, "desactives": 1, "ignores": 0}
        assert User.objects.get(pk=a["id"]).last_name == "Renommée"
        assert User.objects.get(pk=b["id"]).is_active is False

    def test_admin_local_jamais_touche(self, create_user):
        admin = create_user(username="admin-local@service.assista-crise.local", email="admin-local@service.assista-crise.local",
                            type="ADMIN", is_superuser=True)
        compte = self._compte(str(admin.id), "pirate@mairie.fr", "x")
        resultat = appliquer_comptes(self._donnees([compte]))
        admin.refresh_from_db()
        assert resultat["ignores"] == 1
        assert admin.email == "admin-local@service.assista-crise.local" and admin.is_active

    def test_email_deja_pris_localement_n_empeche_pas_les_autres(self, create_user):
        create_user(username="pris@mairie.fr", email="pris@mairie.fr", type="AUT_LOCALE")
        doublon = self._compte("aaaaaaaa-0000-0000-0000-000000000004", "pris@mairie.fr", "x")
        autre = self._compte("aaaaaaaa-0000-0000-0000-000000000005", "autre@mairie.fr", "x")
        resultat = appliquer_comptes(self._donnees([doublon, autre]))
        assert resultat["ignores"] == 1 and resultat["crees"] == 1
