import io
import zipfile

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AuditLog,
    Competence,
    Crisis,
    DelegationCompetence,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    PointOperationnel,
    PointType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise export module", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_EXPORT_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie export test", type=itype)


@pytest.fixture
def responsable(create_user, crisis, institution):
    user = create_user(username="resp-export-crise@test.fr", email="resp-export-crise@test.fr", type="AUT_LOCALE")
    ImplicationInstitution.objects.create(
        crise=crisis, institution=institution, type_implication="ACTEUR",
        responsable=user, actif=True,
    )
    return user


@pytest.mark.django_db
class TestCrisisExport:

    def test_responsable_can_export(self, responsable, crisis, institution):
        point_type = PointType.objects.create(code="COLLECTE_EXPORT_TEST", libelle="Point de collecte")
        PointOperationnel.objects.create(nom="Point export test", crise=crisis, type=point_type, responsable=responsable)
        competence = Competence.objects.create(nom="Competence export test")
        itype2 = InstitutionType.objects.create(code="ASSO_EXPORT_TEST", libelle="Association")
        asso = Institution.objects.create(nom="Association export test", type=itype2)
        DelegationCompetence.objects.create(
            institution_source=institution, institution_cible=asso, competence=competence, crise=crisis,
        )

        client = APIClient()
        client.force_authenticate(user=responsable)

        response = client.get(reverse('crisis-export', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/zip"

        content = b"".join(response.streaming_content) if response.streaming else response.content
        zf = zipfile.ZipFile(io.BytesIO(content))
        names = set(zf.namelist())
        assert {
            "audit_log.csv", "dossiers.csv", "dossiers_historique.csv", "dossiers_commentaires.csv",
            "institutions_impliquees.csv", "points_operationnels.csv", "points_inventaire.csv",
            "points_disponibilites_equipe.csv", "delegations_competences.csv",
        }.issubset(names)

        points_csv = zf.read("points_operationnels.csv").decode()
        assert "Point export test" in points_csv

        delegations_csv = zf.read("delegations_competences.csv").decode()
        assert "Competence export test" in delegations_csv

    def test_export_writes_audit_log(self, responsable, crisis):
        client = APIClient()
        client.force_authenticate(user=responsable)

        client.get(reverse('crisis-export', args=[crisis.id]))

        assert AuditLog.objects.filter(objet_id=crisis.id, action__code="EXPORT").exists()

    def test_unrelated_institutional_actor_cannot_export(self, create_user, crisis):
        autre = create_user(username="autre-export-crise@test.fr", email="autre-export-crise@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=autre)

        response = client.get(reverse('crisis-export', args=[crisis.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_anonymous_cannot_export(self, crisis):
        client = APIClient()

        response = client.get(reverse('crisis-export', args=[crisis.id]))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_admin_can_export(self, create_user, crisis):
        admin = create_user(username="admin-export-crise@test.fr", email="admin-export-crise@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('crisis-export', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK
