"""Import CSV/XLS d'institutions (core/imports.py, ImportApercuView/ImportInstitutionsView) :
mapping de colonnes, création d'institutions, et les gardes-fous propres à cet import — type
d'institution qui doit déjà exister (jamais créé à la volée), nom déjà pris signalé en erreur
plutôt que dupliqué."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from core.imports import exemple_csv_institutions, importer_institutions
from core.models import Institution, InstitutionType


def _csv_file(lignes, entetes=("Nom", "Type", "Description", "Téléphone", "Email", "Adresse")):
    buffer = io.StringIO()
    buffer.write(";".join(entetes) + "\n")
    for ligne in lignes:
        buffer.write(";".join(ligne) + "\n")
    return SimpleUploadedFile("import.csv", buffer.getvalue().encode("utf-8-sig"), content_type="text/csv")


_MAPPING = {
    "nom": "Nom", "type": "Type", "description": "Description",
    "telephone": "Téléphone", "email": "Email", "adresse": "Adresse",
}


@pytest.mark.django_db
class TestImporterInstitutions:

    def test_creates_institution(self, rf, create_user):
        InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        admin = create_user(username="admin-import-inst@test.fr", email="admin-import-inst@test.fr", type="ADMIN")
        request = rf.post("/")
        request.user = admin

        lignes = [{
            "Nom": "Mairie de Testville", "Type": "Mairie", "Description": "",
            "Téléphone": "0100000000", "Email": "mairie@testville.fr", "Adresse": "1 rue Test",
        }]

        resultat = importer_institutions(request, lignes, _MAPPING)

        assert resultat == {"crees": 1, "erreurs": []}
        institution = Institution.objects.get(nom="Mairie de Testville")
        assert institution.type.code == "MAIRIE"
        assert institution.email == "mairie@testville.fr"
        assert institution.telephone == "0100000000"

    def test_type_matching_is_case_insensitive(self, rf, create_user):
        InstitutionType.objects.create(code="ASSO", libelle="Association")
        admin = create_user(username="admin-import-inst2@test.fr", email="admin-import-inst2@test.fr", type="ADMIN")
        request = rf.post("/")
        request.user = admin

        lignes = [{"Nom": "Croix-Rouge Test", "Type": "  association  ", "Description": "", "Téléphone": "", "Email": "", "Adresse": ""}]

        resultat = importer_institutions(request, lignes, _MAPPING)

        assert resultat["crees"] == 1
        assert Institution.objects.filter(nom="Croix-Rouge Test", type__code="ASSO").exists()

    def test_unknown_type_is_reported_as_error(self, rf, create_user):
        admin = create_user(username="admin-import-inst3@test.fr", email="admin-import-inst3@test.fr", type="ADMIN")
        request = rf.post("/")
        request.user = admin

        lignes = [{"Nom": "Institution X", "Type": "TypeInexistant", "Description": "", "Téléphone": "", "Email": "", "Adresse": ""}]

        resultat = importer_institutions(request, lignes, _MAPPING)

        assert resultat["crees"] == 0
        assert len(resultat["erreurs"]) == 1
        assert "inconnu" in resultat["erreurs"][0]["message"].lower()

    def test_missing_nom_or_type_is_reported_as_error(self, rf, create_user):
        InstitutionType.objects.create(code="MAIRIE2", libelle="Mairie")
        admin = create_user(username="admin-import-inst4@test.fr", email="admin-import-inst4@test.fr", type="ADMIN")
        request = rf.post("/")
        request.user = admin

        lignes = [{"Nom": "", "Type": "Mairie", "Description": "", "Téléphone": "", "Email": "", "Adresse": ""}]

        resultat = importer_institutions(request, lignes, _MAPPING)

        assert resultat["crees"] == 0
        assert resultat["erreurs"][0]["ligne"] == 2

    def test_duplicate_name_is_reported_as_error_not_recreated(self, rf, create_user):
        itype = InstitutionType.objects.create(code="MAIRIE3", libelle="Mairie")
        Institution.objects.create(nom="Mairie Déjà Là", type=itype)
        admin = create_user(username="admin-import-inst5@test.fr", email="admin-import-inst5@test.fr", type="ADMIN")
        request = rf.post("/")
        request.user = admin

        lignes = [{"Nom": "Mairie Déjà Là", "Type": "Mairie", "Description": "", "Téléphone": "", "Email": "", "Adresse": ""}]

        resultat = importer_institutions(request, lignes, _MAPPING)

        assert resultat["crees"] == 0
        assert len(resultat["erreurs"]) == 1
        assert Institution.objects.filter(nom="Mairie Déjà Là").count() == 1


@pytest.mark.django_db
class TestImportInstitutionsViews:

    def test_import_end_to_end_via_api(self, create_user):
        InstitutionType.objects.create(code="MAIRIE4", libelle="Mairie")
        user = create_user(username="import-inst-e2e@test.fr", email="import-inst-e2e@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("Mairie E2E", "Mairie", "", "", "", "")])
        response = client.post(reverse("import_institutions"), {
            "fichier": fichier,
            "mapping_nom": "Nom", "mapping_type": "Type", "mapping_description": "Description",
            "mapping_telephone": "Téléphone", "mapping_email": "Email", "mapping_adresse": "Adresse",
        }, format="multipart")

        assert response.status_code == 200
        assert response.data["crees"] == 1
        assert Institution.objects.filter(nom="Mairie E2E").exists()

    def test_forbidden_for_non_institutional_actor(self, create_user):
        user = create_user(username="simple-import-inst@test.fr", email="simple-import-inst@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("A", "Mairie", "", "", "", "")])
        response = client.post(reverse("import_institutions"), {
            "fichier": fichier, "mapping_nom": "Nom", "mapping_type": "Type",
        }, format="multipart")

        assert response.status_code == 403

    def test_import_without_type_mapping_returns_400(self, create_user):
        user = create_user(username="import-inst-nomapping@test.fr", email="import-inst-nomapping@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("A", "Mairie", "", "", "", "")])
        response = client.post(reverse("import_institutions"), {
            "fichier": fichier, "mapping_nom": "Nom",
        }, format="multipart")

        assert response.status_code == 400

    def test_exemple_download(self, create_user):
        user = create_user(username="exemple-dl-inst@test.fr", email="exemple-dl-inst@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("import_institutions_exemple"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")


class TestExempleCsvInstitutions:

    def test_contains_expected_headers(self):
        contenu = exemple_csv_institutions()
        assert "Nom de l'institution" in contenu
        assert "Type (libellé exact déjà existant, ex: Mairie)" in contenu
