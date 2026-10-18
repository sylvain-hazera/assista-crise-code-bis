"""InstitutionViewSet.update/partial_update n'avait aucune restriction de permission :
n'importe quel compte authentifié pouvait modifier l'institution de n'importe qui d'autre.
Verrouille le correctif (seul un membre de l'institution, ou un administrateur, peut la
modifier) et la règle spécifique à secteur_override (PROD : super-admin Django uniquement ;
DEMO : tout membre actif de cette institution — champ de simulation, jamais posable par un
compte extérieur)."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_PERM_TEST", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie permissions test", type=itype, commune_code="38185")


def _add_member(institution, user, environment="PROD"):
    return ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True, environment=environment)


@pytest.mark.django_db
class TestInstitutionEditPermission:

    def test_non_member_cannot_edit(self, create_user, institution):
        outsider = create_user(username="outsider@test.fr", email="outsider@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.patch(reverse("institution-detail", args=[institution.id]), {"adresse": "1 rue Test"}, format="json")
        assert response.status_code == 403

    def test_member_can_edit(self, create_user, institution):
        member = create_user(username="membre@test.fr", email="membre@test.fr", type="AUT_LOCALE")
        _add_member(institution, member)
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.patch(reverse("institution-detail", args=[institution.id]), {"adresse": "1 rue Test"}, format="json")
        assert response.status_code == 200
        institution.refresh_from_db()
        assert institution.adresse == "1 rue Test"

    def test_administrator_can_edit_any_institution(self, create_user, institution):
        admin = create_user(username="admin-inst@test.fr", email="admin-inst@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(reverse("institution-detail", args=[institution.id]), {"adresse": "2 rue Admin"}, format="json")
        assert response.status_code == 200


@pytest.mark.django_db
class TestSecteurOverrideEditRule:

    def test_prod_non_superuser_member_cannot_set_secteur_override(self, create_user, institution):
        member = create_user(username="membre-prod@test.fr", email="membre-prod@test.fr", type="AUT_LOCALE")
        _add_member(institution, member, environment="PROD")
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.patch(
            reverse("institution-detail", args=[institution.id]), {"secteur_override": "national"}, format="json",
        )
        assert response.status_code == 200  # la requête réussit, le champ est juste ignoré
        institution.refresh_from_db()
        assert institution.secteur_override is None

    def test_prod_superuser_can_set_secteur_override(self, create_user, institution):
        member = create_user(username="superadmin-prod@test.fr", email="superadmin-prod@test.fr", type="ADMIN")
        member.is_superuser = True
        member.save(update_fields=["is_superuser"])
        _add_member(institution, member, environment="PROD")
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.patch(
            reverse("institution-detail", args=[institution.id]), {"secteur_override": "national"}, format="json",
        )
        assert response.status_code == 200
        institution.refresh_from_db()
        assert institution.secteur_override == "national"

    def test_demo_member_can_set_secteur_override(self, create_user, institution):
        member = create_user(username="membre-demo@test.fr", email="membre-demo@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        _add_member(institution, member, environment="DEMO")
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.patch(
            reverse("institution-detail", args=[institution.id]), {"secteur_override": "region"},
            format="json", HTTP_X_ENVIRONMENT="DEMO",
        )
        assert response.status_code == 200
        institution.refresh_from_db()
        assert institution.secteur_override == "region"

    def test_demo_member_without_demo_contact_cannot_edit_at_all(self, create_user, institution):
        # Membre côté PROD uniquement (pas de ContactInstitution DEMO) : IsInstitutionMember-
        # OrAdministrator lui-même bloque la requête en contexte DEMO — pas seulement
        # secteur_override, aucune édition n'est autorisée hors du contexte où il est membre.
        member = create_user(username="membre-prod-only@test.fr", email="membre-prod-only@test.fr", type="AUT_LOCALE", demo_role="AUT_LOCALE")
        _add_member(institution, member, environment="PROD")
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.patch(
            reverse("institution-detail", args=[institution.id]), {"secteur_override": "region"},
            format="json", HTTP_X_ENVIRONMENT="DEMO",
        )
        assert response.status_code == 403
        institution.refresh_from_db()
        assert institution.secteur_override is None
