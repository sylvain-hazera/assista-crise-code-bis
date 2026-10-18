"""Journal de bord de la Vue Ma Collectivité : texte libre par institution ET par crise (une
institution peut être impliquée sur plusieurs crises actives simultanément), immuable (pas de
route update/delete), journalisé dans AuditLog — voir JournalCollectiviteViewSet."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    AuditLog,
    Crisis,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    JournalCollectivite,
)


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
    return Institution.objects.create(nom="Mairie de Tests", type=itype)


@pytest.fixture
def autre_institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
    return Institution.objects.create(nom="Autre mairie", type=itype)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise journal test", location=Point(5.72, 45.18, srid=4326))


@pytest.fixture
def autre_crisis(db):
    return Crisis.objects.create(name="Autre crise journal test", location=Point(2.35, 48.86, srid=4326))


def _impliquer(institution, crisis, type_implication="IMPLIQUE", actif=True):
    return ImplicationInstitution.objects.create(
        institution=institution, crise=crisis, type_implication=type_implication, actif=actif,
    )


@pytest.mark.django_db
class TestJournalCollectiviteCreation:

    def test_create_entry_sets_auteur_institution_environment(self, create_user, institution, crisis):
        _impliquer(institution, crisis)
        user = create_user(email="secretaire@test.fr", username="secretaire@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Réunion de crise à 14h.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 201
        entry = JournalCollectivite.objects.get(id=response.data["id"])
        assert entry.institution == institution
        assert entry.crise == crisis
        assert entry.auteur == user
        assert entry.environment == "PROD"
        assert entry.contenu == "Réunion de crise à 14h."
        assert response.data["crise_nom"] == crisis.name

    def test_create_writes_audit_log(self, create_user, institution, crisis):
        _impliquer(institution, crisis)
        user = create_user(email="secretaire2@test.fr", username="secretaire2@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Point de situation.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 201
        log = AuditLog.objects.filter(action__code="JOURNAL_BORD", objet_id=response.data["id"]).first()
        assert log is not None
        assert log.utilisateur == user
        assert "Point de situation." in log.commentaire

    def test_create_without_institution_is_rejected(self, create_user, crisis):
        user = create_user(email="sans-institution@test.fr", username="sans-institution@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Test.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 403

    def test_non_institutional_actor_cannot_create(self, create_user, institution, crisis):
        user = create_user(email="simple@test.fr", username="simple@test.fr", type="UTIL_SIMPLE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Test.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 403

    def test_client_cannot_set_institution_or_auteur(self, create_user, institution, autre_institution, crisis):
        _impliquer(institution, crisis)
        user = create_user(email="secretaire3@test.fr", username="secretaire3@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Test.", "crise": str(crisis.id), "institution": str(autre_institution.id)},
            format="json",
        )

        assert response.status_code == 201
        entry = JournalCollectivite.objects.get(id=response.data["id"])
        assert entry.institution == institution

    def test_create_requires_crise_field(self, create_user, institution):
        user = create_user(email="sans-crise@test.fr", username="sans-crise@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(reverse("journal-collectivite-list"), {"contenu": "Test."}, format="json")

        assert response.status_code == 400
        assert "crise" in response.data

    def test_create_rejects_crise_without_active_implication(self, create_user, institution, crisis):
        # Aucune ImplicationInstitution créée : l'institution n'est pas impliquée sur cette
        # crise — même pattern que DelegationCompetenceSerializer.validate.
        user = create_user(email="sans-implication@test.fr", username="sans-implication@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Test.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 400
        assert "crise" in response.data
        assert not JournalCollectivite.objects.filter(contenu="Test.").exists()

    def test_create_rejects_inactive_implication(self, create_user, institution, crisis):
        _impliquer(institution, crisis, actif=False)
        user = create_user(email="implication-inactive@test.fr", username="implication-inactive@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Test.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 400

    def test_create_accepts_acteur_implication(self, create_user, institution, crisis):
        _impliquer(institution, crisis, type_implication="ACTEUR")
        user = create_user(email="acteur-crise@test.fr", username="acteur-crise@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse("journal-collectivite-list"),
            {"contenu": "Test acteur.", "crise": str(crisis.id)},
            format="json",
        )

        assert response.status_code == 201


@pytest.mark.django_db
class TestJournalCollectiviteImmutability:

    def test_no_update_route(self, create_user, institution, crisis):
        user = create_user(email="secretaire4@test.fr", username="secretaire4@test.fr", type="AUT_LOCALE", institution=institution)
        entry = JournalCollectivite.objects.create(institution=institution, crise=crisis, auteur=user, contenu="Original.")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            reverse("journal-collectivite-detail", args=[entry.id]), {"contenu": "Modifié."}, format="json",
        )

        assert response.status_code == 405
        entry.refresh_from_db()
        assert entry.contenu == "Original."

    def test_no_delete_route(self, create_user, institution, crisis):
        user = create_user(email="secretaire5@test.fr", username="secretaire5@test.fr", type="AUT_LOCALE", institution=institution)
        entry = JournalCollectivite.objects.create(institution=institution, crise=crisis, auteur=user, contenu="Original.")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.delete(reverse("journal-collectivite-detail", args=[entry.id]))

        assert response.status_code == 405
        assert JournalCollectivite.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
class TestJournalCollectiviteScoping:

    def test_list_scoped_to_own_institution(self, create_user, institution, autre_institution, crisis):
        user = create_user(email="secretaire6@test.fr", username="secretaire6@test.fr", type="AUT_LOCALE", institution=institution)
        other_user = create_user(email="autre@test.fr", username="autre@test.fr", type="AUT_LOCALE", institution=autre_institution)
        JournalCollectivite.objects.create(institution=institution, crise=crisis, auteur=user, contenu="Chez moi.")
        JournalCollectivite.objects.create(institution=autre_institution, crise=crisis, auteur=other_user, contenu="Chez l'autre.")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("journal-collectivite-list"))

        assert response.status_code == 200
        contenus = [entry["contenu"] for entry in response.data]
        assert contenus == ["Chez moi."]

    def test_ordering_most_recent_first(self, create_user, institution, crisis):
        user = create_user(email="secretaire7@test.fr", username="secretaire7@test.fr", type="AUT_LOCALE", institution=institution)
        first = JournalCollectivite.objects.create(institution=institution, crise=crisis, auteur=user, contenu="Premier.")
        second = JournalCollectivite.objects.create(institution=institution, crise=crisis, auteur=user, contenu="Second.")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("journal-collectivite-list"))

        assert [entry["id"] for entry in response.data] == [str(second.id), str(first.id)]

    def test_filter_by_crise(self, create_user, institution, crisis, autre_crisis):
        user = create_user(email="secretaire8@test.fr", username="secretaire8@test.fr", type="AUT_LOCALE", institution=institution)
        entry_crisis = JournalCollectivite.objects.create(institution=institution, crise=crisis, auteur=user, contenu="Sur la crise 1.")
        JournalCollectivite.objects.create(institution=institution, crise=autre_crisis, auteur=user, contenu="Sur la crise 2.")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(reverse("journal-collectivite-list"), {"crise": str(crisis.id)})

        assert response.status_code == 200
        assert [entry["id"] for entry in response.data] == [str(entry_crisis.id)]


@pytest.mark.django_db
class TestImplicationInstitutionActifFilter:
    """?actif= (ImplicationInstitutionViewSet.filterset_fields) — alimente le sélecteur de
    crise du journal de bord (VueMairieComponent), qui ne doit proposer que les implications
    actives de l'institution appelante."""

    def test_filters_by_actif(self, create_user, institution, crisis, autre_crisis):
        active = _impliquer(institution, crisis, actif=True)
        _impliquer(institution, autre_crisis, actif=False)
        user = create_user(email="filtre-actif@test.fr", username="filtre-actif@test.fr", type="AUT_LOCALE", institution=institution)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("implicationinstitution-list"), {"institution": str(institution.id), "actif": "true"})

        assert response.status_code == 200
        assert [i["id"] for i in response.data] == [str(active.id)]
