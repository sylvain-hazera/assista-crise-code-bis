from django.core import mail
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel,
    AuditLog,
    Competence,
    Crisis,
    Dossier,
    DossierParticipant,
    Institution,
    InstitutionType,
    Notification,
    RoleOperationnel,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise important", type="INCENDIE", location=Point(5.72, 45.18, srid=4326))


@pytest.fixture
def competence(db):
    return Competence.objects.create(nom="Déblaiement important test")


def _make_dossier(crisis, equipe, **kwargs):
    defaults = dict(
        numero=f"DOS-IMP-{Dossier.objects.count()}",
        crise=crisis, equipe=equipe, titre="Maison à déblayer", description="",
    )
    defaults.update(kwargs)
    return Dossier.objects.create(**defaults)


def _make_regulateur(create_user, competence, suffix):
    role, _ = RoleOperationnel.objects.get_or_create(code="REGULATEUR", defaults={"libelle": "Régulateur"})
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_IMPORTANT_TEST", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom=f"Mairie important test {suffix}", type=itype)
    regulateur = create_user(username=f"regul-important-{suffix}@test.fr", email=f"regul-important-{suffix}@test.fr", type="UTIL_SIMPLE")
    AffectationRoleOperationnel.objects.create(
        utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
    )
    return regulateur


@pytest.mark.django_db
class TestMarquerImportant:

    def test_plain_participant_can_mark_important(self, create_user, crisis):
        chef = create_user(username="chef-imp1@test.fr", email="chef-imp1@test.fr", type="UTIL_SIMPLE")
        membre = create_user(username="membre-imp1@test.fr", email="membre-imp1@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe important 1", leader=chef)
        team.members.add(membre)
        dossier = _make_dossier(crisis, team)
        DossierParticipant.objects.create(dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE)

        client = APIClient()
        client.force_authenticate(user=membre)
        response = client.post(reverse("dossier-marquer-important", args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.important is True
        assert dossier.date_signalement_important is not None

    def test_unrelated_user_cannot_reach_dossier(self, create_user, crisis):
        chef = create_user(username="chef-imp2@test.fr", email="chef-imp2@test.fr", type="UTIL_SIMPLE")
        unrelated = create_user(username="sans-lien-imp2@test.fr", email="sans-lien-imp2@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe important 2", leader=chef)
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=unrelated)
        response = client.post(reverse("dossier-marquer-important", args=[dossier.id]))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_marking_important_notifies_regulateurs(self, create_user, crisis, competence):
        chef = create_user(username="chef-imp3@test.fr", email="chef-imp3@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe important 3", leader=chef)
        dossier = _make_dossier(crisis, team, competence=competence)
        regulateur = _make_regulateur(create_user, competence, "imp3")

        mail.outbox.clear()
        client = APIClient()
        client.force_authenticate(user=chef)
        response = client.post(reverse("dossier-marquer-important", args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        assert Notification.objects.filter(utilisateur=regulateur, dossier=dossier).exists()
        assert any(regulateur.email in m.to for m in mail.outbox)
        assert AuditLog.objects.filter(objet_id=dossier.id, action__code="MODIFICATION").exists()

    def test_toggling_off_clears_timestamp_and_does_not_renotify(self, create_user, crisis, competence):
        chef = create_user(username="chef-imp4@test.fr", email="chef-imp4@test.fr", type="UTIL_SIMPLE")
        team = Team.objects.create(name="Equipe important 4", leader=chef)
        dossier = _make_dossier(crisis, team, competence=competence)
        regulateur = _make_regulateur(create_user, competence, "imp4")

        client = APIClient()
        client.force_authenticate(user=chef)
        client.post(reverse("dossier-marquer-important", args=[dossier.id]))

        Notification.objects.filter(utilisateur=regulateur, dossier=dossier).delete()
        mail.outbox.clear()

        response = client.post(reverse("dossier-marquer-important", args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.important is False
        assert dossier.date_signalement_important is None
        assert not Notification.objects.filter(utilisateur=regulateur, dossier=dossier).exists()
        assert len(mail.outbox) == 0

    def test_important_field_not_writable_via_patch(self, create_user, crisis):
        admin = create_user(username="admin-imp5@test.fr", email="admin-imp5@test.fr", type="ADMIN")
        team = Team.objects.create(name="Equipe important 5")
        dossier = _make_dossier(crisis, team)

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(reverse("dossier-detail", args=[dossier.id]), {"important": True}, format="json")

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.important is False
