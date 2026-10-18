import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, Crisis, DemandeMobilisation, Institution,
    InstitutionType, Notification, Offer, OfferType, RoleOperationnel,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_DEMANDE', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test demande', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


def _make_crisis():
    return Crisis.objects.create(name='Crise demande test', type='INCENDIE', location='POINT (5.72 45.18)')


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie Demande A')


@pytest.fixture
def crisis(institution_a):
    return _make_crisis()


def _client_avec_role(create_user, institution, role_code, email):
    user = create_user(username=email, email=email, type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    if role_code:
        role, _ = RoleOperationnel.objects.get_or_create(code=role_code, defaults={'libelle': role_code})
        AffectationRoleOperationnel.objects.create(utilisateur=user, institution=institution, role=role, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def responsable_client(create_user, institution_a):
    return _client_avec_role(create_user, institution_a, 'RESPONSABLE', 'responsable-demande@test.fr')


@pytest.fixture
def regulateur_client(create_user, institution_a):
    return _client_avec_role(create_user, institution_a, 'REGULATEUR', 'regulateur-demande@test.fr')


@pytest.fixture
def simple_membre_client(create_user, institution_a):
    """Membre institutionnel SANS rôle responsable/régulateur — doit pouvoir consulter mais
    jamais émettre."""
    return _client_avec_role(create_user, institution_a, None, 'membre-simple-demande@test.fr')


def _payload_de_base(crisis, institution_a, **overrides):
    payload = {
        'crise': str(crisis.id),
        'institution_emettrice': str(institution_a.id),
        'type_demande': 'MISE_A_DISPOSITION',
        'motif': 'Renfort nécessaire',
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestCreationDemandeMobilisation:

    def test_responsable_peut_emettre_vers_utilisateur(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-demande@test.fr', email='cible-demande@test.fr')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['cible_type'] == 'utilisateur'
        assert response.data['cible_nom']
        assert response.data['statut'] == 'ACTIVE'
        assert response.data['jeton_verification']

    def test_regulateur_peut_emettre(self, regulateur_client, crisis, institution_a, create_user):
        client, _ = regulateur_client
        cible = create_user(username='cible-demande-2@test.fr', email='cible-demande-2@test.fr')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_membre_simple_ne_peut_pas_emettre(self, simple_membre_client, crisis, institution_a, create_user):
        client, _ = simple_membre_client
        cible = create_user(username='cible-demande-3@test.fr', email='cible-demande-3@test.fr')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not DemandeMobilisation.objects.exists()

    def test_cible_institution(self, responsable_client, crisis, institution_a):
        client, _ = responsable_client
        autre_institution = _make_institution(nom='SDIS Demande Cible')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_institution=str(autre_institution.id)),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['cible_type'] == 'institution'
        assert response.data['cible_nom'] == 'SDIS Demande Cible'

    def test_cible_offre_sans_compte(self, responsable_client, crisis, institution_a):
        client, _ = responsable_client
        offer_type, _ = OfferType.objects.get_or_create(type='Test Offre Demande', defaults={'description': ''})
        offre = Offer.objects.create(
            title='Camion à prêter', first_name_offer='Jean', last_name_offer='Sanscompte',
            email_offer='sanscompte@test.fr', status='DISPONIBLE', offer_type=offer_type,
        )

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_offre=str(offre.id)),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['cible_type'] == 'offre'
        assert response.data['cible_nom'] == 'Jean Sanscompte'

    def test_refuse_zero_cible(self, responsable_client, crisis, institution_a):
        client, _ = responsable_client
        response = client.post(
            reverse('demandemobilisation-list'), _payload_de_base(crisis, institution_a), format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_refuse_plusieurs_cibles(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-demande-4@test.fr', email='cible-demande-4@test.fr')
        autre_institution = _make_institution(nom='Institution Demande Double')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(
                crisis, institution_a,
                cible_utilisateur=str(cible.id), cible_institution=str(autre_institution.id),
            ),
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_type_se_rendre_a_avec_lieu_texte(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-demande-5@test.fr', email='cible-demande-5@test.fr')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(
                crisis, institution_a, type_demande='SE_RENDRE_A', lieu_texte='Mairie, salle des fêtes',
                cible_utilisateur=str(cible.id),
            ),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['lieu_texte'] == 'Mairie, salle des fêtes'

    def test_notifie_la_cible_si_utilisateur(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-demande-6@test.fr', email='cible-demande-6@test.fr')

        response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Notification.objects.filter(utilisateur=cible, titre='Demande de mobilisation').exists()

    def test_requires_institutional_actor(self, api_client, crisis, institution_a):
        response = api_client.post(
            reverse('demandemobilisation-list'), _payload_de_base(crisis, institution_a), format='json',
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestVisibiliteDemandeMobilisation:

    def test_institution_emettrice_voit_sa_demande(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-vis-1@test.fr', email='cible-vis-1@test.fr')
        create_response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )
        demande_id = create_response.data['id']

        response = client.get(reverse('demandemobilisation-list'))
        assert any(d['id'] == demande_id for d in response.data)

    def test_cible_utilisateur_voit_la_demande(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-vis-2@test.fr', email='cible-vis-2@test.fr')
        client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )

        cible_client = APIClient()
        cible_client.force_authenticate(user=cible)
        response = cible_client.get(reverse('demandemobilisation-list'))
        assert len(response.data) == 1

    def test_institution_tierce_ne_voit_rien(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-vis-3@test.fr', email='cible-vis-3@test.fr')
        client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )

        tierce_institution = _make_institution(nom='Institution Tierce Demande')
        tierce_client, _ = _client_avec_role(create_user, tierce_institution, 'RESPONSABLE', 'tierce-demande@test.fr')
        response = tierce_client.get(reverse('demandemobilisation-list'))
        assert response.data == []

    def test_cible_institution_voit_la_demande(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        institution_cible = _make_institution(nom='Institution Cible Voit Demande')
        client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_institution=str(institution_cible.id)),
            format='json',
        )

        cible_client, _ = _client_avec_role(create_user, institution_cible, None, 'membre-cible-inst@test.fr')
        response = cible_client.get(reverse('demandemobilisation-list'))
        assert len(response.data) == 1


@pytest.mark.django_db
class TestRevocationDemandeMobilisation:

    def test_responsable_peut_revoquer(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-revoc-1@test.fr', email='cible-revoc-1@test.fr')
        create_response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )
        demande_id = create_response.data['id']

        response = client.post(reverse('demandemobilisation-revoquer', args=[demande_id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['statut'] == 'REVOQUEE'
        demande = DemandeMobilisation.objects.get(id=demande_id)
        assert demande.date_revocation is not None

    def test_revocation_idempotente(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        cible = create_user(username='cible-revoc-2@test.fr', email='cible-revoc-2@test.fr')
        create_response = client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )
        demande_id = create_response.data['id']

        client.post(reverse('demandemobilisation-revoquer', args=[demande_id]))
        demande = DemandeMobilisation.objects.get(id=demande_id)
        premiere_date_revocation = demande.date_revocation

        second_response = client.post(reverse('demandemobilisation-revoquer', args=[demande_id]))
        demande.refresh_from_db()

        assert second_response.status_code == status.HTTP_200_OK
        assert demande.date_revocation == premiere_date_revocation

    def test_membre_simple_ne_peut_pas_revoquer(self, responsable_client, simple_membre_client, crisis, institution_a, create_user):
        emetteur_client, _ = responsable_client
        cible = create_user(username='cible-revoc-3@test.fr', email='cible-revoc-3@test.fr')
        create_response = emetteur_client.post(
            reverse('demandemobilisation-list'),
            _payload_de_base(crisis, institution_a, cible_utilisateur=str(cible.id)),
            format='json',
        )
        demande_id = create_response.data['id']

        membre_client, _ = simple_membre_client
        response = membre_client.post(reverse('demandemobilisation-revoquer', args=[demande_id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        demande = DemandeMobilisation.objects.get(id=demande_id)
        assert demande.statut == 'ACTIVE'
