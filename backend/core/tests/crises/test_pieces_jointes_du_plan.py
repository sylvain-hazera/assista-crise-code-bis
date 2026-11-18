"""Fichiers joints au plan communal de sauvegarde (18/11/2026).

Demande de Sylvain : « prévoir au niveau des fiches réflexes / fiches de la commune un dépôt de
fichiers PDF, avec la même sécurité que le reste : pas d'accès direct, droits… »"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from rest_framework.test import APIClient

from core.models import AuditLog, ContactInstitution, FonctionPCS, Institution, InstitutionType, PieceJointePCS

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\nPROCEDURE-SIRENE-SECRETE"


def _mairie(create_user, nom, code):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom=nom, type=itype, commune_code=code)
    user = create_user(username=f"{code}@pj.fr", email=f"{code}@pj.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return mairie, client, user


@pytest.fixture
def mairie(create_user):
    return _mairie(create_user, "Mairie des pièces", "42186")


def _deposer(client, **corps):
    return client.post("/api/pcs-pieces/", {"fichier": SimpleUploadedFile("sirene.pdf", PDF, content_type="application/pdf"),
                                            "titre": "Déclenchement de la sirène", **corps}, format="multipart")


@pytest.mark.django_db
class TestDepot:

    def test_la_commune_depose_un_pdf_et_le_relit(self, mairie):
        _, client, _ = mairie
        reponse = _deposer(client)
        assert reponse.status_code == 201, reponse.data
        assert (reponse.data["titre"], reponse.data["nom_fichier"], reponse.data["taille"]) == ("Déclenchement de la sirène", "sirene.pdf", len(PDF))
        assert "fichier" not in reponse.data                       # aucune adresse directe n'est rendue

        lu = client.get(f"/api/pcs-pieces/{reponse.data['id']}/fichier/")
        assert lu.status_code == 200 and b"".join(lu.streaming_content) == PDF
        assert "no-store" in lu["Cache-Control"] and "attachment" in lu["Content-Disposition"]

    def test_le_fichier_est_chiffre_sur_le_disque(self, mairie):
        _deposer(mairie[1])
        piece = PieceJointePCS.objects.get()
        assert piece.fichier.name.startswith("documents/")         # dossier que le serveur web refuse de servir
        with open(piece.fichier.path, "rb") as brut:
            contenu = brut.read()
        assert b"PROCEDURE-SIRENE-SECRETE" not in contenu and b"%PDF" not in contenu

    def test_chaque_telechargement_est_a_la_main_courante(self, mairie):
        _, client, utilisateur = mairie
        identifiant = _deposer(client).data["id"]
        client.get(f"/api/pcs-pieces/{identifiant}/fichier/")
        lignes = AuditLog.objects.filter(objet_type="PieceJointePCS", objet_id=identifiant, utilisateur=utilisateur)
        assert {l.commentaire for l in lignes} >= {"Plan communal de sauvegarde : fichier joint",
                                                    "Plan communal de sauvegarde : fichier joint téléchargé"}

    def test_ce_qui_n_est_ni_pdf_ni_photo_est_refuse(self, mairie):
        reponse = mairie[1].post("/api/pcs-pieces/", {"fichier": SimpleUploadedFile("macro.docm", b"PK\x03\x04pas un pdf")}, format="multipart")
        assert reponse.status_code == 400 and not PieceJointePCS.objects.exists()

    def test_retirer_la_piece_retire_le_fichier(self, mairie):
        import os
        _, client, _ = mairie
        identifiant = _deposer(client).data["id"]
        chemin = PieceJointePCS.objects.get().fichier.path
        assert client.delete(f"/api/pcs-pieces/{identifiant}/").status_code == 204
        assert not os.path.exists(chemin)


@pytest.mark.django_db
class TestDroits:

    def test_une_autre_commune_ne_voit_ni_ne_lit_ni_ne_retire(self, mairie, create_user):
        identifiant = _deposer(mairie[1]).data["id"]
        _, voisine, _ = _mairie(create_user, "Mairie voisine", "42207")
        assert voisine.get("/api/pcs-pieces/").data == []
        assert voisine.get(f"/api/pcs-pieces/{identifiant}/fichier/").status_code == 404
        assert voisine.delete(f"/api/pcs-pieces/{identifiant}/").status_code == 404
        assert PieceJointePCS.objects.count() == 1

    def test_un_particulier_n_y_accede_pas(self, mairie, create_user):
        identifiant = _deposer(mairie[1]).data["id"]
        particulier = APIClient()
        particulier.force_authenticate(user=create_user(username="p@pj.fr", email="p@pj.fr", type="UTIL_SIMPLE"))
        assert particulier.get(f"/api/pcs-pieces/{identifiant}/fichier/").status_code == 403
        assert APIClient().get(f"/api/pcs-pieces/{identifiant}/fichier/").status_code in (401, 403)

    def test_on_ne_rattache_pas_a_la_fiche_d_une_autre_commune(self, mairie, create_user):
        _, voisine, _ = _mairie(create_user, "Mairie voisine", "42207")
        voisine.post("/api/pcs-fonctions/", {"fonction": "DOS"}, format="json")
        fiche_voisine = FonctionPCS.objects.get()
        reponse = _deposer(mairie[1], fonction=str(fiche_voisine.id))
        assert reponse.status_code == 400 and not PieceJointePCS.objects.exists()

    def test_les_pieces_d_une_fiche_reflexe_se_listent_a_part(self, mairie):
        _, client, _ = mairie
        client.post("/api/pcs-fonctions/", {"fonction": "ALERTE"}, format="json")
        fiche = FonctionPCS.objects.get()
        _deposer(client, fonction=str(fiche.id))
        _deposer(client, titre="Plan du gymnase")
        assert [p["titre"] for p in client.get(f"/api/pcs-pieces/?fonction={fiche.id}").data] == ["Déclenchement de la sirène"]
        assert len(client.get("/api/pcs-pieces/").data) == 2
