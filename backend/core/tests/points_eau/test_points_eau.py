"""Points d'eau incendie (24/11/2026) : relevé OSM par département, import SDIS au schéma
national, signalements terrain validés par la commune, export pour le SDIS. Aucun appel réel :
la réponse d'Overpass est une fixture."""
import datetime
import uuid
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import points_eau_osm, points_eau_sdis
from core.models import (
    Commune, ContactInstitution, Institution, InstitutionType, Notification, PointEauIncendie,
    ReleveDepartementPEI, SignalementPEI, Team,
)

SAINT_ETIENNE, FIRMINY, LE_PUY, VOISINE_43 = "42218", "42095", "43157", "43999"


@pytest.fixture
def communes(db):
    for code, nom, dep, lat, lon in (
        (SAINT_ETIENNE, "Saint-Étienne", "42", 45.4397, 4.3872),
        (FIRMINY, "Firminy", "42", 45.3880, 4.2890),
        (LE_PUY, "Le Puy-en-Velay", "43", 45.0434, 3.8858),
        # Une commune de Haute-Loire tout contre la Loire, dans le rectangle relevé pour le 42.
        (VOISINE_43, "Voisine 43", "43", 45.3600, 4.3000),
    ):
        Commune.objects.update_or_create(code=code, defaults={"nom": nom, "departement_code": dep,
                                                              "centre_latitude": lat, "centre_longitude": lon})


