"""Accès à l'outil « Simulation d'inondation » (peut_simuler_commune) : un acteur institutionnel
couvre tout son secteur (correctif du 20/10/2026 -- un Conseil départemental était refusé sur
les communes de son propre département, hors sa commune siège), et en DEMO il peut simuler
n'importe quelle commune (jeux de démonstration répartis sur plusieurs départements)."""
import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from core.habitations import peut_simuler_commune
from core.models import Commune, Institution, InstitutionType, UserRole


def _requete(user, environment="PROD"):
    request = APIRequestFactory().get("/api/simulation-inondation/42183/", HTTP_X_ENVIRONMENT=environment)
    force_authenticate(request, user=user)
    request.user = user
    return request


@pytest.fixture
def commune_loire():
    # 42183 Saint-Chamond, 42218 Saint-Étienne : département 42 ; 33281 Bordeaux : département 33.
    Commune.objects.get_or_create(code="42183", defaults={"departement_code": "42", "epci_code": "244200770", "region_code": "84"})
    Commune.objects.get_or_create(code="42218", defaults={"departement_code": "42", "region_code": "84"})
    Commune.objects.get_or_create(code="33281", defaults={"departement_code": "33", "region_code": "75"})


def _departement_institution():
    itype, _ = InstitutionType.objects.get_or_create(code="cg", defaults={"libelle": "Conseil départemental"})
    inst = Institution.objects.create(nom="Conseil départemental test", type=itype, commune_code="42218")
    # Institution.save() dénormalise le secteur depuis la commune + le type.
    inst.secteur_niveau_effectif = "departement"
    inst.departement_code = "42"
    inst.save()
    return inst


@pytest.fixture
def agent_departement(create_user, commune_loire):
    inst = _departement_institution()
    return create_user(username="agent-cd42@test.fr", email="agent-cd42@test.fr", type="AUT_LOCALE",
                       demo_role="AUT_LOCALE", institution=inst)


@pytest.mark.django_db
class TestAccesSimulation:

    def test_departement_couvre_une_commune_de_son_departement(self, agent_departement):
        assert peut_simuler_commune(_requete(agent_departement), "42183") is True

    def test_departement_couvre_sa_commune_siege(self, agent_departement):
        assert peut_simuler_commune(_requete(agent_departement), "42218") is True

    def test_departement_ne_couvre_pas_hors_departement_en_prod(self, agent_departement):
        assert peut_simuler_commune(_requete(agent_departement), "33281") is False

    def test_en_demo_toute_commune_est_accessible(self, agent_departement):
        # Corse, hors du département 42 : refusée en prod, autorisée en démo.
        assert peut_simuler_commune(_requete(agent_departement, "DEMO"), "2A269") is True

    def test_mairie_couvre_sa_commune_seulement(self, create_user, commune_loire):
        itype, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
        inst = Institution.objects.create(nom="Mairie test", type=itype, commune_code="42183")
        inst.secteur_niveau_effectif = "commune"
        inst.save()
        maire = create_user(username="maire42183@test.fr", email="maire42183@test.fr", type="AUT_LOCALE", institution=inst)
        assert peut_simuler_commune(_requete(maire), "42183") is True
        assert peut_simuler_commune(_requete(maire), "42218") is False

    def test_admin_accede_a_tout(self, create_user):
        admin = create_user(username="admin-simu@test.fr", email="admin-simu@test.fr", type="ADMIN")
        assert peut_simuler_commune(_requete(admin), "2A269") is True

    def test_utilisateur_non_institutionnel_refuse(self, create_user):
        simple = create_user(username="simple-simu@test.fr", email="simple-simu@test.fr", type="UTIL_SIMPLE")
        assert peut_simuler_commune(_requete(simple), "42183") is False
