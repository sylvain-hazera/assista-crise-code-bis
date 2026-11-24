"""Circuit réflexe « feu → points d'eau → binômes → cellule → CODIS » (24/11/2026)."""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    ActionCellule, ActivationPointEau, Crisis, ImplicationInstitution, Institution, InstitutionType,
    InterlocuteurAlertePCS, JalonCrise, LienCodis, MessageConversation, Mission, NotificationAlertePCS,
    PointEauIncendie, StatutImplication, Team,
)

SAINT_ETIENNE = "42218"


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def scene(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_CIRCUIT", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie de Saint-Étienne", type=itype, commune_code=SAINT_ETIENNE)
    feu = Crisis.objects.create(name="Feu du Pilat", type="INCENDIE", location=Point(4.387, 45.44, srid=4326), radius=5)
    ImplicationInstitution.objects.create(crise=feu, institution=mairie, type_implication="ACTEUR", actif=True,
                                          statut=StatutImplication.VALIDEE)
    cellule = create_user(username="cellule-eau@test.fr", email="cellule-eau@test.fr", type="AUT_LOCALE", institution=mairie)
    binome = create_user(username="binome-eau@test.fr", email="binome-eau@test.fr", type="UTIL_SIMPLE")
    autre = create_user(username="autre-eau@test.fr", email="autre-eau@test.fr", type="UTIL_SIMPLE")
    rcsc = Team.objects.create(name="RCSC Saint-Étienne", indicatif="RCSC", institution=mairie)
    rcsc.members.add(binome)
    rcsc.assigned_crises.add(feu)
    maintenant = timezone.now()
    borne = PointEauIncendie.objects.create(source="OSM", ref_source="77", departement_code="42", insee=SAINT_ETIENNE,
                                            type_pei="PI", ref_terrain="BI-12", debit=60, location=Point(4.388, 45.441, srid=4326),
                                            releve_le=maintenant)
    citerne = PointEauIncendie.objects.create(source="SDIS", ref_source="42-9", departement_code="42", insee=SAINT_ETIENNE,
                                              type_pei="CI", volume=120, location=Point(4.39, 45.445, srid=4326), releve_le=maintenant)
    loin = PointEauIncendie.objects.create(source="OSM", ref_source="78", departement_code="42", type_pei="PI",
                                           location=Point(5.5, 45.9, srid=4326), releve_le=maintenant)
    codis = InterlocuteurAlertePCS.objects.create(nom="Officier CODIS", organisme="SDIS 42 — CODIS", categorie="SDIS",
                                                  email="codis42@example.org", telephone="04 77 00 00 00")
    codis.institutions.add(mairie)
    return {"feu": feu, "mairie": mairie, "cellule": cellule, "binome": binome, "autre": autre, "rcsc": rcsc,
            "borne": borne, "citerne": citerne, "loin": loin}


def _activer(scene):
    return _client(scene["cellule"]).post(reverse("circuit-eau-activer"), {"crise": str(scene["feu"].id), "affectations": [
        {"pei": scene["borne"].pk, "equipe": str(scene["rcsc"].id)}, {"pei": scene["citerne"].pk, "equipe": str(scene["rcsc"].id)},
    ]}, format="json")


@pytest.mark.django_db
class TestProposition:
    def test_propose_pour_un_feu_avec_les_points_proches(self, scene):
        reponse = _client(scene["cellule"]).get(reverse("circuit-eau"), {"crise": str(scene["feu"].id)})
        assert reponse.status_code == 200, reponse.data
        assert reponse.data["propose"] is True and reponse.data["peut_piloter"] is True
        refs = [p["ref"] for p in reponse.data["candidats"]]
        assert refs == ["77", "42-9"] and "78" not in refs
        assert [e["indicatif"] for e in reponse.data["equipes"]] == ["RCSC"]

    def test_pas_de_proposition_hors_feu(self, scene):
        scene["feu"].type = "INONDATION"
        scene["feu"].save()
        assert _client(scene["cellule"]).get(reverse("circuit-eau"), {"crise": str(scene["feu"].id)}).data["propose"] is False

    def test_hors_crise_refuse(self, scene):
        assert _client(scene["autre"]).get(reverse("circuit-eau"), {"crise": str(scene["feu"].id)}).status_code == 403


@pytest.mark.django_db
class TestActivation:
    def test_un_clic_missions_et_jalon_puis_idempotent(self, scene):
        reponse = _activer(scene)
        assert reponse.status_code == 201, reponse.data
        assert ActivationPointEau.objects.count() == 2
        mission = ActivationPointEau.objects.get(pei=scene["borne"]).mission
        assert mission.titre.startswith("Pompe au point d'eau Poteau d'incendie n° BI-12")
        assert "Lambert 93 X" in mission.description
        assert list(mission.equipes.all()) == [scene["rcsc"]] and mission.statut == "EN_COURS"
        assert JalonCrise.objects.filter(crise=scene["feu"]).count() == 1
        assert _activer(scene).status_code == 201 and ActivationPointEau.objects.count() == 2
        assert Mission.objects.filter(activations_point_eau__isnull=False).distinct().count() == 2
        etat = _client(scene["cellule"]).get(reverse("circuit-eau"), {"crise": str(scene["feu"].id)}).data
        assert etat["propose"] is False and len(etat["activations"]) == 2
        # La mission porte son point, pour les boutons de l'application.
        missions = _client(scene["binome"]).get(reverse("mission-list")).data
        missions = missions["results"] if isinstance(missions, dict) else missions
        assert {m["point_eau"]["statut"] for m in missions if m.get("point_eau")} == {"DEMANDE"}

    def test_un_intervenant_n_active_pas(self, scene):
        reponse = _client(scene["binome"]).post(reverse("circuit-eau-activer"), {"crise": str(scene["feu"].id), "affectations": [
            {"pei": scene["borne"].pk, "equipe": str(scene["rcsc"].id)}]}, format="json")
        assert reponse.status_code == 403


