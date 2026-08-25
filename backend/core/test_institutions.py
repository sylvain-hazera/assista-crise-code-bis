import pytest
from unittest.mock import patch
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status

from core.models import (
    AffectationRoleOperationnel,
    ContactInstitution,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    User,
)
from core.institution_attachment import attach_by_known_domain


def _activation_url(user):
    from core.views import MAGIC_LINK_SIGNER
    uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = MAGIC_LINK_SIGNER.sign(uidb64)
    return reverse('activate_account', args=[uidb64, token])


@pytest.mark.django_db
class TestInstitutionCRUD:

    def test_create_institution_authenticated(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")

        response = client.post(
            reverse('institution-list'),
            {"nom": "Mairie de Test", "type": str(institution_type.id), "actif": True},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Institution.objects.filter(nom="Mairie de Test").exists()
        assert response.data["type_libelle"] == "Mairie"

    def test_list_institutions_requires_authentication(self, api_client):
        response = api_client.get(reverse('institution-list'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_update_institution(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Ancien nom", type=institution_type)

        response = client.patch(
            reverse('institution-detail', args=[institution.id]),
            {"nom": "Nouveau nom"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        institution.refresh_from_db()
        assert institution.nom == "Nouveau nom"

    def test_delete_institution(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="À supprimer", type=institution_type)

        response = client.delete(reverse('institution-detail', args=[institution.id]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Institution.objects.filter(id=institution.id).exists()

    def test_anonymous_cannot_delete_institution(self, api_client):
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Protégée", type=institution_type)

        response = api_client.delete(reverse('institution-detail', args=[institution.id]))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert Institution.objects.filter(id=institution.id).exists()


@pytest.mark.django_db
class TestInstitutionAutoAttachment:
    """Le rattachement automatique à une institution ne doit JAMAIS avoir lieu avant que la
    possession de l'email n'ait été prouvée (activation) — sinon n'importe qui peut se déclarer
    "contact@loire.fr" sans jamais recevoir ni cliquer sur aucun email et se faire directement
    rattacher à la vraie institution. Exception : la création directe d'une institution par un
    utilisateur déjà authentifié (celui-là a déjà prouvé son identité via son propre login)."""

    def test_creator_becomes_principal_contact(self, authenticated_client):
        client, user = authenticated_client
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")

        response = client.post(
            reverse('institution-list'),
            {"nom": "SDIS 33", "type": str(institution_type.id), "actif": True},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        institution = Institution.objects.get(id=response.data["id"])

        contact = ContactInstitution.objects.get(institution=institution, utilisateur=user)
        assert contact.contact_principal is True

    def test_registration_does_not_attach_before_activation(self, api_client, user_data):
        """Même avec un domaine email déjà connu du système, la simple inscription ne doit
        rattacher personne ni délivrer de session : c'est exactement la faille corrigée."""
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=True)

        payload = {
            **user_data,
            "email": "agent@sdis33.fr",
            "username": "agent@sdis33.fr",
            "type": "AUT_LOCALE",
            "institution_name": "SDIS 33",
            "institution_type": "sdis",
        }
        response = api_client.post(reverse('user-register'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert 'token' not in response.data
        assert response.data.get('requires_email_confirmation') is True

        user_id = response.data["user"]["id"]
        created_user = User.objects.get(id=user_id)
        assert created_user.enabled is False
        assert not ContactInstitution.objects.filter(utilisateur_id=user_id).exists()
        assert not AffectationRoleOperationnel.objects.filter(utilisateur_id=user_id).exists()

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
    def test_unactivated_account_cannot_log_in(self, mock_search, api_client, user_data):
        """is_active doit être false tant que l'email n'est pas confirmé : c'est le seul champ
        réellement vérifié par /api/token/ (l'endpoint que le frontend utilise réellement) —
        enabled=False seul ne bloque pas la connexion."""
        mock_search.return_value = None  # pas de correspondance annuaire, repli sur le regex

        payload = {
            **user_data,
            "email": "agent@mairie-test-securite.fr",
            "username": "agent@mairie-test-securite.fr",
            "password": "TestPass123!",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie Test Securite",
            "institution_type": "mairie",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        assert register_response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(id=register_response.data["user"]["id"])
        assert user.is_active is False

        login_response = api_client.post(
            reverse('token_obtain_pair'),
            {"email": "agent@mairie-test-securite.fr", "password": "TestPass123!"},
            format='json',
        )
        assert login_response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_activation_attaches_to_cached_domain_and_returns_token(self, api_client, user_data):
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=True)

        payload = {
            **user_data,
            "email": "agent@sdis33.fr",
            "username": "agent@sdis33.fr",
            "type": "AUT_LOCALE",
            "institution_name": "SDIS 33",
            "institution_type": "sdis",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])

        activation_response = api_client.get(_activation_url(user))

        assert activation_response.status_code == status.HTTP_200_OK
        assert 'token' in activation_response.data
        user.refresh_from_db()
        assert user.enabled is True
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        affectation = AffectationRoleOperationnel.objects.get(institution=institution, utilisateur=user)
        assert affectation.role.code == 'RESPONSABLE'
        assert affectation.competence is None, (
            "aucune compétence arbitraire ne doit être posée automatiquement : "
            "le responsable la précise ensuite via l'écran dédié"
        )

    def test_activation_is_idempotent(self, api_client, user_data):
        """Cliquer deux fois sur le lien d'activation ne doit pas créer de doublons."""
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=True)

        payload = {
            **user_data,
            "email": "agent@sdis33.fr",
            "username": "agent@sdis33.fr",
            "type": "AUT_LOCALE",
            "institution_name": "SDIS 33",
            "institution_type": "sdis",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])
        url = _activation_url(user)

        api_client.get(url)
        api_client.get(url)

        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).count() == 1
        assert AffectationRoleOperationnel.objects.filter(institution=institution, utilisateur=user).count() == 1

    def test_invalid_cached_domain_is_not_matched(self):
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        Institution.objects.create(nom="SDIS 33", type=institution_type, email="")
        InstitutionDomaine.objects.create(
            institution=Institution.objects.get(nom="SDIS 33"), domaine="sdis33.fr", valide=False
        )

        user = User.objects.create_user(
            username="a@sdis33.fr", email="a@sdis33.fr", password="x", type="AUT_LOCALE"
        )
        assert attach_by_known_domain(user) is None


ANNUAIRE_SDIS_RECORD = {
    "fields": {
        "nom": "SDIS 33",
        "adresse_courriel": "contact@sdis33.fr",
        "pivot": {"type_service_local": "sdis"},
    }
}


@pytest.mark.django_db
class TestAnnuaireRegistration:
    """L'annuaire officiel de l'administration doit pouvoir valider ET rattacher un utilisateur
    à une institution dont le domaine ne serait pas reconnu par la validation regex existante —
    mais le rattachement effectif n'a lieu qu'après activation, jamais à l'inscription."""

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
    def test_activation_via_annuaire_creates_institution_domaine_and_contact(self, mock_search, api_client, user_data):
        mock_search.return_value = [ANNUAIRE_SDIS_RECORD]

        payload = {
            **user_data,
            "email": "agent@sdis33.fr",
            "username": "agent@sdis33.fr",
            "type": "AUT_LOCALE",
            "institution_name": "SDIS 33",
            "institution_type": "sdis",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        assert register_response.status_code == status.HTTP_201_CREATED
        assert 'token' not in register_response.data

        user = User.objects.get(id=register_response.data["user"]["id"])
        activation_response = api_client.get(_activation_url(user))

        assert activation_response.status_code == status.HTTP_200_OK
        assert 'token' in activation_response.data

        institution = Institution.objects.get(nom="SDIS 33")
        assert InstitutionDomaine.objects.filter(institution=institution, domaine="sdis33.fr", valide=True).exists()
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        assert AffectationRoleOperationnel.objects.filter(institution=institution, utilisateur=user).exists()

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
    def test_activation_on_cached_domain_skips_annuaire_call(self, mock_search, api_client, user_data):
        """Un domaine déjà mis en cache (par une précédente confirmation annuaire) doit être
        reconnu directement à l'activation, sans re-solliciter l'API gouvernementale."""
        institution_type = InstitutionType.objects.create(code="sdis", libelle="Sdis")
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=True)

        mock_search.return_value = None

        payload = {
            **user_data,
            "email": "autre-agent@sdis33.fr",
            "username": "autre-agent@sdis33.fr",
            "type": "AUT_LOCALE",
            "institution_name": "SDIS 33",
            "institution_type": "sdis",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])

        api_client.get(_activation_url(user))

        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        mock_search.assert_not_called()
