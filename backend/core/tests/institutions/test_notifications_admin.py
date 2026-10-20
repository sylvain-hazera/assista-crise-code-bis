"""Alertes admin (core/notifications_admin.py), page des comptes en attente et portée nationale
des SDIS en zone DEMO -- demandes utilisateur du 19/10 (préparation du POC SDIS 40)."""
import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from core.imports import importer_institutions
from core.models import Institution, InstitutionType, User
from core.zone_scoping import viewer_zone_code


@pytest.fixture
def admins(create_user):
    reel = create_user(username="admin-notif@test.fr", email="admin-notif@test.fr", type="ADMIN")
    create_user(username="0807demo@zone.demo", email="0807demo@zone.demo", type="ADMIN")
    return reel


@pytest.mark.django_db
class TestAlerteInstitutionCreee:

    def test_notifie_les_admins_hors_adresses_demo(self, admins, django_capture_on_commit_callbacks):
        itype = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        with django_capture_on_commit_callbacks(execute=True):
            Institution.objects.create(nom="SDIS Test Notif", type=itype)

        alertes = [m for m in mail.outbox if "SDIS Test Notif" in m.subject]
        assert len(alertes) == 1
        assert alertes[0].to == ["admin-notif@test.fr"]

    def test_pas_d_alerte_a_la_modification(self, admins, django_capture_on_commit_callbacks):
        itype = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        institution = Institution.objects.create(nom="SDIS Modif", type=itype)
        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            institution.description = "modifiée"
            institution.save()
        assert not [m for m in mail.outbox if "Nouvelle institution" in m.subject]

    def test_import_un_seul_recapitulatif(self, rf, admins, django_capture_on_commit_callbacks):
        InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})[0]
        request = rf.post("/")
        request.user = admins
        lignes = [{"Nom": f"Mairie Import {i}", "Type": "Mairie"} for i in range(3)]

        with django_capture_on_commit_callbacks(execute=True):
            importer_institutions(request, lignes, {"nom": "Nom", "type": "Type"})

        assert not [m for m in mail.outbox if "Nouvelle institution" in m.subject]
        recap = [m for m in mail.outbox if "importée(s)" in m.subject]
        assert len(recap) == 1
        assert "3 institution(s)" in recap[0].subject


@pytest.mark.django_db
class TestComptesEnAttente:

    def _secours(self, email="agent@sdis40.fr"):
        return User.objects.create_user(
            username=email, email=email, password="Test1234!", type="SECOURS",
            enabled=False, is_active=False, pending_institution_type="sdis",
            pending_institution_name="SDIS des Landes",
        )

    def test_compte_secours_inactif_est_liste(self, admins):
        attente = self._secours()
        client = APIClient()
        client.force_authenticate(user=admins)
        response = client.get(reverse("user-pending-validations"))
        assert str(attente.id) in {u["id"] for u in response.data}

    def test_compte_rejete_n_est_plus_liste(self, admins):
        attente = self._secours(email="rejete@sdis40.fr")
        client = APIClient()
        client.force_authenticate(user=admins)
        client.post(reverse("user-reject-account", kwargs={"pk": attente.id}), {"reason": "test"}, format="json")
        response = client.get(reverse("user-pending-validations"))
        assert str(attente.id) not in {u["id"] for u in response.data}


@pytest.mark.django_db
class TestSdisPorteeNationaleEnDemo:

    def _requete(self, rf, user, environnement):
        request = rf.get("/", HTTP_X_ENVIRONMENT=environnement)
        request.user = user
        return request

    def test_sdis_national_en_demo_departement_en_prod(self, rf, create_user):
        sdis = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        institution = Institution.objects.create(
            nom="SDIS Portee", type=sdis, commune_code="40192", departement_code="40",
        )
        Institution.objects.filter(pk=institution.pk).update(secteur_niveau_effectif="departement", departement_code="40")
        user = create_user(username="agent-portee@sdis40.fr", email="agent-portee@sdis40.fr", type="AUT_LOCALE")
        user.institution = Institution.objects.get(pk=institution.pk)
        user.save(update_fields=["institution"])

        assert viewer_zone_code(self._requete(rf, user, "DEMO")) == ("national", None)
        assert viewer_zone_code(self._requete(rf, user, "PROD")) == ("departement", "40")

    def test_mairie_inchangee_en_demo(self, rf, create_user):
        mairie = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})[0]
        institution = Institution.objects.create(nom="Mairie Portee", type=mairie, commune_code="40192")
        Institution.objects.filter(pk=institution.pk).update(secteur_niveau_effectif="commune")
        user = create_user(username="agent-mairie@test.fr", email="agent-mairie@test.fr", type="AUT_LOCALE")
        user.institution = Institution.objects.get(pk=institution.pk)
        user.save(update_fields=["institution"])

        assert viewer_zone_code(self._requete(rf, user, "DEMO")) == ("commune", "40192")
