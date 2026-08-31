import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AuditLog,
    ContactInstitution,
    Crisis,
    ImplicationInstitution,
    Information,
    InformationType,
    Institution,
    InstitutionType,
    Offer,
    OfferType,
    Request,
    RequestType,
    Team,
)


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_DESACT_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie désactivation test", type=itype)


@pytest.fixture
def institutional_client(create_user, institution):
    user = create_user(username="autorite-desact@test.fr", email="autorite-desact@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def offer_type(db):
    return OfferType.objects.create(type="Matériel (desact test)", description="")


@pytest.fixture
def offer(db, offer_type, create_user):
    author = create_user(username="offreur-desact@test.fr", email="offreur-desact@test.fr", type="UTIL_SIMPLE")
    return Offer.objects.create(
        title="Offre désactivation", location="POINT (5.7245 45.1885)",
        first_name_offer="Jean", last_name_offer="Offreur", email_offer="jean.offreur-desact@test.fr",
        status="DISPONIBLE", offer_type=offer_type, author=author,
        deletion_token="token-offer-desact-test",
    )


@pytest.fixture
def request_type(db):
    return RequestType.objects.create(type="Besoin (desact test)", description="")


@pytest.fixture
def demande(db, request_type, create_user):
    author = create_user(username="demandeur-desact@test.fr", email="demandeur-desact@test.fr", type="UTIL_SIMPLE")
    return Request.objects.create(
        title="Demande désactivation", location="POINT (5.7245 45.1885)",
        first_name_request="Marie", last_name_request="Demandeuse", email_request="marie.demandeuse-desact@test.fr",
        phone_request="0600000000", status="NON_TRAITEE", request_type=request_type, author=author,
        deletion_token="token-request-desact-test",
    )


@pytest.fixture
def information_type(db):
    return InformationType.objects.create(type="Signalement (desact test)", description="")


@pytest.fixture
def information(db, information_type, create_user):
    author = create_user(username="signaleur-desact@test.fr", email="signaleur-desact@test.fr", type="UTIL_SIMPLE")
    return Information.objects.create(
        title="Signalement désactivation", location="POINT (5.7245 45.1885)",
        first_name_information="Paul", last_name_information="Signaleur", email_information="paul.signaleur-desact@test.fr",
        phone_information="0600000000", status="DISPONIBLE", information_type=information_type, author=author,
        deletion_token="token-information-desact-test",
    )


@pytest.fixture
def team(db, institution):
    return Team.objects.create(name="Équipe désactivation test", institution=institution)


@pytest.mark.django_db
class TestOfferDesactivation:

    def test_destroy_deactivates_instead_of_deleting(self, institutional_client, offer):
        client, _ = institutional_client
        response = client.delete(reverse('offer-detail', args=[offer.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        offer.refresh_from_db()
        assert offer.actif is False
        assert AuditLog.objects.filter(objet_id=offer.id, action__code="DESACTIVATION").exists()

    def test_deactivated_offer_hidden_from_default_list(self, api_client, offer):
        offer.actif = False
        offer.save(update_fields=['actif'])

        response = api_client.get(reverse('offer-list'))

        assert response.status_code == status.HTTP_200_OK
        assert str(offer.id) not in [item['id'] for item in response.data]

    def test_actif_all_shows_deactivated_offer_for_institutional(self, institutional_client, offer):
        offer.actif = False
        offer.save(update_fields=['actif'])
        client, _ = institutional_client

        response = client.get(reverse('offer-list'), {'actif': 'all'})

        assert str(offer.id) in [item['id'] for item in response.data]

    def test_actif_all_ignored_for_non_institutional(self, api_client, offer):
        offer.actif = False
        offer.save(update_fields=['actif'])

        response = api_client.get(reverse('offer-list'), {'actif': 'all'})

        assert str(offer.id) not in [item['id'] for item in response.data]

    def test_reactiver_restores_visibility(self, institutional_client, offer):
        client, _ = institutional_client
        offer.actif = False
        offer.save(update_fields=['actif'])

        response = client.post(reverse('offer-reactiver', args=[offer.id]))

        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.actif is True
        assert AuditLog.objects.filter(objet_id=offer.id, action__code="REACTIVATION").exists()

    def test_actif_field_not_writable_via_patch(self, institutional_client, offer):
        client, _ = institutional_client
        response = client.patch(reverse('offer-detail', args=[offer.id]), {'actif': False}, format='json')

        assert response.status_code == status.HTTP_200_OK
        offer.refresh_from_db()
        assert offer.actif is True

    def test_delete_offer_view_token_deactivates_without_deleting(self, api_client, offer):
        response = api_client.get(reverse('delete_offer', args=[offer.deletion_token]))

        assert response.status_code == status.HTTP_200_OK
        assert Offer.objects.filter(id=offer.id).exists()
        offer.refresh_from_db()
        assert offer.actif is False


@pytest.mark.django_db
class TestRequestDesactivation:

    def test_destroy_deactivates_instead_of_deleting(self, institutional_client, demande):
        client, _ = institutional_client
        response = client.delete(reverse('request-detail', args=[demande.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        demande.refresh_from_db()
        assert demande.actif is False
        assert AuditLog.objects.filter(objet_id=demande.id, action__code="DESACTIVATION").exists()

    def test_reactiver_restores_visibility(self, institutional_client, demande):
        client, _ = institutional_client
        demande.actif = False
        demande.save(update_fields=['actif'])

        response = client.post(reverse('request-reactiver', args=[demande.id]))

        assert response.status_code == status.HTTP_200_OK
        demande.refresh_from_db()
        assert demande.actif is True

    def test_delete_request_view_token_deactivates_without_deleting(self, api_client, demande):
        response = api_client.get(reverse('delete_request', args=[demande.deletion_token]))

        assert response.status_code == status.HTTP_200_OK
        assert Request.objects.filter(id=demande.id).exists()
        demande.refresh_from_db()
        assert demande.actif is False


@pytest.mark.django_db
class TestInformationDesactivation:

    def test_destroy_deactivates_instead_of_deleting(self, institutional_client, information):
        client, _ = institutional_client
        response = client.delete(reverse('information-detail', args=[information.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        information.refresh_from_db()
        assert information.actif is False
        assert AuditLog.objects.filter(objet_id=information.id, action__code="DESACTIVATION").exists()

    def test_reactiver_restores_visibility(self, institutional_client, information):
        client, _ = institutional_client
        information.actif = False
        information.save(update_fields=['actif'])

        response = client.post(reverse('information-reactiver', args=[information.id]))

        assert response.status_code == status.HTTP_200_OK
        information.refresh_from_db()
        assert information.actif is True

    def test_delete_information_view_token_deactivates_without_deleting(self, api_client, information):
        response = api_client.get(reverse('delete_information', args=[information.deletion_token]))

        assert response.status_code == status.HTTP_200_OK
        assert Information.objects.filter(id=information.id).exists()
        information.refresh_from_db()
        assert information.actif is False


@pytest.mark.django_db
class TestTeamDesactivation:

    def test_destroy_deactivates_instead_of_deleting(self, institutional_client, team):
        client, _ = institutional_client
        response = client.delete(reverse('team-detail', args=[team.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        team.refresh_from_db()
        assert team.actif is False
        assert AuditLog.objects.filter(objet_id=team.id, action__code="DESACTIVATION").exists()

    def test_deactivated_team_hidden_from_default_list(self, institutional_client, team):
        client, _ = institutional_client
        team.actif = False
        team.save(update_fields=['actif'])

        response = client.get(reverse('team-list'))

        assert str(team.id) not in [item['id'] for item in response.data]

    def test_actif_all_shows_deactivated_team(self, institutional_client, team):
        client, _ = institutional_client
        team.actif = False
        team.save(update_fields=['actif'])

        response = client.get(reverse('team-list'), {'actif': 'all'})

        assert str(team.id) in [item['id'] for item in response.data]

    def test_reactiver_restores_visibility(self, institutional_client, team):
        client, _ = institutional_client
        team.actif = False
        team.save(update_fields=['actif'])

        response = client.post(reverse('team-reactiver', args=[team.id]))

        assert response.status_code == status.HTTP_200_OK
        team.refresh_from_db()
        assert team.actif is True
        assert AuditLog.objects.filter(objet_id=team.id, action__code="REACTIVATION").exists()


@pytest.mark.django_db
class TestUserDesactivation:

    def test_destroy_sets_is_active_false_instead_of_deleting(self, institutional_client, create_user):
        client, _ = institutional_client
        target = create_user(username="cible-desact@test.fr", email="cible-desact@test.fr", type="UTIL_SIMPLE")

        response = client.delete(reverse('user-detail', args=[target.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        target.refresh_from_db()
        assert target.is_active is False
        assert AuditLog.objects.filter(objet_id=target.id, action__code="DESACTIVATION").exists()

    def test_reactiver_restores_is_active(self, institutional_client, create_user):
        client, _ = institutional_client
        target = create_user(username="cible-react@test.fr", email="cible-react@test.fr", type="UTIL_SIMPLE")
        target.is_active = False
        target.save(update_fields=['is_active'])

        response = client.post(reverse('user-reactiver', args=[target.id]))

        assert response.status_code == status.HTTP_200_OK
        target.refresh_from_db()
        assert target.is_active is True
        assert AuditLog.objects.filter(objet_id=target.id, action__code="REACTIVATION").exists()

    def test_deactivated_user_still_listed(self, institutional_client, create_user):
        """Comportement inchangé : is_active=False n'a jamais masqué un compte de la liste
        admin (voir UserViewSet.get_queryset, non touché par ce chantier)."""
        client, _ = institutional_client
        target = create_user(username="cible-liste@test.fr", email="cible-liste@test.fr", type="UTIL_SIMPLE")
        target.is_active = False
        target.save(update_fields=['is_active'])

        response = client.get(reverse('user-list'))

        assert str(target.id) in [item['id'] for item in response.data]


@pytest.mark.django_db
class TestCrisisClotureAutoPurge:

    def test_purges_only_deactivated_content_on_cloture(self, create_user, offer_type, request_type, information_type):
        institution2 = Institution.objects.create(
            nom="Mairie purge test", type=InstitutionType.objects.create(code="MAIRIE_PURGE_TEST", libelle="Mairie"),
        )
        crisis = Crisis.objects.create(name="Crise purge test", type="INCENDIE", location="POINT (5.72 45.18)")
        responsable = create_user(username="resp-purge@test.fr", email="resp-purge@test.fr", type="AUT_LOCALE")
        ImplicationInstitution.objects.create(
            crise=crisis, institution=institution2, type_implication="IMPLIQUE",
            responsable=responsable, actif=True,
        )

        offre_active = Offer.objects.create(
            title="Offre active", location="POINT (5.7245 45.1885)",
            first_name_offer="A", last_name_offer="Active", email_offer="active-purge@test.fr",
            status="DISPONIBLE", offer_type=offer_type, crisis=crisis, actif=True,
        )
        offre_desactivee = Offer.objects.create(
            title="Offre désactivée", location="POINT (5.7245 45.1885)",
            first_name_offer="D", last_name_offer="Desactivee", email_offer="desact-purge@test.fr",
            status="DISPONIBLE", offer_type=offer_type, crisis=crisis, actif=False,
        )
        demande_desactivee = Request.objects.create(
            title="Demande désactivée", location="POINT (5.7245 45.1885)",
            first_name_request="D", last_name_request="Desactivee", email_request="desact-purge-req@test.fr",
            phone_request="0600000000", status="NON_TRAITEE", request_type=request_type, crisis=crisis, actif=False,
        )
        info_desactivee = Information.objects.create(
            title="Signalement désactivé", location="POINT (5.7245 45.1885)",
            first_name_information="D", last_name_information="Desactivee", email_information="desact-purge-info@test.fr",
            phone_information="0600000000", status="DISPONIBLE", information_type=information_type, crisis=crisis, actif=False,
        )

        client = APIClient()
        client.force_authenticate(user=responsable)
        response = client.post(reverse('crisis-cloturer', args=[crisis.id]))

        assert response.status_code == status.HTTP_200_OK
        assert Offer.objects.filter(id=offre_active.id).exists()
        assert not Offer.objects.filter(id=offre_desactivee.id).exists()
        assert not Request.objects.filter(id=demande_desactivee.id).exists()
        assert not Information.objects.filter(id=info_desactivee.id).exists()
