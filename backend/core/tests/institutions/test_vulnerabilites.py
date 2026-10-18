import pytest
from django.test import RequestFactory
from rest_framework.test import APIClient

from core.models import (
    Competence,
    DelegationCompetence,
    Institution,
    InstitutionType,
    PersonneVulnerable,
    Team,
)
from core.vulnerabilites import NOM_COMPETENCE_VULNERABILITES, institution_accede_commune

COMMUNE_CODE = "38185"


@pytest.fixture
def mairie(db):
    itype = InstitutionType.objects.create(code="MAIRIE_VULN_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie vulnerables test", type=itype, commune_code=COMMUNE_CODE)


@pytest.fixture
def association(db):
    itype = InstitutionType.objects.create(code="ASSO_VULN_TEST", libelle="Association")
    return Institution.objects.create(nom="Association vulnerables test", type=itype)


@pytest.fixture
def competence_vulnerables(db):
    # Déjà seedée par la migration 0201_seed_type_vulnerabilite_et_competence -- get_or_create
    # pour ne pas entrer en collision avec cette ligne déjà présente en base de test.
    competence, _ = Competence.objects.get_or_create(nom=NOM_COMPETENCE_VULNERABILITES)
    return competence


@pytest.fixture
def rcsc_team(db, mairie):
    return Team.objects.create(name="RCSC Test", institution=mairie, est_equipe_rcsc=True)


def _request_for(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.mark.django_db
class TestInstitutionAccedeCommuneVulnerables:
    def test_membre_rcsc_de_la_mairie_a_acces(self, create_user, mairie, rcsc_team):
        user = create_user(username="rcsc-membre@test.fr", email="rcsc-membre@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        rcsc_team.members.add(user)

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is True

    def test_membre_sous_equipe_rcsc_a_acces(self, create_user, mairie, rcsc_team):
        # Une RCSC scindée en sous-équipes (equipe_parente) doit rester UNE RCSC.
        sous_equipe = Team.objects.create(name="RCSC Test - secteur nord", institution=mairie, equipe_parente=rcsc_team)
        user = create_user(username="rcsc-sous-equipe@test.fr", email="rcsc-sous-equipe@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        sous_equipe.members.add(user)

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is True

    def test_agent_mairie_hors_rcsc_sans_role_est_refuse(self, create_user, mairie, rcsc_team):
        user = create_user(username="agent-simple@test.fr", email="agent-simple@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        # Pas ajouté à rcsc_team, pas de rôle RESPONSABLE -- ne doit PAS avoir accès, même s'il
        # est bien AUT_LOCALE de la bonne commune (contrairement à habitations.py).
        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_institution_tierce_avec_delegation_active_a_acces(
        self, create_user, mairie, association, competence_vulnerables
    ):
        DelegationCompetence.objects.create(
            institution_source=mairie, institution_cible=association,
            competence=competence_vulnerables, active=True,
            communes=[COMMUNE_CODE],
        )
        user = create_user(username="asso-deleguee@test.fr", email="asso-deleguee@test.fr", type="SECOURS")
        user.institution = association
        user.save()

        # Accès standard : pas besoin d'appartenir à une équipe particulière de l'association.
        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is True

    def test_institution_tierce_sans_delegation_est_refusee(self, create_user, association):
        user = create_user(username="asso-non-deleguee@test.fr", email="asso-non-deleguee@test.fr", type="SECOURS")
        user.institution = association
        user.save()

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False


@pytest.mark.django_db
class TestPersonneVulnerableViewSet:
    def _payload(self):
        return {
            "nom": "Dupont", "prenom": "Jeanne", "adresse": "1 rue du Test, 38185",
            "commune_code": COMMUNE_CODE, "mode_consentement": "VOLONTAIRE",
        }

    def test_creation_refusee_sans_acces(self, create_user, mairie):
        user = create_user(username="agent-refuse@test.fr", email="agent-refuse@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 403

    def test_creation_acceptee_pour_membre_rcsc(self, create_user, mairie, rcsc_team):
        user = create_user(username="rcsc-createur@test.fr", email="rcsc-createur@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        rcsc_team.members.add(user)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 201, response.data
        personne = PersonneVulnerable.objects.get(pk=response.data["id"])
        assert personne.institution_declarante_id == mairie.id
        assert personne.nom == "Dupont"  # déchiffré transparemment à la lecture ORM

    def test_champs_sensibles_illisibles_en_base_brute(self, create_user, mairie, rcsc_team):
        from django.db import connection

        user = create_user(username="rcsc-chiffre@test.fr", email="rcsc-chiffre@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        rcsc_team.members.add(user)
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 201

        with connection.cursor() as cursor:
            cursor.execute("SELECT nom, adresse FROM core_personnevulnerable WHERE id = %s", [response.data["id"]])
            nom_brut, adresse_brut = cursor.fetchone()
        assert "Dupont" not in nom_brut
        assert "Test" not in adresse_brut
