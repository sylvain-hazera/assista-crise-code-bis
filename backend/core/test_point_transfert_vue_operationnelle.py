import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Crisis,
    MaterielCatalogue,
    MaterielPoint,
    Notification,
    NiveauStock,
    Offer,
    OfferType,
    PointOperationnel,
    PointType,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise transfert test", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def point_type(db):
    return PointType.objects.create(code="REGROUPEMENT_MOYENS_TEST", libelle="Regroupement des moyens test")


@pytest.fixture
def point_source(db, crisis, point_type, create_user):
    responsable = create_user(username="resp-source@test.fr", email="resp-source@test.fr", type="AUT_LOCALE")
    return PointOperationnel.objects.create(nom="Centre A", type=point_type, crise=crisis, responsable=responsable)


@pytest.fixture
def point_destination(db, crisis, point_type):
    return PointOperationnel.objects.create(nom="Centre B", type=point_type, crise=crisis)


@pytest.fixture
def materiel_point(db, point_source):
    item = MaterielCatalogue.objects.create(nom="Lits de camp (test transfert)")
    return MaterielPoint.objects.create(point=point_source, item=item, niveau_stock=NiveauStock.EN_TROP, quantite=12, unite="unité")


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="acteur-transfert@test.fr", email="acteur-transfert@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestPointResponsablesEffectifs:

    def test_union_of_responsable_and_responsables_m2m(self, point_source, create_user):
        resp2 = create_user(username="resp2@test.fr", email="resp2@test.fr", type="AUT_LOCALE")
        point_source.responsables.add(resp2)
        effectifs = point_source.responsables_effectifs()
        emails = {u.email for u in effectifs}
        assert emails == {"resp-source@test.fr", "resp2@test.fr"}

    def test_includes_team_leaders_from_equipes_gestion(self, point_source, create_user):
        chef = create_user(username="chef-equipe@test.fr", email="chef-equipe@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe gestion test", description="", color="#3b82f6", leader=chef)
        point_source.equipes_gestion.add(team)
        effectifs = point_source.responsables_effectifs()
        emails = {u.email for u in effectifs}
        assert "chef-equipe@test.fr" in emails
        assert "resp-source@test.fr" in emails

    def test_dedupes_same_person_in_multiple_roles(self, point_source):
        # Le responsable historique est aussi ajouté au M2M : ne doit compter qu'une fois.
        point_source.responsables.add(point_source.responsable)
        assert len(point_source.responsables_effectifs()) == 1

    def test_no_responsable_returns_empty_list(self, point_destination):
        assert point_destination.responsables_effectifs() == []


@pytest.mark.django_db
class TestStocksComparaisonIncludesContactsEtQuantites:

    def test_points_include_responsables_contacts(self, institutional_client, crisis, point_source, point_destination):
        client, _ = institutional_client
        response = client.get(reverse('crisis-stocks-comparaison', args=[crisis.id]))
        assert response.status_code == status.HTTP_200_OK
        point_a = next(p for p in response.data['points'] if p['nom'] == 'Centre A')
        assert point_a['responsables_contacts'][0]['email'] == 'resp-source@test.fr'

    def test_items_include_materiel_point_id_and_quantite(self, institutional_client, crisis, point_source, materiel_point):
        client, _ = institutional_client
        response = client.get(reverse('crisis-stocks-comparaison', args=[crisis.id]))
        assert response.status_code == status.HTTP_200_OK
        item_row = next(i for i in response.data['items'] if i['item_nom'] == 'Lits de camp (test transfert)')
        cell = item_row['niveaux'][str(point_source.id)]
        assert cell['materiel_point_id'] == str(materiel_point.id)
        assert cell['quantite'] == 12
        assert cell['unite'] == 'unité'


