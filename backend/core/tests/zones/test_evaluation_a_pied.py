"""Évaluation des dégâts à pied, depuis l'application (lot C, core/evaluation_terrain.py) :
tournée, constat idempotent, position replacée, point nouveau avec type de bien extensible,
rapprochement proposé jamais automatique, rapprochement à la main et séparation."""
import datetime
import uuid
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.models import (
    AdresseBAN, ConstatTerrain, Crisis, Dossier, Habitation, HabitationHistorique, Institution, InstitutionType,
    ModuleDegatsCrise, RapprochementBien, TypeBien,
)

COMMUNE = "33333"
UTC = datetime.timezone.utc


@pytest.fixture
def terrain(db, create_user):
    feu = Crisis.objects.create(name="Feu du Porge", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326))
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie du Porge", type=itype, commune_code=COMMUNE, commune_nom="Le Porge")
    ModuleDegatsCrise.objects.create(crise=feu, institution=mairie, actif=True)
    elue = create_user(username="elue-pied@test.fr", email="elue-pied@test.fr", type="AUT_LOCALE")
    elue.institution = mairie
    elue.save()
    association = create_user(username="asso-pied@test.fr", email="asso-pied@test.fr", type="UTIL_SIMPLE")
    for i, (lon, numero) in enumerate(((-1.2000, "1"), (-1.2003, "3"), (-1.2100, "12"))):
        AdresseBAN.objects.create(ban_id=f"33333_0010_0000{i}", commune_code=COMMUNE, commune_nom="Le Porge", code_postal="33680",
                                  numero=numero, voie="Rue des Pins", location=Point(lon, 44.87, srid=4326),
                                  modifie_le=datetime.datetime(2026, 11, 1, tzinfo=UTC))
    clients = {}
    for nom, compte in (("elue", elue), ("autre", association)):
        clients[nom] = APIClient()
        clients[nom].force_authenticate(user=compte)
    return {"feu": feu, "mairie": mairie, **clients}


def _constat(client, crise, **champs):
    corps = {"id": str(uuid.uuid4()), "crise": str(crise.id), "statut_evaluation": "DEGATS_FORTS", **champs}
    with patch("core.views.commune_code_from_point", return_value=COMMUNE):
        return client.post("/api/habitations/constat/", corps, format="json"), corps


@pytest.mark.django_db
class TestTournee:
    def test_les_points_les_plus_proches_d_abord(self, terrain):
        Habitation.objects.create(crise=terrain["feu"], adresse="1 Rue des Pins", commune_code=COMMUNE,
                                  ban_id="33333_0010_00000", location=Point(-1.2000, 44.87, srid=4326), statut_evaluation="DETRUITE")
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            r = terrain["elue"].get("/api/habitations/tournee/", {"crise": str(terrain["feu"].id), "latitude": 44.87,
                                                                  "longitude": -1.2001, "rayon_m": 100})
        assert r.status_code == 200, r.data
        assert [p["ban_id"] for p in r.data["points"]] == ["33333_0010_00000", "33333_0010_00001"]
        assert r.data["points"][0]["statut_evaluation"] == "DETRUITE" and r.data["points"][1]["statut_evaluation"] is None

    def test_reservee_au_personnel_municipal_et_aux_elus(self, terrain):
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            r = terrain["autre"].get("/api/habitations/tournee/", {"crise": str(terrain["feu"].id), "latitude": 44.87, "longitude": -1.2})
        assert r.status_code == 403

    def test_le_refus_dit_la_vraie_raison(self, terrain):
        """23/11/2026 : « réservé aux élus » couvrait tous les cas ; un membre de la réserve
        communale, rattaché à sa mairie, ne savait pas que seul manquait l'activation du module."""
        params = {"crise": str(terrain["feu"].id), "latitude": 44.87, "longitude": -1.2}
        with patch("core.views.commune_code_from_point", return_value="33063"):
            ailleurs = terrain["elue"].get("/api/habitations/tournee/", params)
        assert ailleurs.status_code == 403 and "hors du territoire" in str(ailleurs.data["detail"])
        ModuleDegatsCrise.objects.filter(crise=terrain["feu"]).update(actif=False)
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            sans_module = terrain["elue"].get("/api/habitations/tournee/", params)
        assert sans_module.status_code == 403 and "Activation du module" in str(sans_module.data["detail"])
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            autre = terrain["autre"].get("/api/habitations/tournee/", params)
        assert "comptes d'une mairie" in str(autre.data["detail"])


