import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution,
    Crisis,
    Institution,
    InstitutionType,
    PointOperationnel,
    PointType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise point test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def point_type(db):
    return PointType.objects.create(code="COLLECTE_POINT_TEST", libelle="Point de collecte test")


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_POINT_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie point test", type=itype)


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="acteur-point@test.fr", email="acteur-point@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestPointOperationnelSeedTypes:

    def test_four_requested_point_types_exist(self):
        libelles = set(PointType.objects.values_list('libelle', flat=True))
        assert {
            "Point de transit", "Point de regroupement des moyens",
            "Centre d'accueil des personnes", "Point de collecte",
        }.issubset(libelles)


@pytest.mark.django_db
class TestPointOperationnelLocationSerialization:

    def test_create_with_location_returns_lat_lon(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Point test", "type": str(point_type.id), "crise": str(crisis.id),
                "location": '{"type": "Point", "coordinates": [5.72, 45.18]}',
                "description": "Un point de test",
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["latitude"] == pytest.approx(45.18)
        assert response.data["longitude"] == pytest.approx(5.72)
        assert response.data["description"] == "Un point de test"


@pytest.mark.django_db
class TestPointOperationnelEditPermissions:

    def test_owner_institutional_actor_can_edit(self, institutional_client, crisis, point_type):
        client, user = institutional_client
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis, responsable=user)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nom": "Point renommé", "date_ouverture": "2026-08-27T10:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        point.refresh_from_db()
        assert point.nom == "Point renommé"
        assert point.date_ouverture is not None

    def test_non_institutional_user_cannot_edit(self, create_user, crisis, point_type):
        """Régression : avant ce volet, n'importe quel compte connecté pouvait modifier le
        point opérationnel d'une institution tierce (seul `create` était restreint)."""
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        simple_user = create_user(username="simple-point@test.fr", email="simple-point@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nom": "Modifié sans droit"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_institutional_user_cannot_delete(self, create_user, crisis, point_type):
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        simple_user = create_user(username="simple-point-del@test.fr", email="simple-point-del@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.delete(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PointOperationnel.objects.filter(id=point.id).exists()

    def test_edit_writes_audit_log(self, institutional_client, crisis, point_type):
        from core.models import AuditLog
        client, user = institutional_client
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)

        client.patch(reverse('pointoperationnel-detail', args=[point.id]), {"nom": "Point audité"}, format='json')

        assert AuditLog.objects.filter(
            objet_id=point.id, action__code="MODIFICATION", objet_type="PointOperationnel",
        ).exists()
