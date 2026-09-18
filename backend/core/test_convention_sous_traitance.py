import pytest
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
    RoleOperationnel,
    User,
)
from core.convention_sous_traitance import CONVENTION_VERSION, institution_necessite_convention


def _activation_url(user):
    from core.views import MAGIC_LINK_SIGNER
    uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = MAGIC_LINK_SIGNER.sign(uidb64)
    return reverse('activate_account', args=[uidb64, token])


def _activate_and_authenticate(api_client, user):
    activation_response = api_client.get(_activation_url(user))
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {activation_response.data['token']}")
    return activation_response


@pytest.mark.django_db
class TestInstitutionNecessiteConvention:

    def test_none_institution_does_not_require_convention(self):
        assert institution_necessite_convention(None) is False

    @pytest.mark.parametrize("code", ["mairie", "MAIRIE", "epci", "EPCI", "sdis", "SDIS"])
    def test_collectivite_types_require_convention_regardless_of_case(self, code):
        institution_type = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})[0]
        institution = Institution.objects.create(nom=f"Institution {code}", type=institution_type)
        assert institution_necessite_convention(institution) is True

    def test_non_collectivite_type_does_not_require_convention(self):
        institution_type = InstitutionType.objects.get_or_create(code="ASSOCIATION", defaults={"libelle": "Association"})[0]
        institution = Institution.objects.create(nom="Une association", type=institution_type)
        assert institution_necessite_convention(institution) is False

    def test_already_accepted_does_not_require_convention_again(self):
        from django.utils import timezone

        institution_type = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})[0]
        institution = Institution.objects.create(nom="Mairie déjà signée", type=institution_type)
        institution.convention_sous_traitance_acceptee_le = timezone.now()
        institution.save(update_fields=["convention_sous_traitance_acceptee_le"])
        assert institution_necessite_convention(institution) is False


@pytest.mark.django_db
class TestInstitutionSuggestionExposesConventionRequise:

    def test_convention_requise_true_for_matched_collectivite_not_yet_accepted(self, api_client, user_data):
        institution_type = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
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
        _activate_and_authenticate(api_client, user)

        suggestion_response = api_client.get(reverse('user-institution-suggestion'))
        assert suggestion_response.status_code == status.HTTP_200_OK
        assert suggestion_response.data["convention_requise"] is True

    def test_convention_requise_false_once_already_accepted_for_that_institution(self, api_client, user_data):
        from django.utils import timezone

        institution_type = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        institution.convention_sous_traitance_acceptee_le = timezone.now()
        institution.save(update_fields=["convention_sous_traitance_acceptee_le"])
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis33.fr", valide=True)

        payload = {
            **user_data,
            "email": "agent2@sdis33.fr",
            "username": "agent2@sdis33.fr",
            "type": "AUT_LOCALE",
            "institution_name": "SDIS 33",
            "institution_type": "sdis",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])
        _activate_and_authenticate(api_client, user)

        suggestion_response = api_client.get(reverse('user-institution-suggestion'))
        assert suggestion_response.data["convention_requise"] is False


@pytest.mark.django_db
class TestConfirmerInstitutionConventionGate:

    def _register_and_authenticate_sdis_agent(self, api_client, user_data, institution, email="agent@sdis33.fr"):
        InstitutionDomaine.objects.get_or_create(institution=institution, domaine="sdis33.fr", defaults={"valide": True})
        payload = {
            **user_data,
            "email": email,
            "username": email,
            "type": "AUT_LOCALE",
            "institution_name": institution.nom,
            "institution_type": "sdis",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])
        _activate_and_authenticate(api_client, user)
        return user

    def test_confirmer_refuses_without_convention_acceptee(self, api_client, user_data):
        RoleOperationnel.objects.get_or_create(code='REGULATEUR', defaults={'libelle': 'Régulateur'})
        institution_type = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        user = self._register_and_authenticate_sdis_agent(api_client, user_data, institution)

        response = api_client.post(
            reverse('user-confirmer-institution'), {"role_code": "REGULATEUR"}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "convention_acceptee" in response.data
        assert not ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        institution.refresh_from_db()
        assert institution.convention_sous_traitance_acceptee_le is None

    def test_confirmer_accepts_records_and_emails_when_convention_acceptee(self, api_client, user_data):
        from django.core import mail

        RoleOperationnel.objects.get_or_create(code='REGULATEUR', defaults={'libelle': 'Régulateur'})
        institution_type = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        user = self._register_and_authenticate_sdis_agent(api_client, user_data, institution)

        mail.outbox.clear()
        response = api_client.post(
            reverse('user-confirmer-institution'),
            {"role_code": "REGULATEUR", "convention_acceptee": True},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()
        institution.refresh_from_db()
        assert institution.convention_sous_traitance_acceptee_le is not None
        assert institution.convention_sous_traitance_acceptee_par_id == user.id
        assert institution.convention_sous_traitance_version == CONVENTION_VERSION
        assert any("Convention de sous-traitance" in m.subject for m in mail.outbox)
        convention_mail = next(m for m in mail.outbox if "Convention de sous-traitance" in m.subject)
        assert user.email in convention_mail.to

    def test_second_member_of_same_institution_not_required_to_accept_again(self, api_client, user_data):
        from django.utils import timezone

        RoleOperationnel.objects.get_or_create(code='REGULATEUR', defaults={'libelle': 'Régulateur'})
        institution_type = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})[0]
        institution = Institution.objects.create(nom="SDIS 33", type=institution_type)
        institution.convention_sous_traitance_acceptee_le = timezone.now()
        institution.save(update_fields=["convention_sous_traitance_acceptee_le"])

        second_client = api_client.__class__()
        user = self._register_and_authenticate_sdis_agent(
            second_client, user_data, institution, email="agent2@sdis33.fr",
        )

        response = second_client.post(
            reverse('user-confirmer-institution'), {"role_code": "REGULATEUR"}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=user).exists()


