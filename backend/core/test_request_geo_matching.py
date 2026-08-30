import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationCompetence,
    AffectationRoleOperationnel,
    Besoin,
    BesoinCompetence,
    Competence,
    Crisis,
    Dossier,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    Notification,
    RequestTypeBesoin,
    RoleOperationnel,
    Team,
)


def _declare_responsable(crisis, create_user):
    """Rend une crise 'surveillée' (Volet 8) : sans ImplicationInstitution.responsable
    actif, le dépôt de demande sur cette crise est désormais rejeté par le serializer."""
    itype = InstitutionType.objects.create(code=f"ITYPE-MONITOR-{crisis.id}", libelle="Mairie")
    institution = Institution.objects.create(nom=f"Institution monitor {crisis.id}", type=itype)
    responsable = create_user(username=f"resp-{crisis.id}@test.fr", email=f"resp-{crisis.id}@test.fr", type="AUT_LOCALE")
    ImplicationInstitution.objects.create(
        crise=crisis, institution=institution, type_implication="IMPLIQUE",
        responsable=responsable, actif=True,
    )
    return responsable
from core.views import department_code_from_commune_code, team_zone_specificity


class TestDepartmentCodeFromCommuneCode:

    def test_metropolitan(self):
        assert department_code_from_commune_code("38185") == "38"

    def test_corsica(self):
        assert department_code_from_commune_code("2A004") == "2A"
        assert department_code_from_commune_code("2b033") == "2B"

    def test_overseas(self):
        assert department_code_from_commune_code("97411") == "974"

    def test_empty(self):
        assert department_code_from_commune_code(None) is None
        assert department_code_from_commune_code("") is None


@pytest.mark.django_db
class TestTeamZoneSpecificity:

    def test_no_zone_declared_matches_everywhere(self, db):
        team = Team.objects.create(name="Sans zone", description="", color="#3b82f6")
        demande = type("D", (), {"location": None, "commune_code": "38185"})()
        assert team_zone_specificity(team, demande) == 0

    def test_department_match(self, db):
        team = Team.objects.create(name="Dept", description="", color="#3b82f6", departements=["38"])
        demande = type("D", (), {"location": None, "commune_code": "38185"})()
        assert team_zone_specificity(team, demande) == 1

    def test_department_mismatch_excludes_team(self, db):
        team = Team.objects.create(name="Dept", description="", color="#3b82f6", departements=["73"])
        demande = type("D", (), {"location": None, "commune_code": "38185"})()
        assert team_zone_specificity(team, demande) is None

    def test_commune_match_outscores_department(self, db):
        team = Team.objects.create(
            name="Commune", description="", color="#3b82f6",
            departements=["38"], communes=["38185"],
        )
        demande = type("D", (), {"location": None, "commune_code": "38185"})()
        assert team_zone_specificity(team, demande) == 2

    def test_precise_zone_match(self, db):
        from django.contrib.gis.geos import GEOSGeometry
        polygon = GEOSGeometry("POLYGON((5.7 45.1, 5.8 45.1, 5.8 45.2, 5.7 45.2, 5.7 45.1))")
        team = Team.objects.create(name="Precise", description="", color="#3b82f6", zone_precise=polygon)
        point = GEOSGeometry("POINT (5.72 45.18)")
        demande = type("D", (), {"location": point, "commune_code": None})()
        assert team_zone_specificity(team, demande) == 3

    def test_precise_zone_outside_excludes_team(self, db):
        from django.contrib.gis.geos import GEOSGeometry
        polygon = GEOSGeometry("POLYGON((5.7 45.1, 5.8 45.1, 5.8 45.2, 5.7 45.2, 5.7 45.1))")
        team = Team.objects.create(name="Precise", description="", color="#3b82f6", zone_precise=polygon)
        point = GEOSGeometry("POINT (0.0 0.0)")
        demande = type("D", (), {"location": point, "commune_code": None})()
        assert team_zone_specificity(team, demande) is None


