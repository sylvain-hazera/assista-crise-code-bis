import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    ContributionMateriel,
    MaterielCatalogue,
    MaterielPoint,
    Offer,
    OfferType,
    PointOperationnel,
    PointType,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise contribution test", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def responsable(create_user):
    return create_user(username="resp-contrib@test.fr", email="resp-contrib@test.fr", type="AUT_LOCALE")


@pytest.fixture
def point(crisis, responsable):
    point_type = PointType.objects.create(code="COLLECTE_CONTRIB_TEST", libelle="Point de collecte test contrib")
    return PointOperationnel.objects.create(nom="Point contrib test", type=point_type, crise=crisis, responsable=responsable)


@pytest.fixture
def responsable_client(responsable):
    client = APIClient()
    client.force_authenticate(user=responsable)
    return client, responsable


@pytest.fixture
def item(db):
    return MaterielCatalogue.objects.create(nom="Couvertures test contrib")


@pytest.fixture
def materiel_point(point, item):
    return MaterielPoint.objects.create(point=point, item=item)


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Matériel (test contrib)", description="")


@pytest.mark.django_db
class TestContributionMaterielCrud:

    def test_create_contribution(self, responsable_client, materiel_point):
        client, _ = responsable_client
        response = client.post(
            reverse('contributionmateriel-list'),
            {"materiel_point": str(materiel_point.id), "fournisseur_nom": "Jean Dupont", "quantite": 5, "unite": "unité"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["fournisseur_nom"] == "Jean Dupont"
        assert response.data["responsable_nom"]

    def test_unrelated_user_cannot_create(self, create_user, materiel_point):
        user = create_user(username="simple-contrib@test.fr", email="simple-contrib@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('contributionmateriel-list'),
            {"materiel_point": str(materiel_point.id), "fournisseur_nom": "X", "quantite": 1},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_team_member_can_create(self, create_user, point, materiel_point):
        member = create_user(username="membre-contrib@test.fr", email="membre-contrib@test.fr", type="AUT_LOCALE")
        team = Team.objects.create(name="Equipe contrib test")
        team.members.add(member)
        point.equipe = team
        point.save()

        client = APIClient()
        client.force_authenticate(user=member)
        response = client.post(
            reverse('contributionmateriel-list'),
            {"materiel_point": str(materiel_point.id), "fournisseur_nom": "Y", "quantite": 1},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_blocked_on_closed_crisis(self, responsable_client, materiel_point, crisis):
        client, _ = responsable_client
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.post(
            reverse('contributionmateriel-list'),
            {"materiel_point": str(materiel_point.id), "fournisseur_nom": "Z", "quantite": 1},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_filter_by_materiel_point(self, responsable_client, materiel_point, point, item):
        client, _ = responsable_client
        autre_item = MaterielCatalogue.objects.create(nom="Autre item test contrib")
        autre_ligne = MaterielPoint.objects.create(point=point, item=autre_item)
        ContributionMateriel.objects.create(materiel_point=materiel_point, fournisseur_nom="A", quantite=1)
        ContributionMateriel.objects.create(materiel_point=autre_ligne, fournisseur_nom="B", quantite=1)

        response = client.get(reverse('contributionmateriel-list'), {"materiel_point": str(materiel_point.id)})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["fournisseur_nom"] == "A"


@pytest.mark.django_db
class TestQuantiteTotale:

    def test_sums_active_contributions(self, materiel_point):
        ContributionMateriel.objects.create(materiel_point=materiel_point, fournisseur_nom="A", quantite=3)
        ContributionMateriel.objects.create(materiel_point=materiel_point, fournisseur_nom="B", quantite=4)
        ContributionMateriel.objects.create(materiel_point=materiel_point, fournisseur_nom="C", quantite=10, statut="RETIRE")

        from core.serializers import MaterielPointSerializer
        data = MaterielPointSerializer(materiel_point).data
        assert data["quantite_totale"] == 7

    def test_none_when_no_contributions(self, materiel_point):
        from core.serializers import MaterielPointSerializer
        data = MaterielPointSerializer(materiel_point).data
        assert data["quantite_totale"] is None


@pytest.mark.django_db
class TestOffreAffecterStock:

    def test_affecter_stock_fixed_type_resolves_catalogue_by_label(self, responsable_client, point, offer_type):
        client, _ = responsable_client
        offer = Offer.objects.create(
            title="Cuve à prêter", first_name_offer="Jean", last_name_offer="Dupont",
            email_offer="jean-cuve@test.fr", status="DISPONIBLE", offer_type=offer_type,
            materiel_type="CUVE", quantite=1, unite="unité",
        )

        response = client.post(reverse('offer-affecter-stock', args=[offer.id]), {"point_id": str(point.id)}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        materiel_point = MaterielPoint.objects.get(point=point, item__nom__iexact="Cuve")
        contribution = materiel_point.contributions.get()
        assert contribution.offre_id == offer.id
        assert contribution.fournisseur_nom == "Jean Dupont"

    def test_affecter_stock_autre_uses_materiel_catalogue(self, responsable_client, point, offer_type, item):
        client, _ = responsable_client
        offer = Offer.objects.create(
            title="Lits de camp", first_name_offer="A", last_name_offer="B",
            email_offer="lits@test.fr", status="DISPONIBLE", offer_type=offer_type,
            materiel_type="AUTRE", materiel_catalogue=item, quantite=8, unite="unité",
        )

        response = client.post(reverse('offer-affecter-stock', args=[offer.id]), {"point_id": str(point.id)}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        materiel_point = MaterielPoint.objects.get(point=point, item=item)
        contribution = materiel_point.contributions.get()
        assert contribution.quantite == 8

    def test_rejects_non_materiel_offer(self, responsable_client, point, offer_type):
        client, _ = responsable_client
        offer = Offer.objects.create(
            title="Aide bénévole", first_name_offer="A", last_name_offer="B",
            email_offer="benevole@test.fr", status="DISPONIBLE", offer_type=offer_type,
        )

        response = client.post(reverse('offer-affecter-stock', args=[offer.id]), {"point_id": str(point.id)}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unrelated_user_forbidden(self, create_user, point, offer_type):
        user = create_user(username="simple-affecter@test.fr", email="simple-affecter@test.fr", type="AUT_LOCALE")
        offer = Offer.objects.create(
            title="Pompe", first_name_offer="A", last_name_offer="B",
            email_offer="pompe@test.fr", status="DISPONIBLE", offer_type=offer_type, materiel_type="POMPE",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse('offer-affecter-stock', args=[offer.id]), {"point_id": str(point.id)}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_reuses_existing_materiel_point_line(self, responsable_client, point, offer_type, materiel_point, item):
        """Deux offres du même item catalogue sur le même point doivent créer deux
        contributions sur LA MÊME ligne MaterielPoint, pas deux lignes (contrainte unique)."""
        client, _ = responsable_client
        offer1 = Offer.objects.create(
            title="Couvertures 1", first_name_offer="A", last_name_offer="B", email_offer="c1@test.fr",
            status="DISPONIBLE", offer_type=offer_type, materiel_type="AUTRE", materiel_catalogue=item, quantite=5,
        )
        offer2 = Offer.objects.create(
            title="Couvertures 2", first_name_offer="C", last_name_offer="D", email_offer="c2@test.fr",
            status="DISPONIBLE", offer_type=offer_type, materiel_type="AUTRE", materiel_catalogue=item, quantite=3,
        )

        r1 = client.post(reverse('offer-affecter-stock', args=[offer1.id]), {"point_id": str(point.id)}, format='json')
        r2 = client.post(reverse('offer-affecter-stock', args=[offer2.id]), {"point_id": str(point.id)}, format='json')

        assert r1.status_code == status.HTTP_201_CREATED
        assert r2.status_code == status.HTTP_201_CREATED
        assert MaterielPoint.objects.filter(point=point, item=item).count() == 1
        assert materiel_point.contributions.count() == 2