@pytest.mark.django_db
class TestConstat:
    def test_sur_une_adresse_cree_le_bien_et_un_renvoi_ne_double_rien(self, terrain):
        r, corps = _constat(terrain["elue"], terrain["feu"], ban_id="33333_0010_00001", dangers=["GAZ", "INCONNU"],
                            constate_le="2026-11-20T09:15:00+00:00")
        assert r.status_code == 201, r.data
        bien = Habitation.objects.get()
        assert bien.ban_id == "33333_0010_00001" and bien.adresse == "3 Rue des Pins, 33680 Le Porge"
        assert bien.statut_evaluation == "DEGATS_FORTS" and bien.nature_degats == "FEU" and bien.dangers == ["GAZ"]
        assert ConstatTerrain.objects.get().constate_le == datetime.datetime(2026, 11, 20, 9, 15, tzinfo=UTC)
        # La file du téléphone rejoue le même constat : rien de plus.
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            encore = terrain["elue"].post("/api/habitations/constat/", corps, format="json")
        assert encore.status_code == 200 and encore.data["deja_recu"] is True
        assert Habitation.objects.count() == 1 and ConstatTerrain.objects.count() == 1

    def test_le_point_replace_garde_son_adresse(self, terrain):
        r, _ = _constat(terrain["elue"], terrain["feu"], ban_id="33333_0010_00000", latitude=44.8702, longitude=-1.2004,
                        position_corrigee=True)
        assert r.status_code == 201, r.data
        bien = Habitation.objects.get()
        assert bien.position_corrigee and round(bien.location.y, 4) == 44.8702 and bien.ban_id == "33333_0010_00000"
        assert HabitationHistorique.objects.filter(habitation=bien, evenement__startswith="Position replacée").exists()

    def test_un_point_nouveau_avec_un_type_libre_qui_enrichit_la_liste(self, terrain):
        r, _ = _constat(terrain["elue"], terrain["feu"], latitude=44.871, longitude=-1.205, type_bien_libre="Camping-car",
                        description="isolé sur le parking", statut_evaluation="DETRUITE")
        assert r.status_code == 201, r.data
        bien = Habitation.objects.get()
        assert bien.ban_id is None and bien.type_bien.nom == "Camping-car" and bien.adresse == "Camping-car — isolé sur le parking"
        assert TypeBien.objects.filter(cle="camping-car").count() == 1
        # « camping-car » écrit autrement retrouve la même entrée.
        _constat(terrain["elue"], terrain["feu"], latitude=44.875, longitude=-1.21, type_bien_libre="  CAMPING-CAR ")
        assert TypeBien.objects.filter(cle="camping-car").count() == 1
        assert Dossier.objects.filter(habitation=bien).exists()                # détruit : un dossier

    def test_personne_a_reloger_ouvre_un_dossier(self, terrain):
        _constat(terrain["elue"], terrain["feu"], ban_id="33333_0010_00002", statut_evaluation="DEGATS_FAIBLES", a_reloger=True)
        assert Dossier.objects.filter(habitation__ban_id="33333_0010_00002").exists()

    def test_reserve_au_personnel_municipal_et_aux_elus(self, terrain):
        r, _ = _constat(terrain["autre"], terrain["feu"], ban_id="33333_0010_00001")
        assert r.status_code == 403 and not Habitation.objects.exists()


@pytest.mark.django_db
class TestRapprochement:
    def _voiture(self, terrain, lon, lat=44.871):
        vehicule = TypeBien.objects.get(cle="vehicule")
        r, _ = _constat(terrain["elue"], terrain["feu"], latitude=lat, longitude=lon, type_bien=str(vehicule.id),
                        statut_evaluation="DETRUITE")
        assert r.status_code == 201, r.data
        return r.data

    def test_proche_et_du_meme_type_c_est_propose_jamais_fusionne(self, terrain):
        premiere = self._voiture(terrain, -1.2050)
        seconde = self._voiture(terrain, -1.2053)                              # à 24 m
        assert seconde["rapprochements_proposes"] == 1
        assert Habitation.objects.filter(fusionne_dans__isnull=True).count() == 2   # rien de fusionné d'office
        loin = self._voiture(terrain, -1.2150)
        assert loin["rapprochements_proposes"] == 0
        propose = terrain["elue"].get("/api/rapprochements-biens/", {"crise": str(terrain["feu"].id)}).data
        assert len(propose) == 1 and propose[0]["bien"]["id"] == premiere["id"] and propose[0]["autre"]["id"] == seconde["id"]

    def test_confirmer_rattache_sans_effacer_puis_separer(self, terrain):
        premiere = self._voiture(terrain, -1.2050)
        seconde = self._voiture(terrain, -1.2053)
        rapprochement = RapprochementBien.objects.get()
        r = terrain["elue"].post(f"/api/rapprochements-biens/{rapprochement.id}/confirmer/")
        assert r.status_code == 200, r.data
        assert Habitation.objects.get(pk=seconde["id"]).fusionne_dans_id == uuid.UUID(premiere["id"])
        liste = terrain["elue"].get("/api/habitations/", {"crise": str(terrain["feu"].id)}).data
        identifiants = [h["id"] for h in (liste["results"] if isinstance(liste, dict) else liste)]
        assert premiere["id"] in identifiants and seconde["id"] not in identifiants   # compté une fois
        assert ConstatTerrain.objects.filter(habitation_id=seconde["id"]).exists()   # rien d'effacé
        # Erreur : on sépare.
        r = terrain["elue"].post(f"/api/habitations/{seconde['id']}/separer/")
        assert r.status_code == 200, r.data
        assert Habitation.objects.get(pk=seconde["id"]).fusionne_dans_id is None
        assert RapprochementBien.objects.get().statut == "SEPARE"

    def test_refuser_et_ne_plus_reproposer(self, terrain):
        self._voiture(terrain, -1.2050)
        self._voiture(terrain, -1.2053)
        rapprochement = RapprochementBien.objects.get()
        assert terrain["elue"].post(f"/api/rapprochements-biens/{rapprochement.id}/refuser/").status_code == 200
        assert terrain["elue"].get("/api/rapprochements-biens/", {"crise": str(terrain["feu"].id)}).data == []

    def test_rapprocher_a_la_main(self, terrain):
        un, _ = _constat(terrain["elue"], terrain["feu"], ban_id="33333_0010_00000")
        deux, _ = _constat(terrain["elue"], terrain["feu"], latitude=44.873, longitude=-1.2, description="Garage du 1")
        r = terrain["elue"].post(f"/api/habitations/{un.data['id']}/rapprocher/", {"autre": deux.data["id"]}, format="json")
        assert r.status_code == 200, r.data
        rapprochement = RapprochementBien.objects.get(manuel=True)
        assert rapprochement.statut == "CONFIRME"
        assert Habitation.objects.get(pk=deux.data["id"]).fusionne_dans_id == uuid.UUID(un.data["id"])

    def test_les_types_de_bien_de_depart(self, terrain):
        noms = [t["nom"] for t in terrain["elue"].get("/api/types-bien/").data]
        assert noms[0] == "Logement" and "Véhicule" in noms and noms[-1] == "Autre"


