"""Import CSV/XLS du personnel communal/élus (core/imports.py, ImportApercuView/
ImportPersonnelCommunalView) : parsing des deux formats, mapping de colonnes, création/
rattachement de comptes complets, et surtout la garantie qu'aucune colonne au-delà de
prénom/nom/email/téléphone/fonction ne peut jamais être lue (pas de donnée de santé)."""
import io

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from core.imports import exemple_csv_personnel_communal, importer_personnel_communal, parse_fichier
from core.models import ContactInstitution, Institution, InstitutionType, User


def _make_institution():
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
    return Institution.objects.create(nom="Mairie import test", type=itype)


def _csv_file(lignes, entetes=("Prénom", "Nom", "Email", "Téléphone", "Fonction")):
    buffer = io.StringIO()
    buffer.write(";".join(entetes) + "\n")
    for ligne in lignes:
        buffer.write(";".join(ligne) + "\n")
    return SimpleUploadedFile("import.csv", buffer.getvalue().encode("utf-8-sig"), content_type="text/csv")


def _xlsx_file(entetes, lignes):
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.append(list(entetes))
    for ligne in lignes:
        feuille.append(list(ligne))
    buffer = io.BytesIO()
    classeur.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        "import.xlsx", buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@pytest.mark.django_db
class TestParseFichier:

    def test_parses_csv_with_bom_and_semicolon(self):
        fichier = _csv_file([("Jeanne", "Martin", "jeanne@test.fr", "0600000000", "Maire")])
        colonnes, lignes = parse_fichier(fichier)
        assert colonnes == ["Prénom", "Nom", "Email", "Téléphone", "Fonction"]
        assert lignes == [{
            "Prénom": "Jeanne", "Nom": "Martin", "Email": "jeanne@test.fr",
            "Téléphone": "0600000000", "Fonction": "Maire",
        }]

    def test_parses_xlsx(self):
        fichier = _xlsx_file(["Prénom", "Nom", "Email"], [("Paul", "Durand", "paul@test.fr")])
        colonnes, lignes = parse_fichier(fichier)
        assert colonnes == ["Prénom", "Nom", "Email"]
        assert lignes == [{"Prénom": "Paul", "Nom": "Durand", "Email": "paul@test.fr"}]

    def test_unrecognised_extension_raises(self):
        fichier = SimpleUploadedFile("import.txt", b"contenu", content_type="text/plain")
        with pytest.raises(ValueError):
            parse_fichier(fichier)


@pytest.mark.django_db
class TestImporterPersonnelCommunal:

    def test_creates_account_and_attaches(self, rf, create_user):
        institution = _make_institution()
        admin = create_user(username="admin-import@test.fr", email="admin-import@test.fr", type="AUT_LOCALE", institution=institution)
        request = rf.post("/")
        request.user = admin

        lignes = [{"Prénom": "Jeanne", "Nom": "Martin", "Email": "jeanne.martin@test.fr", "Téléphone": "0600000000", "Fonction": "Maire"}]
        mapping = {"prenom": "Prénom", "nom": "Nom", "email": "Email", "telephone": "Téléphone", "fonction": "Fonction"}

        resultat = importer_personnel_communal(request, institution, lignes, mapping)

        assert resultat == {"crees": 1, "rattaches": 0, "erreurs": []}
        user = User.objects.get(email="jeanne.martin@test.fr")
        assert user.first_name == "Jeanne"
        assert user.last_name == "Martin"
        assert user.institution_id == institution.id
        assert user.type == "AUT_LOCALE"
        assert user.enabled is True
        assert user.is_active is False
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user, fonction="Maire").exists()

    def test_existing_email_is_attached_not_recreated(self, rf, create_user):
        institution = _make_institution()
        admin = create_user(username="admin-import2@test.fr", email="admin-import2@test.fr", type="AUT_LOCALE", institution=institution)
        existant = create_user(username="deja-la@test.fr", email="deja-la@test.fr", type="UTIL_SIMPLE")
        request = rf.post("/")
        request.user = admin

        lignes = [{"Prénom": "X", "Nom": "Y", "Email": "deja-la@test.fr", "Téléphone": "", "Fonction": "Adjoint"}]
        mapping = {"prenom": "Prénom", "nom": "Nom", "email": "Email", "telephone": "Téléphone", "fonction": "Fonction"}

        resultat = importer_personnel_communal(request, institution, lignes, mapping)

        assert resultat == {"crees": 0, "rattaches": 1, "erreurs": []}
        assert User.objects.filter(email="deja-la@test.fr").count() == 1
        existant.refresh_from_db()
        assert existant.institution_id == institution.id

    def test_row_without_email_is_reported_as_error(self, rf, create_user):
        institution = _make_institution()
        admin = create_user(username="admin-import3@test.fr", email="admin-import3@test.fr", type="AUT_LOCALE", institution=institution)
        request = rf.post("/")
        request.user = admin

        lignes = [{"Prénom": "Sans", "Nom": "Email", "Email": "", "Téléphone": "", "Fonction": ""}]
        mapping = {"prenom": "Prénom", "nom": "Nom", "email": "Email", "telephone": "Téléphone", "fonction": "Fonction"}

        resultat = importer_personnel_communal(request, institution, lignes, mapping)

        assert resultat["crees"] == 0
        assert len(resultat["erreurs"]) == 1
        assert resultat["erreurs"][0]["ligne"] == 2

    def test_columns_beyond_the_five_target_fields_are_never_read(self, rf, create_user):
        """Garde-fou santé : même si le fichier source contient une colonne "Allergies" ou
        "Besoins médicaux", elle n'est mappée à AUCUN champ cible et ne peut donc jamais
        atteindre le compte créé — le mapping ne connaît que CHAMPS_PERSONNEL_COMMUNAL."""
        institution = _make_institution()
        admin = create_user(username="admin-import4@test.fr", email="admin-import4@test.fr", type="AUT_LOCALE", institution=institution)
        request = rf.post("/")
        request.user = admin

        lignes = [{
            "Prénom": "Jeanne", "Nom": "Martin", "Email": "jeanne2@test.fr",
            "Allergies": "Pénicilline", "Traitement en cours": "Anticoagulants",
        }]
        mapping = {"prenom": "Prénom", "nom": "Nom", "email": "Email", "telephone": "", "fonction": ""}

        importer_personnel_communal(request, institution, lignes, mapping)

        user = User.objects.get(email="jeanne2@test.fr")
        # Aucun champ santé n'existe sur User : la seule vérification possible est qu'aucune
        # trace de "Allergies"/"Pénicilline" ne s'est glissée nulle part sur le compte créé.
        assert "Pénicilline" not in (user.first_name, user.last_name, user.phone_number or "")


