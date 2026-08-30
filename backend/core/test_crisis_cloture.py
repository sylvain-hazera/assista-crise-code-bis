import pytest
from django.urls import reverse
from django.utils import timezone
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
    return Crisis.objects.create(name="Crise cloture module", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_CLOTURE_CRISE_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie cloture crise test", type=itype)


@pytest.fixture
def responsable(create_user, crisis, institution):
    user = create_user(username="resp-cloture-crise@test.fr", email="resp-cloture-crise@test.fr", type="AUT_LOCALE")
    ImplicationInstitution.objects.create(
        crise=crisis, institution=institution, type_implication="IMPLIQUE",
        responsable=user, actif=True,
    )
    return user


@pytest.mark.django_db
class TestCloturerCrisis:

    def test_responsable_can_cloturer(self, responsable, crisis):
        client = APIClient()
        client.force_authenticate(user=responsable)

        response = client.post(reverse('crisis-cloturer', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK
        crisis.refresh_from_db()
        assert crisis.end_date is not None
        assert AuditLog.objects.filter(objet_id=crisis.id, action__code="CLOTURE").exists()

    def test_admin_can_cloturer(self, create_user, crisis):
        admin = create_user(username="admin-cloture-crise@test.fr", email="admin-cloture-crise@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('crisis-cloturer', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK

    def test_unrelated_user_cannot_cloturer(self, create_user, crisis):
        autre = create_user(username="autre-cloture-crise@test.fr", email="autre-cloture-crise@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=autre)

        response = client.post(reverse('crisis-cloturer', args=[crisis.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        crisis.refresh_from_db()
        assert crisis.end_date is None

    def test_double_cloture_rejected(self, responsable, crisis):
        client = APIClient()
        client.force_authenticate(user=responsable)
        client.post(reverse('crisis-cloturer', args=[crisis.id]))

        response = client.post(reverse('crisis-cloturer', args=[crisis.id]))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_admin_can_reouvrir(self, create_user, responsable, crisis):
        client = APIClient()
        client.force_authenticate(user=responsable)
        client.post(reverse('crisis-cloturer', args=[crisis.id]))

        admin = create_user(username="admin-reouvre@test.fr", email="admin-reouvre@test.fr", type="ADMIN")
        admin_client = APIClient()
        admin_client.force_authenticate(user=admin)

        response = admin_client.post(reverse('crisis-reouvrir', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK
        crisis.refresh_from_db()
        assert crisis.end_date is None

    def test_responsable_cannot_reouvrir(self, responsable, crisis):
        client = APIClient()
        client.force_authenticate(user=responsable)
        client.post(reverse('crisis-cloturer', args=[crisis.id]))

        response = client.post(reverse('crisis-reouvrir', args=[crisis.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCrisisLockAppliesToLinkedResources:

    def test_cannot_create_implication_on_closed_crisis(self, responsable, crisis, institution, create_user):
        crisis.end_date = timezone.now()
        crisis.save()
        autre_institution_type = InstitutionType.objects.create(code="SDIS_CLOTURE_TEST", libelle="SDIS")
        autre_institution = Institution.objects.create(nom="SDIS cloture test", type=autre_institution_type)
        user = create_user(username="declarant-cloture@test.fr", email="declarant-cloture@test.fr", type="AUT_LOCALE")
        from core.models import ContactInstitution
        ContactInstitution.objects.create(institution=autre_institution, utilisateur=user, actif=True)

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(autre_institution.id), "type_implication": "IMPLIQUE"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "crise" in response.data

    def test_cannot_create_point_on_closed_crisis(self, crisis, create_user, institution):
        crisis.end_date = timezone.now()
        crisis.save()
        point_type = PointType.objects.create(code="COLLECTE_CLOTURE_TEST", libelle="Point de collecte")
        user = create_user(username="acteur-cloture@test.fr", email="acteur-cloture@test.fr", type="AUT_LOCALE")
        from core.models import ContactInstitution
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('pointoperationnel-list'),
            {"nom": "Point test cloture", "type": str(point_type.id), "crise": str(crisis.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "crise" in response.data

    def test_cannot_create_delegation_on_closed_crisis(self, crisis, institution, create_user):
        crisis.end_date = timezone.now()
        crisis.save()
        itype2 = InstitutionType.objects.create(code="ASSO_CLOTURE_TEST", libelle="Association")
        association = Institution.objects.create(nom="Association cloture test", type=itype2)
        competence = Competence.objects.create(nom="Competence cloture test")
        user = create_user(username="delegant-cloture@test.fr", email="delegant-cloture@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('delegationcompetence-list'),
            {
                "institution_source": str(institution.id), "institution_cible": str(association.id),
                "competence": str(competence.id), "crise": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "crise" in response.data

    def test_can_still_edit_point_without_crise_in_payload_when_crisis_closed(self, crisis, institution, create_user):
        """Un PATCH qui ne touche pas au champ `crise` doit quand même être bloqué si la
        crise déjà rattachée à l'instance est fermée — sinon le verrou est contournable en ne
        renvoyant jamais ce champ dans le payload."""
        point_type = PointType.objects.create(code="COLLECTE_CLOTURE_TEST2", libelle="Point de collecte 2")
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        crisis.end_date = timezone.now()
        crisis.save()
        user = create_user(username="editeur-cloture@test.fr", email="editeur-cloture@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nom": "Point renommé"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_can_still_create_implication_on_open_crisis(self, crisis, institution, create_user):
        """Non-régression : le verrou ne doit pas bloquer une crise ouverte."""
        user = create_user(username="declarant-ouvert@test.fr", email="declarant-ouvert@test.fr", type="AUT_LOCALE")
        from core.models import ContactInstitution
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(institution.id), "type_implication": "IMPLIQUE"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
