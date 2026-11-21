"""Suivi départemental (21/11/2026) : enrôlement et avancement du PCS / PICS, branche par branche."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core import document_pcs
from core.models import (
    Commune, ContactInstitution, DelegationGestion, DossierPCS, Institution, InstitutionType, Team, User,
)
from core.suivi_departement import enrolement


def _type(code):
    return InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})[0]


@pytest.fixture
def monde(db):
    for code, nom in (("42186", "Rive-de-Gier"), ("42218", "Saint-Étienne"), ("42001", "Aboën")):
        Commune.objects.update_or_create(code=code, defaults={"nom": nom, "departement_code": "42", "epci_code": "244200770"})
    cg = Institution.objects.create(nom="Conseil départemental — Loire", type=_type("cg"), commune_code="42218",
                                    departement_code="42", secteur_override="departement")
    aasc = Institution.objects.create(nom="Réserve essai", type=_type("aasc"))
    cadre = User.objects.create_user(username="cadre@suivi.test", email="cadre@suivi.test", password="x", type="SECOURS")
    ContactInstitution.objects.create(institution=aasc, utilisateur=cadre, actif=True)
    loire = Team.objects.create(name="Coordination Loire", institution=aasc, echelon="DEPARTEMENTAL", territoire_code="42", environment="PROD")
    loire.membres_encadrement.add(cadre)
    d = DelegationGestion.objects.create(collectivite=cg, aasc=aasc, convention_signee_le="2026-10-01", environment="PROD")
    metropole = Institution.objects.create(nom="Saint-Étienne Métropole", type=_type("epci"), commune_code="42218", epci_code="244200770")
    rive = Institution.objects.create(nom="Mairie - Rive-de-Gier", type=_type("mairie"), commune_code="42186", email="m@rive.exemple")
    agent = User.objects.create_user(username="agent@rive.test", email="agent@rive.test", password="x", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=rive, utilisateur=agent, actif=True)
    DossierPCS.objects.create(institution=rive, environment="PROD", arrete_numero="2024-12", arrete_date="2024-03-01")
    Institution.objects.create(nom="Mairie - Saint-Étienne", type=_type("mairie"), commune_code="42218")
    return dict(d=d, cadre=cadre, metropole=metropole, rive=rive)


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def test_chaque_manque_nomme_une_partie_connue():
    """Si `_manques` gagne une partie, PARTIES doit la connaître, sinon l'avancement ment."""
    import inspect, re
    source = inspect.getsource(document_pcs._manques)
    for partie in set(re.findall(r'manque\("([^"]+)"', source)):
        assert partie in document_pcs.PARTIES, partie


def test_etats_d_enrolement():
    assert enrolement(None) == "non_creee"
    assert enrolement({"membres": 2}) == "a_rejoint"
    assert enrolement({"membres": 0, "invitee_le": "2026-11-21"}) == "invitee"
    assert enrolement({"membres": 0, "email": None}) == "pas_d_adresse"
    assert enrolement({"membres": 0, "email": "m@x.fr"}) == "non_invitee"
    assert enrolement({"membres": 0, "email": None, "referent": {"email": "r@x.fr"}}) == "non_invitee"


@pytest.mark.django_db
def test_vue_departement_puis_branche(monde):
    c = _client(monde["cadre"])
    url = reverse("delegationgestion-suivi", args=[monde["d"].id])
    r = c.get(url)
    assert r.status_code == 200, r.data
    branche = r.data["epcis"][0]
    assert branche["nom"] == "Saint-Étienne Métropole"
    assert (branche["communes"], branche["ont_rejoint"], branche["sans_adresse"]) == (3, 1, 1)

    r = c.get(url, {"epci": "244200770"})
    assert r.status_code == 200, r.data
    communes = {x["code"]: x for x in r.data["communes"]}
    assert communes["42186"]["enrolement"] == "a_rejoint"
    assert communes["42186"]["pcs"]["parties_total"] == len(document_pcs.PARTIES)
    assert "Arrêté" not in communes["42186"]["pcs"]["restantes"]  # arrêté pris
    assert communes["42001"]["enrolement"] == "non_creee" and communes["42001"]["pcs"] is None
    assert r.data["pics"]["parties_total"] == len(document_pcs.PARTIES)


@pytest.mark.django_db
def test_reserve_a_ceux_qui_suivent_le_departement(monde, create_user):
    intrus = create_user(username="intrus@suivi.test", email="intrus@suivi.test", type="SECOURS")
    r = _client(intrus).get(reverse("delegationgestion-suivi", args=[monde["d"].id]))
    assert r.status_code in (403, 404)
