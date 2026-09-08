import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel,
    AuditLog,
    Competence,
    ContactInstitution,
    Institution,
    InstitutionType,
    RoleOperationnel,
)


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_AFF_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie affectation test", type=itype)


@pytest.fixture
def other_institution(db):
    itype = InstitutionType.objects.create(code="SDIS_AFF_TEST", libelle="SDIS")
    return Institution.objects.create(nom="SDIS affectation test", type=itype)


@pytest.fixture
def role_regulateur(db):
    return RoleOperationnel.objects.create(code="REGULATEUR_TEST", libelle="Régulateur")


@pytest.fixture
def competence(db):
    return Competence.objects.create(nom="Compétence affectation test")


@pytest.fixture
def own_institution_client(create_user, institution):
    user = create_user(username="membre-institution@test.fr", email="membre-institution@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def admin_client(create_user):
    user = create_user(username="admin-affectation@test.fr", email="admin-affectation@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestAffectationRoleOperationnelPermissions:

    def test_own_institution_member_can_create(self, own_institution_client, institution, role_regulateur, create_user):
        client, _ = own_institution_client
        target = create_user(username="futur-regulateur@test.fr", email="futur-regulateur@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {"utilisateur": str(target.id), "institution": str(institution.id), "role": str(role_regulateur.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert AuditLog.objects.filter(objet_type="AffectationRoleOperationnel", action__code="AFFECTATION").exists()

    def test_non_member_cannot_create_for_other_institution(self, own_institution_client, other_institution, role_regulateur, create_user):
        client, _ = own_institution_client
        target = create_user(username="cible@test.fr", email="cible@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {"utilisateur": str(target.id), "institution": str(other_institution.id), "role": str(role_regulateur.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not AffectationRoleOperationnel.objects.filter(institution=other_institution).exists()

    def test_admin_can_create_for_any_institution(self, admin_client, other_institution, role_regulateur, create_user):
        client, _ = admin_client
        target = create_user(username="cible2@test.fr", email="cible2@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {"utilisateur": str(target.id), "institution": str(other_institution.id), "role": str(role_regulateur.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_can_create_without_competence(self, own_institution_client, institution, role_regulateur, create_user):
        client, _ = own_institution_client
        target = create_user(username="sans-theme@test.fr", email="sans-theme@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {"utilisateur": str(target.id), "institution": str(institution.id), "role": str(role_regulateur.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["competence"] is None

    def test_create_with_competence(self, own_institution_client, institution, role_regulateur, competence, create_user):
        client, _ = own_institution_client
        target = create_user(username="avec-theme@test.fr", email="avec-theme@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {
                "utilisateur": str(target.id), "institution": str(institution.id),
                "role": str(role_regulateur.id), "competence": str(competence.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data["competence"]) == str(competence.id)

    def test_create_with_zone_and_responsabilite(self, own_institution_client, institution, role_regulateur, create_user):
        """Zone d'intervention (catalogue Zone de l'institution) et responsabilité (texte
        libre) — onglet "Régulateurs / thèmes" des Institutions."""
        from core.models import Zone

        client, _ = own_institution_client
        target = create_user(username="avec-zone@test.fr", email="avec-zone@test.fr", type="UTIL_SIMPLE")
        zone = Zone.objects.create(institution=institution, nom="Quartier Nord")

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {
                "utilisateur": str(target.id), "institution": str(institution.id),
                "role": str(role_regulateur.id), "zone": str(zone.id),
                "responsabilite": "Coordination hébergement nord",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data["zone"]) == str(zone.id)
        assert response.data["responsabilite"] == "Coordination hébergement nord"

    def test_simple_user_cannot_create(self, create_user, institution, role_regulateur):
        outsider = create_user(username="simple-affectation@test.fr", email="simple-affectation@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.post(
            reverse('affectationroleoperationnel-list'),
            {"utilisateur": str(outsider.id), "institution": str(institution.id), "role": str(role_regulateur.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
