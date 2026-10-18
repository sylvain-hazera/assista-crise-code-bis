import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Commune, ContactInstitution, Crisis, Institution, InstitutionType, Offer, OfferType,
    PointOperationnel, PointType, Team,
)
from core.serializers import TeamSerializer, UserSerializer


def _make_institution(nom, code):
    itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={'libelle': 'Test'})
    return Institution.objects.create(nom=nom, type=itype)


@pytest.mark.django_db
class TestUserSerializerInstitutionId:
    """Le sélecteur de responsables du point-modal a besoin de l'institution active de
    l'utilisateur connecté pour filtrer les listes proposées à sa propre institution."""

    def test_returns_active_institution_id(self, create_user):
        institution = _make_institution('Mairie Scoping A', 'SCOPING_A')
        user = create_user(username='scoping-a@test.fr', email='scoping-a@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)

        data = UserSerializer(user).data
        assert data['institution_id'] == str(institution.id)

    def test_none_without_active_institution(self, create_user):
        user = create_user(username='scoping-none@test.fr', email='scoping-none@test.fr', type='UTIL_SIMPLE')
        data = UserSerializer(user).data
        assert data['institution_id'] is None

    def test_ignores_inactive_contact(self, create_user):
        institution = _make_institution('Mairie Scoping B', 'SCOPING_B')
        user = create_user(username='scoping-b@test.fr', email='scoping-b@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=False)

        data = UserSerializer(user).data
        assert data['institution_id'] is None


@pytest.mark.django_db
class TestUsersListInstitutionFilter:
    """Filtre déjà existant côté UserViewSet (?institution=<id>), désormais consommé par le
    point-modal pour restreindre responsables/responsables-supplémentaires à mon institution."""

    def test_filters_to_requested_institution(self, create_user):
        institution_a = _make_institution('Mairie Scoping C', 'SCOPING_C')
        institution_b = _make_institution('Mairie Scoping D', 'SCOPING_D')
        user_a = create_user(username='scoping-c@test.fr', email='scoping-c@test.fr', type='AUT_LOCALE')
        user_b = create_user(username='scoping-d@test.fr', email='scoping-d@test.fr', type='AUT_LOCALE')
        ContactInstitution.objects.create(institution=institution_a, utilisateur=user_a, actif=True)
        ContactInstitution.objects.create(institution=institution_b, utilisateur=user_b, actif=True)

        client = APIClient()
        client.force_authenticate(user=user_a)
        response = client.get(reverse('user-list'), {'institution': str(institution_a.id)})

        assert response.status_code == 200
        emails = {u['email'] for u in response.data}
        assert 'scoping-c@test.fr' in emails
        assert 'scoping-d@test.fr' not in emails


@pytest.mark.django_db
class TestTeamSerializerVehiculesCount:
    """"Équipes de terrain ravitaillées ici" (point-modal) affiche le nombre de véhicules par
    équipe — comptés via les offres de type Transport affectées à l'équipe comme ressource."""

    def test_counts_only_transport_offers(self, create_user):
        institution = _make_institution('Mairie Scoping E', 'SCOPING_E')
        team = Team.objects.create(name='Équipe Scoping E', institution=institution)
        author = create_user(username='scoping-e-offreur@test.fr', email='scoping-e-offreur@test.fr', type='UTIL_SIMPLE')

        transport_type, _ = OfferType.objects.get_or_create(type='Transport', defaults={'description': ''})
        materiel_type, _ = OfferType.objects.get_or_create(type='Matériel', defaults={'description': ''})

        camion = Offer.objects.create(
            title='Camion citerne', first_name_offer='O', last_name_offer='Ffreur',
            email_offer='scoping-e-offreur@test.fr', status='DISPONIBLE', offer_type=transport_type, author=author,
        )
        fourgon = Offer.objects.create(
            title='Fourgon', first_name_offer='O', last_name_offer='Ffreur',
            email_offer='scoping-e-offreur@test.fr', status='DISPONIBLE', offer_type=transport_type, author=author,
        )
        groupe_electrogene = Offer.objects.create(
            title='Groupe électrogène', first_name_offer='O', last_name_offer='Ffreur',
            email_offer='scoping-e-offreur@test.fr', status='DISPONIBLE', offer_type=materiel_type, author=author,
        )
        team.assigned_offers.set([camion, fourgon, groupe_electrogene])

        data = TeamSerializer(team).data
        assert data['vehicules_count'] == 2

    def test_zero_without_transport_offers(self, create_user):
        institution = _make_institution('Mairie Scoping F', 'SCOPING_F')
        team = Team.objects.create(name='Équipe Scoping F', institution=institution)

        data = TeamSerializer(team).data
        assert data['vehicules_count'] == 0


@pytest.mark.django_db
class TestPointOperationnelListZoneScoping:
    """La liste des points opérationnels (action `list`) est réduite à la zone de compétence
    de l'appelant : directement via l'institution de l'équipe rattachée, ou par géocodage
    inverse pour un point sans équipe/institution (voir
    PointOperationnelViewSet._filter_points_to_viewer_zone)."""

    @pytest.fixture
    def commune_a(self, db):
        return Commune.objects.create(
            code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
            region_code="84", centre_latitude=45.18, centre_longitude=5.72,
        )

    @pytest.fixture
    def commune_b(self, db):
        return Commune.objects.create(
            code="38544", nom="Voiron", departement_code="38", epci_code="200070078",
            region_code="84", centre_latitude=45.36, centre_longitude=5.59,
        )

    @pytest.fixture
    def crisis(self, db):
        from django.contrib.gis.geos import Point
        return Crisis.objects.create(name="Crise test points zone", location=Point(5.72, 45.18, srid=4326))

    @pytest.fixture
    def point_type(self, db):
        return PointType.objects.create(code="POINT_ZONE_TEST", libelle="Point test zone")

    def _make_institution(self, code, commune):
        itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})
        return Institution.objects.create(nom=f"Institution {code}", type=itype, commune_code=commune.code)

    def test_point_with_equipe_filtered_by_institution_zone(self, create_user, commune_a, commune_b, crisis, point_type):
        institution_a = self._make_institution("POINT_ZONE_A", commune_a)
        institution_b = self._make_institution("POINT_ZONE_B", commune_b)
        equipe_a = Team.objects.create(name="Equipe Zone A", institution=institution_a)
        equipe_b = Team.objects.create(name="Equipe Zone B", institution=institution_b)
        point_a = PointOperationnel.objects.create(nom="Point A", type=point_type, crise=crisis, equipe=equipe_a)
        point_b = PointOperationnel.objects.create(nom="Point B", type=point_type, crise=crisis, equipe=equipe_b)

        user = create_user(username="point-zone-a@test.fr", email="point-zone-a@test.fr", type="AUT_LOCALE")
        user.institution = institution_a
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('pointoperationnel-list'))
        assert response.status_code == status.HTTP_200_OK
        names = {p['nom'] for p in response.data}
        assert point_a.nom in names
        assert point_b.nom not in names

    def test_point_without_equipe_filtered_by_reverse_geocoding(self, create_user, commune_a, crisis, point_type):
        from django.contrib.gis.geos import Point as GeoPoint
        from unittest.mock import patch

        institution_a = self._make_institution("POINT_ZONE_C", commune_a)
        point_sans_equipe = PointOperationnel.objects.create(
            nom="Point sans équipe", type=point_type, crise=crisis,
            location=GeoPoint(commune_a.centre_longitude, commune_a.centre_latitude, srid=4326),
        )

        user = create_user(username="point-zone-c@test.fr", email="point-zone-c@test.fr", type="AUT_LOCALE")
        user.institution = institution_a
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        with patch("core.views.commune_code_from_point", return_value=commune_a.code):
            response = client.get(reverse('pointoperationnel-list'))

        assert response.status_code == status.HTTP_200_OK
        names = {p['nom'] for p in response.data}
        assert point_sans_equipe.nom in names

    def test_admin_sees_all_zones(self, create_user, commune_a, commune_b, crisis, point_type):
        institution_a = self._make_institution("POINT_ZONE_D", commune_a)
        institution_b = self._make_institution("POINT_ZONE_E", commune_b)
        equipe_a = Team.objects.create(name="Equipe Zone D", institution=institution_a)
        equipe_b = Team.objects.create(name="Equipe Zone E", institution=institution_b)
        PointOperationnel.objects.create(nom="Point D", type=point_type, crise=crisis, equipe=equipe_a)
        PointOperationnel.objects.create(nom="Point E", type=point_type, crise=crisis, equipe=equipe_b)

        user = create_user(username="point-zone-admin@test.fr", email="point-zone-admin@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('pointoperationnel-list'))
        assert response.status_code == status.HTTP_200_OK
        names = {p['nom'] for p in response.data}
        assert {"Point D", "Point E"}.issubset(names)
