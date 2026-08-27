import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Crisis, MaterielCatalogue, MaterielPoint, PointOperationnel, PointType, Team


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise materiel test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def responsable(create_user):
    return create_user(username="resp-materiel@test.fr", email="resp-materiel@test.fr", type="AUT_LOCALE")


@pytest.fixture
def point(crisis, responsable):
    point_type = PointType.objects.create(code="COLLECTE_MATERIEL_TEST", libelle="Point de collecte test")
    return PointOperationnel.objects.create(nom="Point materiel test", type=point_type, crise=crisis, responsable=responsable)


@pytest.fixture
def responsable_client(responsable):
    client = APIClient()
    client.force_authenticate(user=responsable)
    return client, responsable


@pytest.fixture
def item(db):
    return MaterielCatalogue.objects.create(nom="Pompe immergée test")


@pytest.mark.django_db
class TestMaterielPointCrud:

    def test_create_materiel(self, responsable_client, point, item):
        client, user = responsable_client
        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "item": str(item.id), "niveau_stock": "FAIBLE", "quantite": 2, "unite": "unité", "statut": "EN_TRANSIT"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["item_nom"] == "Pompe immergée test"
        assert response.data["niveau_stock_libelle"] == "Faible"
        assert response.data["statut_libelle"] == "En transit"
        assert response.data["responsable_nom"]

    def test_filter_by_statut(self, responsable_client, point, item):
        client, _ = responsable_client
        autre_item = MaterielCatalogue.objects.create(nom="Cuve test")
        MaterielPoint.objects.create(point=point, item=autre_item, statut="SUR_PLACE")
        MaterielPoint.objects.create(point=point, item=item, statut="EN_TRANSIT")

        response = client.get(reverse('materielpoint-list'), {"point": str(point.id), "statut": "EN_TRANSIT"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["item_nom"] == "Pompe immergée test"

    def test_unrelated_user_cannot_create(self, create_user, point, item):
        user = create_user(username="simple-materiel@test.fr", email="simple-materiel@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "item": str(item.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_team_member_can_create(self, create_user, crisis, point, item):
        member = create_user(username="membre-equipe-materiel@test.fr", email="membre-equipe-materiel@test.fr", type="AUT_LOCALE")
        team = Team.objects.create(name="Equipe materiel test")
        team.members.add(member)
        point.equipe = team
        point.save()

        client = APIClient()
        client.force_authenticate(user=member)
        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "item": str(item.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_update_writes_audit_log(self, responsable_client, point, item):
        from core.models import AuditLog
        client, _ = responsable_client
        materiel = MaterielPoint.objects.create(point=point, item=item)

        client.patch(reverse('materielpoint-detail', args=[materiel.id]), {"niveau_stock": "OK"}, format='json')

        assert AuditLog.objects.filter(objet_id=materiel.id, action__code="MODIFICATION", objet_type="MaterielPoint").exists()

    def test_blocked_on_closed_crisis(self, responsable_client, point, crisis, item):
        client, _ = responsable_client
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "item": str(item.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unique_constraint_point_item(self, responsable_client, point, item):
        client, _ = responsable_client
        MaterielPoint.objects.create(point=point, item=item)

        response = client.post(
            reverse('materielpoint-list'),
            {"point": str(point.id), "item": str(item.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestMaterielCatalogueTagLike:

    def test_search_by_keyword(self, responsable_client):
        client, _ = responsable_client
        MaterielCatalogue.objects.create(nom="Pain frais")

        response = client.get(reverse('materielcatalogue-list'), {"q": "pain"})

        assert response.status_code == status.HTTP_200_OK
        assert any(i["nom"] == "Pain frais" for i in response.data)

    def test_create_reuses_existing_case_insensitive(self, responsable_client):
        client, _ = responsable_client
        existing = MaterielCatalogue.objects.create(nom="Couvertures")

        response = client.post(reverse('materielcatalogue-list'), {"nom": "couvertures"}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(existing.id)
        assert MaterielCatalogue.objects.filter(nom__iexact="couvertures").count() == 1

    def test_create_new_item(self, responsable_client):
        client, _ = responsable_client
        response = client.post(reverse('materielcatalogue-list'), {"nom": "Pain"}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert MaterielCatalogue.objects.filter(nom="Pain").exists()


@pytest.mark.django_db
class TestPointStocksAction:

    def test_stocks_includes_untouched_items_as_nul(self, responsable_client, point, item):
        """L'item existe dans le catalogue mais ce point n'a encore aucune ligne MaterielPoint
        pour lui : il doit quand même apparaître, avec un niveau nul par défaut."""
        client, _ = responsable_client

        response = client.get(reverse('pointoperationnel-stocks', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        entry = next(e for e in response.data if e["item_nom"] == item.nom)
        assert entry["niveau_stock"] == "NUL"
        assert entry["id"] is None

    def test_stocks_reflects_actual_level_when_set(self, responsable_client, point, item):
        client, _ = responsable_client
        MaterielPoint.objects.create(point=point, item=item, niveau_stock="OK")

        response = client.get(reverse('pointoperationnel-stocks', args=[point.id]))

        entry = next(e for e in response.data if e["item_nom"] == item.nom)
        assert entry["niveau_stock"] == "OK"
        assert entry["id"] is not None

    def test_new_item_appears_nul_on_other_point(self, responsable_client, point, crisis):
        """Un item ajouté par un centre doit apparaître, à niveau nul, dans la liste d'un AUTRE
        centre — sans qu'aucune action manuelle n'ait été faite sur cet autre centre."""
        client, _ = responsable_client
        point_type = PointType.objects.create(code="AUTRE_CENTRE_TEST", libelle="Autre centre test")
        autre_point = PointOperationnel.objects.create(nom="Autre centre", type=point_type, crise=crisis)

        # Le premier centre crée un tout nouvel item catalogue
        client.post(reverse('materielcatalogue-list'), {"nom": "Pain complet nouveau"}, format='json')

        response = client.get(reverse('pointoperationnel-stocks', args=[autre_point.id]))
        entry = next(e for e in response.data if e["item_nom"] == "Pain complet nouveau")
        assert entry["niveau_stock"] == "NUL"


@pytest.mark.django_db
class TestCrisisStocksComparaison:

    def test_comparaison_shape(self, responsable_client, point, crisis, item):
        client, _ = responsable_client
        MaterielPoint.objects.create(point=point, item=item, niveau_stock="EN_TROP")

        response = client.get(reverse('crisis-stocks-comparaison', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK
        assert any(p["id"] == str(point.id) for p in response.data["points"])
        item_entry = next(i for i in response.data["items"] if i["item_nom"] == item.nom)
        assert item_entry["niveaux"][str(point.id)]["niveau_stock"] == "EN_TROP"