def _overpass(*noeuds):
    return {"elements": [{"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}
                         for i, lat, lon, tags in noeuds]}


REPONSE_42 = _overpass(
    (1, 45.4400, 4.3870, {"emergency": "fire_hydrant", "fire_hydrant:type": "pillar", "water_source": "main",
                          "fire_hydrant:diameter": "100", "ref": "BI-12", "operator": "Eau de Saint-Étienne"}),
    (2, 45.3885, 4.2895, {"emergency": "fire_hydrant", "fire_hydrant:type": "underground", "flow_rate": "1000 l/min"}),
    (3, 45.4410, 4.3880, {"emergency": "suction_point", "water_source": "river"}),
    (4, 45.4420, 4.3890, {"emergency": "water_tank", "water_tank:volume": "120 m3"}),
    (5, 45.4430, 4.3900, {"disused:emergency": "fire_hydrant", "fire_hydrant:type": "pillar"}),
    # Dans le rectangle relevé, mais plus près d'une commune de Haute-Loire : pas au 42.
    (6, 45.3550, 4.3000, {"emergency": "fire_hydrant", "fire_hydrant:type": "pillar"}),
    # Hors du rectangle (une réponse trop large) : ignoré.
    (7, 44.0000, 3.0000, {"emergency": "fire_hydrant", "fire_hydrant:type": "pillar"}),
)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _mairie(commune=SAINT_ETIENNE, nom="Mairie de Saint-Étienne"):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_PEI", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom=nom, type=itype, commune_code=commune)


@pytest.fixture
def mairie(db, create_user):
    institution = _mairie()
    agent = create_user(username="agent-pei@test.fr", email="agent-pei@test.fr", type="AUT_LOCALE", institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=agent, actif=True)
    return institution, agent


@pytest.fixture
def intervenant(db, create_user):
    user = create_user(username="reserviste-pei@test.fr", email="reserviste-pei@test.fr", type="UTIL_SIMPLE")
    Team.objects.create(name="Réserve PEI").members.add(user)
    return user


@pytest.fixture
def borne(db):
    return PointEauIncendie.objects.create(source="OSM", ref_source="1", departement_code="42", insee=SAINT_ETIENNE,
                                           type_pei="PI", location=Point(4.3870, 45.4400, srid=4326),
                                           releve_le=timezone.now())


@pytest.mark.django_db
class TestTraductionOSM:
    def test_balises_vers_schema_national(self):
        assert points_eau_osm.traduire({"emergency": "fire_hydrant", "fire_hydrant:type": "pillar"})["type_pei"] == "PI"
        assert points_eau_osm.traduire({"emergency": "fire_hydrant", "fire_hydrant:type": "wall"})["type_pei"] == "BI"
        assert points_eau_osm.traduire({"emergency": "fire_hydrant", "water_source": "pond"})["type_pei"] == "PA"
        assert points_eau_osm.traduire({"emergency": "fire_hydrant", "water_source": "water_tank"})["type_pei"] == "CI"
        champs = points_eau_osm.traduire({"emergency": "fire_hydrant", "fire_hydrant:type": "pillar", "water_source": "main",
                                          "ref:FR:SIS": "42-0001", "pressure": "4"})
        assert champs["source_eau"] == "reseau_aep" and champs["ref_terrain"] == "42-0001" and champs["pression"] == 4
        assert points_eau_osm.traduire({"disused:emergency": "fire_hydrant"})["disponible"] is False

    def test_debit_sans_unite_n_est_pas_cru(self):
        assert points_eau_osm.debit_m3h("1000 l/min") == 60.0
        assert points_eau_osm.debit_m3h("60 m³/h") == 60.0
        assert points_eau_osm.debit_m3h("60") is None
        assert points_eau_osm.volume_m3("30000 l") == 30.0 and points_eau_osm.volume_m3("120") == 120


@pytest.mark.django_db
class TestReleveOSM:
    def test_un_departement_points_rattaches_au_bon_departement(self, communes):
        with patch.object(points_eau_osm, "interroger", return_value=REPONSE_42) as appel:
            assert points_eau_osm.relever(departement="42") == 5
        ouest, sud, est, nord = appel.call_args.args[0]
        assert sud < 45.3880 < 45.4397 < nord and ouest < 4.2890 < 4.3872 < est
        assert not PointEauIncendie.objects.filter(ref_source__in=["6", "7"]).exists()
        bouche = PointEauIncendie.objects.get(ref_source="2")
        assert bouche.type_pei == "BI" and bouche.debit == 60.0 and bouche.insee == FIRMINY
        assert PointEauIncendie.objects.get(ref_source="5").disponible is False
        etat = ReleveDepartementPEI.objects.get(departement_code="42")
        assert etat.nombre == 5 and etat.releve_le is not None and etat.erreur == ""

    def test_reponse_effondree_garde_la_copie(self, communes):
        maintenant = timezone.now()
        for i in range(30):
            PointEauIncendie.objects.create(source="OSM", ref_source=f"x{i}", departement_code="42",
                                            location=Point(4.38, 45.44, srid=4326), releve_le=maintenant)
        with patch.object(points_eau_osm, "interroger", return_value=_overpass()), pytest.raises(ValueError):
            points_eau_osm.relever(departement="42")
        assert PointEauIncendie.objects.filter(departement_code="42").count() == 30
        assert "copie précédente conservée" in ReleveDepartementPEI.objects.get(departement_code="42").erreur

    def test_rotation_jamais_releve_puis_le_plus_ancien_et_echec_reessaye_plus_tard(self, db):
        maintenant = timezone.now()
        for code in points_eau_osm.DEPARTEMENTS:
            ReleveDepartementPEI.objects.create(departement_code=code, releve_le=maintenant)
        ReleveDepartementPEI.objects.filter(departement_code="43").update(releve_le=maintenant - datetime.timedelta(days=9))
        assert points_eau_osm.prochain_departement(maintenant) == "43"
        # 43 vient d'échouer : il passe son tour six heures, le suivant le plus ancien passe.
        ReleveDepartementPEI.objects.filter(departement_code="43").update(essaye_le=maintenant - datetime.timedelta(hours=1))
        ReleveDepartementPEI.objects.filter(departement_code="15").update(releve_le=maintenant - datetime.timedelta(days=5))
        assert points_eau_osm.prochain_departement(maintenant) == "15"
        assert points_eau_osm.prochain_departement(maintenant + datetime.timedelta(hours=6)) == "43"
        ReleveDepartementPEI.objects.filter(departement_code="2A").delete()
        assert points_eau_osm.prochain_departement(maintenant) == "2A"


CSV_SDIS = (
    "insee;id_sdis;ref_terr;type_pei;type_rd;diam_pei;source_pei;debit;disponible;date_ct;x;y;lon;lat\n"
    f"{SAINT_ETIENNE};42-0001;BI-12;PI;PI100;100;reseau_aep;65;1;2026-05-02;;;4.3870;45.4400\n"
    f"{SAINT_ETIENNE};42-0002;;BI;;;;;0;;652470;6861990;;\n"
    f"{SAINT_ETIENNE};42-0003;;XX;;;;;;;;;4.38;45.44\n"
    ";42-0004;;PI;;;;;;;;;4.38;45.44\n"
).encode()


@pytest.mark.django_db
class TestImportSDIS:
    def test_csv_lambert_et_refus(self, communes):
        rapport = points_eau_sdis.importer("42", CSV_SDIS, "pei42.csv")
        assert rapport["importes"] == 2 and rapport["refuses"] == 2
        assert {r["ligne"] for r in rapport["refus"]} == {4, 5}
        poteau = PointEauIncendie.objects.get(source="SDIS", ref_source="42-0001")
        assert poteau.debit == 65 and poteau.disponible is True and poteau.date_controle == datetime.date(2026, 5, 2)
        lambert = PointEauIncendie.objects.get(source="SDIS", ref_source="42-0002")
        # 652470 / 6861990 en Lambert 93 : Paris, île de la Cité.
        assert abs(lambert.location.x - 2.35) < 0.02 and abs(lambert.location.y - 48.853) < 0.02
        assert ReleveDepartementPEI.objects.get(departement_code="42").sdis_nombre == 2

    def test_reimport_remplace_le_departement_seulement_et_garde_l_etat_terrain(self, communes):
        points_eau_sdis.importer("42", CSV_SDIS, "pei42.csv")
        PointEauIncendie.objects.filter(ref_source="42-0001").update(etat_terrain="INDISPONIBLE")
        autre = PointEauIncendie.objects.create(source="SDIS", ref_source="43-9", departement_code="43",
                                                location=Point(3.88, 45.04, srid=4326), releve_le=timezone.now())
        geojson = (b'{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point",'
                   b'"coordinates":[4.387,45.44]},"properties":{"insee":"42218","id_sdis":"42-0001","type_pei":"PI"}}]}')
        rapport = points_eau_sdis.importer("42", geojson, "pei42.geojson")
        assert rapport["importes"] == 1 and rapport["supprimes"] == 1
        assert PointEauIncendie.objects.get(ref_source="42-0001").etat_terrain == "INDISPONIBLE"
        assert PointEauIncendie.objects.filter(pk=autre.pk).exists()


@pytest.mark.django_db
class TestCarte:
    def test_reserve_aux_comptes_connectes(self, api_client, borne):
        assert api_client.get(reverse("points-eau"), {"bbox": "4.3,45.4,4.5,45.5"}).status_code == 401

    def test_emprise_et_osm_efface_quand_le_sdis_est_importe(self, mairie, borne, communes):
        client = _client(mairie[1])
        reponse = client.get(reverse("points-eau"), {"bbox": "4.3,45.4,4.5,45.5"})
        assert reponse.status_code == 200 and reponse.data["total"] == 1
        point = reponse.data["resultats"][0]
        assert point["source"] == "OSM" and point["attribution"].startswith("© contributeurs OpenStreetMap")
        points_eau_sdis.importer("42", CSV_SDIS, "pei42.csv")
        sources = {p["source"] for p in client.get(reverse("points-eau"), {"bbox": "4.3,45.4,4.5,45.5"}).data["resultats"]}
        assert sources == {"SDIS"}
        tous = client.get(reverse("points-eau"), {"bbox": "4.3,45.4,4.5,45.5", "osm": "tous"}).data["resultats"]
        assert {p["source"] for p in tous} == {"SDIS", "OSM"}


def _signaler(client, **champs):
    corps = {"id": str(uuid.uuid4()), "genre": "INDISPONIBLE", "latitude": 45.4400, "longitude": 4.3870,
             "observe_le": timezone.now().isoformat(), "commentaire": "Capot arraché, pas d'eau", **champs}
    return client.post(reverse("points-eau-signalements"), corps, format="json")


@pytest.mark.django_db
class TestSignalements:
    def test_intervenant_signale_la_mairie_valide_l_etat_suit(self, intervenant, mairie, borne):
        reponse = _signaler(_client(intervenant), pei=borne.pk)
        assert reponse.status_code == 201, reponse.data
        assert reponse.data["commune_code"] == SAINT_ETIENNE and reponse.data["statut"] == "A_VALIDER"
        assert Notification.objects.filter(utilisateur=mairie[1]).exists()
        # Renvoyé (file rejouée) : pas de doublon.
        again = _client(intervenant).post(reverse("points-eau-signalements"),
                                          {"id": reponse.data["id"], "genre": "INDISPONIBLE", "pei": borne.pk,
                                           "latitude": 45.44, "longitude": 4.387}, format="json")
        assert again.status_code == 200 and SignalementPEI.objects.count() == 1
        # L'intervenant ne valide pas.
        url = reverse("points-eau-signalement-decider", args=[reponse.data["id"]])
        assert _client(intervenant).post(url, {"geste": "valider"}, format="json").status_code == 403
        decision = _client(mairie[1]).post(url, {"geste": "valider", "motif": "Vu sur place"}, format="json")
        assert decision.status_code == 200 and decision.data["statut"] == "VALIDE"
        borne.refresh_from_db()
        assert borne.etat_terrain == "INDISPONIBLE"
        assert _client(mairie[1]).post(url, {"geste": "rejeter"}, format="json").status_code == 400
        assert Notification.objects.filter(utilisateur=intervenant).exists()

    def test_une_autre_commune_ne_valide_pas(self, intervenant, borne, create_user):
        autre = create_user(username="firminy-pei@test.fr", email="firminy-pei@test.fr", type="AUT_LOCALE",
                            institution=_mairie(FIRMINY, "Mairie de Firminy"))
        reponse = _signaler(_client(intervenant), pei=borne.pk)
        url = reverse("points-eau-signalement-decider", args=[reponse.data["id"]])
        refus = _client(autre).post(url, {"geste": "valider"}, format="json")
        assert refus.status_code == 403 and "autre commune" in str(refus.data)
        assert _client(autre).get(reverse("points-eau-signalements")).data == []

    def test_un_compte_sans_equipe_ne_signale_pas(self, create_user, borne):
        seul = create_user(username="seul-pei@test.fr", email="seul-pei@test.fr", type="UTIL_SIMPLE")
        assert _signaler(_client(seul), pei=borne.pk).status_code == 403

    def test_nouveau_point_doublon_propose_et_valide_cree_un_point_terrain(self, intervenant, mairie, borne):
        with patch("core.geo_lookup.commune_code_from_point", return_value=SAINT_ETIENNE):
            reponse = _signaler(_client(intervenant), genre="NOUVEAU", type_pei="CI", source_eau="citerne",
                                volume_estime=60, latitude=45.44002, longitude=4.38702)
        assert reponse.status_code == 201, reponse.data
        assert [d["ref"] for d in reponse.data["doublons_possibles"]] == ["1"]
        url = reverse("points-eau-signalement-decider", args=[reponse.data["id"]])
        _client(mairie[1]).post(url, {"geste": "valider"}, format="json")
        cree = PointEauIncendie.objects.get(source="TERRAIN")
        assert cree.type_pei == "CI" and cree.volume == 60 and cree.environment == "PROD" and cree.insee == SAINT_ETIENNE

    def test_commentaire_chiffre_en_base(self, intervenant, borne):
        reponse = _signaler(_client(intervenant), pei=borne.pk)
        with connection.cursor() as curseur:
            curseur.execute("SELECT commentaire FROM core_signalementpei WHERE id = %s", [reponse.data["id"]])
            assert "Capot" not in (curseur.fetchone()[0] or "")

    def test_photo_apres_le_signalement(self, intervenant, borne):
        from django.core.files.uploadedfile import SimpleUploadedFile

        reponse = _signaler(_client(intervenant), pei=borne.pk)
        image = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0" + b"0" * 200, content_type="image/jpeg")
        envoi = _client(intervenant).post(reverse("points-eau-signalement-photo"),
                                          {"signalement": reponse.data["id"], "fichier": image}, format="multipart")
        assert envoi.status_code in (201, 400), envoi.data
        inconnu = _client(intervenant).post(reverse("points-eau-signalement-photo"),
                                            {"signalement": str(uuid.uuid4())}, format="multipart")
        assert inconnu.status_code == 404


@pytest.mark.django_db
class TestExport:
    def test_csv_au_schema_sans_osm_et_lambert(self, intervenant, mairie, borne):
        with patch("core.geo_lookup.commune_code_from_point", return_value=SAINT_ETIENNE):
            nouveau = _signaler(_client(intervenant), genre="NOUVEAU", type_pei="PA", latitude=45.45, longitude=4.39)
        etat = _signaler(_client(intervenant), pei=borne.pk)
        for r in (nouveau, etat):
            _client(mairie[1]).post(reverse("points-eau-signalement-decider", args=[r.data["id"]]), {"geste": "valider"}, format="json")
        reponse = _client(mairie[1]).get(reverse("points-eau-export"))
        assert reponse.status_code == 200
        lignes = reponse.content.decode().splitlines()
        assert lignes[0].split(";") == list(__import__("core.points_eau", fromlist=["x"]).COLONNES_SCHEMA)
        assert len(lignes) == 3
        valeurs = dict(zip(lignes[0].split(";"), lignes[1].split(";")))
        assert valeurs["insee"] == SAINT_ETIENNE and valeurs["type_pei"] == "PA"
        assert 790000 < float(valeurs["x"]) < 820000 and 6470000 < float(valeurs["y"]) < 6500000
        # La ligne du signalement sur une borne OSM ne recopie rien d'OSM (ni référence, ni nature).
        osm = dict(zip(lignes[0].split(";"), lignes[2].split(";")))
        assert osm["id_sdis"] == "" and osm["type_pei"] == "" and osm["disponible"] == "0"

    def test_export_refuse_a_un_intervenant(self, intervenant):
        assert _client(intervenant).get(reverse("points-eau-export"), {"commune": SAINT_ETIENNE}).status_code == 403
