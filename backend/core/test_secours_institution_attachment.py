from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.institution_attachment import attach_secours_user_to_institution
from core.models import (
    ContactInstitution,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    User,
)


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        username="admin-secours@test.fr", email="admin-secours@test.fr",
        password="Test1234!", type="ADMIN", enabled=True,
    )


def _make_pending_secours(pending_type, commune_code="38185", commune_name="Grenoble", institution_name="AASC Test"):
    return User.objects.create_user(
        username=f"pending-{pending_type}@test.fr", email=f"pending-{pending_type}@test.fr",
        password="Test1234!", type="SECOURS", enabled=False, postal_code="38000",
        pending_institution_type=pending_type,
        pending_institution_name=institution_name,
        pending_commune_code=commune_code,
        pending_commune_name=commune_name,
    )


@pytest.mark.django_db
class TestAascAttachment:

    def test_approve_account_creates_aasc_institution(self, api_client, admin):
        pending = _make_pending_secours("aasc", institution_name="AASC Grenoble Secours")

        api_client.force_authenticate(user=admin)
        with patch("django.core.mail.send_mail"):
            response = api_client.post(reverse("user-approve-account", kwargs={"pk": pending.id}))

        assert response.status_code == status.HTTP_200_OK
        pending.refresh_from_db()
        assert pending.enabled is True
        institution = Institution.objects.get(nom="AASC Grenoble Secours")
        assert institution.type.code == "aasc"
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=pending).exists()
        assert pending.pending_institution_type is None
        assert pending.pending_institution_name is None

    def test_aasc_attachment_direct_call_is_idempotent(self, admin):
        pending = _make_pending_secours("aasc", institution_name="AASC Idempotence Test")

        first = attach_secours_user_to_institution(pending)
        pending.refresh_from_db()
        # pending_* déjà nettoyés : un second appel ne retrouve plus le type, ne fait rien.
        second = attach_secours_user_to_institution(pending)

        assert first is not None
        assert second is None
        assert Institution.objects.filter(nom="AASC Idempotence Test").count() == 1
        assert ContactInstitution.objects.filter(institution=first, utilisateur=pending).count() == 1


@pytest.mark.django_db
class TestRcscAttachment:

    def test_approve_account_attaches_to_existing_mairie(self, api_client, admin):
        itype = InstitutionType.objects.create(code="MAIRIE_RCSC_TEST", libelle="Mairie")
        # doit matcher sur type.code == 'mairie', pas un code arbitraire
        mairie_type, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie RCSC Test", type=mairie_type, commune_code="38185", actif=True)
        pending = _make_pending_secours("rcsc", commune_code="38185")

        api_client.force_authenticate(user=admin)
        with patch("django.core.mail.send_mail") as mock_send_mail:
            response = api_client.post(reverse("user-approve-account", kwargs={"pk": pending.id}))

        assert response.status_code == status.HTTP_200_OK
        assert ContactInstitution.objects.filter(institution=mairie, utilisateur=pending, fonction="Réserviste RCSC").exists()
        # Pas de notification "rattachement manuel" puisqu'une mairie a bien été trouvée.
        manual_attach_calls = [
            c for c in mock_send_mail.call_args_list
            if c.kwargs.get('recipient_list') == ['contact@assista-crise.fr']
            and 'RCSC' in c.kwargs.get('subject', '')
        ]
        assert not manual_attach_calls

    def test_approve_account_without_matching_mairie_notifies_contact(self, api_client, admin):
        pending = _make_pending_secours("rcsc", commune_code="99999", commune_name="Commune Sans Mairie")

        api_client.force_authenticate(user=admin)
        mail.outbox.clear()
        response = api_client.post(reverse("user-approve-account", kwargs={"pk": pending.id}))

        assert response.status_code == status.HTTP_200_OK
        pending.refresh_from_db()
        assert pending.enabled is True
        assert not ContactInstitution.objects.filter(utilisateur=pending).exists()
        contact_emails = [m for m in mail.outbox if "contact@assista-crise.fr" in m.to]
        assert len(contact_emails) == 1
        assert "RCSC" in contact_emails[0].subject

    def test_rcsc_ignores_inactive_mairie(self, admin):
        mairie_type, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
        Institution.objects.create(nom="Mairie Inactive RCSC Test", type=mairie_type, commune_code="38185", actif=False)
        pending = _make_pending_secours("rcsc", commune_code="38185")

        matched = attach_secours_user_to_institution(pending)

        assert matched is None
        assert not ContactInstitution.objects.filter(utilisateur=pending).exists()


