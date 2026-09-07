import pytest
from unittest.mock import patch
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel,
    Commune,
    ContactInstitution,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    RoleOperationnel,
    User,
)
from core.institution_attachment import find_institution_by_known_domain


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
        # Seul un membre de l'institution (ou un administrateur) peut la modifier depuis le
        # correctif de ce soir — voir IsInstitutionMemberOrAdministrator.
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)

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
        # Seul un membre de l'institution (ou un administrateur) peut la supprimer depuis le
        # correctif de ce soir — voir IsInstitutionMemberOrAdministrator.
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)

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

    def test_activation_finds_cached_domain_without_attaching(self, api_client, user_data):
        """L'activation seule ne fait plus que RETROUVER l'institution (voir
        institution_suggestion) — le rattachement effectif attend une confirmation explicite
        (voir confirmer_institution, testé séparément)."""
        from django.core import mail

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

        mail.outbox.clear()
        activation_response = api_client.get(_activation_url(user))

        assert activation_response.status_code == status.HTTP_200_OK
        assert 'token' in activation_response.data
        user.refresh_from_db()
        assert user.enabled is True
        assert not ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        assert not AffectationRoleOperationnel.objects.filter(institution=institution, utilisateur=user).exists()
        # Rattachement automatiquement trouvable : pas de notification "sans institution".
        assert not any('contact@assista-crise.fr' in m.to for m in mail.outbox)

    def _activate_and_authenticate(self, api_client, user):
        activation_response = api_client.get(_activation_url(user))
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {activation_response.data['token']}")
        return activation_response

    def test_confirmer_institution_attaches_with_chosen_role(self, api_client, user_data):
        RoleOperationnel.objects.get_or_create(code='REGULATEUR', defaults={'libelle': 'Régulateur'})
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
        self._activate_and_authenticate(api_client, user)

        suggestion_response = api_client.get(reverse('user-institution-suggestion'))
        assert suggestion_response.status_code == status.HTTP_200_OK
        assert suggestion_response.data["institution"]["id"] == str(institution.id)

        confirm_response = api_client.post(
            reverse('user-confirmer-institution'), {"role_code": "REGULATEUR"}, format='json',
        )

        assert confirm_response.status_code == status.HTTP_200_OK
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        affectation = AffectationRoleOperationnel.objects.get(institution=institution, utilisateur=user)
        assert affectation.role.code == 'REGULATEUR'
        assert affectation.competence is None
        user.refresh_from_db()
        assert user.pending_institution_name is None

    def test_confirmer_institution_is_idempotent(self, api_client, user_data):
        """Confirmer deux fois ne doit pas créer de doublons."""
        RoleOperationnel.objects.get_or_create(code='RESPONSABLE', defaults={'libelle': 'Responsable'})
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
        self._activate_and_authenticate(api_client, user)

        # Le premier appel nettoie pending_institution_name : institution_suggestion (et donc
        # confirmer_institution) refuserait un second appel avec 400 — reproduit volontairement
        # côté serveur pour vérifier qu'aucun doublon n'est possible même en cas de double-clic
        # côté client avant que l'UI ait eu le temps de se mettre à jour.
        api_client.post(reverse('user-confirmer-institution'), {"role_code": "RESPONSABLE"}, format='json')
        second_response = api_client.post(reverse('user-confirmer-institution'), {"role_code": "RESPONSABLE"}, format='json')

        assert second_response.status_code == status.HTTP_400_BAD_REQUEST
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).count() == 1
        assert AffectationRoleOperationnel.objects.filter(institution=institution, utilisateur=user).count() == 1

    def test_creer_mon_institution_when_no_suggestion(self, api_client, user_data):
        RoleOperationnel.objects.get_or_create(code='RESPONSABLE', defaults={'libelle': 'Responsable'})
        institution_type = InstitutionType.objects.create(code="mairie", libelle="Mairie")

        payload = {
            **user_data,
            "email": "agent@mairie-a-creer.fr",
            "username": "agent@mairie-a-creer.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie à créer",
            "institution_type": "mairie",
        }
        with patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None):
            register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])
        with patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None):
            self._activate_and_authenticate(api_client, user)

            suggestion_response = api_client.get(reverse('user-institution-suggestion'))
            assert suggestion_response.data["institution"] is None

            create_response = api_client.post(reverse('user-creer-mon-institution'), {
                "nom": "Mairie Créée Par Elle-Même",
                "type": str(institution_type.id),
                "role_code": "RESPONSABLE",
            }, format='json')

        assert create_response.status_code == status.HTTP_201_CREATED
        institution = Institution.objects.get(nom="Mairie Créée Par Elle-Même")
        contact = ContactInstitution.objects.get(institution=institution, utilisateur=user)
        assert contact.fonction == 'Créateur'
        assert contact.contact_principal is True
        affectation = AffectationRoleOperationnel.objects.get(institution=institution, utilisateur=user)
        assert affectation.role.code == 'RESPONSABLE'
        user.refresh_from_db()
        assert user.pending_institution_name is None

    def test_confirmer_institution_requires_role_code(self, api_client, user_data):
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
        self._activate_and_authenticate(api_client, user)

        response = api_client.post(reverse('user-confirmer-institution'), {}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()

    def test_needs_institution_setup_true_until_confirmed(self, api_client, user_data):
        RoleOperationnel.objects.get_or_create(code='RESPONSABLE', defaults={'libelle': 'Responsable'})
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        InstitutionDomaine.objects.create(
            institution=Institution.objects.create(nom="SDIS 33", type=institution_type),
            domaine="sdis33.fr", valide=True,
        )

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

        assert register_response.data["user"]["needs_institution_setup"] is False, (
            "pas encore activé : rien à proposer avant la preuve de possession de l'email"
        )

        activation_response = self._activate_and_authenticate(api_client, user)
        assert activation_response.data["user"]["needs_institution_setup"] is True

        api_client.post(reverse('user-confirmer-institution'), {"role_code": "RESPONSABLE"}, format='json')
        me_response = api_client.get(reverse('auth_me'))
        assert me_response.data["needs_institution_setup"] is False

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
    def test_activation_without_institution_match_notifies_contact(self, mock_search, api_client, user_data):
        """Un compte mairie activé sans qu'aucune institution n'ait pu être auto-rattachée
        (ni domaine connu, ni correspondance annuaire) ne doit pas rester silencieusement sans
        institution : contact@ doit être notifié pour un rattachement manuel."""
        from django.core import mail

        mock_search.return_value = None  # pas de correspondance annuaire, repli sur le regex

        payload = {
            **user_data,
            "email": "agent@mairie-sans-match.fr",
            "username": "agent@mairie-sans-match.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie Sans Match",
            "institution_type": "mairie",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        assert register_response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(id=register_response.data["user"]["id"])

        mail.outbox.clear()
        activation_response = api_client.get(_activation_url(user))

        assert activation_response.status_code == status.HTTP_200_OK
        assert not ContactInstitution.objects.filter(utilisateur=user).exists()
        contact_emails = [m for m in mail.outbox if 'contact@assista-crise.fr' in m.to]
        assert len(contact_emails) == 1
        assert "sans institution" in contact_emails[0].subject.lower()

    def test_invalid_cached_domain_is_not_matched(self):
        institution_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        Institution.objects.create(nom="SDIS 33", type=institution_type, email="")
        InstitutionDomaine.objects.create(
            institution=Institution.objects.get(nom="SDIS 33"), domaine="sdis33.fr", valide=False
        )

        user = User.objects.create_user(
            username="a@sdis33.fr", email="a@sdis33.fr", password="x", type="AUT_LOCALE"
        )
        assert find_institution_by_known_domain(user) is None


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
    def test_activation_via_annuaire_creates_institution_domaine_without_attaching(self, mock_search, api_client, user_data):
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

        # L'institution elle-même (réelle, indépendante de qui s'y rattache) et son domaine
        # sont bien trouvés/mis en cache dès l'activation ; le rattachement de CET utilisateur,
        # lui, attend sa confirmation explicite (voir confirmer_institution, testé séparément).
        institution = Institution.objects.get(nom="SDIS 33")
        assert InstitutionDomaine.objects.filter(institution=institution, domaine="sdis33.fr", valide=True).exists()
        assert not ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        assert not AffectationRoleOperationnel.objects.filter(institution=institution, utilisateur=user).exists()

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
    def test_activation_on_cached_domain_skips_annuaire_call(self, mock_search, api_client, user_data):
        """Un domaine déjà mis en cache (par une précédente confirmation annuaire) doit être
        reconnu directement à l'activation, sans re-solliciter l'API gouvernementale."""
        institution_type, _ = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "Sdis"})
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

        activation_response = api_client.get(_activation_url(user))

        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {activation_response.data['token']}")
        suggestion_response = api_client.get(reverse('user-institution-suggestion'))
        assert suggestion_response.data["institution"]["id"] == str(institution.id)
        mock_search.assert_not_called()