@pytest.mark.django_db
class TestCreerMonInstitutionConventionGate:

    def _register_and_authenticate_mairie_creator(self, api_client, user_data, email="agent@mairie-a-creer.fr"):
        from unittest.mock import patch

        payload = {
            **user_data,
            "email": email,
            "username": email,
            "type": "AUT_LOCALE",
            "institution_name": "Mairie à créer",
            "institution_type": "mairie",
        }
        with patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None):
            register_response = api_client.post(reverse('user-register'), payload, format='json')
            user = User.objects.get(id=register_response.data["user"]["id"])
            _activate_and_authenticate(api_client, user)
        return user

    def test_creer_refuses_without_convention_acceptee_and_leaves_no_orphan_institution(self, api_client, user_data):
        RoleOperationnel.objects.get_or_create(code='RESPONSABLE', defaults={'libelle': 'Responsable'})
        institution_type = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})[0]
        user = self._register_and_authenticate_mairie_creator(api_client, user_data)

        refused_response = api_client.post(reverse('user-creer-mon-institution'), {
            "nom": "Mairie Créée Par Elle-Même",
            "type": str(institution_type.id),
            "role_code": "RESPONSABLE",
        }, format='json')

        assert refused_response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Institution.objects.filter(nom="Mairie Créée Par Elle-Même").exists(), (
            "la convention refusée doit annuler la création de l'institution (transaction.atomic) : "
            "pas d'institution orpheline avec un nom déjà consommé"
        )

        # Retenter avec le même nom, cette fois en acceptant la convention, doit réussir — la
        # tentative refusée ci-dessus ne doit pas avoir "brûlé" le nom unique.
        accepted_response = api_client.post(reverse('user-creer-mon-institution'), {
            "nom": "Mairie Créée Par Elle-Même",
            "type": str(institution_type.id),
            "role_code": "RESPONSABLE",
            "convention_acceptee": True,
        }, format='json')

        assert accepted_response.status_code == status.HTTP_201_CREATED
        institution = Institution.objects.get(nom="Mairie Créée Par Elle-Même")
        assert institution.convention_sous_traitance_acceptee_le is not None
        assert AffectationRoleOperationnel.objects.filter(institution=institution, utilisateur=user).exists()

    def test_creer_cannot_bypass_gate_by_forging_acceptee_le_in_payload(self, api_client, user_data):
        """InstitutionSerializer expose convention_sous_traitance_acceptee_le en écriture par
        défaut (fields = "__all__") : un payload de création malveillant qui le renseigne
        directement ne doit PAS suffire à contourner _traiter_acceptation_convention — ces 3
        champs doivent être read_only sur le serializer (voir InstitutionSerializer.Meta)."""
        RoleOperationnel.objects.get_or_create(code='RESPONSABLE', defaults={'libelle': 'Responsable'})
        institution_type = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})[0]
        self._register_and_authenticate_mairie_creator(api_client, user_data)

        response = api_client.post(reverse('user-creer-mon-institution'), {
            "nom": "Mairie Qui Triche",
            "type": str(institution_type.id),
            "role_code": "RESPONSABLE",
            "convention_sous_traitance_acceptee_le": "2020-01-01T00:00:00Z",
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Institution.objects.filter(nom="Mairie Qui Triche").exists()

    def test_creer_accepts_and_emails_when_convention_acceptee(self, api_client, user_data):
        from django.core import mail

        RoleOperationnel.objects.get_or_create(code='RESPONSABLE', defaults={'libelle': 'Responsable'})
        institution_type = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})[0]
        user = self._register_and_authenticate_mairie_creator(api_client, user_data)

        mail.outbox.clear()
        response = api_client.post(reverse('user-creer-mon-institution'), {
            "nom": "Mairie Créée Directement",
            "type": str(institution_type.id),
            "role_code": "RESPONSABLE",
            "convention_acceptee": True,
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        institution = Institution.objects.get(nom="Mairie Créée Directement")
        assert institution.convention_sous_traitance_acceptee_le is not None
        assert institution.convention_sous_traitance_acceptee_par_id == user.id
        assert any("Convention de sous-traitance" in m.subject for m in mail.outbox)
