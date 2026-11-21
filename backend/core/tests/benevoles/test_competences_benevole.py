"""Compétences d'un membre de l'association (21/11/2026).

Avant : un membre n'avait nulle part où dire ce qu'il sait faire. Sa ressource (l'offre
« Bénévolat » interne, sur laquelle tournent les campagnes et la constitution d'équipe) n'avait
aucune compétence, et une campagne filtrée sur « Pompage » ne trouvait aucun membre.

Désormais : le même arbre que « Proposer mon aide » (catalogue Competence), saisi sur la fiche
de bénévole, recopié sur la ressource de chaque association, et repris à l'import."""
import pytest
from rest_framework.test import APIClient

from core.fiches_benevoles import TYPE_OFFRE_BENEVOLE
from core.imports import importer_benevoles_association
from core.models import (
    Competence, ContactInstitution, FicheBenevole, Institution, InstitutionType, Offer, User,
)

URL_FICHE = "/api/ma-fiche-benevole/"


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="Association compétences", type=itype)


@pytest.fixture
def arbre(db):
    technique = Competence.objects.create(nom="Technique (test)")
    pompage = Competence.objects.create(nom="Pompage (test)", parent=technique)
    retiree = Competence.objects.create(nom="Ancienne compétence (test)", active=False)
    return technique, pompage, retiree


@pytest.fixture
def benevole(db, asso):
    u = User.objects.create_user(username="comp@essai.invalide", email="comp@essai.invalide", password=None,
                                 first_name="Lina", last_name="Roux", type="UTIL_SIMPLE", enabled=True, is_active=True)
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True)
    return u


def _ressource(u, asso):
    return Offer.objects.get(author=u, institution=asso, offer_type__type=TYPE_OFFRE_BENEVOLE)


@pytest.mark.django_db
class TestCompetencesSurLaFiche:

    def test_le_membre_declare_ses_competences_et_sa_ressource_les_porte(self, benevole, asso, arbre):
        technique, pompage, _ = arbre
        client = APIClient(); client.force_authenticate(user=benevole)
        r = client.patch(URL_FICHE, {"competences": [str(technique.id), str(pompage.id)]}, format="json")
        assert r.status_code == 200, r.data
        assert set(r.data["competences_libelles"]) == {"Technique (test)", "Pompage (test)"}
        assert set(_ressource(benevole, asso).competences.all()) == {technique, pompage}

        # Retirer une compétence la retire aussi de la ressource : le ciblage lit la ressource.
        client.patch(URL_FICHE, {"competences": [str(pompage.id)]}, format="json")
        assert list(_ressource(benevole, asso).competences.all()) == [pompage]

    def test_une_competence_desactivee_ne_se_choisit_pas(self, benevole, arbre):
        _, _, retiree = arbre
        client = APIClient(); client.force_authenticate(user=benevole)
        r = client.patch(URL_FICHE, {"competences": [str(retiree.id)]}, format="json")
        assert r.status_code == 400

    def test_une_campagne_sur_une_competence_trouve_le_membre(self, benevole, asso, arbre):
        from core.ciblage_benevoles import _filtre_competences, ressources_de_l_institution
        _, pompage, _ = arbre
        client = APIClient(); client.force_authenticate(user=benevole)
        client.patch(URL_FICHE, {"competences": [str(pompage.id)]}, format="json")
        ContactInstitution.objects.filter(utilisateur=benevole).update(statut=ContactInstitution.StatutMembre.ACTIF)
        trouves = _filtre_competences(ressources_de_l_institution(asso, _ressource(benevole, asso).environment), [pompage])
        assert [o.author_id for o in trouves] == [benevole.id]


@pytest.mark.django_db
class TestCompetencesALImport:

    def test_la_colonne_competences_est_reprise_et_l_inconnu_signale(self, rf, monkeypatch, asso, arbre):
        from django.contrib.auth.models import AnonymousUser
        monkeypatch.setattr("core.imports._geocoder_adresse", lambda adresse: (None, None, None, None))
        _, pompage, _ = arbre
        requete = rf.post("/api/x/"); requete.user = AnonymousUser()
        ligne = {"EMAIL": "importe@essai.invalide", "NOM": "Durand", "PRENOM": "Paul", "CODE_POSTAL": "33950",
                 "COMP": "pompage (TEST) ; Plongée sous-marine"}
        resultat = importer_benevoles_association(
            requete, asso, [ligne], {"email": "EMAIL", "nom": "NOM", "prenom": "PRENOM",
                                     "code_postal": "CODE_POSTAL", "competences": "COMP"}, inviter=False)
        u = User.objects.get(email_bidx=__import__("core.crypto_fields", fromlist=["blind_index"]).blind_index("importe@essai.invalide"))
        assert list(FicheBenevole.objects.get(utilisateur=u).competences.all()) == [pompage]
        assert list(_ressource(u, asso).competences.all()) == [pompage]
        messages = " ".join(e["message"] for e in resultat["erreurs"])
        assert "Plongée sous-marine" in messages
        assert not Competence.objects.filter(nom__icontains="Plongée").exists()
