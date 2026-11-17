"""Formulaires de terrain (17/11/2026) : la collectivité compose, lit et exporte ; une
institution à qui elle a délégué une compétence répond ; personne d'autre ne les voit."""
import json
import uuid

import pytest
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient

from core import formulaires_terrain as ft
from core.models import (
    Competence, ContactInstitution, DelegationCompetence, FormulaireTerrain, Institution,
    InstitutionType, ReponseFormulaireTerrain,
)

QUESTIONS = [
    {"libelle": "Logement habitable ?", "type": "OUI_NON", "obligatoire": True},
    {"libelle": "Nombre de personnes à reloger", "type": "NOMBRE", "min": 1, "max": 30,
     "obligatoire": True, "si": {"cle": "logement_habitable", "valeur": False}},
    {"libelle": "Dégâts constatés", "type": "CHOIX_MULTIPLE", "options": ["Toiture", "Eau", "Électricité"]},
    {"libelle": "Remarques", "type": "TEXTE_LONG"},
]


def _compte(create_user, institution, courriel, type_compte):
    user = create_user(username=courriel, email=courriel, type=type_compte)
    user.institution = institution
    user.save()
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie formulaires", type=itype, commune_code="42001")


@pytest.fixture
def association(db):
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="Association formulaires", type=itype)


@pytest.fixture
def agent(create_user, mairie):
    return _compte(create_user, mairie, "agent@form.fr", "AUT_LOCALE")


@pytest.fixture
def benevole(create_user, association):
    return _compte(create_user, association, "benevole@form.fr", "SECOURS")


@pytest.fixture
def formulaire(agent):
    reponse = agent.post(reverse("formulaireterrain-list"),
                         {"titre": "Évaluation des logements", "questions": QUESTIONS}, format="json")
    assert reponse.status_code == 201, reponse.data
    return FormulaireTerrain.objects.get(id=reponse.data["id"])


def _deleguer(mairie, association):
    DelegationCompetence.objects.create(
        institution_source=mairie, institution_cible=association, active=True,
        competence=Competence.objects.get_or_create(nom="Évaluation formulaires")[0],
    )


def _repondre(client, formulaire, donnees, **extra):
    return client.post(reverse("formulaireterrain-repondre", args=[formulaire.id]),
                       {"identifiant_client": str(uuid.uuid4()), "donnees": donnees, **extra}, format="json")


class TestQuestionnaire:

    def test_les_cles_naissent_des_intitules_et_restent_uniques(self):
        propres = ft.nettoyer_questions([
            {"libelle": "Dégâts ?", "type": "OUI_NON"}, {"libelle": "Dégâts ?", "type": "TEXTE"},
            {"libelle": "1er étage touché", "type": "OUI_NON"},
        ])
        assert [q["cle"] for q in propres] == ["degats", "degats_2", "q_1er_etage_touche"]

    @pytest.mark.parametrize("questions, extrait", [
        ([], "au moins une question"),
        ([{"libelle": "", "type": "TEXTE"}], "intitulé"),
        ([{"libelle": "X", "type": "PHOTO"}], "type de question inconnu"),
        ([{"libelle": "X", "type": "CHOIX", "options": ["seul"]}], "au moins deux choix"),
        ([{"libelle": "X", "type": "NOMBRE", "min": 5, "max": 1}], "minimum dépasse"),
        ([{"libelle": "X", "type": "TEXTE", "si": {"cle": "apres", "valeur": True}},
          {"libelle": "Après", "type": "OUI_NON", "cle": "apres"}], "placée avant elle"),
    ])
    def test_un_questionnaire_mal_forme_est_refuse_avec_sa_raison(self, questions, extrait):
        with pytest.raises(ft.ErreurFormulaire, match=extrait):
            ft.nettoyer_questions(questions)

    def test_une_question_masquee_n_est_ni_exigee_ni_gardee(self):
        questions = ft.nettoyer_questions(QUESTIONS)
        # Logement habitable : la question du relogement n'est pas posée, et ce qu'on y aurait
        # répondu est écarté.
        assert ft.nettoyer_reponses(questions, {"logement_habitable": True, "nombre_de_personnes_a_reloger": 4}) == {
            "logement_habitable": True}
        with pytest.raises(ft.ErreurFormulaire, match="attend une réponse"):
            ft.nettoyer_reponses(questions, {"logement_habitable": False})

    @pytest.mark.parametrize("donnees, extrait", [
        ({"logement_habitable": "oui"}, "oui ou non"),
        ({"logement_habitable": False, "nombre_de_personnes_a_reloger": 99}, "au plus 30"),
        ({"logement_habitable": True, "degats_constates": ["Incendie"]}, "choix inconnu"),
        ({"logement_habitable": True, "inventee": 1}, "question inconnue"),
    ])
    def test_une_reponse_fausse_est_refusee_avec_sa_raison(self, donnees, extrait):
        with pytest.raises(ft.ErreurFormulaire, match=extrait):
            ft.nettoyer_reponses(ft.nettoyer_questions(QUESTIONS), donnees)


