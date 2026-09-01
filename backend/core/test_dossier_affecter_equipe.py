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
    DossierHistorique,
    DossierParticipant,
    Institution,
    InstitutionType,
    Notification,
    RoleOperationnel,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise affecter equipe", type="INCENDIE", location=Point(5.72, 45.18, srid=4326))


@pytest.fixture
def competence(db):
    return Competence.objects.create(nom="Competence affecter equipe test")


@pytest.fixture
def dossier(db, crisis, competence):
    return Dossier.objects.create(
        numero="DOS-AFFECT-1", crise=crisis, competence=competence,
        titre="Dossier non affecté", statut=Dossier.Statut.NOUVEAU,
    )


@pytest.fixture
def team(db):
    return Team.objects.create(name="Équipe cible affectation")


@pytest.fixture
def admin(create_user):
    return create_user(username="admin-affect-equipe@test.fr", email="admin-affect-equipe@test.fr", type="ADMIN")


@pytest.mark.django_db
class TestAffecterEquipe:

    def test_admin_can_assign_team_to_dossier(self, admin, dossier, team):
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-affecter-equipe', args=[dossier.id]), {"equipe": str(team.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.equipe_id == team.id
        assert dossier.statut == Dossier.Statut.AFFECTE

    def test_assigning_team_populates_participants_and_notifies_regulateur(self, admin, dossier, team, competence):
        role, _ = RoleOperationnel.objects.get_or_create(code="REGULATEUR", defaults={"libelle": "Régulateur"})
        itype = InstitutionType.objects.create(code="MAIRIE_AFFECT_EQUIPE_TEST", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie affect equipe test", type=itype)
        from core.models import User
        regulateur = User.objects.create_user(username="regul-affect-equipe@test.fr", email="regul-affect-equipe@test.fr", type="UTIL_SIMPLE")
        AffectationRoleOperationnel.objects.create(utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True)

        client = APIClient()
        client.force_authenticate(user=admin)
        mail.outbox.clear()

        response = client.post(reverse('dossier-affecter-equipe', args=[dossier.id]), {"equipe": str(team.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert DossierParticipant.objects.filter(dossier=dossier, utilisateur=regulateur, role=DossierParticipant.Role.REGULATION).exists()
        assert Notification.objects.filter(utilisateur=regulateur, dossier=dossier).exists()
        assert DossierHistorique.objects.filter(dossier=dossier, evenement__icontains="Équipe affectée").exists()

    def test_does_not_regress_status_already_further_along(self, admin, dossier, team):
        dossier.statut = Dossier.Statut.EN_COURS
        dossier.save(update_fields=['statut'])
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-affecter-equipe', args=[dossier.id]), {"equipe": str(team.id)}, format='json')

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.EN_COURS

    def test_requires_equipe_field(self, admin, dossier):
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-affecter-equipe', args=[dossier.id]), {}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_plain_member_cannot_assign_team(self, create_user, dossier, team):
        membre = create_user(username="membre-affect-equipe@test.fr", email="membre-affect-equipe@test.fr", type="UTIL_SIMPLE")
        DossierParticipant.objects.create(dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE)
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.post(reverse('dossier-affecter-equipe', args=[dossier.id]), {"equipe": str(team.id)}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDefinirStatut:

    def test_admin_can_change_status(self, admin, dossier):
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-definir-statut', args=[dossier.id]), {"statut": "EN_COURS"}, format='json')

        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.EN_COURS
        assert AuditLog.objects.filter(objet_id=dossier.id, action__code="MODIFICATION").exists()

    def test_rejects_cloture_status(self, admin, dossier):
        """CLOTURE/RESOLU restent exclusivement gérés par cloturer(), avec sa propre garde."""
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-definir-statut', args=[dossier.id]), {"statut": "CLOTURE"}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        dossier.refresh_from_db()
        assert dossier.statut == Dossier.Statut.NOUVEAU

    def test_rejects_invalid_status(self, admin, dossier):
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(reverse('dossier-definir-statut', args=[dossier.id]), {"statut": "PAS_UN_VRAI_STATUT"}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_plain_member_cannot_change_status(self, create_user, dossier):
        membre = create_user(username="membre-def-statut@test.fr", email="membre-def-statut@test.fr", type="UTIL_SIMPLE")
        DossierParticipant.objects.create(dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE)
        client = APIClient()
        client.force_authenticate(user=membre)

        response = client.post(reverse('dossier-definir-statut', args=[dossier.id]), {"statut": "EN_COURS"}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
