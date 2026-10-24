"""Cellule de crise, « le site apprend » (22/10/2026) : affecter un dossier d'une compétence à
une équipe enregistre que cette équipe prend cette compétence sur la crise, et les dossiers
encore en attente de cette compétence lui sont aussitôt suggérés. Annuler l'apprentissage
retire ces suggestions."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import AffectationCompetence, Competence, Crisis, Dossier, Request, RequestType, Team


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Inondation test apprentissage", type="INONDATION", location=Point(4.5, 45.5, srid=4326))


@pytest.fixture
def nettoyage(db):
    return Competence.objects.create(nom="Nettoyage (test apprentissage)")


@pytest.fixture
def cai(crise):
    equipe = Team.objects.create(name="CAI")
    equipe.assigned_crises.add(crise)
    return equipe


@pytest.fixture
def client_cadre(create_user):
    client = APIClient()
    client.force_authenticate(user=create_user(username="fred-appr@test.fr", email="fred-appr@test.fr", type="ADMIN"))
    return client


def _dossier(crise, competence, numero):
    type_demande, _ = RequestType.objects.get_or_create(type="Nettoyage (test apprentissage)", defaults={"description": ""})
    demande = Request.objects.create(
        title=f"Cave inondée {numero}", location=Point(4.5, 45.5, srid=4326), first_name_request="A",
        last_name_request="B", email_request="a@t.fr", phone_request="0600000000",
        request_type=type_demande, commune_code="42207", crisis=crise,
    )
    return Dossier.objects.create(
        numero=numero, crise=crise, competence=competence, demande=demande, titre=demande.title,
        statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
    )


def _affecter(client, dossier, equipe, apprendre=True):
    reponse = client.post(reverse('dossier-affecter-equipe', args=[dossier.id]),
                          {"equipe": str(equipe.id), "apprendre": apprendre}, format="json")
    assert reponse.status_code == 200, reponse.data
    return reponse.data


@pytest.mark.django_db
class TestApprentissage:

    def test_affecter_apprend_et_suggere_les_dossiers_en_attente(self, client_cadre, crise, nettoyage, cai):
        premier, suivant = _dossier(crise, nettoyage, "DOS-A1"), _dossier(crise, nettoyage, "DOS-A2")

        data = _affecter(client_cadre, premier, cai)

        assert AffectationCompetence.objects.filter(crise=crise, competence=nettoyage, equipe=cai, active=True).exists()
        assert data["apprentissages"][0]["cree"] is True and data["apprentissages"][0]["dossiers_resuggeres"] == 1
        suivant.refresh_from_db()
        assert suivant.equipe_id == cai.id and suivant.statut == Dossier.Statut.EN_ATTENTE_AFFECTATION   # suggéré, pas affecté

    def test_nouveau_dossier_suggere_apres_apprentissage(self, client_cadre, crise, nettoyage, cai):
        _affecter(client_cadre, _dossier(crise, nettoyage, "DOS-B1"), cai)
        from core.views import meilleure_equipe_pour_competence
        nouveau = _dossier(crise, nettoyage, "DOS-B2")
        assert meilleure_equipe_pour_competence(crise, nettoyage, nouveau.demande) == cai

    def test_sans_le_drapeau_rien_n_est_appris(self, client_cadre, crise, nettoyage, cai):
        data = _affecter(client_cadre, _dossier(crise, nettoyage, "DOS-C1"), cai, apprendre=False)
        assert "apprentissages" not in data
        assert not AffectationCompetence.objects.exists()

    def test_dossier_sans_competence_rien_a_apprendre(self, client_cadre, crise, cai):
        data = _affecter(client_cadre, _dossier(crise, None, "DOS-D1"), cai)
        assert data["apprentissages"] == [] and not AffectationCompetence.objects.exists()

    def test_deja_appris_pas_de_doublon(self, client_cadre, crise, nettoyage, cai):
        _affecter(client_cadre, _dossier(crise, nettoyage, "DOS-E1"), cai)
        data = _affecter(client_cadre, _dossier(crise, nettoyage, "DOS-E2"), cai)
        assert data["apprentissages"] == []
        assert AffectationCompetence.objects.count() == 1

    def test_annuler_l_apprentissage_retire_les_suggestions(self, client_cadre, crise, nettoyage, cai):
        premier, suivant = _dossier(crise, nettoyage, "DOS-F1"), _dossier(crise, nettoyage, "DOS-F2")
        appris = _affecter(client_cadre, premier, cai)["apprentissages"][0]

        reponse = client_cadre.delete(reverse('affectationcompetence-detail', args=[appris["id"]]))

        assert reponse.status_code == 204
        suivant.refresh_from_db()
        assert suivant.equipe_id is None
        premier.refresh_from_db()
        assert premier.equipe_id == cai.id and premier.statut == Dossier.Statut.AFFECTE   # affectation faite gardée

    def test_affectation_groupee_apprend_une_fois(self, client_cadre, crise, nettoyage, cai):
        dossiers = [_dossier(crise, nettoyage, f"DOS-G{i}") for i in range(3)]

        reponse = client_cadre.post(reverse('dossier-affecter-equipe-masse'),
                                    {"dossiers": [str(d.id) for d in dossiers], "equipe": str(cai.id), "apprendre": True}, format="json")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["affectes"] == 3 and len(reponse.data["apprentissages"]) == 1
        assert all(Dossier.objects.get(pk=d.pk).statut == Dossier.Statut.AFFECTE for d in dossiers)


@pytest.mark.django_db
class TestAffectationIdempotente:
    """Le wizard de démarrage de crise crée une affectation par compétence cochée et peut être
    rejoué (retour en arrière, double clic, reprise d'une crise déjà démarrée) -- 24/10/2026."""

    def test_creer_deux_fois_la_meme_affectation_ne_cree_pas_de_doublon(self, client_cadre, crise, nettoyage, cai):
        corps = {"crise": str(crise.id), "competence": str(nettoyage.id), "equipe": str(cai.id)}

        premiere = client_cadre.post(reverse('affectationcompetence-list'), corps, format="json")
        seconde = client_cadre.post(reverse('affectationcompetence-list'), corps, format="json")

        assert premiere.status_code == 201 and seconde.status_code == 201
        assert AffectationCompetence.objects.filter(crise=crise, competence=nettoyage, equipe=cai).count() == 1

    def test_recreer_une_affectation_desactivee_la_reactive(self, client_cadre, crise, nettoyage, cai):
        AffectationCompetence.objects.create(crise=crise, competence=nettoyage, equipe=cai, active=False)

        reponse = client_cadre.post(reverse('affectationcompetence-list'),
                                    {"crise": str(crise.id), "competence": str(nettoyage.id), "equipe": str(cai.id)},
                                    format="json")

        assert reponse.status_code == 201
        affectations = AffectationCompetence.objects.filter(crise=crise, competence=nettoyage, equipe=cai)
        assert affectations.count() == 1 and affectations.get().active is True

    def test_une_affectation_creee_rend_la_suggestion_possible(self, client_cadre, crise, nettoyage, cai):
        dossier = _dossier(crise, nettoyage, "DOS-W1")

        client_cadre.post(reverse('affectationcompetence-list'),
                          {"crise": str(crise.id), "competence": str(nettoyage.id), "equipe": str(cai.id)},
                          format="json")

        dossier.refresh_from_db()
        assert dossier.equipe_id == cai.id        # suggérée sans intervention humaine
