"""MeshCore, 19/11/2026 : liaisons tirées des trames entendues par nos companions et par les
observateurs MQTT, traceroutes en liaisons, nature du trafic, calque de la carte radio.

Les trames sont fabriquées octet par octet (en-tête, octet de chemin, sauts) : c'est ce que le
firmware émet, et la seule façon de savoir ce qu'on doit en tirer."""
import json

import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.ingestion_observateurs_meshcore import ingerer_paquet, lire_message
from core.models import (
    CompagnonMeshCore, CompteurPaquetsMeshCore, ContactMeshCore, LiaisonMeshCore, TracerouteMeshCore,
    UserRole,
)
from core.tests.mesh.test_ingestion_observateurs import trame_advert

NOUS = "c0" * 32
RELAIS_A = "aaaa" + "11" * 30
RELAIS_B = "bbbb" + "22" * 30


def trame(sauts, taille=2, charge=0x02, route=1, corps=b"\x01\x02\x03\x04" + b"\x00" * 16):
    """En-tête (charge, route) + octet de chemin + sauts + corps. TXT_MSG en inondation par défaut."""
    octet_chemin = ((taille - 1) << 6) | len(sauts)
    return (bytes([(charge << 2) | route, octet_chemin]) + b"".join(bytes.fromhex(s) for s in sauts) + corps).hex()


@pytest.fixture
def compagnon(db):
    c = CompagnonMeshCore.objects.create(nom="Mairie", pubkey_hex=NOUS, location=Point(-0.57, 44.84, srid=4326))
    for cle, x in ((RELAIS_A, -0.50), (RELAIS_B, -0.55)):
        ContactMeshCore.objects.create(compagnon=c, pubkey_hex=cle, nom=f"Relais {cle[:2]}",
                                       location=Point(x, 44.80, srid=4326))
    return c


@pytest.fixture
def pont(db, create_user):
    u = create_user(username="pont-mc@x.fr", email="pont-mc@x.fr", type=UserRole.SIMPLE_USER)
    u.compte_service_pont = True
    u.save()
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def liaisons():
    return {(l.emetteur_prefixe_hex, l.recepteur_pubkey_hex, l.source): l.snr for l in LiaisonMeshCore.objects.all()}


@pytest.mark.django_db
class TestTramesDeNosCompanions:

    def test_un_message_relaye_donne_le_dernier_relais_et_le_chemin(self, compagnon, pont):
        r = pont.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-observations/", {"observations": [
            {"raw": trame(["aaaa", "bbbb"]), "snr": 6.25, "rssi": -80},
            {"raw": "zz"},                                       # illisible : compté, ignoré
        ]}, format="json")
        assert r.status_code == 200, r.data
        assert (r.data["decodees"], r.data["illisibles"]) == (1, 1)
        assert liaisons() == {("bbbb", NOUS, "RF"): 6.25, ("aaaa", RELAIS_B, "CHEMIN"): None}
        assert CompteurPaquetsMeshCore.objects.get(type_paquet="TXT_MSG").nombre == 1

    def test_un_chemin_a_un_octet_ne_prouve_pas_de_maillon(self, compagnon, pont):
        pont.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-observations/",
                  {"observations": [{"raw": trame(["aa", "bb"], taille=1), "snr": 2}]}, format="json")
        assert liaisons() == {("bb", NOUS, "RF"): 2.0}

    def test_un_advert_relaye_n_est_pas_attribue_a_son_auteur(self, compagnon, pont):
        brut, publique = trame_advert()
        avec_saut = brut[:2] + "41" + "bbbb" + brut[4:]          # même advert, relayé par B
        pont.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-observations/",
                  {"observations": [{"raw": avec_saut, "snr": 4}]}, format="json")
        assert liaisons() == {("bbbb", NOUS, "RF"): 4.0, (publique, RELAIS_B, "CHEMIN"): None}

    def test_un_chemin_direct_n_est_pas_un_chemin_parcouru(self, compagnon, pont):
        pont.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-observations/",
                  {"observations": [{"raw": trame(["aaaa", "bbbb"], route=2), "snr": 1}]}, format="json")
        assert liaisons() == {}

    def test_seul_un_pont_rapporte(self, compagnon, create_user):
        u = create_user(username="curieux@x.fr", email="curieux@x.fr", type=UserRole.SIMPLE_USER)
        c = APIClient()
        c.force_authenticate(user=u)
        assert c.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-observations/",
                      {"observations": []}, format="json").status_code == 403


