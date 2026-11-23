"""Cellule de crise dans le pilotage : décisions, actions, relève (23/11/2026)."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    ActionCellule, AuditLog, ContactInstitution, Crisis, DecisionCellule, ImplicationInstitution, Institution,
    InstitutionType, ReleveCellule, User,
)


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def cellule(db):
    t, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie Cellule", type=t)
    ailleurs = Institution.objects.create(nom="Mairie Ailleurs", type=t)
    crise = Crisis.objects.create(name="Crue cellule", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    ImplicationInstitution.objects.create(crise=crise, institution=mairie, type_implication="ACTEUR")
    comptes = {}
    for nom, inst in (("maire", mairie), ("adjoint", mairie), ("autre", ailleurs)):
        u = User.objects.create_user(username=f"{nom}-cel@test.fr", email=f"{nom}-cel@test.fr", password="x", type="AUT_LOCALE",
                                     first_name=nom.capitalize(), last_name="Test")
        u.institution = inst
        u.save()
        ContactInstitution.objects.create(institution=inst, utilisateur=u, actif=True)
        comptes[nom] = u
    return {"crise": crise, "mairie": mairie, **comptes}


@pytest.mark.django_db
class TestDecisionsEtActions:
    def test_une_decision_et_ses_actions_chiffrees_et_journalisees(self, cellule):
        r = _client(cellule["maire"]).post(reverse("cellule-decision-list"), {
            "crise": str(cellule["crise"].id), "texte": "Évacuer la rue des Saules",
            "actions": [{"intitule": "Ouvrir le gymnase", "responsable": str(cellule["adjoint"].id),
                         "echeance": (timezone.now() - datetime.timedelta(hours=1)).isoformat()},
                        {"intitule": "Prévenir le SDIS", "responsable_libre": "SDIS 42"}],
        }, format="json")
        assert r.status_code == 201, r.data
        assert len(r.data["actions"]) == 2
        en_retard = next(a for a in r.data["actions"] if a["intitule"] == "Ouvrir le gymnase")
        assert en_retard["en_retard"] and en_retard["responsable_nom"] == "Adjoint Test"
        assert DecisionCellule.objects.get().texte == "Évacuer la rue des Saules"
        assert AuditLog.objects.filter(objet_type="DecisionCellule").exists()
        # Le texte est chiffré en base.
        from django.db import connection
        with connection.cursor() as c:
            c.execute("select texte from core_decisioncellule")
            assert "Saules" not in c.fetchone()[0]

    def test_mes_actions_et_passage_a_fait(self, cellule):
        client = _client(cellule["maire"])
        a = client.post(reverse("cellule-action-list"), {"crise": str(cellule["crise"].id), "intitule": "Commander des sacs",
                                                         "responsable": str(cellule["adjoint"].id)}, format="json").data
        miennes = _client(cellule["adjoint"]).get(reverse("cellule-action-list"), {"crise": str(cellule["crise"].id), "miennes": 1}).data
        assert [x["intitule"] for x in miennes] == ["Commander des sacs"]
        r = _client(cellule["adjoint"]).patch(reverse("cellule-action-detail", args=[a["id"]]), {"statut": "FAIT"}, format="json")
        assert r.status_code == 200 and r.data["faite_le"]

    def test_une_institution_non_impliquee_n_a_pas_de_cellule_sur_la_crise(self, cellule):
        r = _client(cellule["autre"]).get(reverse("cellule-decision-list"), {"crise": str(cellule["crise"].id)})
        assert r.status_code == 403

    def test_un_responsable_d_une_autre_institution_est_refuse(self, cellule):
        r = _client(cellule["maire"]).post(reverse("cellule-action-list"), {
            "crise": str(cellule["crise"].id), "intitule": "x", "responsable": str(cellule["autre"].id)}, format="json")
        assert r.status_code == 400


@pytest.mark.django_db
class TestReleve:
    def test_la_releve_est_preremplie_et_reprise_par_un_autre(self, cellule):
        client = _client(cellule["maire"])
        client.post(reverse("cellule-action-list"), {"crise": str(cellule["crise"].id), "intitule": "Tenir le PC"}, format="json")
        r = client.post(reverse("cellule-releve-list"), {"crise": str(cellule["crise"].id), "points_vigilance": "Crue de nuit"},
                        format="json")
        assert r.status_code == 201, r.data
        assert [a["intitule"] for a in r.data["instantane"]["actions_ouvertes"]] == ["Tenir le PC"]
        releve = r.data["id"]
        assert client.post(reverse("cellule-releve-reprendre", args=[releve])).status_code == 400   # pas soi-même
        r = _client(cellule["adjoint"]).post(reverse("cellule-releve-reprendre", args=[releve]))
        assert r.status_code == 200 and r.data["reprise_par_nom"] == "Adjoint Test"
        assert ReleveCellule.objects.get().points_vigilance == "Crue de nuit"


@pytest.mark.django_db
class TestChronologiePointsRetex:
    def test_la_chronologie_fusionne_jalons_saisis_et_automatiques(self, cellule):
        client = _client(cellule["maire"])
        client.post(reverse("cellule-decision-list"), {"crise": str(cellule["crise"].id), "texte": "Ouvrir le PC"}, format="json")
        r = client.post(reverse("cellule-chronologie-list"), {"crise": str(cellule["crise"].id), "libelle": "Pic de crue"}, format="json")
        assert r.status_code == 201, r.data
        genres = {j["genre"] for j in client.get(reverse("cellule-chronologie-list"), {"crise": str(cellule["crise"].id)}).data}
        assert {"CRISE", "DECISION", "JALON"} <= genres

    def test_cadence_et_point_de_situation_du(self, cellule):
        from unittest import mock
        client = _client(cellule["maire"])
        crise = str(cellule["crise"].id)
        assert client.post(reverse("cellule-point-cadence"), {"crise": crise, "heures": 99}, format="json").status_code == 400
        client.post(reverse("cellule-point-cadence"), {"crise": crise, "heures": 2}, format="json")
        Crisis.objects.filter(pk=cellule["crise"].pk).update(start_date=timezone.now() - datetime.timedelta(hours=3))
        etat = client.get(reverse("cellule-point-list"), {"crise": crise}).data
        assert etat["cadence_h"] == 2 and etat["du"] is True
        with mock.patch("core.geo_lookup.commune_code_from_point", return_value="42186"):
            r = client.post(reverse("cellule-point-list"), {"crise": crise, "texte": "Situation stable"}, format="json")
        assert r.status_code == 201, r.data
        assert "chiffres" in r.data["instantane"]
        assert client.get(reverse("cellule-point-list"), {"crise": crise}).data["du"] is False

    def test_retex_et_delais_sans_donnee_nominative(self, cellule):
        from core.models import Dossier, RetexCrise
        maintenant = timezone.now()
        Dossier.objects.create(numero="D-R1", crise=cellule["crise"], date_affectation=maintenant + datetime.timedelta(minutes=30),
                               date_resolution=maintenant + datetime.timedelta(hours=4))
        client = _client(cellule["maire"])
        crise = str(cellule["crise"].id)
        client.post(reverse("cellule-retex-list"), {"crise": crise, "ce_qui_a_marche": "La radio", "ce_qui_a_manque": "Des sacs"},
                    format="json")
        r = client.get(reverse("cellule-retex-list"), {"crise": crise}).data
        assert r["retex"]["ce_qui_a_marche"] == "La radio"
        assert r["delais"]["dossiers"] == 1 and r["delais"]["creation_affectation"]["nombre"] == 1
        assert RetexCrise.objects.get().ce_qui_a_manque == "Des sacs"