@pytest.mark.django_db
class TestAcces:

    def test_la_collectivite_compose_et_un_tiers_ne_voit_rien(self, formulaire, benevole, create_user):
        """« Pas visible de tous » : sans délégation, l'association n'en voit aucun."""
        assert benevole.get(reverse("formulaireterrain-list")).data == []
        assert benevole.get(reverse("formulaireterrain-detail", args=[formulaire.id])).status_code == 404
        citoyen = APIClient()
        citoyen.force_authenticate(user=create_user(username="c@form.fr", email="c@form.fr", type="UTIL_SIMPLE"))
        assert citoyen.get(reverse("formulaireterrain-list")).status_code == 403

    def test_une_association_ne_compose_pas(self, benevole):
        reponse = benevole.post(reverse("formulaireterrain-list"),
                                {"titre": "Le mien", "questions": QUESTIONS}, format="json")
        assert reponse.status_code == 403

    def test_le_delegue_repond_et_ne_relit_que_ses_reponses(self, formulaire, agent, benevole, mairie, association):
        _deleguer(mairie, association)
        assert _repondre(agent, formulaire, {"logement_habitable": True}).status_code == 201
        assert _repondre(benevole, formulaire, {"logement_habitable": False,
                                                "nombre_de_personnes_a_reloger": 3}).status_code == 201

        url = reverse("formulaireterrain-reponses", args=[formulaire.id])
        assert len(agent.get(url).data) == 2
        (sienne,) = benevole.get(url).data
        assert sienne["donnees"]["nombre_de_personnes_a_reloger"] == 3
        assert benevole.get(reverse("formulaireterrain-list")).data[0]["nb_reponses"] == 1
        assert benevole.get(reverse("formulaireterrain-export", args=[formulaire.id])).status_code == 403

    def test_un_questionnaire_ferme_disparait_pour_le_delegue(self, formulaire, agent, benevole, mairie, association):
        _deleguer(mairie, association)
        agent.patch(reverse("formulaireterrain-detail", args=[formulaire.id]), {"actif": False}, format="json")
        assert benevole.get(reverse("formulaireterrain-list")).data == []
        assert _repondre(agent, formulaire, {"logement_habitable": True}).status_code == 400


@pytest.mark.django_db
class TestReponses:

    def test_rien_en_clair_en_base(self, formulaire, agent):
        _repondre(agent, formulaire, {"logement_habitable": True, "remarques": "Madame Durand, 3 rue Haute"})
        with connection.cursor() as curseur:
            curseur.execute("SELECT donnees FROM core_reponseformulaireterrain")
            (brut,) = curseur.fetchone()
        assert "Durand" not in brut and "logement" not in brut

    def test_un_renvoi_apres_coupure_ne_cree_pas_de_doublon(self, formulaire, agent):
        corps = {"identifiant_client": str(uuid.uuid4()), "donnees": {"logement_habitable": True}}
        url = reverse("formulaireterrain-repondre", args=[formulaire.id])
        premiere = agent.post(url, corps, format="json")
        seconde = agent.post(url, corps, format="json")
        assert (premiere.status_code, seconde.status_code) == (201, 200)
        assert seconde.data == {"id": premiere.data["id"], "deja_recue": True}
        assert ReponseFormulaireTerrain.objects.count() == 1

    def test_une_reponse_fausse_n_est_pas_rangee(self, formulaire, agent):
        reponse = _repondre(agent, formulaire, {"logement_habitable": False})
        assert reponse.status_code == 400
        assert "attend une réponse" in str(reponse.data)
        assert not ReponseFormulaireTerrain.objects.exists()

    def test_les_exports_portent_les_intitules(self, formulaire, agent):
        _repondre(agent, formulaire, {"logement_habitable": False, "nombre_de_personnes_a_reloger": 2,
                                      "degats_constates": ["Eau", "Toiture"]}, latitude=45.4, longitude=4.3)
        _repondre(agent, formulaire, {"logement_habitable": True})

        csv = agent.get(reverse("formulaireterrain-export", args=[formulaire.id])).content.decode("utf-8")
        assert "Logement habitable ?" in csv.splitlines()[0]
        assert "Toiture ; Eau" in csv and ";non;2;" in csv

        geojson = json.loads(agent.get(
            reverse("formulaireterrain-export", args=[formulaire.id]), {"type": "geojson"}).content)
        (point,) = geojson["features"]                      # seule la réponse située
        assert point["geometry"]["coordinates"] == [4.3, 45.4]
        assert point["properties"]["Nombre de personnes à reloger"] == "2"

    def test_on_ne_retire_pas_une_question_deja_repondue(self, formulaire, agent):
        _repondre(agent, formulaire, {"logement_habitable": True})
        url = reverse("formulaireterrain-detail", args=[formulaire.id])
        assert agent.patch(url, {"questions": formulaire.questions[1:]}, format="json").status_code == 400
        plus = formulaire.questions + [{"libelle": "Animaux ?", "type": "OUI_NON"}]
        assert agent.patch(url, {"questions": plus}, format="json").status_code == 200
        assert agent.delete(url).status_code == 400