@pytest.mark.django_db
def test_un_traceroute_donne_une_liaison_par_saut(compagnon, pont):
    trace = TracerouteMeshCore.objects.create(compagnon=compagnon)
    r = pont.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-traceroute/", {
        "id": str(trace.id), "statut": "TERMINE", "tag": 7,
        "chemin": [{"hash": "aaaa", "snr": 5.0}, {"hash": "bbbb", "snr": 2.5}, {"snr": -3.0}]}, format="json")
    assert r.status_code == 200 and r.data["liaisons"] == 3
    assert liaisons() == {(NOUS, RELAIS_A, "TRACEROUTE"): 5.0, ("aaaa", RELAIS_B, "TRACEROUTE"): 2.5,
                          ("bbbb", NOUS, "TRACEROUTE"): -3.0}


@pytest.mark.django_db
def test_un_observateur_mqtt_passe_par_la_meme_lecture(compagnon):
    from core.observations_meshcore import IndexCles
    IndexCles._partages.clear()
    message = lire_message(f"meshcore/BOD/{NOUS}/packets", json.dumps({"raw": trame(["aaaa", "bbbb"]), "SNR": 3}))
    decode, liaison = ingerer_paquet(message)
    assert decode is not None and liaison is None
    assert ("bbbb", NOUS, "RF") in liaisons()


@pytest.mark.django_db
def test_le_calque_de_la_carte(compagnon, pont, create_user):
    pont.post(f"/api/compagnons-meshcore/{compagnon.id}/rapporter-observations/",
              {"observations": [{"raw": trame(["aaaa", "bbbb"]), "snr": 6}]}, format="json")
    LiaisonMeshCore.objects.create(emetteur_prefixe_hex="cc", recepteur_pubkey_hex=NOUS, source="RF",
                                   prefixe_octets=1, dernier_vu="2030-01-01T00:00:00Z")   # un octet : pas placé
    agent = create_user(username="admin-mc@x.fr", email="admin-mc@x.fr", type=UserRole.ADMINISTRATOR)
    c = APIClient()
    c.force_authenticate(user=agent)
    r = c.get("/api/liaisons-meshtastic/geojson-meshcore/")
    assert r.status_code == 200, r.data
    paires = {(f["properties"]["emetteur"], f["properties"]["recepteur"], f["properties"]["source"])
              for f in r.data["features"]}
    assert paires == {(RELAIS_B, NOUS, "RF"), (RELAIS_A, RELAIS_B, "CHEMIN")}
    assert all(f["properties"]["reseau"] == "MESHCORE" for f in r.data["features"])


@pytest.mark.django_db
def test_le_relais_navigateur_rapporte_par_le_meme_chemin(compagnon, create_user):
    from core.models import ContactInstitution, Institution, InstitutionType
    from core.relais_navigateur import ouvrir
    t, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    compagnon.institution = Institution.objects.create(nom="Mairie relais", type=t)
    compagnon.save()
    membre = create_user(username="relais-mc@x.fr", email="relais-mc@x.fr", type=UserRole.LOCAL_AUTHORITY)
    ContactInstitution.objects.create(institution=compagnon.institution, utilisateur=membre, actif=True)
    c = APIClient()
    c.force_authenticate(user=membre)
    corps = {"protocole": "MESHCORE", "compagnon": str(compagnon.id),
             "observations": [{"raw": trame(["aaaa", "bbbb"]), "snr": 5, "rssi": -90, "t": 1}]}
    assert c.post("/api/relais-serie/mesures/", corps, format="json").status_code == 403
    session, erreur = ouvrir(membre, compagnon, "PROD")
    assert session is not None, erreur
    r = c.post("/api/relais-serie/mesures/", corps, format="json")
    assert r.status_code == 200, r.data
    assert ("bbbb", NOUS, "RF") in liaisons()


# ── Flux continus : tampon, doublons, CoreScope (19/11/2026) ───────────────────

@pytest.mark.django_db
def test_le_tampon_agrege_puis_ecrit_en_une_fois(compagnon):
    from django.utils import timezone
    from core.observations_meshcore import IndexCles, TamponLiaisons, tirer_liaisons
    from core.decodeur_meshcore import decoder_paquet
    tampon = TamponLiaisons()
    index = IndexCles("PROD")
    for snr in (2.0, 7.5, 4.0):
        tirer_liaisons(decoder_paquet(trame(["aaaa", "bbbb"])), snr, NOUS, index, "PROD", timezone.now(), tampon=tampon)
    assert LiaisonMeshCore.objects.count() == 0            # rien d'écrit avant le vidage
    assert tampon.notees == 6
    assert tampon.vider() == 2
    rf = LiaisonMeshCore.objects.get(source="RF")
    assert (rf.nombre, rf.snr) == (3, 7.5)
    assert LiaisonMeshCore.objects.get(source="CHEMIN").nombre == 3
    tampon.noter("bbbb", NOUS, "RF", 9.0, "PROD", 2)
    tampon.vider()
    rf.refresh_from_db()
    assert (rf.nombre, rf.snr) == (4, 9.0)


