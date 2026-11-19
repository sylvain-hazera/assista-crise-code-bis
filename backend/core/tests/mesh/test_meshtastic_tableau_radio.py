"""Meshtastic, 19/11/2026 : opérations complétées, télémétrie, compteurs de paquets, traceroute
qui alimente les liaisons, et tableau radio d'une passerelle."""
import time

import pytest
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshtastic, ContactMeshtastic, Institution, InstitutionType, LiaisonMeshtastic,
    MeshtasticConnexionType, MesureTelemetrieMeshtastic, NoeudUtilisateurMeshtastic,
    SourceLiaisonMeshtastic, TacheAdminMeshtastic, UserRole,
)

URL_TACHES = "/api/taches-admin-meshtastic/"
GW = 0xD001


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def institution(db):
    t, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie mesh", type=t)


@pytest.fixture
def passerelle(institution):
    return CompagnonMeshtastic.objects.create(
        nom="Passerelle mairie", node_num=GW, institution=institution,
        connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM4")


@pytest.fixture
def agent(create_user, institution, passerelle):
    u = create_user(username="agent-mt@x.fr", email="agent-mt@x.fr", type="SECOURS", institution=institution)
    NoeudUtilisateurMeshtastic.objects.create(utilisateur=u, node_num=0xD010)
    return u


@pytest.fixture
def pont(db, create_user):
    u = create_user(username="pont-mt@x.fr", email="pont-mt@x.fr", type=UserRole.SIMPLE_USER)
    u.compte_service_pont = True
    u.save()
    return _client(u)


@pytest.mark.django_db
class TestOperations:

    def test_traceroute_exige_un_noeud_cible(self, agent, passerelle):
        refus = _client(agent).post(URL_TACHES, {"compagnon": str(passerelle.id), "type_tache": "TRACEROUTE"}, format="json")
        assert refus.status_code == 400
        ok = _client(agent).post(URL_TACHES, {"compagnon": str(passerelle.id), "type_tache": "TRACEROUTE",
                                              "node_num_cible": 0xD010}, format="json")
        assert ok.status_code == 201, ok.data

    @pytest.mark.parametrize("type_tache,parametres", [
        ("FAVORI", {}),
        ("DEFINIR_MESSAGES_PREDEF", {"messages": "x" * 250}),
        ("POSITION_FIXE", {"latitude": 100, "longitude": 0}),
        ("VIDER_BASE_NOEUDS", {}),
    ])
    def test_parametres_refuses(self, agent, passerelle, type_tache, parametres):
        r = _client(agent).post(URL_TACHES, {"compagnon": str(passerelle.id), "node_num_cible": 0xD010,
                                             "type_tache": type_tache, "parametres": parametres}, format="json")
        assert r.status_code == 400

    def test_les_nouvelles_sections_de_reglages_sont_ouvertes(self, agent, passerelle):
        r = _client(agent).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "node_num_cible": 0xD010, "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "store_forward", "valeurs": {"enabled": True, "records": 100}}}, format="json")
        assert r.status_code == 201, r.data
        refus = _client(agent).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "node_num_cible": 0xD010, "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "security", "valeurs": {}}}, format="json")
        assert refus.status_code == 400          # la section sécurité reste fermée

    def test_un_traceroute_reussi_cree_les_liaisons(self, agent, passerelle, pont):
        tache = TacheAdminMeshtastic.objects.create(compagnon=passerelle, node_num_cible=0xD010,
                                                   type_tache="TRACEROUTE", statut="EN_COURS", tentatives=1)
        r = pont.post(f"{URL_TACHES}{tache.id}/rapporter/", {"succes": True, "reponse": {
            "aller": [GW, 0xD020, 0xD010], "snr_aller": [8.0, 3.5],
            "retour": [0xD010, 0xD020, GW], "snr_retour": [4.0, None]}}, format="json")
        assert r.status_code == 200, r.data
        liaisons = {(l.emetteur, l.recepteur): l.snr for l in LiaisonMeshtastic.objects.filter(
            source=SourceLiaisonMeshtastic.TRACEROUTE)}
        assert liaisons == {(GW, 0xD020): 8.0, (0xD020, 0xD010): 3.5, (0xD010, 0xD020): 4.0, (0xD020, GW): None}


@pytest.mark.django_db
class TestTelemetrieEtTableau:

    def test_seul_le_pont_rapporte(self, agent, passerelle):
        r = _client(agent).post(f"/api/compagnons-meshtastic/{passerelle.id}/rapporter-telemetrie/",
                                {"mesures": [], "compteurs": []}, format="json")
        assert r.status_code == 403

    def test_rapport_puis_tableau(self, agent, passerelle, pont):
        maintenant = int(time.time())
        r = pont.post(f"/api/compagnons-meshtastic/{passerelle.id}/rapporter-telemetrie/", {
            "mesures": [
                {"node_num": GW, "horodatage": maintenant - 600, "occupation_canal": 10.0, "paquets_tx": 100, "paquets_rx": 1000},
                {"node_num": GW, "horodatage": maintenant - 60, "occupation_canal": 20.0, "paquets_tx": 110, "paquets_rx": 1050},
                {"node_num": 0xD020, "horodatage": maintenant - 30, "batterie": 64, "tension": 3.9},
                {"node_num": "pas un nombre", "horodatage": maintenant},
                {"node_num": 1, "horodatage": maintenant, "batterie": True},      # booléen : ignoré
            ],
            "compteurs": [{"heure": maintenant // 3600 * 3600, "type": "TEXT_MESSAGE_APP", "nombre": 3},
                          {"heure": maintenant // 3600 * 3600, "type": "TEXT_MESSAGE_APP", "nombre": 2},
                          {"heure": maintenant // 3600 * 3600, "type": "POSITION_APP", "nombre": 7}],
        }, format="json")
        assert r.status_code == 200 and r.data["mesures"] == 4
        assert MesureTelemetrieMeshtastic.objects.filter(node_num=1).get().batterie is None
        ContactMeshtastic.objects.create(compagnon=passerelle, node_num=0xD020, long_name="Relais Pilat", sauts=1)
        LiaisonMeshtastic.objects.create(emetteur=0xD020, recepteur=GW, source="RF", snr=6.25,
                                         dernier_vu="2026-11-19T10:00:00Z")

        t = _client(agent).get(f"/api/compagnons-meshtastic/{passerelle.id}/tableau/", {"fenetre": "1h"})
        assert t.status_code == 200, t.data
        assert [s["v"] for s in t.data["series"]["occupation_canal"]] in ([10.0, 20.0], [15.0])
        assert sum(s["v"] for s in t.data["series"]["paquets_tx"]) == 10           # écart, pas cumul
        assert t.data["types_paquets"][0] == {"type": "POSITION_APP", "nombre": 7}
        assert {"type": "TEXT_MESSAGE_APP", "nombre": 5} in t.data["types_paquets"]
        (noeud,) = t.data["noeuds"]
        assert (noeud["nom"], noeud["batterie"], noeud["sauts"], noeud["snr"]) == ("Relais Pilat", 64, 1, 6.25)

    def test_les_sauts_arrivent_par_la_synchronisation(self, passerelle, pont):
        r = pont.post(f"/api/compagnons-meshtastic/{passerelle.id}/synchroniser-contacts/", {
            "contacts": [{"node_num": 0xD030, "sauts": 3, "dernier_entendu": time.time()}]}, format="json")
        assert r.status_code == 200
        contact = ContactMeshtastic.objects.get(node_num=0xD030)
        assert contact.sauts == 3 and contact.dernier_entendu is not None


@pytest.mark.django_db
class TestHistoriqueEtEnvoiGroupe:

    def test_historique_d_un_noeud(self, agent, passerelle, pont):
        maintenant = int(time.time())
        pont.post(f"/api/compagnons-meshtastic/{passerelle.id}/rapporter-telemetrie/", {"mesures": [
            {"node_num": 0xD020, "horodatage": maintenant - 7200, "batterie": 80},
            {"node_num": 0xD020, "horodatage": maintenant - 60, "batterie": 70},
            {"node_num": 0xD021, "horodatage": maintenant - 60, "batterie": 10}], "compteurs": []}, format="json")
        r = _client(agent).get(f"/api/compagnons-meshtastic/{passerelle.id}/tableau/",
                               {"fenetre": "24h", "noeud": 0xD020})
        assert r.status_code == 200
        assert r.data["nombre_mesures"] == 2
        assert [p["v"] for p in r.data["series"]["batterie"]] == [80, 70]
        assert _client(agent).get(f"/api/compagnons-meshtastic/{passerelle.id}/tableau/",
                                  {"noeud": "x"}).status_code == 400

    def test_les_messages_de_plusieurs_canaux_en_un_appel(self, create_user, institution, passerelle, pont):
        from core.models import CanalMeshtastic, MessageCanalMeshtastic
        a = CanalMeshtastic.objects.create(nom="A", institution=institution)
        b = CanalMeshtastic.objects.create(nom="B", institution=institution)
        c = CanalMeshtastic.objects.create(nom="C", institution=institution)
        for canal in (a, b, c):
            MessageCanalMeshtastic.objects.create(canal=canal, direction="SORTANT", statut="EN_ATTENTE",
                                                  contenu=f"pour {canal.nom}")
        r = pont.get("/api/messages-canal-meshtastic/a-envoyer/",
                     {"canaux": f"{a.id},{b.id},pas-un-uuid", "compagnon": str(passerelle.id)})
        assert r.status_code == 200
        assert sorted(m["canal"] for m in r.data) == sorted([str(a.id), str(b.id)])
        assert pont.get("/api/messages-canal-meshtastic/a-envoyer/", {"canaux": ""}).data == []


@pytest.mark.django_db
def test_metriques_de_telemetrie(passerelle):
    from django.utils import timezone
    from core.metrics import MeshStateCollector
    maintenant = timezone.now()
    MesureTelemetrieMeshtastic.objects.create(compagnon=passerelle, node_num=GW, horodatage=maintenant,
                                              occupation_canal=31.5)
    MesureTelemetrieMeshtastic.objects.create(compagnon=passerelle, node_num=0xD020, horodatage=maintenant,
                                              occupation_canal=80, batterie=12)
    MesureTelemetrieMeshtastic.objects.create(compagnon=passerelle, node_num=0xD021, horodatage=maintenant,
                                              batterie=101)          # secteur : pas une batterie faible
    familles = {f.name: f for f in MeshStateCollector._telemetrie_meshtastic()}
    (occupation,) = familles["assista_meshtastic_occupation_canal_max_pourcent"].samples
    assert occupation.value == 31.5        # la passerelle seulement, pas le nœud distant à 80 %
    (faibles,) = familles["assista_meshtastic_noeuds_batterie_faible"].samples
    assert faibles.value == 1