@pytest.mark.django_db
class TestPointActif:
    def _etat(self, user, activation, etat):
        return _client(user).post(reverse("circuit-eau-etat", args=[activation.id]), {"etat": etat}, format="json")

    def test_actif_previent_cellule_et_codis_puis_accuse_coche_la_tache(self, scene):
        _activer(scene)
        activation = ActivationPointEau.objects.get(pei=scene["borne"])
        assert self._etat(scene["autre"], activation, "ACTIF").status_code == 403
        assert self._etat(scene["binome"], activation, "EN_ROUTE").status_code == 200
        mail.outbox.clear()
        reponse = self._etat(scene["binome"], activation, "ACTIF")
        assert reponse.status_code == 200 and reponse.data["statut"] == "ACTIF"
        # Cellule : message dans sa conversation, jalon.
        textes = [m.texte for m in MessageConversation.objects.filter(conversation__genre="CELLULE")]
        assert any("ACTIF" in t and "RCSC" in t for t in textes)
        assert JalonCrise.objects.filter(crise=scene["feu"]).count() == 2
        # CODIS : email avec la carte en direct et l'accusé, tâche d'appel, lien créé.
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["codis42@example.org"]
        assert "/codis/" in mail.outbox[0].body and "confirmation-pcs" in mail.outbox[0].body
        lien = LienCodis.objects.get(crise=scene["feu"])
        action = ActionCellule.objects.get(crise=scene["feu"])
        assert action.statut == "A_FAIRE" and "477000000" in action.commentaire
        # Rejoué (file de l'application) : rien de plus.
        assert self._etat(scene["binome"], activation, "ACTIF").status_code == 200 and len(mail.outbox) == 1
        # Le point est vert sur la carte.
        points = _client(scene["cellule"]).get(reverse("points-eau"), {"bbox": "4.3,45.4,4.5,45.5"}).data["resultats"]
        assert {p["ref"]: p["actif_crise"] for p in points}["77"] is True
        # Le CODIS accuse réception : la tâche se coche.
        notification = NotificationAlertePCS.objects.get(motif="POINT_EAU")
        jeton = notification.token_confirmation
        accuse = APIClient().post(reverse("accuser_reception_alerte_pcs", args=[jeton]), {"reponse": "PAS_DE_RAPPEL"}, format="json")
        assert accuse.status_code == 200, accuse.data
        action.refresh_from_db()
        assert action.statut == "FAIT"
        # Fermé : retiré, cellule et CODIS prévenus.
        assert self._etat(scene["binome"], activation, "FERME").status_code == 200
        assert len(mail.outbox) == 2 and "FERMÉ" in mail.outbox[1].subject
        activation.refresh_from_db()
        assert activation.mission.statut == "TERMINEE"
        assert lien.revoque_le is None

    def test_transition_impossible(self, scene):
        _activer(scene)
        activation = ActivationPointEau.objects.get(pei=scene["borne"])
        assert self._etat(scene["binome"], activation, "FERME").status_code == 400
        assert self._etat(scene["binome"], activation, "ANNULE").status_code == 403
        assert self._etat(scene["cellule"], activation, "ANNULE").status_code == 200


@pytest.mark.django_db
class TestCarteCodis:
    def test_sans_compte_sans_nom_revocable_jeton_chiffre(self, scene):
        _activer(scene)
        activation = ActivationPointEau.objects.get(pei=scene["borne"])
        _client(scene["binome"]).post(reverse("circuit-eau-etat", args=[activation.id]), {"etat": "ACTIF"}, format="json")
        lien = LienCodis.objects.get(crise=scene["feu"])
        carte = APIClient().get(reverse("carte-codis", args=[lien.jeton]))
        assert carte.status_code == 200 and carte.data["actifs"] == 1
        point = next(p for p in carte.data["points"] if p["statut"] == "ACTIF")
        assert point["indicatif"] == "RCSC" and point["equipe"] is None and point["mission"] is None
        assert "binome" not in str(carte.data) and "cellule" not in str(carte.data)
        with connection.cursor() as curseur:
            curseur.execute("SELECT jeton FROM core_liencodis WHERE id = %s", [lien.id])
            assert lien.jeton not in curseur.fetchone()[0]
        assert APIClient().get(reverse("carte-codis", args=["inconnu"])).status_code == 404
        renouvele = _client(scene["cellule"]).post(reverse("circuit-eau-lien-codis"),
                                                   {"crise": str(scene["feu"].id), "geste": "renouveler"}, format="json")
        assert renouvele.status_code == 200 and lien.jeton not in renouvele.data["lien_codis"]
        assert APIClient().get(reverse("carte-codis", args=[lien.jeton])).status_code == 404
        scene["feu"].end_date = timezone.now()
        scene["feu"].save()
        nouveau = LienCodis.objects.get(crise=scene["feu"], revoque_le__isnull=True)
        assert APIClient().get(reverse("carte-codis", args=[nouveau.jeton])).status_code == 404
