import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis, MaterielPoint, PointOperationnel, PointType


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise materiel test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def point(crisis):
    point_type = PointType.objects.create(code="COLLECTE_MATERIEL_TEST", libelle="Point de collecte test")
    return PointOperationnel.objects.create(nom="Point materiel test", type=point_type, crise=crisis)


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="acteur-materiel@test.fr", email="acteur-materiel@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestMaterielPointCrud:

    def test_create_materiel(self, institutional_client, point):
        client, user = institutional_client
        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "type": "POMPE", "nom": "Pompe immergée", "quantite": 2, "unite": "unité", "statut": "EN_TRANSIT"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["type_libelle"] == "Pompe"
        assert response.data["statut_libelle"] == "En transit"
        assert response.data["responsable_nom"]

    def test_filter_by_statut(self, institutional_client, point):
        client, _ = institutional_client
        MaterielPoint.objects.create(point=point, type="CUVE", nom="Cuve 1000L", statut="SUR_PLACE")
        MaterielPoint.objects.create(point=point, type="POMPE", nom="Pompe A", statut="EN_TRANSIT")

        response = client.get(reverse('materielpoint-list'), {"point": str(point.id), "statut": "EN_TRANSIT"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["nom"] == "Pompe A"

    def test_non_institutional_cannot_create(self, create_user, point):
        user = create_user(username="simple-materiel@test.fr", email="simple-materiel@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "type": "AUTRE", "nom": "Test"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_update_writes_audit_log(self, institutional_client, point):
        from core.models import AuditLog
        client, _ = institutional_client
        materiel = MaterielPoint.objects.create(point=point, type="CUVE", nom="Cuve test")

        client.patch(reverse('materielpoint-detail', args=[materiel.id]), {"statut": "RETIRE"}, format='json')

        assert AuditLog.objects.filter(objet_id=materiel.id, action__code="MODIFICATION", objet_type="MaterielPoint").exists()

    def test_blocked_on_closed_crisis(self, institutional_client, point, crisis):
        client, _ = institutional_client
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "type": "CUVE", "nom": "Cuve fermée"},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
