import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Offer, OfferType, Team
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