def test_une_observation_recue_deux_fois_n_est_comptee_qu_une_fois():
    from core.observations_meshcore import DejaVus
    vus = DejaVus()
    assert vus.deja_vu("AB" * 32, "1100AA") is False
    assert vus.deja_vu("ab" * 32, "1100aa") is True        # même observateur, même trame
    assert vus.deja_vu("cd" * 32, "1100aa") is False       # autre observateur : autre observation


def test_lecture_d_un_message_corescope():
    from core.ingestion_observateurs_meshcore import lire_message_corescope
    message = lire_message_corescope(json.dumps({"type": "packet", "data": {
        "direction": "rx", "raw_hex": "1100", "snr": 6.5, "rssi": -90, "observer_id": "AB" * 32,
        "resolved_path": [RELAIS_A], "scope_name": "BOD"}}))
    assert (message.observateur, message.sorte, message.donnees["SNR"]) == ("ab" * 32, "packets", 6.5)
    assert message.donnees["chemin_resolu"] == [RELAIS_A]
    assert lire_message_corescope('{"type": "stats"}') is None
    assert lire_message_corescope("pas du json") is None
    assert lire_message_corescope(json.dumps({"type": "packet", "data": {
        "direction": "tx", "raw_hex": "11", "observer_id": "AB" * 32}})) is None


@pytest.mark.django_db
def test_les_relais_resolus_par_la_source_servent_aux_recepteurs(db):
    """Aucun nœud connu chez nous : sans les clés résolues par CoreScope, pas de maillon."""
    from django.utils import timezone
    from core.observations_meshcore import IndexCles, tirer_liaisons
    from core.decodeur_meshcore import decoder_paquet
    inconnu_b = "bbbb" + "99" * 30
    n = tirer_liaisons(decoder_paquet(trame(["aaaa", "bbbb"])), 3.0, NOUS, IndexCles("PROD"), "PROD",
                       timezone.now(), resolus=["aaaa" + "88" * 30, inconnu_b])
    assert n == 2
    assert LiaisonMeshCore.objects.filter(source="CHEMIN", emetteur_prefixe_hex="aaaa",
                                          recepteur_pubkey_hex=inconnu_b).exists()
    # Une clé « résolue » qui ne commence pas par le préfixe du saut est refusée.
    LiaisonMeshCore.objects.all().delete()
    tirer_liaisons(decoder_paquet(trame(["aaaa", "bbbb"])), 3.0, NOUS, IndexCles("PROD"), "PROD",
                   timezone.now(), resolus=["aaaa" + "88" * 30, "cccc" + "77" * 30])
    assert not LiaisonMeshCore.objects.filter(source="CHEMIN").exists()


@pytest.mark.django_db
def test_une_source_corescope_se_declare_sans_filtre(create_user):
    admin = create_user(username="admin-cs@x.fr", email="admin-cs@x.fr", type=UserRole.ADMINISTRATOR)
    c = APIClient()
    c.force_authenticate(user=admin)
    r = c.post("/api/sources-observateurs-meshcore/", {
        "nom": "Meshstats", "type_source": "CORESCOPE", "broker_host": "meshstats.exemple.invalide",
        "broker_port": 443, "mqtt_use_tls": True, "mqtt_ws_chemin": "/", "filtre_topic": ""}, format="json")
    assert r.status_code == 201, r.data
    from core.management.commands.ingerer_observateurs_meshcore import ClientCoreScope
    from core.models import SourceObservateurMeshCore
    source = SourceObservateurMeshCore.objects.get()
    client = ClientCoreScope.__new__(ClientCoreScope)
    client.source = source
    assert client.url == "wss://meshstats.exemple.invalide/"
    refus = c.post("/api/sources-observateurs-meshcore/", {
        "nom": "MQTT sans filtre", "broker_host": "mqtt.exemple.invalide", "filtre_topic": ""}, format="json")
    assert refus.status_code == 400
