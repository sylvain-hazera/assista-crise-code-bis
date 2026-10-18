"""grant_institution_and_demo_access (institution_attachment.py) : à chaque rattachement réel
d'un compte à une institution, pose User.institution (jamais posé jusqu'ici par le flux normal
d'inscription — constaté en direct sur la prod réelle) et accorde automatiquement le même rôle
en zone DEMO, sans clobber un choix déjà fait (institution existante, ou accès démo déjà réglé
manuellement par un administrateur)."""
import pytest

from core.institution_attachment import (
    attach_secours_user_to_institution,
    attach_user_with_role,
    grant_institution_and_demo_access,
    resolve_or_invite_responsable,
)
from core.models import Institution, InstitutionType, RoleOperationnel, User


def _make_institution(nom="Institution test", type_code="MAIRIE"):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=nom, type=itype)


def _make_user(email, **kwargs):
    defaults = {"type": "AUT_LOCALE", "enabled": True}
    defaults.update(kwargs)
    return User.objects.create_user(username=email, email=email, password="Test1234!", **defaults)


@pytest.mark.django_db
class TestGrantInstitutionAndDemoAccess:

    def test_sets_institution_and_demo_role_when_both_empty(self):
        user = _make_user("nouveau@test.fr", type="AUT_LOCALE")
        institution = _make_institution()

        grant_institution_and_demo_access(user, institution)
        user.refresh_from_db()

        assert user.institution_id == institution.id
        assert user.demo_role == "AUT_LOCALE"

    def test_does_not_overwrite_existing_institution(self):
        deja_rattachee = _make_institution("Déjà rattachée")
        user = _make_user("multi@test.fr", institution=deja_rattachee)
        autre_institution = _make_institution("Autre")

        grant_institution_and_demo_access(user, autre_institution)
        user.refresh_from_db()

        assert user.institution_id == deja_rattachee.id

    def test_does_not_overwrite_existing_demo_role(self):
        user = _make_user("demo-deja-regle@test.fr", type="AUT_LOCALE", demo_role="ADMIN")
        institution = _make_institution()

        grant_institution_and_demo_access(user, institution)
        user.refresh_from_db()

        assert user.demo_role == "ADMIN"


@pytest.mark.django_db
class TestAttachUserWithRoleGrantsDemoAccess:

    def test_confirming_institution_grants_institution_and_demo_role(self):
        RoleOperationnel.objects.get_or_create(code="RESPONSABLE", defaults={"libelle": "Responsable"})
        user = _make_user("confirme@test.fr", type="AUT_LOCALE")
        institution = _make_institution()

        attach_user_with_role(user, institution, "RESPONSABLE")
        user.refresh_from_db()

        assert user.institution_id == institution.id
        assert user.demo_role == "AUT_LOCALE"


@pytest.mark.django_db
class TestSecoursAttachmentGrantsDemoAccess:

    def test_aasc_attachment_grants_institution_and_demo_role(self):
        user = _make_user(
            "aasc@test.fr", type="SECOURS", enabled=False,
            pending_institution_type="aasc", pending_institution_name="AASC Test",
        )

        institution = attach_secours_user_to_institution(user)
        user.refresh_from_db()

        assert institution is not None
        assert user.institution_id == institution.id
        assert user.demo_role == "SECOURS"

    def test_rcsc_attachment_grants_institution_and_demo_role(self):
        mairie = _make_institution("Mairie RCSC", type_code="MAIRIE")
        mairie.commune_code = "38185"
        mairie.save(update_fields=["commune_code"])
        user = _make_user(
            "rcsc@test.fr", type="SECOURS", enabled=False,
            pending_institution_type="rcsc", pending_commune_code="38185",
        )

        institution = attach_secours_user_to_institution(user)
        user.refresh_from_db()

        assert institution == mairie
        assert user.institution_id == mairie.id
        assert user.demo_role == "SECOURS"


@pytest.mark.django_db
class TestResolveOrInviteResponsableGrantsDemoAccess:

    def test_existing_user_by_id_gets_institution_and_demo_role(self):
        institution = _make_institution("Institution crise")
        user = _make_user("existant@test.fr", type="UTIL_SIMPLE")

        resolved, invited = resolve_or_invite_responsable(str(user.id), None, institution)
        user.refresh_from_db()

        assert invited is False
        assert resolved.id == user.id
        assert user.institution_id == institution.id
        assert user.demo_role == "REGULATEUR"

    def test_new_invited_user_gets_institution_and_demo_role(self):
        institution = _make_institution("Institution invitation")

        resolved, invited = resolve_or_invite_responsable(None, "invite@test.fr", institution)

        assert invited is True
        assert resolved.institution_id == institution.id
        assert resolved.demo_role == "REGULATEUR"
