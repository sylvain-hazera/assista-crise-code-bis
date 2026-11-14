"""Commenter un dossier et y verser une photo depuis le terrain.

Demande de Sylvain du 14/11/2026 : l'intervenant doit pouvoir laisser des commentaires et des
photos prises avec son téléphone, dans le circuit de traçabilité existant (empreinte du
fichier, position lue dans la photo, journal). Ce que ces tests verrouillent :

1. **Celui qui est devant la maison peut photographier**, même entré dans l'équipe après
   l'affectation du dossier — la liste des participants, elle, est figée à l'affectation.
2. **La trace est complète** : empreinte SHA-256 des octets reçus, position rendue à l'équipe,
   ligne d'historique.
3. **La position reste une donnée sensible** : rien pour qui n'est ni de l'équipe ni
   participant.
"""
import hashlib
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from core.models import Crisis, Document, Dossier, DossierCommentaire, DossierHistorique, Team


def _photo_geolocalisee():
    """Un JPEG portant sa position, comme l'application en produit."""
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (44.0, 50.0, 24.0), 3: "W", 4: (0.0, 34.0, 12.0)}
    tampon = BytesIO()
    Image.new("RGB", (32, 24), (40, 90, 160)).save(tampon, "JPEG", exif=exif)
    return tampon.getvalue()


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def terrain(db, create_user, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    crise = Crisis.objects.create(name="Crue terrain", type="INCENDIE", location="POINT (5.72 45.18)")
    equipe = Team.objects.create(name="Pompage", description="", color="#3b82f6")
    dossier = Dossier.objects.create(numero="DOS-TERRAIN", crise=crise, equipe=equipe,
                                     titre="Cave inondée", statut=Dossier.Statut.AFFECTE)
    # Entré dans l'équipe APRÈS l'affectation : il n'est pas dans les participants.
    arrive_apres = create_user(username="apres@terrain.test", email="apres@terrain.test", type="UTIL_SIMPLE")
    equipe.members.add(arrive_apres)
    etranger = create_user(username="etranger@terrain.test", email="etranger@terrain.test", type="UTIL_SIMPLE")
    return dossier, arrive_apres, etranger


@pytest.mark.django_db
class TestPhotoDeTerrain:

    def _deposer(self, utilisateur, dossier, octets):
        return _client(utilisateur).post("/api/documents/", {
            "fichier": SimpleUploadedFile("photo.jpg", octets, content_type="image/jpeg"),
            "dossier": str(dossier.id), "commentaire": "Niveau d'eau à 40 cm",
        }, format="multipart")

    def test_un_membre_arrive_apres_l_affectation_peut_photographier(self, terrain):
        dossier, membre, _ = terrain

        reponse = self._deposer(membre, dossier, _photo_geolocalisee())

        assert reponse.status_code == 201, reponse.data

    def test_la_trace_est_complete(self, terrain):
        dossier, membre, _ = terrain
        octets = _photo_geolocalisee()

        reponse = self._deposer(membre, dossier, octets)

        # L'empreinte est celle des octets envoyés : le téléphone la compare à la sienne.
        assert reponse.data["sha256"] == hashlib.sha256(octets).hexdigest()
        assert reponse.data["latitude"] == pytest.approx(44.84, abs=0.001)
        assert reponse.data["longitude"] == pytest.approx(-0.57, abs=0.001)
        assert DossierHistorique.objects.filter(
            dossier=dossier, auteur=membre, evenement="Document ajouté").exists()

    def test_la_position_n_est_pas_dans_les_metadonnees_publiques(self, terrain):
        dossier, membre, _ = terrain
        self._deposer(membre, dossier, _photo_geolocalisee())

        document = Document.objects.get(dossier=dossier)

        assert "GPSLatitude" in document.metadata_privees
        assert not any("GPS" in str(cle) for cle in document.metadata_publiques)

    def test_un_etranger_ne_depose_ni_ne_lit(self, terrain):
        dossier, membre, etranger = terrain
        self._deposer(membre, dossier, _photo_geolocalisee())

        assert self._deposer(etranger, dossier, _photo_geolocalisee()).status_code == 403
        assert _client(etranger).get(f"/api/documents/?dossier={dossier.id}").data == []

    def test_l_equipe_lit_les_photos_du_dossier_avec_leur_position(self, terrain, create_user):
        dossier, membre, _ = terrain
        self._deposer(membre, dossier, _photo_geolocalisee())
        collegue = create_user(username="collegue@terrain.test", email="collegue@terrain.test", type="UTIL_SIMPLE")
        dossier.equipe.members.add(collegue)

        documents = _client(collegue).get(f"/api/documents/?dossier={dossier.id}").data

        assert len(documents) == 1
        assert documents[0]["latitude"] == pytest.approx(44.84, abs=0.001)


@pytest.mark.django_db
class TestCommentaireDeTerrain:

    def test_un_membre_arrive_apres_peut_commenter_et_c_est_au_journal(self, terrain):
        dossier, membre, _ = terrain

        reponse = _client(membre).post("/api/dossier-commentaires/", {
            "dossier": str(dossier.id), "commentaire": "Pompe en place, deux heures de travail."}, format="json")

        assert reponse.status_code == 201, reponse.data
        assert DossierHistorique.objects.filter(
            dossier=dossier, auteur=membre, evenement="Commentaire ajouté").exists()

    def test_un_etranger_ne_commente_pas(self, terrain):
        dossier, _, etranger = terrain

        reponse = _client(etranger).post("/api/dossier-commentaires/", {
            "dossier": str(dossier.id), "commentaire": "Bonjour"}, format="json")

        assert reponse.status_code == 403

    def test_le_fil_d_un_dossier_ne_rend_que_ce_dossier(self, terrain):
        dossier, membre, _ = terrain
        autre = Dossier.objects.create(numero="DOS-AUTRE", crise=dossier.crise, equipe=dossier.equipe,
                                       titre="Autre", statut=Dossier.Statut.AFFECTE)
        DossierCommentaire.objects.create(dossier=dossier, auteur=membre, commentaire="ici")
        DossierCommentaire.objects.create(dossier=autre, auteur=membre, commentaire="ailleurs")

        fil = _client(membre).get(f"/api/dossier-commentaires/?dossier={dossier.id}").data

        assert [c["commentaire"] for c in fil] == ["ici"]