@pytest.mark.django_db
class TestPourLApplication:
    def test_la_photo_vise_le_constat_et_rejoint_le_bien(self, terrain):
        import hashlib
        import io

        from core.models import Document

        r, corps = _constat(terrain["elue"], terrain["feu"], latitude=44.871, longitude=-1.205, description="Grange")
        contenu = b"\xff\xd8\xff\xe0photo"
        photo = terrain["elue"].post("/api/habitations/constat-photo/", {"constat": corps["id"], "commentaire": "Toiture",
                                                                         "fichier": io.BytesIO(contenu)}, format="multipart")
        assert photo.status_code == 201, photo.data
        document = Document.objects.get()
        assert str(document.habitation_id) == r.data["id"] and photo.data["empreinte"] == hashlib.sha256(contenu).hexdigest()
        inconnu = terrain["elue"].post("/api/habitations/constat-photo/", {"constat": str(uuid.uuid4()),
                                                                           "fichier": io.BytesIO(contenu)}, format="multipart")
        assert inconnu.status_code == 404
        etranger = terrain["autre"].post("/api/habitations/constat-photo/", {"constat": corps["id"],
                                                                             "fichier": io.BytesIO(contenu)}, format="multipart")
        assert etranger.status_code == 403

    def test_le_secteur_embarque(self, terrain):
        un, _ = _constat(terrain["elue"], terrain["feu"], ban_id="33333_0010_00000", statut_evaluation="DETRUITE")
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            r = terrain["elue"].get("/api/habitations/secteur/", {"crise": str(terrain["feu"].id), "latitude": 44.87,
                                                                  "longitude": -1.2, "rayon_m": 500})
        assert r.status_code == 200, r.data
        assert {a[0] for a in r.data["adresses"]} == {"33333_0010_00000", "33333_0010_00001"}     # le n° 12 est à 800 m
        assert [b["id"] for b in r.data["biens"]] == [un.data["id"]]
        assert [d["habitation"] for d in r.data["dossiers"]] == [un.data["id"]]             # détruit : un dossier ouvert
        assert r.data["cercles"] == [] and r.data["rayon_m"] == 500
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            assert terrain["autre"].get("/api/habitations/secteur/", {"crise": str(terrain["feu"].id), "latitude": 44.87,
                                                                      "longitude": -1.2}).status_code == 403


@pytest.mark.django_db
class TestReevaluer:
    def test_un_bien_sans_adresse_se_reevalue_sans_doublon(self, terrain):
        vehicule = TypeBien.objects.get(cle="vehicule")
        premier, _ = _constat(terrain["elue"], terrain["feu"], latitude=44.871, longitude=-1.205, type_bien=str(vehicule.id),
                              statut_evaluation="DEGATS_FORTS")
        encore, _ = _constat(terrain["elue"], terrain["feu"], habitation=premier.data["id"], statut_evaluation="DETRUITE")
        assert encore.status_code == 201, encore.data
        assert Habitation.objects.count() == 1 and Habitation.objects.get().statut_evaluation == "DETRUITE"
        assert ConstatTerrain.objects.filter(habitation_id=premier.data["id"]).count() == 2
        assert encore.data["rapprochements_proposes"] == 0
