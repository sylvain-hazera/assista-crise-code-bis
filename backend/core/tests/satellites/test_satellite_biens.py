"""Évaluation des dégâts hors ligne entre satellite et central (lot F) : biens, constats,
historique et types de bien par la file de synchronisation ; photos par leur propre canal."""
import datetime
import hashlib
import io
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from core import sync_pieces
from core.models import (
    ConstatTerrain, Crisis, Document, EvenementSynchronisation, Habitation, HabitationHistorique, Institution,
    InstitutionType, PieceEnvoyee, Satellite, StatutEnrolementSatellite, TypeBien,
)
from core.sync_outbox import construire_payload

UTC = datetime.timezone.utc


@pytest.fixture
def satellite(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie Biens", type=itype, commune_code="33333")
    compte = create_user(username="sat-biens@service.assista-crise.local", email="sat-biens@service.assista-crise.local",
                         type="UTIL_SIMPLE", institution=mairie)
    return Satellite.objects.create(institution=mairie, nom="Sat biens", profil="FULL",
                                    statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte)


@pytest.fixture
def feu(db):
    return Crisis.objects.create(name="Feu du Porge", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326))


def _client(satellite):
    client = APIClient()
    client.force_authenticate(user=satellite.compte_service)
    return client


@pytest.mark.django_db
class TestTypesDeBien:
    def test_le_meme_identifiant_partout(self):
        vehicule = TypeBien.objects.get(cle="vehicule")
        assert vehicule.id == TypeBien.id_de("vehicule")                       # celui de la migration
        libre = TypeBien.objects.create(nom="Camping-car")
        assert libre.id == TypeBien.id_de("camping-car")                       # un texte libre aussi


@pytest.mark.django_db
class TestMontee:
    def test_le_satellite_note_bien_constat_et_historique_dans_la_file(self, settings, feu):
        settings.INSTANCE_SATELLITE_LOCALE = True
        bien = Habitation.objects.create(crise=feu, adresse="Véhicule — parking", commune_code="33333",
                                         location=Point(-1.205, 44.871, srid=4326), type_bien=TypeBien.objects.get(cle="vehicule"),
                                         dangers=["GAZ"], statut_evaluation="DETRUITE")
        HabitationHistorique.objects.create(habitation=bien, evenement="Point ajouté sur le terrain")
        ConstatTerrain.objects.create(id=uuid.uuid4(), crise=feu, habitation=bien, statut_evaluation="DETRUITE",
                                      constate_le=datetime.datetime(2026, 11, 20, 9, tzinfo=UTC), nouveau_bien=True)
        modeles = list(EvenementSynchronisation.objects.order_by("cree_le").values_list("modele", flat=True))
        assert modeles == ["Habitation", "HabitationHistorique", "ConstatTerrain"]
        payload = EvenementSynchronisation.objects.get(modele="Habitation").payload
        assert '"Point"' in payload["location"] and payload["dangers"] == ["GAZ"]
        assert payload["type_bien_id"] == str(TypeBien.id_de("vehicule"))

    def test_le_central_recree_le_bien_et_son_constat(self, satellite, feu):
        bien = Habitation(id=uuid.uuid4(), crise=feu, adresse="Véhicule — parking", commune_code="33333",
                          location=Point(-1.205, 44.871, srid=4326), type_bien=TypeBien.objects.get(cle="vehicule"),
                          statut_evaluation="DETRUITE", valeur_estimee="1500.00")
        constat = ConstatTerrain(id=uuid.uuid4(), crise=feu, habitation_id=bien.id, statut_evaluation="DETRUITE",
                                 constate_le=datetime.datetime(2026, 11, 20, 9, tzinfo=UTC), nouveau_bien=True)
        evenements = [
            {"id": str(uuid.uuid4()), "modele": "Habitation", "objet_id": str(bien.id), "action": "CREATION",
             "payload": construire_payload(bien, "Habitation"), "version_de_base": None},
            {"id": str(uuid.uuid4()), "modele": "ConstatTerrain", "objet_id": str(constat.id), "action": "CREATION",
             "payload": construire_payload(constat, "ConstatTerrain"), "version_de_base": None},
            {"id": str(uuid.uuid4()), "modele": "TypeBien", "objet_id": str(TypeBien.id_de("vehicule")), "action": "CREATION",
             "payload": {"nom": "Véhicule", "cle": "vehicule", "a_une_adresse": False, "ordre": 50, "actif": True},
             "version_de_base": None},
        ]
        r = _client(satellite).post(f"/api/satellites/{satellite.id}/synchroniser/", {"evenements": evenements}, format="json")
        assert [x["resultat"] for x in r.data["resultats"]] == ["applique", "applique", "deja_applique"], r.data
        recu = Habitation.objects.get(pk=bien.id)
        assert round(recu.location.x, 3) == -1.205 and recu.type_bien.cle == "vehicule" and str(recu.valeur_estimee) == "1500.00"
        assert ConstatTerrain.objects.get(pk=constat.id).habitation_id == bien.id