@pytest.mark.django_db
class TestRequestAutoAssignmentGeoMatching:

    def _setup_competence_chain(self, request_type):
        besoin = Besoin.objects.create(nom="Besoin geo test")
        RequestTypeBesoin.objects.create(request_type=request_type, besoin=besoin)
        competence = Competence.objects.create(nom="Competence geo test")
        BesoinCompetence.objects.create(besoin=besoin, competence=competence)
        return competence

    def test_request_routed_to_team_matching_department(self, request_type, create_user):
        competence = self._setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise geo", type="INCENDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)
        team_far = Team.objects.create(name="Equipe loin", description="", color="#3b82f6", departements=["73"])
        team_near = Team.objects.create(name="Equipe proche", description="", color="#3b82f6", departements=["38"])
        AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team_far, active=True)
        AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team_near, active=True)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande geo test", "location": "POINT (5.72 45.18)", "commune_code": "38185",
                "first_name_request": "A", "last_name_request": "B", "email_request": "geo@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=competence)
        assert dossier.equipe == team_near

    def test_request_not_routed_when_no_team_matches_zone(self, request_type, create_user):
        competence = self._setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise geo 2", type="INCENDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)
        team_far = Team.objects.create(name="Equipe loin 2", description="", color="#3b82f6", departements=["73"])
        AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team_far, active=True)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande geo test 2", "location": "POINT (5.72 45.18)", "commune_code": "38185",
                "first_name_request": "A", "last_name_request": "B", "email_request": "geo2@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=competence)
        assert dossier.equipe is None

    def test_request_type_without_besoin_mapping_does_not_crash(self, request_type):
        """Régression : `mapping_competence` référencé hors de son bloc de définition
        provoquait un UnboundLocalError silencieusement avalé — plus aucun Dossier n'était
        créé du tout, même sans équipe. Vérifie que la demande est acceptée normalement."""
        client = APIClient()

        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande sans mapping", "location": "POINT (5.72 45.18)",
                "first_name_request": "A", "last_name_request": "B", "email_request": "nomapping@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_request_without_crisis_and_without_mapping_does_not_poison_transaction(self, request_type):
        """Régression : le dossier de secours (aucune compétence trouvée) était créé avec
        `crise=None`, violant la contrainte NOT NULL de `Dossier.crise` — l'IntegrityError
        était avalée par le except englobant, mais laissait la transaction inutilisable pour
        toute requête suivante (ex: la propre confirmation de la demande). Une demande sans
        crise, dont le type n'a pas de compétence mappée, doit pouvoir être relue juste après
        sans lever `TransactionManagementError`."""
        client = APIClient()

        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande sans crise sans mapping", "location": "POINT (5.72 45.18)",
                "first_name_request": "A", "last_name_request": "B",
                "email_request": "sanscrisesansmapping@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        # Si la transaction avait été empoisonnée, cette requête suivante échouerait.
        from core.models import Request
        assert Request.objects.get(id=response.data["id"]).title == "Demande sans crise sans mapping"

    def test_regulateur_notified_on_automatic_assignment(self, request_type, create_user):
        """Contrairement au chemin manuel (`assign_team`), le chemin automatique de
        `perform_create` ne notifiait jusqu'ici aucun régulateur — un dossier pouvait
        rester invisible tant que personne ne parcourait la liste complète."""
        competence = self._setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise notif", type="INCENDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)
        team = Team.objects.create(name="Equipe notif", description="", color="#3b82f6")
        AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team, active=True)

        regulateur = create_user(username="regul-notif@test.fr", email="regul-notif@test.fr", type="UTIL_SIMPLE")
        role = RoleOperationnel.objects.create(code="REGULATEUR", libelle="Régulateur")
        itype = InstitutionType.objects.create(code="MAIRIE_NOTIF_TEST", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie notif test", type=itype)
        AffectationRoleOperationnel.objects.create(
            utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
        )

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande a notifier", "location": "POINT (5.72 45.18)", "commune_code": "38185",
                "first_name_request": "A", "last_name_request": "B", "email_request": "notif@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=competence)
        assert Notification.objects.filter(utilisateur=regulateur, dossier=dossier).exists()

    def test_no_notification_when_no_regulateur_on_competence(self, request_type, create_user):
        """Aucun régulateur affecté sur cette compétence : la création ne doit pas crasher."""
        competence = self._setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise sans regul", type="INCENDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande sans regulateur", "location": "POINT (5.72 45.18)",
                "first_name_request": "A", "last_name_request": "B", "email_request": "sansregul@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert not Notification.objects.filter(dossier__crise=crisis).exists()
