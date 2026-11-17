"""Clôture d'une crise en deux temps : proposée, puis effective sept jours plus tard. Entre les
deux, chacun reçoit un lien pour se faire envoyer son rapport ; les rapports sont gardés
chiffrés, et tout est effacé à la clôture."""
import datetime
import io

import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from core import cloture_crise
from core.models import (
    BienSinistre, ContactInstitution, Crisis, DemandeRapport, Document, Dossier, DossierParticipant, ImplicationInstitution,
    Institution, InstitutionType, RapportConserve, Request, RequestType,
)

COMMUNE = "33529"


def _image() -> bytes:
    from PIL import Image
    tampon = io.BytesIO()
    Image.new("RGB", (320, 240), (90, 90, 90)).save(tampon, format="JPEG")
    return tampon.getvalue()


@pytest.fixture
def monde(db, create_user, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.SERVER_URL = "https://exemple.test"
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie de La Teste", type=itype, commune_code=COMMUNE, commune_nom="La Teste-de-Buch")
    agent = create_user(username="agent-cloture@test.fr", email="agent-cloture@test.fr", type="AUT_LOCALE")
    agent.institution = mairie
    agent.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
    crise = Crisis.objects.create(name="Feu de la Teste", type="INCENDIE", location=Point(-1.14, 44.63, srid=4326))
    ImplicationInstitution.objects.create(crise=crise, institution=mairie, type_implication="ACTEUR", responsable=agent, actif=True)
    rtype, _ = RequestType.objects.get_or_create(type="Aide urgente", defaults={"description": "x"})
    demande = Request.objects.create(title="Maison brûlée", request_type=rtype, first_name_request="Jeanne", last_name_request="Durand",
                                     email_request="Jeanne.Durand@exemple.fr", phone_request="0600000000", commune_code=COMMUNE, crisis=crise)
    dossier = Dossier.objects.create(numero="DOS-FEU-1", crise=crise, demande=demande, titre="Maison brûlée, allée des Pins",
                                     description="Relogement.", statut=Dossier.Statut.EN_COURS)
    benevole = create_user(username="benevole-cloture@test.fr", email="benevole@exemple.fr", type="UTIL_SIMPLE")
    DossierParticipant.objects.create(dossier=dossier, utilisateur=benevole)
    voiture = BienSinistre.objects.create(crise=crise, institution=mairie, commune_code=COMMUNE, designation="Renault Clio grise",
                                          identification="AB-123-CD", statut_evaluation="DETRUITE", nature_degats="FEU",
                                          proprietaire_nom="Paul Martin", proprietaire_email="paul.martin@exemple.fr",
                                          location=Point(-1.14, 44.63, srid=4326))
    client = APIClient()
    client.force_authenticate(user=agent)
    return {"mairie": mairie, "agent": agent, "crise": crise, "dossier": dossier, "voiture": voiture, "client": client}


def _proposer(monde):
    return monde["client"].post(f"/api/crises/{monde['crise'].id}/proposer-fermeture/", {}, format="json")


@pytest.mark.django_db
class TestProposition:
    def test_la_crise_reste_ouverte_sept_jours_et_chacun_recoit_son_lien(self, monde):
        reponse = _proposer(monde)

        assert reponse.status_code == 200, reponse.data
        crise = Crisis.objects.get(pk=monde["crise"].pk)
        assert crise.end_date is None                                   # toujours ouverte
        assert (crise.fermeture_prevue_le - crise.fermeture_proposee_le) == datetime.timedelta(days=7)
        assert reponse.data["personnes_prevenues"] == 3 and reponse.data["courriels_en_echec"] == 0
        # La bénéficiaire, le participant, le propriétaire de la voiture : un courriel chacun, un lien chacun.
        assert sorted(m.to[0] for m in mail.outbox) == ["benevole@exemple.fr", "jeanne.durand@exemple.fr", "paul.martin@exemple.fr"]
        assert DemandeRapport.objects.filter(crise=crise).count() == 3
        courriel = next(m for m in mail.outbox if m.to == ["jeanne.durand@exemple.fr"])
        jeton = DemandeRapport.objects.get(crise=crise, role="BENEFICIAIRE").jeton
        assert f"https://exemple.test/rapport/{jeton}" in courriel.body and "DOS-FEU-1" in courriel.body
        assert "%PDF" not in courriel.body and not courriel.attachments           # un lien, pas la pièce d'office

    def test_ladresse_du_lien_est_chiffree_en_base(self, monde):
        from django.db import connection

        _proposer(monde)
        with connection.cursor() as curseur:
            curseur.execute("SELECT email FROM core_demanderapport")
            en_base = " ".join(ligne[0] for ligne in curseur.fetchall())
        assert "exemple.fr" not in en_base

    def test_une_crise_dessai_ne_se_propose_pas_et_une_seconde_proposition_est_refusee(self, monde):
        Crisis.objects.filter(pk=monde["crise"].pk).update(essai=True)
        refus = _proposer(monde)
        assert refus.status_code == 400 and "essai" in refus.data["error"] and mail.outbox == []

        Crisis.objects.filter(pk=monde["crise"].pk).update(essai=False)
        assert _proposer(monde).status_code == 200
        assert _proposer(monde).status_code == 400

    def test_reservee_a_qui_peut_cloturer_et_annulable(self, monde, create_user):
        autre = create_user(username="autre-cloture@test.fr", email="autre-cloture@test.fr", type="AUT_LOCALE")
        etranger = APIClient()
        etranger.force_authenticate(user=autre)
        assert etranger.post(f"/api/crises/{monde['crise'].id}/proposer-fermeture/", {}, format="json").status_code == 403
        assert APIClient().post(f"/api/crises/{monde['crise'].id}/proposer-fermeture/", {}, format="json").status_code in (401, 403)

        _proposer(monde)
        assert monde["client"].post(f"/api/crises/{monde['crise'].id}/annuler-fermeture/", {}, format="json").status_code == 200
        crise = Crisis.objects.get(pk=monde["crise"].pk)
        assert crise.fermeture_prevue_le is None and crise.end_date is None
        # Ces dates ne s'écrivent pas par une modification ordinaire de la crise.
        monde["client"].patch(f"/api/crises/{crise.id}/", {"fermeture_prevue_le": "2020-01-01T00:00:00Z"}, format="json")
        assert Crisis.objects.get(pk=crise.pk).fermeture_prevue_le is None


@pytest.mark.django_db
class TestRemiseParLien:
    def _jeton(self, monde, role="BENEFICIAIRE"):
        _proposer(monde)
        mail.outbox.clear()
        return DemandeRapport.objects.get(crise=monde["crise"], role=role).jeton

    def test_le_rapport_part_en_piece_jointe_a_ladresse_du_lien_et_a_elle_seule(self, monde):
        jeton = self._jeton(monde)
        anonyme = APIClient()

        avant = anonyme.get(f"/api/rapports/recevoir/{jeton}/")
        assert avant.status_code == 200 and avant.data["rapport"].startswith("Dossier DOS-FEU-1")
        assert avant.data["adresse"].startswith("j") and "jeanne.durand" not in avant.data["adresse"]      # masquée
        envoi = anonyme.post(f"/api/rapports/recevoir/{jeton}/", {"email": "pirate@ailleurs.test"}, format="json")

        assert envoi.status_code == 200 and envoi.data["envoye"] is True
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["jeanne.durand@exemple.fr"]
        nom, contenu, type_mime = mail.outbox[0].attachments[0]
        assert nom == "rapport-dossier-DOS-FEU-1.pdf" and type_mime == "application/pdf" and bytes(contenu).startswith(b"%PDF")
        assert b"%PDF" not in envoi.content                             # le PDF n'est jamais rendu à la page

    def test_le_proprietaire_dun_bien_recoit_le_rapport_de_son_bien(self, monde):
        jeton = self._jeton(monde, role="PROPRIETAIRE")
        reponse = APIClient().post(f"/api/rapports/recevoir/{jeton}/")
        assert reponse.status_code == 200 and "Renault Clio grise" in reponse.data["rapport"]
        assert mail.outbox[0].to == ["paul.martin@exemple.fr"] and mail.outbox[0].attachments[0][0] == "rapport-bien-sinistre.pdf"

    def test_trois_envois_par_jour_puis_le_lien_meurt_avec_la_cloture(self, monde):
        jeton = self._jeton(monde)
        client = APIClient()
        for _ in range(cloture_crise.ENVOIS_MAX_PAR_JOUR):
            assert client.post(f"/api/rapports/recevoir/{jeton}/").status_code == 200
        trop = client.post(f"/api/rapports/recevoir/{jeton}/")
        assert trop.status_code == 410 and "plusieurs fois" in trop.data["error"]
        assert client.get("/api/rapports/recevoir/jeton-invente/").status_code == 410

        cloture_crise.cloturer(Crisis.objects.get(pk=monde["crise"].pk))
        assert client.get(f"/api/rapports/recevoir/{jeton}/").status_code == 410


@pytest.mark.django_db
class TestRapportsGardesJusquaLaCloture:
    def test_chaque_edition_est_gardee_chiffree_et_remplace_la_precedente(self, monde, tmp_path):
        url = f"/api/dossiers/{monde['dossier'].id}/rapport/"
        monde["client"].get(url)
        monde["client"].get(url)

        gardes = RapportConserve.objects.filter(nature="dossier", objet_id=monde["dossier"].id)
        assert gardes.count() == 1                                      # la dernière édition seulement
        rapport = gardes.get()
        assert rapport.crise_id == monde["crise"].id and rapport.edite_par_id == monde["agent"].id and len(rapport.sha256) == 64
        sur_le_disque = (tmp_path / rapport.fichier.name).read_bytes()
        assert not sur_le_disque.startswith(b"%PDF")                    # rien en clair sur le disque
        with rapport.fichier.open("rb") as fichier:
            assert fichier.read().startswith(b"%PDF")                   # relisible par l'application
        assert len(list(tmp_path.rglob("*.pdf"))) == 1                  # l'ancienne édition a quitté le disque

    def test_la_cloture_a_lecheance_efface_rapports_et_liens_et_epargne_les_crises_dessai(self, monde, tmp_path):
        monde["client"].get(f"/api/dossiers/{monde['dossier'].id}/rapport/")
        monde["client"].get(f"/api/crises/{monde['crise'].id}/rapport/")
        _proposer(monde)
        exercice = Crisis.objects.create(name="Exercice", type="INCENDIE", location=Point(-1.14, 44.63, srid=4326), essai=True,
                                         fermeture_prevue_le=timezone.now() - datetime.timedelta(days=1))

        call_command("cloturer_crises_proposees")                       # trop tôt : rien ne bouge
        assert Crisis.objects.get(pk=monde["crise"].pk).end_date is None and RapportConserve.objects.count() == 2

        Crisis.objects.filter(pk=monde["crise"].pk).update(fermeture_prevue_le=timezone.now() - datetime.timedelta(minutes=1))
        call_command("cloturer_crises_proposees", "--dry-run")
        assert Crisis.objects.get(pk=monde["crise"].pk).end_date is None
        call_command("cloturer_crises_proposees")

        assert Crisis.objects.get(pk=monde["crise"].pk).end_date is not None
        assert RapportConserve.objects.count() == 0 and DemandeRapport.objects.count() == 0
        assert list(tmp_path.rglob("*.pdf")) == []                      # les fichiers aussi
        assert Crisis.objects.get(pk=exercice.pk).end_date is None      # jamais une crise d'essai

    def test_la_cloture_immediate_efface_aussi(self, monde):
        monde["client"].get(f"/api/dossiers/{monde['dossier'].id}/rapport/")
        assert monde["client"].post(f"/api/crises/{monde['crise'].id}/cloturer/", {}, format="json").status_code == 200
        assert RapportConserve.objects.count() == 0


@pytest.mark.django_db
class TestBiensSinistres:
    def test_on_releve_une_voiture_brulee_avec_sa_position_et_ses_photos(self, monde):
        client = monde["client"]
        from unittest.mock import patch
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            cree = client.post("/api/biens-sinistres/", {
                "crise": str(monde["crise"].id), "type_bien": "VEHICULE", "designation": "Peugeot 208 blanche", "identification": "EF-456-GH",
                "description": "Calcinée, devant le n° 14.", "statut_evaluation": "DETRUITE", "latitude": 44.6301, "longitude": -1.1402},
                format="json")

        assert cree.status_code == 201, cree.data
        assert cree.data["latitude"] == 44.6301 and cree.data["nature_degats"] == "FEU"      # proposée d'après la crise
        bien = BienSinistre.objects.get(pk=cree.data["id"])
        assert bien.institution_id == monde["mairie"].id and bien.commune_code == COMMUNE and bien.cree_par_id == monde["agent"].id
        photo = client.post("/api/documents/", {"bien": str(bien.id), "fichier": SimpleUploadedFile("avant.jpg", _image(), content_type="image/jpeg")},
                            format="multipart")
        assert photo.status_code == 201, photo.data
        assert client.get("/api/biens-sinistres/", {"crise": str(monde["crise"].id)}).data[0]["nb_photos"] in (0, 1)
        assert Document.objects.filter(bien=bien).count() == 1

    def test_limmatriculation_et_le_proprietaire_sont_chiffres_en_base(self, monde):
        from django.db import connection
        with connection.cursor() as curseur:
            curseur.execute("SELECT identification, proprietaire_nom, proprietaire_email FROM core_biensinistre")
            en_base = " ".join(str(v) for v in curseur.fetchone())
        assert "AB-123-CD" not in en_base and "Martin" not in en_base and "exemple.fr" not in en_base

    def test_le_rapport_sedite_et_part_au_proprietaire_a_son_adresse(self, monde):
        client, voiture = monde["client"], monde["voiture"]
        Document.objects.create(bien=voiture, auteur=monde["agent"], fichier=SimpleUploadedFile("vue.jpg", _image(), content_type="image/jpeg"))

        pdf = client.get(f"/api/biens-sinistres/{voiture.id}/rapport/")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert RapportConserve.objects.filter(nature="bien", objet_id=voiture.id).count() == 1
        envoi = client.post(f"/api/biens-sinistres/{voiture.id}/envoyer-au-proprietaire/", {}, format="json")

        assert envoi.status_code == 200 and envoi.data["envoye_a"].startswith("p") and "paul.martin" not in envoi.data["envoye_a"]
        assert mail.outbox[-1].to == ["paul.martin@exemple.fr"] and bytes(mail.outbox[-1].attachments[0][1]).startswith(b"%PDF")
        assert BienSinistre.objects.get(pk=voiture.pk).rapport_envoye_le is not None
        BienSinistre.objects.filter(pk=voiture.pk).update(proprietaire_email="")
        assert client.post(f"/api/biens-sinistres/{voiture.id}/envoyer-au-proprietaire/", {}, format="json").status_code == 400

    def test_reserve_aux_acteurs_institutionnels_et_a_sa_collectivite(self, monde, create_user):
        voiture = monde["voiture"]
        habitant = APIClient()
        habitant.force_authenticate(user=create_user(username="habitant-bien@test.fr", email="habitant-bien@test.fr", type="UTIL_SIMPLE"))
        assert habitant.get("/api/biens-sinistres/").status_code == 403
        itype = InstitutionType.objects.get(code="MAIRIE")
        voisine = Institution.objects.create(nom="Mairie voisine", type=itype, commune_code="33199")
        agent_voisin = create_user(username="voisin-bien@test.fr", email="voisin-bien@test.fr", type="AUT_LOCALE")
        agent_voisin.institution = voisine
        agent_voisin.save()
        ContactInstitution.objects.create(institution=voisine, utilisateur=agent_voisin, actif=True)
        voisin = APIClient()
        voisin.force_authenticate(user=agent_voisin)
        assert voisin.get("/api/biens-sinistres/").data == []
        assert voisin.get(f"/api/biens-sinistres/{voiture.id}/rapport/").status_code == 404
        assert monde["client"].get("/api/biens-sinistres/").data[0]["designation"] == "Renault Clio grise"

    def test_on_najoute_pas_de_bien_a_une_crise_close(self, monde):
        Crisis.objects.filter(pk=monde["crise"].pk).update(end_date=timezone.now())
        refus = monde["client"].post("/api/biens-sinistres/", {"crise": str(monde["crise"].id), "designation": "Barque"}, format="json")
        assert refus.status_code == 400 and "close" in str(refus.data)