@pytest.mark.django_db
class TestContactInstitutionPrincipalUniqueness:
    """« Un seul contact principal par institution » est appliqué par un index unique partiel
    en base (migration 0060 — l'index de la migration 0022 d'origine s'est retrouvé absent de
    la base de production). Ajouter un contact secondaire (contact_principal=False) doit
    toujours fonctionner librement ; seule une tentative de second contact PRINCIPAL doit être
    refusée, et proprement (400 avec message exploitable), pas via une IntegrityError brute
    remontée en 500."""

    def _institution(self):
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        return Institution.objects.create(nom="Mairie de Test", type=institution_type)

    def test_second_principal_contact_is_rejected_cleanly(self, authenticated_client):
        client, admin = authenticated_client
        institution = self._institution()
        first = User.objects.create_user(username="premier@mairie.fr", email="premier@mairie.fr", password="Test1234!")
        second = User.objects.create_user(username="second@mairie.fr", email="second@mairie.fr", password="Test1234!")
        ContactInstitution.objects.create(institution=institution, utilisateur=first, contact_principal=True)

        response = client.post(
            reverse('contactinstitution-list'),
            {"institution": str(institution.id), "utilisateur": str(second.id), "contact_principal": True, "actif": True},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'contact_principal' in response.data
        assert ContactInstitution.objects.filter(institution=institution, contact_principal=True).count() == 1

    def test_multiple_secondary_contacts_are_allowed(self, authenticated_client):
        client, admin = authenticated_client
        institution = self._institution()
        principal = User.objects.create_user(username="principal@mairie.fr", email="principal@mairie.fr", password="Test1234!")
        secondaire1 = User.objects.create_user(username="s1@gmail.com", email="s1@gmail.com", password="Test1234!")
        secondaire2 = User.objects.create_user(username="s2@gmail.com", email="s2@gmail.com", password="Test1234!")
        ContactInstitution.objects.create(institution=institution, utilisateur=principal, contact_principal=True)

        for u in (secondaire1, secondaire2):
            response = client.post(
                reverse('contactinstitution-list'),
                {"institution": str(institution.id), "utilisateur": str(u.id), "contact_principal": False, "actif": True},
                format='json',
            )
            assert response.status_code == status.HTTP_201_CREATED

        assert ContactInstitution.objects.filter(institution=institution).count() == 3


@pytest.mark.django_db
class TestUserEditDoesNotReRunInstitutionEmailCheck:
    """La vérification d'email institutionnel (UserSerializer.validate) ne doit s'appliquer
    qu'à la création du compte. Avant ce correctif, elle se redéclenchait sur CHAQUE édition
    d'un compte déjà institutionnel (AUT_LOCALE/SECOURS/ADMIN) — y compris pour un simple
    changement sans rapport, comme régler le rôle démo — et échouait systématiquement, puisque
    le formulaire d'édition ne renvoie pas les informations d'inscription (institution_name/
    type, commune) qui ne sont capturées qu'une fois, à l'inscription."""

    def test_registration_still_rejects_invalid_institutional_email(self, api_client, user_data):
        payload = {
            **user_data,
            "email": "particulier@gmail.com",
            "username": "particulier@gmail.com",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie inventée",
            "institution_type": "mairie",
        }

        response = api_client.post(reverse('user-register'), payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'email' in response.data

    def test_editing_existing_institutional_user_succeeds_without_institution_fields(self, authenticated_client):
        admin_client, admin = authenticated_client
        admin.type = 'ADMIN'
        admin.save()

        secours_user = User.objects.create_user(
            username="secours-edit-test@sdis38.fr", email="secours-edit-test@sdis38.fr",
            password="TestPass123!", type="SECOURS",
        )

        response = admin_client.patch(
            reverse('user-detail', args=[secours_user.id]),
            {
                "username": secours_user.username,
                "email": secours_user.email,
                "type": "SECOURS",
                "demo_role": "ADMIN",
            },
            format='multipart',
        )

        assert response.status_code == status.HTTP_200_OK
        secours_user.refresh_from_db()
        assert secours_user.demo_role == "ADMIN"


@pytest.mark.django_db
class TestInstitutionListZoneScoping:
    """La liste des institutions ("chez moi" + ma zone, sauf rôle ADMIN qui voit tout) est
    désormais toujours paginée (InstitutionPagination, 25/page) — voir InstitutionViewSet.
    get_queryset. AVANT ce correctif, list ne filtrait QUE par environnement PROD/DEMO :
    n'importe quel compte authentifié listait TOUTES les institutions de la plateforme."""

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

    def test_response_is_always_paginated(self, create_user, commune_a):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_LIST_ZONE", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie pagination test", type=itype, commune_code=commune_a.code)
        user = create_user(username="pagination-test@test.fr", email="pagination-test@test.fr", type="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('institution-list'))

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) == {"count", "next", "previous", "results"}

    def test_sees_own_institution_and_zone_not_others(self, create_user, commune_a, commune_b):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_LIST_ZONE2", defaults={"libelle": "Mairie"})
        ma_mairie = Institution.objects.create(nom="Ma mairie", type=itype, commune_code=commune_a.code)
        autre_meme_zone = Institution.objects.create(nom="Autre institution même commune", type=itype, commune_code=commune_a.code)
        autre_zone = Institution.objects.create(nom="Institution hors zone", type=itype, commune_code=commune_b.code)

        user = create_user(username="mairie-list-zone@test.fr", email="mairie-list-zone@test.fr", type="AUT_LOCALE")
        user.institution = ma_mairie
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('institution-list'), {"page_size": 100})

        noms = {i["nom"] for i in response.data["results"]}
        assert ma_mairie.nom in noms
        assert autre_meme_zone.nom in noms
        assert autre_zone.nom not in noms

    def test_own_institution_visible_even_without_resolvable_zone(self, create_user):
        # "Chez moi" reste visible même si mon institution n'a pas de commune_code renseignée
        # (zone non résolvable) — jamais masquée par le filtrage par zone.
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_LIST_ZONE3", defaults={"libelle": "Mairie"})
        ma_mairie = Institution.objects.create(nom="Ma mairie sans commune", type=itype)

        user = create_user(username="sans-commune-list@test.fr", email="sans-commune-list@test.fr", type="AUT_LOCALE")
        user.institution = ma_mairie
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('institution-list'))

        noms = {i["nom"] for i in response.data["results"]}
        assert ma_mairie.nom in noms

    def test_no_institution_sees_nothing(self, create_user, commune_a):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_LIST_ZONE4", defaults={"libelle": "Mairie"})
        Institution.objects.create(nom="Une institution quelconque", type=itype, commune_code=commune_a.code)

        user = create_user(username="aucune-institution-list@test.fr", email="aucune-institution-list@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('institution-list'))

        assert response.data["results"] == []

    def test_admin_sees_everything(self, create_user, commune_a, commune_b):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_LIST_ZONE5", defaults={"libelle": "Mairie"})
        Institution.objects.create(nom="Institution A admin", type=itype, commune_code=commune_a.code)
        Institution.objects.create(nom="Institution B admin", type=itype, commune_code=commune_b.code)

        user = create_user(username="admin-list-zone@test.fr", email="admin-list-zone@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('institution-list'), {"page_size": 100})

        noms = {i["nom"] for i in response.data["results"]}
        assert {"Institution A admin", "Institution B admin"}.issubset(noms)

    def test_retrieve_stays_open_across_zones(self, create_user, commune_a, commune_b):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_LIST_ZONE6", defaults={"libelle": "Mairie"})
        ma_mairie = Institution.objects.create(nom="Ma mairie retrieve", type=itype, commune_code=commune_a.code)
        autre = Institution.objects.create(nom="Autre institution retrieve", type=itype, commune_code=commune_b.code)

        user = create_user(username="retrieve-zone@test.fr", email="retrieve-zone@test.fr", type="AUT_LOCALE")
        user.institution = ma_mairie
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('institution-detail', args=[autre.id]))

        assert response.status_code == status.HTTP_200_OK
