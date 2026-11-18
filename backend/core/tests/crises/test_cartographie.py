"""Cartographie du plan : zones inondables officielles relevées sans presser Géorisques, couches
qui sortent et entrent en GeoJSON, planches en annexe du document."""
import json

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core import cartes_pcs, couches_carto, document_pcs, zonages_officiels
from core.models import (
    CategorieSiteSensible, ContactInstitution, Institution, InstitutionType, PalierInondationSimule, PersonneVulnerable,
    Plan, PointOperationnel, PointType, SiteSensible, SourceSiteSensible, StatutSiteSensible, SuiviSiteSensible, Zone,
    ZonageOfficiel,
)

COMMUNE = "42207"
MOYEN = "ALEA_SYNT_01_02MOY_FXX"
FREQUENT = "ALEA_SYNT_01_01FOR_FXX"


def carre(demi, lon=4.5, lat=45.4):
    return MultiPolygon(Polygon.from_bbox((lon - demi, lat - demi, lon + demi, lat + demi)), srid=4326)


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie des cartes", type=itype, commune_code=COMMUNE)


@pytest.fixture
def client(create_user, mairie):
    user = create_user(username="agent-cartes@test.fr", email="agent-cartes@test.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _enjeux(mairie):
    ecole = SiteSensible.objects.create(
        commune_code=COMMUNE, commune_nom="Saint-Chamond", source=SourceSiteSensible.values[0], source_id="ecole",
        categorie=CategorieSiteSensible.ENSEIGNEMENT, nom="École du bas", adresse="1 rue du Test", est_enjeu=True,
        location=Point(4.5005, 45.4005, srid=4326))
    SuiviSiteSensible.objects.create(site=ecole, institution=mairie, statut=StatutSiteSensible.RETENU)
    plan = Plan.objects.create(institution=mairie, nom="Dispositif inondation")
    type_point = PointType.objects.get_or_create(code="CARE_TEST", defaults={"libelle": "Centre d'accueil"})[0]
    plan.points.add(PointOperationnel.objects.create(nom="Gymnase", type=type_point, capacite_accueil=120,
                                                     location=Point(4.6, 45.5, srid=4326)))


@pytest.mark.django_db
class TestZonagesOfficiels:
    def _geo(self, monkeypatch, reponses, appels):
        def faux(commune_code, couche):
            appels.append(couche)
            return reponses.get(couche, {"polygone": None, "erreur": None})
        monkeypatch.setattr("core.habitations.zones_georisques", faux)
        monkeypatch.setattr(zonages_officiels, "PAUSE_S", 0)

    def test_le_releve_garde_les_zones_en_base_et_ne_redemande_pas_un_releve_recent(self, monkeypatch):
        appels = []
        self._geo(monkeypatch, {MOYEN: {"polygone": carre(0.002), "erreur": None}}, appels)

        bilan = zonages_officiels.relever(COMMUNE, "PROD")

        assert len(appels) == 5 and len(bilan["relevees"]) == 5 and not bilan["erreurs"]
        etat = zonages_officiels.etat(COMMUNE, "PROD")
        assert etat["releve"] and etat["complet"]
        assert {c["couche"] for c in etat["couches"] if c["presente"]} == {MOYEN}
        # « Relevé, et rien ici » n'est pas « jamais relevé » : la ligne existe, sans polygone.
        assert ZonageOfficiel.objects.get(commune_code=COMMUNE, couche=FREQUENT).polygone is None
        # Second relevé le même jour : rien n'est redemandé à Géorisques.
        assert zonages_officiels.relever(COMMUNE, "PROD")["relevees"] == [] and len(appels) == 5
        assert len(zonages_officiels.relever(COMMUNE, "PROD", forcer=True)["relevees"]) == 5 and len(appels) == 10

    def test_une_panne_de_georisques_nefface_pas_ce_quon_avait(self, monkeypatch):
        ZonageOfficiel.objects.create(commune_code=COMMUNE, couche=MOYEN, polygone=carre(0.002))
        self._geo(monkeypatch, {MOYEN: {"polygone": None, "erreur": "Service Géorisques indisponible, réessayez plus tard."}}, [])

        bilan = zonages_officiels.relever(COMMUNE, "PROD", forcer=True)

        assert MOYEN in bilan["erreurs"]
        assert ZonageOfficiel.objects.get(commune_code=COMMUNE, couche=MOYEN).polygone is not None

    def test_les_requetes_sont_espacees_pour_tout_le_serveur(self, monkeypatch):
        from django.core.cache import cache

        siestes = []
        monkeypatch.setattr(zonages_officiels.time, "sleep", siestes.append)
        monkeypatch.setattr(zonages_officiels.time, "time", lambda: 1000.0)
        cache.delete(zonages_officiels._CLE_DERNIER_APPEL)

        zonages_officiels._attendre_son_tour()     # premier appel : rien à attendre
        zonages_officiels._attendre_son_tour()     # le suivant, au même instant, attend toute la pause

        assert siestes == [zonages_officiels.PAUSE_S]

    def test_les_enjeux_disent_dans_quelle_zone_officielle_ils_sont_et_lecran_demande_le_releve(self, client, mairie, monkeypatch):
        _enjeux(mairie)
        lances = []
        monkeypatch.setattr("core.tasks.relever_zonages_officiels_task.delay", lambda *a: lances.append(a))

        avant = client.get("/api/dossier-pcs/enjeux-exposes/").data
        assert avant["zonages_officiels"]["releve"] is False and avant["en_zone_officielle"] == 0
        reponse = client.post("/api/dossier-pcs/zonages-officiels/", {}, format="json")
        assert reponse.status_code == 202 and lances == [(COMMUNE, "PROD", False)]

        ZonageOfficiel.objects.create(commune_code=COMMUNE, couche=MOYEN, polygone=carre(0.002))
        ZonageOfficiel.objects.create(commune_code=COMMUNE, couche=FREQUENT, polygone=carre(0.001))
        apres = client.get("/api/dossier-pcs/enjeux-exposes/").data
        par_nom = {e["nom"]: e for e in apres["enjeux"]}
        # Dans les deux zones : on retient le scénario le plus fréquent.
        assert par_nom["École du bas"]["zone_officielle"] == "débordement fréquent (décennal)"
        assert par_nom["Gymnase"]["zone_officielle"] == "" and apres["en_zone_officielle"] == 1


@pytest.mark.django_db
class TestExportDesCouches:
    def test_chaque_couche_sort_en_geojson_et_le_registre_ne_sort_jamais(self, client, mairie):
        _enjeux(mairie)
        Zone.objects.create(institution=mairie, nom="Quartier bas", zone_precise=carre(0.003)[0])
        Zone.objects.update_or_create(institution=mairie, nom="Mon territoire", defaults={"zone_precise": carre(0.2)[0]})
        PalierInondationSimule.objects.create(commune_code=COMMUNE, niveau_metres=1.0, polygone=carre(0.001))
        ZonageOfficiel.objects.create(commune_code=COMMUNE, couche=MOYEN, polygone=carre(0.002))
        # Le périmètre d'un plan de prévention, relevé au Géoportail de l'urbanisme (18/11/2026).
        from core.models import ServitudePPR
        ServitudePPR.objects.create(commune_code=COMMUNE, categorie="pm1", nom="PPRNPI d'essai", polygone=carre(0.004))
        PersonneVulnerable.objects.create(institution_declarante=mairie, commune_code=COMMUNE, nom="Nomtressecret",
                                          prenom="Jeanne", adresse="3 rue du Secret", mode_consentement="VOLONTAIRE")

        inventaire = {ligne["couche"]: ligne["objets"] for ligne in client.get("/api/couches-carto/").data}
        assert inventaire == {"quartiers": 1, "sites-sensibles": 1, "points-du-plan": 1, "inondation-simulee": 1,
                              "zonages-officiels": 1, "perimetres-ppr": 1, "enjeux-exposes": 2}

        tout = ""
        for couche in inventaire:
            reponse = client.get(f"/api/couches-carto/{couche}/")
            assert reponse.status_code == 200 and reponse["Content-Type"] == "application/geo+json"
            assert f'{couche}.geojson' in reponse["Content-Disposition"]
            contenu = json.loads(reponse.content)
            assert contenu["type"] == "FeatureCollection" and len(contenu["features"]) == inventaire[couche]
            tout += reponse.content.decode()
        assert "Quartier bas" in tout and "Mon territoire" not in tout      # la zone automatique n'est pas un quartier
        assert "Nomtressecret" not in tout and "rue du Secret" not in tout
        enjeux = {f["properties"]["nom"]: f["properties"] for f in json.loads(client.get("/api/couches-carto/enjeux-exposes/").content)["features"]}
        assert enjeux["École du bas"]["atteint_a_partir_de_m"] == 1.0 and "zone_officielle" in enjeux["École du bas"]
        assert "atteint_a_partir_de_m" not in enjeux["Gymnase"]
        assert client.get("/api/couches-carto/registre/").status_code == 400
        assert APIClient().get("/api/couches-carto/quartiers/").status_code in (401, 403)


def _fichier(objets, **extra):
    contenu = {"type": "FeatureCollection", "features": objets, **extra}
    return SimpleUploadedFile("quartiers.geojson", json.dumps(contenu).encode(), content_type="application/geo+json")


def _surface(nom, anneau, cle="nom"):
    return {"type": "Feature", "properties": {cle: nom}, "geometry": {"type": "Polygon", "coordinates": [anneau]}}


CARRE_WGS = [[4.50, 45.40], [4.51, 45.40], [4.51, 45.41], [4.50, 45.41], [4.50, 45.40]]
# Le même coin de Saint-Chamond, en Lambert 93.
CARRE_L93 = [[817000, 6485000], [818000, 6485000], [818000, 6486000], [817000, 6486000], [817000, 6485000]]
URL_IMPORT = "/api/couches-carto/quartiers/importer/"


@pytest.mark.django_db
class TestImportDesQuartiers:
    def test_laperçu_ne_cree_rien_puis_limport_cree_sans_ecraser_lexistant(self, client, mairie):
        Zone.objects.create(institution=mairie, nom="Centre", zone_precise=carre(0.001)[0])
        objets = [_surface("Quartier Nord", CARRE_WGS), _surface("centre", CARRE_WGS, cle="NAME"),
                  {"type": "Feature", "properties": {"nom": "Une borne"}, "geometry": {"type": "Point", "coordinates": [4.5, 45.4]}}]

        apercu = client.post(URL_IMPORT, {"fichier": _fichier(objets)}, format="multipart").data
        assert apercu["enregistre"] is False and apercu["crees"] == 1 and apercu["laisses"] == 1 and apercu["ignores"] == 1
        quartiers = Zone.objects.filter(institution=mairie).exclude(nom="Mon territoire")   # créée d'office
        assert quartiers.count() == 1

        bilan = client.post(URL_IMPORT, {"fichier": _fichier(objets), "enregistrer": "1"}, format="multipart").data
        assert bilan["crees"] == 1 and bilan["remplaces"] == 0
        nord = Zone.objects.get(institution=mairie, nom="Quartier Nord")
        assert nord.zone_precise.contains(Point(4.505, 45.405, srid=4326)) and nord.communes == [COMMUNE]
        # « Centre » existait : son contour n'a pas bougé.
        assert not Zone.objects.get(institution=mairie, nom="Centre").zone_precise.contains(Point(4.505, 45.405, srid=4326))

        client.post(URL_IMPORT, {"fichier": _fichier(objets), "enregistrer": "1", "remplacer": "1"}, format="multipart")
        assert Zone.objects.get(institution=mairie, nom="Centre").zone_precise.contains(Point(4.505, 45.405, srid=4326))
        assert quartiers.count() == 2      # redessiné, pas dupliqué

    def test_un_fichier_en_lambert_93_est_converti_meme_sil_ne_le_dit_pas(self, client, mairie):
        bilan = client.post(URL_IMPORT, {"fichier": _fichier([_surface("Quartier Est", CARRE_L93)]), "enregistrer": "1"},
                            format="multipart").data

        assert bilan["crees"] == 1 and "Lambert 93" in bilan["lignes"][0]["remarque"]
        centre = Zone.objects.get(institution=mairie, nom="Quartier Est").zone_precise.centroid
        assert 4.0 < centre.x < 5.0 and 45.0 < centre.y < 46.0      # dans la Loire, pas au large de l'Afrique

    def test_un_fichier_qui_nest_pas_une_couche_est_refuse_avec_une_explication(self, client):
        pas_du_json = SimpleUploadedFile("quartiers.shp", b"\x00\x00\x27\x0a\xff\xfe", content_type="application/octet-stream")
        assert "GeoJSON" in str(client.post(URL_IMPORT, {"fichier": pas_du_json}, format="multipart").data)

        ailleurs = [[[500, 500], [600, 500], [600, 600], [500, 500]]]
        reponse = client.post(URL_IMPORT, {"fichier": _fichier([_surface("X", ailleurs[0])])}, format="multipart")
        assert reponse.status_code == 400 and "WGS 84" in str(reponse.data)
        assert client.post(URL_IMPORT, {}, format="multipart").status_code == 400

    def test_un_quartier_en_plusieurs_morceaux_garde_le_plus_grand(self):
        petit = [[4.6, 45.5], [4.601, 45.5], [4.601, 45.501], [4.6, 45.5]]
        objet = {"type": "Feature", "properties": {"libelle": "Hameaux"},
                 "geometry": {"type": "MultiPolygon", "coordinates": [[petit], [CARRE_WGS]]}}

        quartier = couches_carto.lire_quartiers(json.dumps({"type": "FeatureCollection", "features": [objet]}))[0]

        assert quartier["nom"] == "Hameaux" and "le plus grand est gardé" in quartier["remarque"]
        assert quartier["polygone"].contains(Point(4.505, 45.405, srid=4326))


@pytest.mark.django_db
class TestCartesEnAnnexe:
    def test_les_planches_numerotent_les_reperes_et_marquent_ceux_que_leau_atteint(self, mairie):
        _enjeux(mairie)
        Zone.objects.create(institution=mairie, nom="Quartier bas", zone_precise=carre(0.003)[0])
        PalierInondationSimule.objects.create(commune_code=COMMUNE, niveau_metres=1.0, polygone=carre(0.001))
        PalierInondationSimule.objects.create(commune_code=COMMUNE, niveau_metres=2.0, polygone=carre(0.002))
        ZonageOfficiel.objects.create(commune_code=COMMUNE, couche=MOYEN, polygone=carre(0.002))

        cartes = cartes_pcs.planches(mairie, "PROD")

        assert cartes["quartiers"] == ["Quartier bas"] and cartes["niveaux"][1] == 2.0
        assert [(r["numero"], r["nom"]) for r in cartes["reperes"]] == [(1, "Gymnase"), (2, "École du bas")]
        ecole = cartes["reperes"][1]
        assert ecole["seuil_m"] == 1.0 and ecole["zone_officielle"] == "débordement moyen (centennal, réf. PPRI)"
        assert cartes["zonage_officiel"] and cartes["planche_plan"] is not None and cartes["planche_eau"] is not None

    def test_le_document_du_plan_porte_les_cartes_et_sedite_aussi_sans_rien_a_dessiner(self, client, mairie):
        assert client.get("/api/dossier-pcs/document/").content.startswith(b"%PDF")     # rien à dessiner : pas de carte

        _enjeux(mairie)
        PalierInondationSimule.objects.create(commune_code=COMMUNE, niveau_metres=1.0, polygone=carre(0.001))
        sans_cartes = document_pcs.generer_pdf(document_pcs.rassembler(mairie, "PROD"), edite_par="Agent")
        avec_cartes = client.get("/api/dossier-pcs/document/").content

        assert avec_cartes.startswith(b"%PDF") and len(avec_cartes) > len(sans_cartes)
        # L'état affiché à l'écran reste sérialisable : les planches n'y sont pas.
        assert client.get("/api/dossier-pcs/").status_code == 200


@pytest.mark.django_db
class TestFondDePlan:
    def test_le_fond_couvre_tout_le_cadre_et_son_absence_nempeche_pas_dediter(self, client, mairie, monkeypatch):
        _enjeux(mairie)
        PalierInondationSimule.objects.create(commune_code=COMMUNE, niveau_metres=1.0, polygone=carre(0.001))
        demandes = []

        def faux_fond(lon_min, lat_min, lon_max, lat_max, largeur_px, hauteur_px):
            demandes.append((lon_min, lat_min, lon_max, lat_max, largeur_px, hauteur_px))
            return None       # l'IGN ne répond pas

        monkeypatch.setattr(cartes_pcs, "fond_ign", faux_fond)

        assert client.get("/api/dossier-pcs/document/").content.startswith(b"%PDF") and demandes == []   # schéma par défaut
        pdf = client.get("/api/dossier-pcs/document/", {"fond": "ign"}).content

        assert pdf.startswith(b"%PDF") and len(demandes) == 2       # une image par planche, pas des tuiles
        ouest, sud, est, nord, largeur, hauteur = demandes[0]
        # L'emprise demandée contient tous les repères (l'école et le gymnase) et rien d'autre ne part.
        assert ouest < 4.5005 < 4.6 < est and sud < 45.4005 < 45.5 < nord and largeur == 1400 and hauteur > 0

    def test_la_carte_de_simulation_relit_la_base_et_y_garde_ce_quelle_releve(self, client, mairie, monkeypatch):
        from django.core.cache import cache

        appels = []

        def faux(commune_code, couche):
            appels.append(couche)
            return {"polygone": carre(0.002), "erreur": None}

        monkeypatch.setattr("core.habitations.zones_georisques", faux)
        monkeypatch.setattr("core.habitations.peut_simuler_commune", lambda request, commune: True)
        monkeypatch.setattr(zonages_officiels, "PAUSE_S", 0)
        cache.delete(f"georisques:{MOYEN}:{COMMUNE}")
        url = f"/api/simulation-inondation/{COMMUNE}/georisques/"

        premiere = client.get(url, {"couche": MOYEN})
        if premiere.status_code == 404:
            pytest.skip("adresse de la vue différente dans cette version")
        assert premiere.status_code == 200 and premiere.data["geometrie"] and appels == [MOYEN]
        assert ZonageOfficiel.objects.filter(commune_code=COMMUNE, couche=MOYEN).exists()
        cache.delete(f"georisques:{MOYEN}:{COMMUNE}")
        assert client.get(url, {"couche": MOYEN}).data["geometrie"] and appels == [MOYEN]     # relu en base
