"""Rapports en PDF d'un dossier, d'une mission, d'une crise pour une collectivité : faits pour
un assureur, ils reprennent ce qui a été enregistré, les photos en annexe, et ne sont ouverts
qu'à qui voit déjà ce qu'ils contiennent."""
import io

import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from core import rapports_pdf
from core.models import (
    AuditLog, ContactInstitution, Crisis, Document, Dossier, DossierCommentaire, DossierHistorique, Habitation,
    Institution, InstitutionType, JournalCollectivite, Mission, Request, RequestType, StatutEvaluationHabitation, Team,
)

COMMUNE = "42207"


def _image(couleur=(200, 60, 40)) -> bytes:
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (640, 480), couleur).save(tampon, format="JPEG")
    return tampon.getvalue()


@pytest.fixture
def monde(db, create_user, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie des rapports", type=itype, commune_code=COMMUNE, commune_nom="Saint-Chamond")
    agent = create_user(username="agent-rapports@test.fr", email="agent-rapports@test.fr", type="AUT_LOCALE")
    agent.institution = mairie
    agent.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
    crise = Crisis.objects.create(name="Crue du Gier", type="INONDATION", location=Point(4.51, 45.47, srid=4326))
    equipe = Team.objects.create(name="Pompage", description="", color="#3b82f6", institution=mairie)
    mission = Mission.objects.create(titre="Pomper les caves du quartier bas", description="Rue du Gier et impasse du Moulin.",
                                     crise=crise, institution=mairie, statut=Mission.Statut.TERMINEE, date_cloture=timezone.now())
    mission.equipes.add(equipe)
    rtype, _ = RequestType.objects.get_or_create(type="Aide urgente", defaults={"description": "x"})
    demande = Request.objects.create(
        title="Cave inondée", description="Un mètre d'eau dans la cave <chaudière> & compteur.", request_type=rtype,
        first_name_request="Jeanne", last_name_request="Durand", email_request="jeanne@test.fr", phone_request="0600000000",
        commune_code=COMMUNE, crisis=crise, photo=SimpleUploadedFile("cave.jpg", _image(), content_type="image/jpeg"))
    habitation = Habitation.objects.create(
        crise=crise, adresse="3 rue du Gier", commune_code=COMMUNE, commune_nom="Saint-Chamond", parcelle_cadastrale="42207000BK0034",
        statut_evaluation=StatutEvaluationHabitation.DEGATS_FORTS, surface_habitable_totale=90, surface_habitable_impactee=40,
        valeur_estimee=180000, valeur_source="DVF", evalue_par=agent, date_derniere_evaluation=timezone.now())
    dossier = Dossier.objects.create(
        numero="DOS-2026-014", crise=crise, equipe=equipe, mission=mission, demande=demande, habitation=habitation,
        institution_demandeuse=mairie, titre="Cave inondée, 3 rue du Gier", description="Pompage et mise hors d'eau.",
        statut=Dossier.Statut.CLOTURE, date_cloture=timezone.now())
    DossierHistorique.objects.create(dossier=dossier, auteur=agent, evenement="Dossier affecté à l'équipe Pompage")
    DossierCommentaire.objects.create(dossier=dossier, auteur=agent, commentaire="Chaudière hors service, à faire constater.")
    Document.objects.create(dossier=dossier, auteur=agent, commentaire="Niveau d'eau au mur",
                            sha256="ab" * 32, fichier=SimpleUploadedFile("mur.jpg", _image((30, 90, 200)), content_type="image/jpeg"))
    Document.objects.create(dossier=dossier, auteur=agent, fichier=SimpleUploadedFile("casse.jpg", b"pas-une-image", content_type="image/jpeg"))
    JournalCollectivite.objects.create(institution=mairie, crise=crise, auteur=agent, contenu="06 h 40 : le Gier déborde rue du Gier.")
    client = APIClient()
    client.force_authenticate(user=agent)
    return {"mairie": mairie, "agent": agent, "crise": crise, "mission": mission, "dossier": dossier, "client": client}


def nommer(utilisateur):
    return utilisateur.username if utilisateur else ""


@pytest.mark.django_db
class TestRapportDeDossier:
    def test_reprend_la_demande_le_bien_la_chronologie_et_les_photos(self, monde):
        resume = rapports_pdf.dossier_resume(monde["dossier"], nommer)

        assert resume["numero"] == "DOS-2026-014" and resume["clos"] is True and resume["equipe"] == "Pompage"
        assert resume["origine"]["nature"] == "Demande d'aide" and resume["origine"]["demandeur"] == "Jeanne Durand"
        assert resume["bien"]["evaluation"] == "Dégâts forts" and resume["bien"]["parcelle"] == "42207000BK0034"
        assert resume["bien"]["surfaces"] == [("Habitable", 90, 40)]
        assert resume["chronologie"][0][2] == "Dossier affecté à l'équipe Pompage"
        assert resume["observations"][0][2] == "Chaudière hors service, à faire constater."
        # La photo de la demande, puis les deux pièces du dossier (dont une illisible).
        assert [p["legende"] for p in resume["photos"]] == [
            "Photo jointe à la demande", "Pièce déposée sur le dossier — Niveau d'eau au mur", "Pièce déposée sur le dossier"]
        assert resume["photos"][1]["empreinte"] == "ab" * 32

    def test_le_pdf_sedite_meme_avec_une_photo_illisible_et_des_caracteres_speciaux(self, monde):
        resume = rapports_pdf.dossier_resume(monde["dossier"], nommer)

        pdf = rapports_pdf.generer("dossier", resume, edite_par="Agent d'essai")
        sans_photos = rapports_pdf.generer("dossier", {**resume, "photos": []}, edite_par="Agent d'essai")
        vignettes = [rapports_pdf._vignette(photo, 200) for photo in resume["photos"]]

        assert pdf.startswith(b"%PDF") and len(pdf) > len(sans_photos)
        # Les deux vraies photos sont reproduites ; le fichier illisible est écarté sans faire échouer l'édition.
        assert [v is not None for v in vignettes] == [True, True, False]
        assert vignettes[0].drawWidth == 200 and round(vignettes[0].drawHeight) == 150       # proportions gardées

    def test_toutes_les_photos_sur_demande_sinon_un_plafond_annonce(self, monde, monkeypatch):
        resume = rapports_pdf.dossier_resume(monde["dossier"], nommer)
        monkeypatch.setitem(rapports_pdf.MAX_PHOTOS, "dossier", 1)
        posees = []
        vraie = rapports_pdf._vignette
        monkeypatch.setattr(rapports_pdf, "_vignette", lambda photo, largeur: posees.append(photo["legende"]) or vraie(photo, largeur))

        rapports_pdf.generer("dossier", resume, edite_par="Agent")
        assert len(posees) == 1                                    # plafonné par défaut
        posees.clear()
        rapports_pdf.generer("dossier", resume, edite_par="Agent", toutes_les_photos=True)
        assert len(posees) == 3                                    # toutes, y compris celle qui s'avérera illisible

        posees.clear()
        assert monde["client"].get(f"/api/dossiers/{monde['dossier'].id}/rapport/", {"photos": "toutes"}).status_code == 200
        assert len(posees) == 3

    def test_ledition_est_reservee_a_qui_voit_le_dossier_et_inscrite_a_la_main_courante(self, monde, create_user):
        url = f"/api/dossiers/{monde['dossier'].id}/rapport/"

        reponse = monde["client"].get(url)

        assert reponse.status_code == 200 and reponse["Content-Type"] == "application/pdf"
        assert reponse.content.startswith(b"%PDF") and "rapport-dossier-DOS-2026-014" in reponse["Content-Disposition"]
        trace = AuditLog.objects.filter(objet_type="Dossier", action__code="EXPORT").latest("date_action")
        assert "DOS-2026-014" in trace.commentaire and "Durand" not in trace.commentaire
        etranger = APIClient()
        etranger.force_authenticate(user=create_user(username="etranger-rapport@test.fr", email="etranger-rapport@test.fr", type="UTIL_SIMPLE"))
        assert etranger.get(url).status_code in (403, 404)
        assert APIClient().get(url).status_code in (401, 403)


@pytest.mark.django_db
class TestRapportDeMission:
    def test_porte_les_dossiers_en_annexe_et_leurs_photos(self, monde):
        resume = rapports_pdf.mission_resume(monde["mission"], nommer)

        assert resume["close"] is True and resume["equipes"] == ["Pompage"]
        assert [d["numero"] for d in resume["dossiers"]] == ["DOS-2026-014"] and resume["dossiers_omis"] == 0
        assert rapports_pdf.generer("mission", resume, edite_par="Agent").startswith(b"%PDF")

    def test_reserve_aux_acteurs_institutionnels(self, monde, create_user):
        url = f"/api/missions/{monde['mission'].id}/rapport/"
        assert monde["client"].get(url).content.startswith(b"%PDF")
        membre = create_user(username="membre-rapport@test.fr", email="membre-rapport@test.fr", type="UTIL_SIMPLE")
        monde["mission"].equipes.first().members.add(membre)
        client = APIClient()
        client.force_authenticate(user=membre)
        assert client.get(url).status_code == 403

    def test_ouvert_au_chef_de_lequipe_meme_sans_compte_de_collectivite(self, monde, create_user):
        chef = create_user(username="chef-rapport@test.fr", email="chef-rapport@test.fr", type="UTIL_SIMPLE")
        equipe = monde["mission"].equipes.first()
        equipe.leader = chef
        equipe.save()
        client = APIClient()
        client.force_authenticate(user=chef)

        assert client.get(f"/api/missions/{monde['mission'].id}/rapport/").content.startswith(b"%PDF")


@pytest.mark.django_db
class TestRapportDeCrise:
    def test_la_crise_vue_par_la_collectivite(self, monde):
        resume = rapports_pdf.crise_resume(monde["crise"], monde["mairie"], "PROD", nommer)

        chiffres = dict(resume["chiffres"])
        assert chiffres["Demandes d'aide reçues sur la commune"] == 1 and chiffres["Dossiers ouverts"] == 1
        assert chiffres["Missions conduites"] == 1 and chiffres["Habitations évaluées"] == 1
        assert resume["degats"] == [("Dégâts forts", {"nombre": 1, "habitable": 40.0, "annexes": 0.0, "valeur": 180000.0})]
        assert resume["journal"][0][2] == "06 h 40 : le Gier déborde rue du Gier."
        assert resume["missions"][0]["dossiers"][0]["numero"] == "DOS-2026-014" and resume["dossiers_hors_mission"] == []
        assert rapports_pdf.generer("crise", resume, edite_par="Agent").startswith(b"%PDF")

    def test_une_autre_collectivite_ne_voit_que_ce_qui_la_concerne(self, monde):
        itype = InstitutionType.objects.get(code="MAIRIE")
        voisine = Institution.objects.create(nom="Mairie voisine", type=itype, commune_code="42218", commune_nom="Saint-Étienne")

        resume = rapports_pdf.crise_resume(monde["crise"], voisine, "PROD", nommer)

        assert dict(resume["chiffres"])["Dossiers ouverts"] == 0 and resume["journal"] == [] and resume["missions"] == []
        assert rapports_pdf.generer("crise", resume, edite_par="Agent").startswith(b"%PDF")      # un rapport vide reste éditable

    def test_la_consultation_publique_dune_crise_ne_donne_pas_le_rapport(self, monde, create_user):
        url = f"/api/crises/{monde['crise'].id}/rapport/"

        reponse = monde["client"].get(url)
        assert reponse.status_code == 200 and reponse.content.startswith(b"%PDF")
        assert "rapport-crise-42207" in reponse["Content-Disposition"]
        assert APIClient().get(url).status_code in (401, 403)
        habitant = APIClient()
        habitant.force_authenticate(user=create_user(username="habitant-rapport@test.fr", email="habitant-rapport@test.fr", type="UTIL_SIMPLE"))
        assert habitant.get(url).status_code == 403