@pytest.mark.django_db
class TestExempleCsv:

    def test_contains_expected_headers(self):
        contenu = exemple_csv_personnel_communal()
        assert "Prénom" in contenu
        assert "Nom" in contenu
        assert "Email" in contenu


@pytest.mark.django_db
class TestImportViews:

    def test_apercu_returns_columns_and_preview(self, create_user):
        institution = _make_institution()
        user = create_user(username="apercu@test.fr", email="apercu@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("Jeanne", "Martin", "jeanne@test.fr", "0600000000", "Maire")])
        response = client.post(reverse("import_apercu"), {"fichier": fichier}, format="multipart")

        assert response.status_code == 200
        assert response.data["colonnes"] == ["Prénom", "Nom", "Email", "Téléphone", "Fonction"]
        assert response.data["total_lignes"] == 1

    def test_apercu_forbidden_for_non_institutional_actor(self, create_user):
        user = create_user(username="simple-apercu@test.fr", email="simple-apercu@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("A", "B", "a@test.fr", "", "")])
        response = client.post(reverse("import_apercu"), {"fichier": fichier}, format="multipart")

        assert response.status_code == 403

    def test_import_end_to_end_via_api(self, create_user):
        institution = _make_institution()
        user = create_user(username="import-e2e@test.fr", email="import-e2e@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("Jeanne", "Martin", "jeanne.e2e@test.fr", "0600000000", "Maire")])
        response = client.post(reverse("import_personnel_communal"), {
            "fichier": fichier,
            "mapping_prenom": "Prénom", "mapping_nom": "Nom", "mapping_email": "Email",
            "mapping_telephone": "Téléphone", "mapping_fonction": "Fonction",
        }, format="multipart")

        assert response.status_code == 200
        assert response.data["crees"] == 1
        assert User.objects.filter(email="jeanne.e2e@test.fr").exists()

    def test_import_without_email_mapping_returns_400(self, create_user):
        institution = _make_institution()
        user = create_user(username="import-nomapping@test.fr", email="import-nomapping@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        fichier = _csv_file([("Jeanne", "Martin", "jeanne3@test.fr", "", "")])
        response = client.post(reverse("import_personnel_communal"), {
            "fichier": fichier, "mapping_nom": "Nom",
        }, format="multipart")

        assert response.status_code == 400

    def test_exemple_download(self, create_user):
        institution = _make_institution()
        user = create_user(username="exemple-dl@test.fr", email="exemple-dl@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("import_personnel_communal_exemple"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
