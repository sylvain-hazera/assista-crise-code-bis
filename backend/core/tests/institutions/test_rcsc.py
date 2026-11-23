"""La réserve communale (RCSC), institution fille de sa mairie, avec les droits de la mairie
(23/11/2026, core/rcsc.py)."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core import evaluation_terrain, rcsc
from core.institution_attachment import grant_institution_and_demo_access
from core.models import (
    ContactInstitution, Crisis, Institution, InstitutionType, ModuleDegatsCrise, Team, UserRole,
)


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def mairie(db):
    t, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie du Porge", type=t, commune_code="33333", commune_nom="Le Porge", actif=True)


@pytest.fixture
def agent(create_user, mairie):
    u = create_user(username="agent-rcsc@test.fr", email="agent-rcsc@test.fr", type=UserRole.LOCAL_AUTHORITY)
    ContactInstitution.objects.create(institution=mairie, utilisateur=u, actif=True)
    u.institution = mairie
    u.save()
    return u


@pytest.mark.django_db
class TestCreation:
    def test_la_mairie_cree_sa_reserve_sous_elle(self, agent, mairie):
        r = _client(agent).post(reverse("institution-list"), {"nom": "RCSC du Porge", "type": str(rcsc.type_rcsc().id)}, format="json")
        assert r.status_code == 201, r.data
        fille = Institution.objects.get(nom="RCSC du Porge")
        assert fille.institution_parente_id == mairie.id
        assert fille.commune_code == "33333"          # la commune de sa mère
        assert Team.objects.filter(institution=fille, est_equipe_rcsc=True).exists()

    def test_une_seule_reserve_par_mairie(self, agent, mairie):
        rcsc.creer_pour(mairie)
        r = _client(agent).post(reverse("institution-list"), {"nom": "Seconde RCSC", "type": str(rcsc.type_rcsc().id)}, format="json")
        assert r.status_code == 400 and "déjà sa réserve" in str(r.data)

    def test_pas_de_reserve_sous_une_association(self, create_user):
        t, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
        asso = Institution.objects.create(nom="Asso Test RCSC", type=t)
        membre = create_user(username="asso-rcsc@test.fr", email="asso-rcsc@test.fr", type=UserRole.ORGANIZED_RESCUE)
        ContactInstitution.objects.create(institution=asso, utilisateur=membre, actif=True)
        membre.institution = asso
        membre.save()
        r = _client(membre).post(reverse("institution-list"), {"nom": "Fausse RCSC", "type": str(rcsc.type_rcsc().id)}, format="json")
        assert r.status_code == 400 and "sous sa mairie" in str(r.data)


@pytest.mark.django_db
class TestDroits:
    def test_le_reserviste_travaille_pour_la_mairie_avec_ses_droits(self, create_user, mairie):
        reserve = rcsc.creer_pour(mairie)
        reserviste = create_user(username="reserviste@test.fr", email="reserviste@test.fr", type=UserRole.SIMPLE_USER)
        ContactInstitution.objects.create(institution=reserve, utilisateur=reserviste, fonction=rcsc.FONCTION_RESERVISTE, actif=True)
        grant_institution_and_demo_access(reserviste, reserve)
        reserviste.refresh_from_db()
        assert reserviste.institution_id == mairie.id
        assert reserviste.type == UserRole.LOCAL_AUTHORITY
        assert Team.objects.get(institution=reserve).members.filter(pk=reserviste.pk).exists()

        # Un droit de la mairie, par exemple l'évaluation des dégâts avec le module de la mairie.
        crise = Crisis.objects.create(name="Feu RCSC", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326))
        ModuleDegatsCrise.objects.create(crise=crise, institution=mairie, actif=True)

        class _Requete:
            user = reserviste
            headers = {}
            META = {}
            query_params = {}
            GET = {}
        assert evaluation_terrain.motif_de_refus(_Requete(), "33333", crise) is None

    def test_un_membre_d_aasc_qui_rejoint_la_reserve_garde_son_role(self, create_user, mairie):
        t, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
        asso = Institution.objects.create(nom="Asso Benevoles", type=t)
        benevole = create_user(username="benev-rcsc@test.fr", email="benev-rcsc@test.fr", type=UserRole.ORGANIZED_RESCUE)
        benevole.institution = asso
        benevole.save()
        grant_institution_and_demo_access(benevole, rcsc.creer_pour(mairie))
        benevole.refresh_from_db()
        assert (benevole.institution_id, benevole.type) == (asso.id, UserRole.ORGANIZED_RESCUE)
