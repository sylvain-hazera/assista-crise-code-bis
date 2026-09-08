from unittest.mock import patch

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
        # ADMIN (bypass universel du zonage, voir zone_scoping.py) : ce test porte sur le champ
        # crise_nom du serializer, pas sur le filtrage par zone — institutional_client n'a pas
        # d'institution/zone résolvable, ce qui exclurait sinon le point de la liste.
        client, user = institutional_client
        user.type = 'ADMIN'
        user.save()
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

    def test_without_mine_and_without_zone_returns_nothing(self, institutional_client, crisis, point_type):
        # AVANT le correctif de zonage, `list` sans `mine` renvoyait TOUS les points de
        # l'environnement, sans filtre géographique — corrigé : sans institution/zone
        # résolvable, la liste par défaut est vide (même règle que TeamViewSet/DossierViewSet).
        client, user = institutional_client
        PointOperationnel.objects.create(nom="Mon point", type=point_type, crise=crisis, responsable=user)
        PointOperationnel.objects.create(nom="Point d'un autre", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'))

        assert response.data == []


@pytest.mark.django_db
class TestPointOperationnelPrevusFilter:
    """Liste "centres prévus" (CentresComponent) : PointOperationnel créés sans crise
    rattachée (crise vide) — voir PointOperationnelViewSet.filterset_fields."""

    def test_crise_isnull_true_returns_only_points_without_crisis(self, create_user, crisis, point_type):
        admin = create_user(username="admin-prevus-point@test.fr", email="admin-prevus-point@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        prevu = PointOperationnel.objects.create(nom="Point prévu", type=point_type, crise=None)
        PointOperationnel.objects.create(nom="Point avec crise", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'), {"crise__isnull": "true"})

        assert response.status_code == status.HTTP_200_OK
        ids = {p["id"] for p in response.data}
        assert ids == {str(prevu.id)}

    def test_crise_isnull_false_excludes_points_without_crisis(self, create_user, crisis, point_type):
        admin = create_user(username="admin-non-prevus-point@test.fr", email="admin-non-prevus-point@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        PointOperationnel.objects.create(nom="Point prévu", type=point_type, crise=None)
        avec_crise = PointOperationnel.objects.create(nom="Point avec crise", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-list'), {"crise__isnull": "false"})

        ids = {p["id"] for p in response.data}
        assert ids == {str(avec_crise.id)}


@pytest.mark.django_db
class TestPointOperationnelCommuneNom:
    """commune_nom (PointOperationnelSerializer) : reverse-géocodage du point, même mécanisme
    que le scoping zone — affiché dans les listes centres (CentresComponent/crises.component)."""

    @patch("core.geo_lookup._fetch_json")
    def test_serializer_exposes_commune_nom_from_location(self, mock_fetch, create_user, crisis, point_type):
        mock_fetch.return_value = {
            "features": [{"properties": {"city": "Grenoble", "citycode": "38185"}}],
        }
        admin = create_user(username="admin-commune-point@test.fr", email="admin-commune-point@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        point = PointOperationnel.objects.create(
            nom="Point avec commune", type=point_type, crise=crisis, location="POINT (5.7245 45.1885)",
        )

        response = client.get(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["commune_nom"] == "Grenoble"

    def test_serializer_returns_none_without_location(self, create_user, crisis, point_type):
        admin = create_user(username="admin-sans-commune-point@test.fr", email="admin-sans-commune-point@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        point = PointOperationnel.objects.create(nom="Point sans localisation", type=point_type, crise=crisis)

        response = client.get(reverse('pointoperationnel-detail', args=[point.id]))

        assert response.data["commune_nom"] is None


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


@pytest.mark.django_db
class TestCreerEquipeEnEditantLePoint:
    """Créer une équipe pour un point déjà existant mais encore sans équipe, en l'éditant —
    jusqu'ici la création à la volée n'était possible qu'à la création du point (voir
    TestCreerEquipeAvecPoint ci-dessus), obligeant sinon un aller-retour par l'écran équipes."""

    def test_creates_team_and_assigns_it_on_update(self, institutional_client, crisis, point_type, institution):
        client, user = institutional_client
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
        point = PointOperationnel.objects.create(nom="Point sans équipe", type=point_type, crise=crisis)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nouvelle_equipe_nom": "Équipe créée en édition"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        team = Team.objects.get(name="Équipe créée en édition")
        assert team.institution_id == institution.id
        assert response.data["equipe"] == team.id

    def test_ignored_when_point_already_has_a_team(self, institutional_client, crisis, point_type):
        client, _ = institutional_client
        existing_team = Team.objects.create(name="Équipe déjà en place")
        point = PointOperationnel.objects.create(nom="Point avec équipe", type=point_type, crise=crisis, equipe=existing_team)
        before = Team.objects.count()

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"nouvelle_equipe_nom": "Ne doit pas être créée"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert Team.objects.count() == before
        assert response.data["equipe"] == existing_team.id
        assert not Team.objects.filter(name="Ne doit pas être créée").exists()


@pytest.mark.django_db
class TestPointResponsableInstitutionRestriction:
    """Le responsable (et les responsables supplémentaires) d'un point doivent être membres de
    l'institution responsable de l'équipe du point, ou de son institution déléguée — sauf pour
    un administrateur, qui peut désigner n'importe qui (voir
    PointOperationnelViewSet._valider_responsable)."""

    def _institution(self, code, nom):
        itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": "Mairie"})
        return Institution.objects.create(nom=nom, type=itype)

    def test_rejects_responsable_outside_institution(self, institutional_client, crisis, point_type, create_user):
        client, _ = institutional_client
        institution_point = self._institution("MAIRIE_RESP_A", "Mairie point A")
        institution_etrangere = self._institution("MAIRIE_RESP_ETRANGERE", "Mairie étrangère")
        team = Team.objects.create(name="Equipe resp test", institution=institution_point)
        point = PointOperationnel.objects.create(nom="Point resp test", type=point_type, crise=crisis, equipe=team)
        outsider = create_user(username="outsider-resp@test.fr", email="outsider-resp@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=institution_etrangere, utilisateur=outsider, actif=True)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"responsable": str(outsider.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        point.refresh_from_db()
        assert point.responsable_id != outsider.id

    def test_allows_responsable_from_own_institution(self, institutional_client, crisis, point_type, create_user):
        client, _ = institutional_client
        institution_point = self._institution("MAIRIE_RESP_B", "Mairie point B")
        team = Team.objects.create(name="Equipe resp test 2", institution=institution_point)
        point = PointOperationnel.objects.create(nom="Point resp test 2", type=point_type, crise=crisis, equipe=team)
        membre = create_user(username="membre-resp@test.fr", email="membre-resp@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=institution_point, utilisateur=membre, actif=True)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"responsable": str(membre.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        point.refresh_from_db()
        assert point.responsable_id == membre.id

    def test_allows_responsable_from_delegated_institution(self, institutional_client, crisis, point_type, create_user):
        client, _ = institutional_client
        institution_point = self._institution("MAIRIE_RESP_C", "Mairie point C")
        institution_deleguee = self._institution("MAIRIE_RESP_DELEGUEE", "Mairie déléguée")
        team = Team.objects.create(
            name="Equipe resp test 3", institution=institution_point, institution_delegataire=institution_deleguee,
        )
        point = PointOperationnel.objects.create(nom="Point resp test 3", type=point_type, crise=crisis, equipe=team)
        membre = create_user(username="membre-deleg-resp@test.fr", email="membre-deleg-resp@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=institution_deleguee, utilisateur=membre, actif=True)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"responsable": str(membre.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_assign_any_responsable(self, create_user, crisis, point_type):
        admin = create_user(username="admin-resp-point@test.fr", email="admin-resp-point@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        institution_point = self._institution("MAIRIE_RESP_D", "Mairie point D")
        team = Team.objects.create(name="Equipe resp test 4", institution=institution_point)
        point = PointOperationnel.objects.create(nom="Point resp test 4", type=point_type, crise=crisis, equipe=team)
        outsider = create_user(username="outsider-admin-resp@test.fr", email="outsider-admin-resp@test.fr", type="AUT_LOCALE")

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"responsable": str(outsider.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK

    def test_point_without_team_is_unrestricted(self, institutional_client, crisis, point_type, create_user):
        client, _ = institutional_client
        point = PointOperationnel.objects.create(nom="Point sans equipe resp test", type=point_type, crise=crisis)
        anyone = create_user(username="anyone-no-team-resp@test.fr", email="anyone-no-team-resp@test.fr", type="AUT_LOCALE")

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"responsable": str(anyone.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK

    def test_rejects_responsables_supplementaires_outside_institution(self, institutional_client, crisis, point_type, create_user):
        client, _ = institutional_client
        institution_point = self._institution("MAIRIE_RESP_E", "Mairie point E")
        institution_etrangere = self._institution("MAIRIE_RESP_ETRANGERE_2", "Mairie étrangère 2")
        team = Team.objects.create(name="Equipe resp test 5", institution=institution_point)
        point = PointOperationnel.objects.create(nom="Point resp test 5", type=point_type, crise=crisis, equipe=team)
        outsider = create_user(username="outsider-resps-supp@test.fr", email="outsider-resps-supp@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=institution_etrangere, utilisateur=outsider, actif=True)

        response = client.patch(
            reverse('pointoperationnel-detail', args=[point.id]),
            {"responsables_ids": [str(outsider.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
