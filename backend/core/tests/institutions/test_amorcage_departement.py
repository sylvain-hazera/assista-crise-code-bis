"""Amorçage d'un département sous convention départementale (21/11/2026).

L'Annuaire de l'administration n'est jamais appelé ici : on rejoue des enregistrements de la
forme réelle (relevée le 21/11/2026 sur Rive-de-Gier et Saint-Étienne).
"""
import json
from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.amorcage_departement import etape_annuaire, lire_enregistrement
from core.models import (
    AmorcageDepartement, Commune, ContactInstitution, DelegationGestion, Institution, InstitutionType,
    InterlocuteurAlertePCS, Team, User,
)


def _rec(type_service, nom, commune, email="contact@exemple.fr", tel="04 00 00 00 00"):
    return {"fields": {
        "pivot": json.dumps([{"type_service_local": type_service, "code_insee_commune": [commune]}]),
        "nom": nom, "adresse_courriel": email,
        "telephone": json.dumps([{"valeur": tel, "description": ""}]),
        "adresse": json.dumps([{"numero_voie": "Rue de l'Hôtel-de-Ville", "code_postal": "42800", "nom_commune": "Rive-de-Gier"}]),
        "site_internet": json.dumps([{"libelle": "", "valeur": "https://www.exemple.fr/"}]),
    }}


ANNUAIRE = {
    "42186": [_rec("mairie", "Mairie - Rive-de-Gier", "42186"), _rec("police_municipale", "Police municipale - Rive-de-Gier", "42186"),
              _rec("france_travail", "Agence France Travail", "42186")],
    "42218": [_rec("mairie", "Mairie - Saint-Étienne", "42218"), _rec("epci", "Métropole - Saint-Étienne", "42218"),
              _rec("prefecture", "Préfecture - Loire", "42218"), _rec("sdis", "SDIS - Loire", "42218")],
}


def _type(code):
    return InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})[0]


@pytest.fixture
def cg(db):
    Commune.objects.update_or_create(code="42186", defaults={"nom": "Rive-de-Gier", "departement_code": "42", "epci_code": "244200770"})
    Commune.objects.update_or_create(code="42218", defaults={"nom": "Saint-Étienne", "departement_code": "42", "epci_code": "244200770"})
    return Institution.objects.create(nom="Conseil départemental — Loire", type=_type("cg"), commune_code="42218",
                                      departement_code="42", secteur_override="departement")


def test_lecture_d_un_enregistrement_reel():
    fiche = lire_enregistrement(_rec("mairie", "Mairie - Rive-de-Gier", "42186", email="mairie@ville.fr", tel="04 77 83 07 80"))
    assert fiche == {"type": "mairie", "nom": "Mairie - Rive-de-Gier", "email": "mairie@ville.fr",
                     "telephone": "04 77 83 07 80", "adresse": "Rue de l'Hôtel-de-Ville 42800 Rive-de-Gier",
                     "site": "https://www.exemple.fr/", "siret": None}


@pytest.mark.django_db
def test_mairies_epci_et_annuaire_de_crise_sans_doublon(cg):
    existante = Institution.objects.create(nom="Mairie de Rive-de-Gier", type=_type("mairie"), commune_code="42186")
    for _ in range(2):  # relancer ne crée rien de plus
        resultat = etape_annuaire(cg, ["42186", "42218"], interroger=lambda c: ANNUAIRE[c], pause=0)
    assert Institution.objects.filter(type__code__iexact="mairie").count() == 2
    existante.refresh_from_db()
    assert existante.telephone == "04 00 00 00 00"  # complétée, pas recréée
    assert Institution.objects.get(type__code="epci").epci_code == "244200770"
    noms = sorted(i.nom for i in InterlocuteurAlertePCS.objects.filter(institutions=cg))
    assert noms == ["Police municipale - Rive-de-Gier", "Préfecture - Loire", "SDIS - Loire"]
    assert resultat["comptes"]["annuaire_ajoutes"] == 0  # second passage


@pytest.mark.django_db
def test_une_commune_en_panne_n_arrete_pas_le_departement(cg):
    def interroger(code):
        if code == "42186":
            raise TimeoutError("annuaire indisponible")
        return ANNUAIRE[code]
    resultat = etape_annuaire(cg, ["42186", "42218"], interroger=interroger, pause=0)
    assert resultat["comptes"]["echecs"] == 1 and resultat["comptes"]["communes"] == 1
    assert "42186" in resultat["erreurs"][0]


@pytest.mark.django_db
def test_l_amorcage_se_lance_depuis_la_delegation_departementale(cg):
    aasc = Institution.objects.create(nom="Réserve essai", type=_type("aasc"))
    cadre = User.objects.create_user(username="cadre42@test.fr", email="cadre42@test.fr", password="x", type="SECOURS")
    ContactInstitution.objects.create(institution=aasc, utilisateur=cadre, actif=True)
    equipe = Team.objects.create(name="Coordination Loire", institution=aasc, echelon="DEPARTEMENTAL",
                                 territoire_code="42", environment="PROD")
    equipe.membres_encadrement.add(cadre)
    d = DelegationGestion.objects.create(collectivite=cg, aasc=aasc, convention_signee_le="2026-10-01", environment="PROD")
    c = APIClient()
    c.force_authenticate(user=cadre)
    with mock.patch("core.tasks.amorcer_departement_task.delay") as tache:
        with mock.patch("django.db.transaction.on_commit", lambda f: f()):
            r = c.post(reverse("delegationgestion-amorcer", args=[d.id]), {"etapes": ["annuaire", "risques"]}, format="json")
    assert r.status_code == 202, r.data
    assert set(r.data["etapes"]) == {"annuaire", "risques"}
    assert tache.call_args.args[1] == ["annuaire", "risques"]
    assert c.post(reverse("delegationgestion-amorcer", args=[d.id]), {}, format="json").status_code == 409
    assert AmorcageDepartement.objects.count() == 1


def test_la_tache_de_la_simulation_garde_sa_signature():
    """La tâche du chargement départemental l'avait écrasée (même nom)."""
    import inspect
    from core import tasks
    assert list(inspect.signature(tasks.charger_adresses_task.run).parameters)[:2] == ["commune_code", "environment"]
    assert list(inspect.signature(tasks.charger_adresses_departement_task.run).parameters) == ["communes"]


@pytest.mark.django_db
def test_les_simulations_sont_programmees_commune_par_commune(cg):
    from core.amorcage_departement import ESPACEMENT_SIMULATIONS, etape_simulations
    from core.models import TacheSimulationInondation
    with mock.patch("core.tasks.calculer_paliers_task.apply_async") as paliers, \
         mock.patch("core.tasks.calculer_ruissellement_task.apply_async") as ruissellement, \
         mock.patch("core.tasks.charger_adresses_task.apply_async") as adresses:
        resultat = etape_simulations(cg, ["42186", "42218"])
    assert resultat["comptes"]["communes_programmees"] == 2
    assert paliers.call_count == ruissellement.call_count == adresses.call_count == 2
    assert paliers.call_args_list[1].kwargs["countdown"] == ESPACEMENT_SIMULATIONS
    assert TacheSimulationInondation.objects.filter(statut="EN_COURS").count() == 6


@pytest.mark.django_db
def test_le_referentiel_recharge_le_departement(cg):
    from core.amorcage_departement import etape_referentiel
    with mock.patch("django.core.management.call_command") as commande:
        resultat = etape_referentiel(cg, ["42186"])
    commande.assert_called_once_with("import_communes", "42")
    assert resultat["comptes"]["communes_avant"] == 1