@pytest.mark.django_db
class TestDemanderTransfert:

    def test_creates_notification_and_email_for_source_responsables(self, institutional_client, point_source, point_destination, materiel_point):
        client, demandeur = institutional_client
        response = client.post(
            reverse('pointoperationnel-demander-transfert', args=[point_source.id]),
            {
                "destination_point_id": str(point_destination.id),
                "items": [{"materiel_point_id": str(materiel_point.id), "quantite_demandee": 5}],
                "message": "On en a besoin rapidement",
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['notifies'] == 1
        assert Notification.objects.filter(utilisateur=point_source.responsable).exists()
        notif = Notification.objects.get(utilisateur=point_source.responsable)
        assert "Centre A" in notif.titre
        assert "Centre B" in notif.titre
        assert "Lits de camp" in notif.message
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["resp-source@test.fr"]

    def test_rejects_empty_items(self, institutional_client, point_source, point_destination):
        client, _ = institutional_client
        response = client.post(
            reverse('pointoperationnel-demander-transfert', args=[point_source.id]),
            {"destination_point_id": str(point_destination.id), "items": []},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_ignores_materiel_point_belonging_to_another_point(self, institutional_client, point_source, point_destination, materiel_point):
        """Un materiel_point_id qui n'appartient pas au point source (pk) est ignoré, pas
        exploitable pour usurper le stock d'un autre point."""
        client, _ = institutional_client
        response = client.post(
            reverse('pointoperationnel-demander-transfert', args=[point_destination.id]),
            {
                "destination_point_id": str(point_source.id),
                "items": [{"materiel_point_id": str(materiel_point.id), "quantite_demandee": 1}],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestVueOperationnelle:

    def test_returns_equipes_gestion_ravitaillement_et_civils(self, institutional_client, point_source, create_user):
        client, _ = institutional_client
        membre = create_user(username="membre-gestion@test.fr", email="membre-gestion@test.fr", type="UTIL_SIMPLE")
        equipe_gestion = Team.objects.create(name="Equipe gestion", description="", color="#3b82f6")
        equipe_gestion.members.add(membre)
        point_source.equipes_gestion.add(equipe_gestion)

        equipe_ravito = Team.objects.create(name="Equipe terrain", description="", color="#22c55e")
        point_source.equipes_ravitaillement.add(equipe_ravito)

        offer_type = OfferType.objects.create(type="Matériel", description="")
        catalogue = MaterielCatalogue.objects.create(nom="Groupe électrogène (test vue op)")
        offre = Offer.objects.create(
            title="Groupe électrogène", offer_type=offer_type,
            first_name_offer="A", last_name_offer="B", email_offer="a@test.fr",
            location="POINT (5.72 45.18)", status="DISPONIBLE",
            materiel_type="AUTRE", materiel_catalogue=catalogue, quantite=2, unite="unité",
        )
        equipe_gestion.assigned_offers.add(offre)

        response = client.get(reverse('pointoperationnel-vue-operationnelle', args=[point_source.id]))
        assert response.status_code == status.HTTP_200_OK
        d = response.data

        gestion = next(e for e in d['equipes_gestion'] if e['nom'] == 'Equipe gestion')
        assert gestion['effectif'] == 1
        assert gestion['materiel'][0]['materiel_catalogue_nom'] == 'Groupe électrogène (test vue op)'
        assert gestion['materiel'][0]['quantite'] == 2

        assert any(e['nom'] == 'Equipe terrain' for e in d['equipes_ravitaillement'])
        assert d['civils_accueillis'] == 0

    def test_civils_accueillis_counts_only_evacues(self, institutional_client, point_source):
        from core.models import RegistrePresence, TypePersonneAccueillie
        client, _ = institutional_client
        RegistrePresence.objects.create(point=point_source, type_personne=TypePersonneAccueillie.EVACUE, nombre=8)
        RegistrePresence.objects.create(point=point_source, type_personne=TypePersonneAccueillie.POMPIER, nombre=3)

        response = client.get(reverse('pointoperationnel-vue-operationnelle', args=[point_source.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['civils_accueillis'] == 8


@pytest.mark.django_db
class TestPatchEquipesEtResponsablesM2M:

    def test_patch_equipes_gestion_ids(self, institutional_client, point_source):
        client, _ = institutional_client
        team = Team.objects.create(name="Nouvelle equipe gestion", description="", color="#3b82f6")
        response = client.patch(
            reverse('pointoperationnel-detail', args=[point_source.id]),
            {"equipes_gestion_ids": [str(team.id)]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['equipes_gestion_noms'] == ['Nouvelle equipe gestion']

    def test_patch_responsables_ids(self, institutional_client, point_source, create_user):
        client, _ = institutional_client
        autre = create_user(username="autre-resp@test.fr", email="autre-resp@test.fr", type="AUT_LOCALE")
        response = client.patch(
            reverse('pointoperationnel-detail', args=[point_source.id]),
            {"responsables_ids": [str(autre.id)]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        emails = {c['email'] for c in response.data['responsables_contacts']}
        assert "autre-resp@test.fr" in emails
        assert "resp-source@test.fr" in emails
