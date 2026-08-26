import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AuditLog,
    Crisis,
    Dossier,
    DossierParticipant,
    ImplicationInstitution,
    Institution,
    InstitutionType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise cloture", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def dossier(db, crisis):
    return Dossier.objects.create(
        numero="DOS-CLOTURE-1", crise=crisis, statut=Dossier.Statut.EN_COURS,
    )


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_CLOTURE_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie cloture test", type=itype)


@pytest.mark.django_db
class TestClotureDossier:

    def test_regulateur_du_dossier_can_cloturer(self, create_user, dossier):
        regulateur = create_user(username="regul-cloture@test.fr", email="regul-cloture@test.fr", type="REGULATEUR")
        DossierParticipant.objects.create(
            dossier=dossier, utilisateur=regulateur, role=DossierParticipant.Role.REGULATION,
        )
        client = APIClient()
        client.force_authenticate(user=regulateur)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.CLOTURE
        assert dossier.date_cloture is not None

    def test_responsable_de_la_crise_can_cloturer(self, create_user, crisis, dossier, institution):
        responsable = create_user(username="resp-cloture@test.fr", email="resp-cloture@test.fr", type="AUT_LOCALE")
        ImplicationInstitution.objects.create(
            crise=crisis, institution=institution, type_implication="IMPLIQUE",
            responsable=responsable, actif=True,
        )
        client = APIClient()
        client.force_authenticate(user=responsable)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK

    def test_unrelated_institutional_user_cannot_cloturer(self, create_user, dossier):
        """Un compte institutionnel qui n'est ni le régulateur de ce dossier ni le
        responsable de la crise ne doit pas pouvoir le clôturer, même si la visibilité en
        lecture (get_queryset) lui montre le dossier."""
        autre = create_user(username="autre-institution@test.fr", email="autre-institution@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=autre)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.EN_COURS

    def test_non_institutional_user_rejected_before_object_check(self, create_user, dossier):
        demandeur = create_user(username="demandeur-cloture@test.fr", email="demandeur-cloture@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=demandeur)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_administrator_can_always_cloturer(self, create_user, dossier):
        admin = create_user(username="admin-cloture@test.fr", email="admin-cloture@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK

    def test_marquer_resolu(self, create_user, dossier):
        admin = create_user(username="admin-resolu@test.fr", email="admin-resolu@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]), {"statut": "RESOLU"}, format='json')

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.RESOLU
        assert dossier.date_resolution is not None
        assert dossier.date_cloture is None

    def test_writes_historique_and_audit_log(self, create_user, dossier):
        admin = create_user(username="admin-audit-cloture@test.fr", email="admin-audit-cloture@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        client.post(reverse('dossier-cloturer', args=[dossier.id]))

        assert dossier.historique.filter(evenement__icontains="clôturé").exists()
        entry = AuditLog.objects.filter(objet_id=dossier.id, action__code="CLOTURE").first()
        assert entry is not None
        assert entry.ancien_etat == Dossier.Statut.EN_COURS
        assert entry.nouvel_etat == Dossier.Statut.CLOTURE

    def test_invalid_statut_rejected(self, create_user, dossier):
        admin = create_user(username="admin-invalid-cloture@test.fr", email="admin-invalid-cloture@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-cloturer', args=[dossier.id]), {"statut": "AFFECTE"}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.EN_COURS


@pytest.mark.django_db
class TestDossierWritePermission:

    def test_participant_cannot_patch_dossier(self, create_user, dossier):
        """Avant ce volet, DossierViewSet n'avait aucune restriction d'écriture au-delà de
        IsAuthenticated : un simple participant (demandeur) pouvait modifier le dossier."""
        demandeur = create_user(username="demandeur-patch@test.fr", email="demandeur-patch@test.fr", type="UTIL_SIMPLE")
        DossierParticipant.objects.create(
            dossier=dossier, utilisateur=demandeur, role=DossierParticipant.Role.DEMANDEUR,
        )
        client = APIClient()
        client.force_authenticate(user=demandeur)

        response = client.patch(reverse('dossier-detail', args=[dossier.id]), {"titre": "Modifié"}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_user_can_patch_dossier(self, create_user, dossier):
        autorite = create_user(username="autorite-patch@test.fr", email="autorite-patch@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=autorite)

        response = client.patch(reverse('dossier-detail', args=[dossier.id]), {"titre": "Modifié"}, format='json')

        assert response.status_code == status.HTTP_200_OK