@pytest.mark.django_db
class TestRegistrationPersistsPendingFieldsForSecours:

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None)
    def test_register_persists_pending_fields_for_organized_rescue(self, mock_search, api_client, user_data):
        payload = {
            **user_data,
            "email": "aasc-register@test.fr",
            "username": "aasc-register@test.fr",
            "type": "SECOURS",
            "institution_name": "AASC Register Test",
            "institution_type": "aasc",
            "commune_name": "Grenoble",
            "commune_code": "38185",
        }
        response = api_client.post(reverse("user-register"), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(id=response.data["user"]["id"])
        assert user.pending_institution_type == "aasc"
        assert user.pending_institution_name == "AASC Register Test"
        assert user.pending_commune_code == "38185"

    def test_register_accepts_rcsc_with_personal_email(self, api_client, user_data):
        """Passe par le vrai endpoint /api/users/register/ (pas de bypass de la validation) —
        c'est ce chemin exact qui était cassé avant l'ajout de "rcsc" à
        requires_limited_access (un email personnel réaliste, jamais gouvernemental, était
        rejeté avant même d'atteindre le rattachement à la mairie)."""
        payload = {
            **user_data,
            "email": "rcsc-register@gmail.com",
            "username": "rcsc-register@gmail.com",
            "type": "SECOURS",
            "institution_name": "",
            "institution_type": "rcsc",
            "commune_name": "Grenoble",
            "commune_code": "38185",
        }
        response = api_client.post(reverse("user-register"), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(id=response.data["user"]["id"])
        assert user.pending_institution_type == "rcsc"
        assert user.pending_commune_code == "38185"


def _make_pending_sdis(email="agent@sdis40.fr"):
    return User.objects.create_user(
        username=email, email=email, password="Test1234!", type="SECOURS", enabled=False,
        postal_code="40000",
        pending_institution_type="sdis",
        pending_institution_name="SDIS des Landes",
        pending_commune_code="40192",
        pending_commune_name="Mont-de-Marsan",
    )


@pytest.mark.django_db
class TestAutreTypeSecoursAttachment:
    """Agent de SDIS ayant choisi "Secours organisés" (et non "Institution") à l'inscription --
    cas attendu pour le POC SDIS 40 du 20/10. Avant correctif : compte approuvé sans institution
    ni accès démo, et pending_* effacés."""

    def test_approve_account_attaches_sdis_via_known_domain(self, api_client, admin):
        sdis_type, _ = InstitutionType.objects.get_or_create(code="sdis", defaults={"libelle": "SDIS"})
        institution = Institution.objects.create(nom="SDIS Landes test", type=sdis_type, actif=True)
        InstitutionDomaine.objects.create(institution=institution, domaine="sdis40.fr", valide=True)
        pending = _make_pending_sdis()

        api_client.force_authenticate(user=admin)
        with patch("django.core.mail.send_mail"):
            response = api_client.post(reverse("user-approve-account", kwargs={"pk": pending.id}))

        assert response.status_code == status.HTTP_200_OK
        pending.refresh_from_db()
        assert pending.is_active is True
        assert pending.institution_id == institution.id
        assert pending.demo_role == "SECOURS"
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=pending, actif=True).exists()
        assert pending.pending_institution_name is None

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None)
    def test_sans_correspondance_conserve_les_pending(self, mock_search, admin):
        pending = _make_pending_sdis(email="agent@sdis-inconnu.fr")

        assert attach_secours_user_to_institution(pending) is None

        pending.refresh_from_db()
        assert pending.institution_id is None
        assert pending.pending_institution_name == "SDIS des Landes"
        assert pending.pending_institution_type == "sdis"


def test_validate_email_domain_accepte_sdis_sans_annuaire():
    from core.auth_validation import InstitutionEmailValidator
    for email in ("agent@sdis40.fr", "agent@sdis2a.fr", "agent@sdis971.fr", "agent@mail.sdis40.fr"):
        assert InstitutionEmailValidator.validate_email_domain(email)[0], email
    assert not InstitutionEmailValidator.validate_email_domain("agent@gmail.com")[0]


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None)
def test_validate_institution_account_sdis_sans_annuaire(mock_search):
    """Annuaire indisponible (simulé) : un email @sdis40.fr de type sdis doit rester accepté."""
    from core.auth_validation import InstitutionEmailValidator
    ok, message, _ = InstitutionEmailValidator.validate_institution_account(
        email="agent@sdis40.fr", institution_name="SDIS des Landes", institution_type="sdis",
        commune_name="Mont-de-Marsan", commune_code="40192",
    )
    assert ok, message