@pytest.mark.django_db
class TestDescente:
    def test_les_biens_des_crises_et_les_types_descendent(self, satellite, feu, monkeypatch):
        from core import views

        monkeypatch.setattr(views, "filter_queryset_to_viewer_zone", lambda request, qs, **k: qs)
        Habitation.objects.create(crise=feu, adresse="1 Rue des Pins", commune_code="33333",
                                  location=Point(-1.2, 44.87, srid=4326), statut_evaluation="DEGATS_FORTS")
        donnees = _client(satellite).get(f"/api/satellites/{satellite.id}/donnees/").data
        assert [h["adresse"] for h in donnees["habitations"]] == ["1 Rue des Pins"]
        assert "vehicule" in {t["cle"] for t in donnees["types_bien"]}

    def test_le_satellite_applique_un_bien_et_sa_position(self, feu):
        from django.apps import apps

        from core.management.commands.synchroniser_entrant import appliquer_objet_mutable

        bien = Habitation.objects.create(crise=feu, adresse="1 Rue des Pins", commune_code="33333",
                                         location=Point(-1.2, 44.87, srid=4326))
        item = {**construire_payload(bien, "Habitation"), "id": str(bien.id),
                "modifie_le": datetime.datetime(2026, 11, 20, 10, tzinfo=UTC).isoformat(), "environment": "PROD"}
        item["location"] = Point(-1.21, 44.88, srid=4326).geojson               # déplacé au central
        assert appliquer_objet_mutable(apps.get_model, "Habitation", item) == "applique"
        bien.refresh_from_db()
        assert round(bien.location.x, 2) == -1.21


@pytest.mark.django_db
class TestPhotos:
    def _photo(self, feu, contenu=b"\xff\xd8photo"):
        bien = Habitation.objects.create(crise=feu, adresse="1 Rue des Pins", commune_code="33333",
                                         location=Point(-1.2, 44.87, srid=4326))
        document = Document(habitation=bien, sha256=hashlib.sha256(contenu).hexdigest(), commentaire="Façade")
        document.fichier.save("constat.jpg", ContentFile(contenu), save=False)
        document.save()
        return bien, document, contenu

    def test_le_central_verifie_l_empreinte_et_ne_double_pas(self, satellite, feu):
        bien, document, contenu = self._photo(feu)
        identifiant = uuid.uuid4()
        url = f"/api/satellites/{satellite.id}/pieces/"
        corps = {"id": str(identifiant), "sha256": hashlib.sha256(contenu).hexdigest(), "habitation": str(bien.id)}
        r = _client(satellite).post(url, {**corps, "fichier": io.BytesIO(contenu)}, format="multipart")
        assert r.status_code == 201, r.data
        recu = Document.objects.get(pk=identifiant)
        assert recu.habitation_id == bien.id and recu.sha256 == corps["sha256"]
        encore = _client(satellite).post(url, {**corps, "fichier": io.BytesIO(contenu)}, format="multipart")
        assert encore.status_code == 200 and encore.data["deja_recue"] is True
        abime = _client(satellite).post(url, {**corps, "id": str(uuid.uuid4()), "fichier": io.BytesIO(b"autre chose")},
                                        format="multipart")
        assert abime.status_code == 400

    def test_un_bien_pas_encore_synchronise_fait_attendre_la_photo(self, satellite, feu):
        contenu = b"\xff\xd8x"
        r = _client(satellite).post(f"/api/satellites/{satellite.id}/pieces/", {
            "id": str(uuid.uuid4()), "sha256": hashlib.sha256(contenu).hexdigest(), "habitation": str(uuid.uuid4()),
            "fichier": io.BytesIO(contenu)}, format="multipart")
        assert r.status_code == 404

    def test_le_satellite_envoie_une_fois(self, feu):
        bien, document, contenu = self._photo(feu)
        envois = []

        def poster(donnees, fichiers):
            envois.append(donnees["id"])
            assert fichiers["fichier"][1] == contenu and donnees["sha256"] == document.sha256
            return 201, {}

        assert sync_pieces.envoyer(poster) == {"envoyees": 1, "en_attente": 0}
        assert PieceEnvoyee.objects.filter(document_id=document.id).exists()
        assert sync_pieces.envoyer(poster) == {"envoyees": 0, "en_attente": 0}
        assert envois == [str(document.id)]

    def test_un_refus_du_central_laisse_la_photo_en_attente(self, feu):
        self._photo(feu)
        assert sync_pieces.envoyer(lambda d, f: (404, {"error": "bien inconnu"})) == {"envoyees": 0, "en_attente": 1}
        assert not PieceEnvoyee.objects.exists()
