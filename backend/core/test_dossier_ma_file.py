import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel,
    Competence,
    Crisis,
    Dossier,
    Institution,
    InstitutionType,
    RoleOperationnel,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise ma_file", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def regulateur_setup(db, create_user):
    """Un régulateur affecté à une compétence, dans une institution donnée."""
    regulateur = create_user(username="regul-mafile@test.fr", email="regul-mafile@test.fr", type="REGULATEUR")
    role = RoleOperationnel.objects.create(code="REGULATEUR", libelle="Régulateur")
    competence = Competence.objects.create(nom="Compétence ma_file")
    itype = InstitutionType.objects.create(code="MAIRIE_MAFILE_TEST", libelle="Mairie")
    institution = Institution.objects.create(nom="Mairie ma_file test", type=itype)
    AffectationRoleOperationnel.objects.create(
        utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
    )
    client = APIClient()
    client.force_authenticate(user=regulateur)
    return client, regulateur, competence


@pytest.mark.django_db
class TestDossierMaFile:

    def test_sees_only_dossier_on_own_competence(self, regulateur_setup, crisis):
        client, _, competence = regulateur_setup
        autre_competence = Competence.objects.create(nom="Autre compétence")

        mine = Dossier.objects.create(
            numero="DOS-MAFILE-1", crise=crisis, competence=competence,
            statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
        )
        Dossier.objects.create(
            numero="DOS-MAFILE-2", crise=crisis, competence=autre_competence,
            statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
        )

        response = client.get(reverse('dossier-ma-file'))

        assert response.status_code == status.HTTP_200_OK
        ids = [d["id"] for d in response.data]
        assert str(mine.id) in ids
        assert len(ids) == 1

    def test_excludes_dossier_already_assigned(self, regulateur_setup, crisis):
        client, _, competence = regulateur_setup
        Dossier.objects.create(
            numero="DOS-MAFILE-3", crise=crisis, competence=competence, statut=Dossier.Statut.AFFECTE,
        )

        response = client.get(reverse('dossier-ma-file'))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_unauthenticated_is_rejected(self, crisis):
        client = APIClient()
        response = client.get(reverse('dossier-ma-file'))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_regulateur_institutional_user_sees_nothing_via_ma_file(self, crisis, create_user):
        """`ma_file` reste réservée aux compétences réellement affectées à l'utilisateur —
        contrairement à la liste générale, un compte institutionnel sans affectation
        régulateur ne doit rien voir ici."""
        competence = Competence.objects.create(nom="Compétence non affectée")
        Dossier.objects.create(
            numero="DOS-MAFILE-4", crise=crisis, competence=competence,
            statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
        )

        user = create_user(username="autorite-mafile@test.fr", email="autorite-mafile@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dossier-ma-file'))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
