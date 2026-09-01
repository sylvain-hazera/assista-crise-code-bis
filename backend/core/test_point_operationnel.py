import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Competence,
    ContactInstitution,
    Crisis,
    Institution,
    InstitutionType,
    PointOperationnel,
    PointType,
    Team,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise point test", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def point_type(db):
    return PointType.objects.create(code="COLLECTE_POINT_TEST", libelle="Point de collecte test")


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_POINT_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie point test", type=itype)


@pytest.fixture
def institutional_client(create_user):
    user = create_user(username="acteur-point@test.fr", email="acteur-point@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestPointOperationnelSeedTypes:

    def test_four_requested_point_types_exist(self):
        libelles = set(PointType.objects.values_list('libelle', flat=True))
        assert {
            "Point de transit", "Point de regroupement des moyens",
            "Centre d'accueil des personnes", "Point de collecte",
        }.issubset(libelles)


@pytest.mark.django_db
class TestPointOperationnelLocationSerialization:

    def test_create_with_location_returns_lat_lon(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Point test", "type": str(point_type.id), "crise": str(crisis.id),
                "location": '{"type": "Point", "coordinates": [5.72, 45.18]}',
                "description": "Un point de test",
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["latitude"] == pytest.approx(45.18)
        assert response.data["longitude"] == pytest.approx(5.72)
        assert response.data["description"] == "Un point de test"

    def test_exposes_type_code(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        point = PointOperationnel.objects.create(nom="Point type code test", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["type_code"] == point_type.code


@pytest.mark.django_db
class TestCartePublique:

    def test_anonymous_sees_hebergement_and_secours_only(self, crisis):
        hebergement_type = PointType.objects.get_or_create(code="HEBERGEMENT", defaults={"libelle": "Centre d'accueil des personnes"})[0]
        secours_type = PointType.objects.get_or_create(code="SECOURS", defaults={"libelle": "Poste de secours"})[0]
        autre_type = PointType.objects.create(code="AUTRE_CARTE_PUB_TEST", libelle="Autre test")

        centre = PointOperationnel.objects.create(nom="Centre public test", type=hebergement_type, crise=crisis, actif=True)
        poste = PointOperationnel.objects.create(nom="Poste secours public test", type=secours_type, crise=crisis, actif=True)
        autre = PointOperationnel.objects.create(nom="Autre point public test", type=autre_type, crise=crisis, actif=True)

        client = APIClient()
        response = client.get(reverse('pointoperationnel-carte-publique'))

        assert response.status_code == status.HTTP_200_OK
        noms = {p["nom"] for p in response.data}
        assert centre.nom in noms
        assert poste.nom in noms
        assert autre.nom not in noms

    def test_excludes_inactive_points(self, crisis):
        hebergement_type = PointType.objects.get_or_create(code="HEBERGEMENT", defaults={"libelle": "Centre d'accueil des personnes"})[0]
        inactif = PointOperationnel.objects.create(nom="Centre inactif test", type=hebergement_type, crise=crisis, actif=False)

        client = APIClient()
        response = client.get(reverse('pointoperationnel-carte-publique'))

        assert inactif.nom not in {p["nom"] for p in response.data}

    def test_exposes_type_code_for_filtering(self, crisis):
        secours_type = PointType.objects.get_or_create(code="SECOURS", defaults={"libelle": "Poste de secours"})[0]
        poste = PointOperationnel.objects.create(nom="Poste type code test", type=secours_type, crise=crisis, actif=True)

        client = APIClient()
        response = client.get(reverse('pointoperationnel-carte-publique'))

        entry = next(p for p in response.data if p["nom"] == poste.nom)
        assert entry["type_code"] == "SECOURS"


@pytest.mark.django_db
class TestPointOperationnelEditPermissions:

    def test_owner_institutional_actor_can_edit(self, institutional_client, crisis, point_type):
        client, user = institutional_client
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis, responsable=user)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nom": "Point renommé", "date_ouverture": "2026-08-27T10:00:00Z"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        point.refresh_from_db()
        assert point.nom == "Point renommé"
        assert point.date_ouverture is not None

    def test_non_institutional_user_cannot_edit(self, create_user, crisis, point_type):
        """Régression : avant ce volet, n'importe quel compte connecté pouvait modifier le
        point opérationnel d'une institution tierce (seul `create` était restreint)."""
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        simple_user = create_user(username="simple-point@test.fr", email="simple-point@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nom": "Modifié sans droit"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_institutional_user_cannot_delete(self, create_user, crisis, point_type):
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        simple_user = create_user(username="simple-point-del@test.fr", email="simple-point-del@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple_user)

        response = client.delete(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PointOperationnel.objects.filter(id=point.id).exists()

    def test_edit_writes_audit_log(self, institutional_client, crisis, point_type):
        from core.models import AuditLog
        client, user = institutional_client
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)

        client.patch(reverse('pointoperationnel-detail', args=[point.id]), {"nom": "Point audité"}, format='json')

        assert AuditLog.objects.filter(
            objet_id=point.id, action__code="MODIFICATION", objet_type="PointOperationnel",
        ).exists()


@pytest.mark.django_db
class TestPointOperationnelCompetencesRequises:

    def test_patch_adds_competences(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        competence = Competence.objects.create(nom="Premiers secours (point test)")

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"competences_requises": [str(competence.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["competences_requises_libelles"] == ["Premiers secours (point test)"]
        point.refresh_from_db()
        assert list(point.competences_requises.all()) == [competence]

    def test_patch_removes_competences(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        competence = Competence.objects.create(nom="Logistique (point test)")
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        point.competences_requises.add(competence)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"competences_requises": []},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        point.refresh_from_db()
        assert point.competences_requises.count() == 0

    def test_patch_competences_blocked_on_closed_crisis(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        competence = Competence.objects.create(nom="Secourisme (point test)")
        point = PointOperationnel.objects.create(nom="Point existant", type=point_type, crise=crisis)
        crisis.end_date = timezone.now()
        crisis.save()

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"competences_requises": [str(competence.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestPointOperationnelCriseNom:

    def test_list_includes_crise_nom(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        PointOperationnel.objects.create(nom="Point avec crise", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'))

        assert response.status_code == status.HTTP_200_OK
        point_data = next(p for p in response.data if p["nom"] == "Point avec crise")
        assert point_data["crise_nom"] == crisis.name


@pytest.mark.django_db
class TestPointOperationnelMineFilter:

    def test_mine_includes_points_i_am_responsable_of(self, institutional_client, crisis, point_type):
        client, user = institutional_client
        mine = PointOperationnel.objects.create(nom="Mon point", type=point_type, crise=crisis, responsable=user)
        PointOperationnel.objects.create(nom="Point d'un autre", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'), {"mine": "true"})

        assert response.status_code == status.HTTP_200_OK
        ids = {p["id"] for p in response.data}
        assert ids == {str(mine.id)}

    def test_mine_includes_points_where_i_am_team_leader(self, institutional_client, crisis, point_type):
        client, user = institutional_client
        team = Team.objects.create(name="Equipe leader mine test", leader=user)
        mine = PointOperationnel.objects.create(nom="Point equipe leader", type=point_type, crise=crisis, equipe=team)
        PointOperationnel.objects.create(nom="Point d'un autre", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'), {"mine": "true"})

        ids = {p["id"] for p in response.data}
        assert ids == {str(mine.id)}

    def test_mine_includes_points_where_i_am_team_member(self, institutional_client, crisis, point_type):
        client, user = institutional_client
        team = Team.objects.create(name="Equipe membre mine test")
        team.members.add(user)
        mine = PointOperationnel.objects.create(nom="Point equipe membre", type=point_type, crise=crisis, equipe=team)
        PointOperationnel.objects.create(nom="Point d'un autre", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'), {"mine": "true"})

        ids = {p["id"] for p in response.data}
        assert ids == {str(mine.id)}

    def test_without_mine_returns_all_points(self, institutional_client, crisis, point_type):
        client, user = institutional_client
        PointOperationnel.objects.create(nom="Mon point", type=point_type, crise=crisis, responsable=user)
        PointOperationnel.objects.create(nom="Point d'un autre", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'))

        assert len(response.data) >= 2


@pytest.mark.django_db
class TestCreerEquipeAvecPoint:
    """Créer une équipe en même temps qu'un point opérationnel — évite d'avoir à en créer une
    séparément avant de pouvoir en assigner une (retour terrain)."""

    def test_creates_team_and_assigns_it_to_the_point(self, institutional_client, crisis, point_type, institution):
        client, user = institutional_client
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)

        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Point avec nouvelle équipe", "type": str(point_type.id), "crise": str(crisis.id),
                "nouvelle_equipe_nom": "Équipe créée avec le point",
                "institution": str(institution.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        team = Team.objects.get(name="Équipe créée avec le point")
        assert team.institution_id == institution.id
        assert response.data["equipe"] == team.id

    def test_existing_equipe_takes_precedence_over_new_team_name(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        existing_team = Team.objects.create(name="Équipe déjà existante")

        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Point avec équipe existante", "type": str(point_type.id), "crise": str(crisis.id),
                "equipe": str(existing_team.id),
                "nouvelle_equipe_nom": "Ne doit pas être créée",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["equipe"] == existing_team.id
        assert not Team.objects.filter(name="Ne doit pas être créée").exists()

    def test_new_team_works_without_crisis(self, institutional_client, point_type):
        client, _ = institutional_client

        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Point sans crise", "type": str(point_type.id),
                "nouvelle_equipe_nom": "Équipe sans crise",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Team.objects.filter(name="Équipe sans crise").exists()

    def test_blank_new_team_name_does_not_create_a_team(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        before = Team.objects.count()

        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Point sans nouvelle équipe", "type": str(point_type.id), "crise": str(crisis.id),
                "nouvelle_equipe_nom": "   ",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Team.objects.count() == before
        assert response.data["equipe"] is None
