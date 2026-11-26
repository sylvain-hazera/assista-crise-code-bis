"""Marqueurs terrain (26/11/2026) : format MeshCore SAR lu derrière les préfixes, entrée par la
radio Meshtastic et MeshCore, relais entre protocoles, dédoublonnage, routes à trois états,
régulation prévenue, API, synchronisation satellite, positions partagées."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import marqueurs_terrain as mt
from core.models import (
    CanalMeshCore, CanalMeshtastic, ContactInstitution, Crisis, DernierePositionUtilisateur, DirectionMessageMesh,
    InscriptionPoste, Institution, InstitutionType, Manifestation, MarqueurTerrain, MessageCanalMeshCore,
    MessageCanalMeshtastic, Mission, Notification, PosteManifestation, Team,
)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestFormat:
    def test_lire_les_formes_de_sar(self):
        assert mt.lire("S:🔥:0:44.84,-0.58:départ de feu")["note"] == "départ de feu"
        assert mt.lire("S:📦:44.84,-0.58")["emoji"] == "📦"          # ancienne forme
        assert mt.lire("S:🔥:0:44.84,-0.58:rdv 14:30")["note"] == "rdv 14:30"

    def test_lire_derriere_un_ou_deux_prefixes(self):
        # La radio MeshCore ajoute « Nom: », le relais du canal de crise ajoute l'auteur.
        assert mt.lire("Léa: S:⛔:0:44.84000,-0.58000")["genre"] == "ROUTE_COUPEE"
        assert mt.lire("Passerelle: Léa: S:⛔:0:44.84000,-0.58000")["genre"] == "ROUTE_COUPEE"

    def test_refuse_ce_qui_n_en_est_pas(self):
        assert mt.lire("Attention: route coupée D20") is None
        assert mt.lire("S:🔥:0:95,2") is None
        assert mt.lire("bonjour") is None

    def test_cinq_etats_de_route_et_anciens_marqueurs(self):
        assert mt.genre_de("⛔", "2 sens · arbre")[0] == "ROUTE_COUPEE_2S"
        assert mt.genre_de("⛔", "1 sens")[0] == "ROUTE_COUPEE_1S"
        assert mt.genre_de("🚧", "1 file, 1 sens · alternat")[0] == "ROUTE_FILE_1S"
        assert mt.genre_de("🚧", "1 file, 2 sens")[0] == "ROUTE_FILE_2S"
        assert mt.genre_de("✅", "")[0] == "ROUTE_LIBEREE"
        # Sans précision (avant le 27/11/2026) : lus, sens non précisé.
        assert mt.genre_de("⛔", "arbre") == ("ROUTE_COUPEE", "Route coupée, sens non précisé")
        assert mt.genre_de("🚧", "")[0] == "ROUTE_UNE_VOIE"
        assert mt.note_de_route("ROUTE_FILE_2S", "alternat") == "1 file, 2 sens · alternat"
        assert mt.note_libre("1 sens · arbre en travers") == "arbre en travers"
        assert mt.note_libre("1 sensation bizarre") == "1 sensation bizarre"

    def test_secours_a_personne_remplace_personne_trouvee_et_blesse(self):
        assert mt.genre_de("🆘") == ("SECOURS", "Secours à personne")
        assert mt.genre_de("🧑")[0] == mt.genre_de("🚑")[0] == "SECOURS"

    def test_ecrire(self):
        assert mt.ecrire("🚧", 44.84, -0.58, "une voie\nalternat") == "S:🚧:0:44.84000,-0.58000:une voie alternat"


@pytest.fixture
def scene(db, create_user):
    """Une crise avec ses deux canaux radio, une équipe engagée (chef et régulateur), et un
    bénévole d'une autre équipe sans lien avec la crise."""
    crise = Crisis.objects.create(name="Crue de la Garonne", location=Point(-0.58, 44.84), environment="PROD")
    regulateur = create_user(username="regul-mq@test.fr", email="regul-mq@test.fr", type="VOLUNTEER")
    chef = create_user(username="chef-mq@test.fr", email="chef-mq@test.fr", type="VOLUNTEER")
    lea = create_user(username="lea-mq@test.fr", email="lea-mq@test.fr", type="VOLUNTEER", first_name="Léa", last_name="Martin")
    max_ = create_user(username="max-mq@test.fr", email="max-mq@test.fr", type="VOLUNTEER")
    intrus = create_user(username="intrus-mq@test.fr", email="intrus-mq@test.fr", type="VOLUNTEER")
    pont = create_user(username="pont-mq@assista-crise.local", email="pont-mq@assista-crise.local", type="ADMIN")
    alpha = Team.objects.create(name="Alpha", leader=chef, regulateur=regulateur)
    alpha.members.add(lea)
    bravo = Team.objects.create(name="Bravo")
    bravo.members.add(max_)
    autre = Team.objects.create(name="Hors crise")
    autre.members.add(intrus)
    for equipe in (alpha, bravo):
        mission = Mission.objects.create(titre=f"Mission {equipe.name}", crise=crise, statut="EN_COURS", environment="PROD")
        mission.equipes.add(equipe)
    mt_canal = CanalMeshtastic.objects.create(nom="Crise-Garonne", crise=crise, psk_hex="00" * 16)
    mc_canal = CanalMeshCore.objects.create(nom="#crise-garonne", crise=crise)
    return {"crise": crise, "regulateur": regulateur, "chef": chef, "lea": lea, "max": max_, "intrus": intrus,
            "pont": _client(pont), "mt": mt_canal, "mc": mc_canal, "alpha": alpha}


def _entrant(scene, protocole, contenu):
    url, canal = (("messagecanalmeshtastic-list", scene["mt"]) if protocole == "MESHTASTIC"
                  else ("messagecanalmeshcore-list", scene["mc"]))
    r = scene["pont"].post(reverse(url), {"canal": str(canal.id), "direction": "ENTRANT", "contenu": contenu}, format="json")
    assert r.status_code in (200, 201), r.data


@pytest.mark.django_db
class TestEntreeRadio:
    def test_marqueur_meshcore_sur_la_carte_de_la_crise_et_relaye_vers_meshtastic(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:🔥:0:44.85000,-0.57000:départ de feu")
        m = MarqueurTerrain.objects.get()
        assert (m.crise, m.genre, m.source, m.auteur_libre) == (scene["crise"], "FEU", "MESHCORE", "Léa")
        assert m.location.y == pytest.approx(44.85)
        # Le relais du canal de crise le porte sur Meshtastic, lisible par l'application et SAR.
        relais = MessageCanalMeshtastic.objects.get(canal=scene["mt"], direction=DirectionMessageMesh.SORTANT)
        assert mt.lire(relais.contenu)["emoji"] == "🔥"

    def test_meshtastic_aussi(self, scene):
        _entrant(scene, "MESHTASTIC", "S:🧑:0:44.85000,-0.57000:personne retrouvée")
        assert MarqueurTerrain.objects.get().source == "MESHTASTIC"

    def test_le_meme_marqueur_entendu_deux_fois_n_est_enregistre_qu_une_fois(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:🔥:0:44.85000,-0.57000")
        _entrant(scene, "MESHTASTIC", "Léa: S:🔥:0:44.85000,-0.57000")
        assert MarqueurTerrain.objects.count() == 1

    def test_un_message_ordinaire_ne_cree_rien(self, scene):
        _entrant(scene, "MESHCORE", "Léa: Attention: route coupée D20")
        assert MarqueurTerrain.objects.count() == 0

    def test_le_regulateur_est_prevenu(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:⛔:0:44.85000,-0.57000:2 sens · arbre en travers")
        notes = Notification.objects.filter(utilisateur__in=[scene["regulateur"], scene["chef"]])
        assert notes.count() == 2
        assert all("Route coupée dans les 2 sens" in n.titre for n in notes)

    def test_canal_d_equipe_rattache_a_la_crise_de_la_mission(self, scene):
        canal = CanalMeshCore.objects.create(nom="AC-ALPHA", equipe=scene["alpha"])
        r = scene["pont"].post(reverse("messagecanalmeshcore-list"), {
            "canal": str(canal.id), "direction": "ENTRANT", "contenu": "Léa: S:🌊:0:44.86000,-0.56000"}, format="json")
        assert r.status_code == 201, r.data
        assert MarqueurTerrain.objects.get().crise == scene["crise"]


@pytest.mark.django_db
class TestRoutes:
    def test_un_nouvel_etat_remplace_le_precedent(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:⛔:0:44.85000,-0.57000")
        _entrant(scene, "MESHCORE", "Léa: S:🚧:0:44.85001,-0.57001:alternat")
        coupee, une_voie = MarqueurTerrain.objects.order_by("cree_le")
        coupee.refresh_from_db()
        assert not coupee.actif and une_voie.actif and une_voie.remplace == coupee

    def test_le_pc_libere_l_axe_et_cela_repart_par_la_radio(self, scene, create_user):
        _entrant(scene, "MESHCORE", "Léa: S:⛔:0:44.85000,-0.57000")
        marqueur = MarqueurTerrain.objects.get()
        pc = create_user(username="pc-mq@test.fr", email="pc-mq@test.fr", type="AUT_LOCALE")
        r = _client(pc).patch(reverse("marqueur_terrain", args=[marqueur.id]), {"etat_route": "ROUTE_LIBEREE"}, format="json")
        assert r.status_code == 200, r.data
        assert r.data["emoji"] == "✅"
        sortants = [m.contenu for m in MessageCanalMeshCore.objects.filter(direction=DirectionMessageMesh.SORTANT)]
        assert any(c.startswith("S:✅:0:44.85000,-0.57000") for c in sortants)

    def test_le_sens_change_et_la_note_libre_reste(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:⛔:0:44.85000,-0.57000:1 sens · arbre en travers")
        marqueur = MarqueurTerrain.objects.get()
        assert marqueur.genre == "ROUTE_COUPEE_1S"
        r = _client(scene["max"]).patch(reverse("marqueur_terrain", args=[marqueur.id]), {"etat_route": "ROUTE_COUPEE_2S"}, format="json")
        assert r.status_code == 200, r.data
        # Même émoji, autre sens : pas pris pour un doublon, l'ancien est remplacé.
        assert (r.data["genre"], r.data["note"]) == ("ROUTE_COUPEE_2S", "2 sens · arbre en travers")
        marqueur.refresh_from_db()
        assert not marqueur.actif
        r = _client(scene["max"]).patch(reverse("marqueur_terrain", args=[r.data["id"]]), {"etat_route": "ROUTE_FILE_2S"}, format="json")
        assert (r.data["emoji"], r.data["libelle"]) == ("🚧", "1 file fermée dans les 2 sens")

    def test_le_terrain_peut_aussi_changer_l_etat(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:⛔:0:44.85000,-0.57000")
        marqueur = MarqueurTerrain.objects.get()
        r = _client(scene["max"]).patch(reverse("marqueur_terrain", args=[marqueur.id]), {"etat_route": "ROUTE_FILE_1S"}, format="json")
        assert r.status_code == 200, r.data

    def test_un_feu_n_a_pas_d_etat_de_route(self, scene):
        _entrant(scene, "MESHCORE", "Léa: S:🔥:0:44.85000,-0.57000")
        marqueur = MarqueurTerrain.objects.get()
        r = _client(scene["lea"]).patch(reverse("marqueur_terrain", args=[marqueur.id]), {"etat_route": "ROUTE_LIBEREE"}, format="json")
        assert r.status_code == 400


@pytest.mark.django_db
class TestApi:
    def test_l_application_pose_un_marqueur_qui_part_par_les_deux_radios(self, scene):
        r = _client(scene["lea"]).post(reverse("marqueurs_terrain"), {
            "crise": str(scene["crise"].id), "emoji": "🔥", "latitude": 44.85, "longitude": -0.57, "note": "fumée",
            "source": "APPLICATION"}, format="json")
        assert r.status_code == 201, r.data
        assert r.data["source"] == "APPLICATION"
        # Colonne chiffrée : filtrée en Python, jamais en SQL.
        for modele in (MessageCanalMeshtastic, MessageCanalMeshCore):
            sortants = [m.contenu for m in modele.objects.filter(direction=DirectionMessageMesh.SORTANT)]
            assert [c for c in sortants if c.startswith("S:🔥")] == ["S:🔥:0:44.85000,-0.57000:fumée"]

    def test_deja_parti_par_la_radio_du_telephone(self, scene):
        r = _client(scene["lea"]).post(reverse("marqueurs_terrain"), {
            "crise": str(scene["crise"].id), "emoji": "🔥", "latitude": 44.85, "longitude": -0.57,
            "source": "APPLICATION", "deja_par_radio": True}, format="json")
        assert r.status_code == 201, r.data
        assert MessageCanalMeshCore.objects.filter(direction=DirectionMessageMesh.SORTANT).count() == 0

    def test_deja_emis_en_meshcore_l_autre_reseau_reste_servi(self, scene):
        r = _client(scene["lea"]).post(reverse("marqueurs_terrain"), {
            "crise": str(scene["crise"].id), "emoji": "⛔", "latitude": 44.85, "longitude": -0.57,
            "source": "APPLICATION", "deja_par_radio": "MESHCORE"}, format="json")
        assert r.status_code == 201, r.data
        assert MessageCanalMeshCore.objects.filter(direction=DirectionMessageMesh.SORTANT).count() == 0
        assert MessageCanalMeshtastic.objects.filter(direction=DirectionMessageMesh.SORTANT).count() == 1

    def test_deja_emis_sur_les_deux_canaux_de_crise(self, scene):
        # L'application a coché les deux canaux de crise (MeshCore et Meshtastic) : « true ».
        r = _client(scene["lea"]).post(reverse("marqueurs_terrain"), {
            "crise": str(scene["crise"].id), "emoji": "🆘", "latitude": 44.85, "longitude": -0.57,
            "source": "APPLICATION", "deja_par_radio": "true"}, format="json")
        assert r.status_code == 201, r.data
        assert MessageCanalMeshCore.objects.filter(direction=DirectionMessageMesh.SORTANT).count() == 0
        assert MessageCanalMeshtastic.objects.filter(direction=DirectionMessageMesh.SORTANT).count() == 0

    def test_hors_de_la_crise_refuse_et_invisible(self, scene):
        r = _client(scene["intrus"]).post(reverse("marqueurs_terrain"), {
            "crise": str(scene["crise"].id), "emoji": "🔥", "latitude": 44.85, "longitude": -0.57}, format="json")
        assert r.status_code == 403
        _entrant(scene, "MESHCORE", "Léa: S:🔥:0:44.85000,-0.57000")
        assert _client(scene["intrus"]).get(reverse("marqueurs_terrain")).data == []
        assert len(_client(scene["max"]).get(reverse("marqueurs_terrain"), {"crise": str(scene["crise"].id)}).data) == 1

    def test_seule_la_regulation_decide_et_un_marqueur_clos_disparait(self, scene, create_user):
        _entrant(scene, "MESHCORE", "Léa: S:🔥:0:44.85000,-0.57000")
        marqueur = MarqueurTerrain.objects.get()
        url = reverse("marqueur_terrain", args=[marqueur.id])
        assert _client(scene["max"]).patch(url, {"decision": "CLOS"}, format="json").status_code == 403
        pc = create_user(username="pc2-mq@test.fr", email="pc2-mq@test.fr", type="AUT_LOCALE")
        assert _client(pc).patch(url, {"decision": "CLOS"}, format="json").status_code == 200
        assert _client(pc).get(reverse("marqueurs_terrain")).data == []

    def test_la_note_est_chiffree_en_base(self, scene):
        _entrant(scene, "MESHCORE", "Ninon: S:🧑:0:44.85000,-0.57000:enfant retrouvé près du lavoir")
        with connection.cursor() as c:
            c.execute(f"SELECT note, auteur_libre FROM {MarqueurTerrain._meta.db_table}")
            note, auteur = c.fetchone()
        assert "lavoir" not in note and "Ninon" not in auteur
        assert MarqueurTerrain.objects.get().note == "enfant retrouvé près du lavoir"


@pytest.mark.django_db
class TestManifestation:
    @pytest.fixture
    def manif(self, create_user):
        itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
        asso = Institution.objects.create(nom="Radio-club d'essai mq", type=itype)
        bureau = create_user(username="bureau-mq@test.fr", email="bureau-mq@test.fr", type="VOLUNTEER")
        a = create_user(username="sig-a@test.fr", email="sig-a@test.fr", type="VOLUNTEER")
        b = create_user(username="sig-b@test.fr", email="sig-b@test.fr", type="VOLUNTEER")
        dehors = create_user(username="dehors-mq@test.fr", email="dehors-mq@test.fr", type="VOLUNTEER")
        ContactInstitution.objects.create(institution=asso, utilisateur=bureau, actif=True, membre_bureau=True)
        for u in (a, b):
            ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True)
        maintenant = timezone.now()
        m = Manifestation.objects.create(institution=asso, titre="Course cycliste", statut="PUBLIEE",
                                         debut=maintenant - datetime.timedelta(hours=1), fin=maintenant + datetime.timedelta(hours=3))
        poste = PosteManifestation.objects.create(manifestation=m, intitule="Carrefour", places=5,
                                                  debut=m.debut, fin=m.fin)
        for u in (a, b):
            InscriptionPoste.objects.create(poste=poste, utilisateur=u, statut="PRESENT")
        for u in (a, b, dehors):
            DernierePositionUtilisateur.objects.create(utilisateur=u, location=Point(-0.5, 44.9), environment="PROD")
        return {"m": m, "bureau": bureau, "a": a, "b": b, "dehors": dehors}

    def test_les_presents_de_la_manifestation_se_voient(self, manif):
        ids = {str(p["utilisateur"]) for p in _client(manif["a"]).get(reverse("positions_equipes")).data}
        assert str(manif["b"].id) in ids and str(manif["dehors"].id) not in ids

    def test_marqueur_de_manifestation_previent_le_bureau(self, manif):
        r = _client(manif["a"]).post(reverse("marqueurs_terrain"), {
            "manifestation": str(manif["m"].id), "emoji": "🚑", "latitude": 44.9, "longitude": -0.5,
            "source": "APPLICATION"}, format="json")
        assert r.status_code == 201, r.data
        assert Notification.objects.filter(utilisateur=manif["bureau"]).count() == 1
        assert len(_client(manif["b"]).get(reverse("marqueurs_terrain"), {"manifestation": str(manif["m"].id)}).data) == 1


@pytest.mark.django_db
class TestPositionsDeLaCrise:
    def test_les_intervenants_de_la_meme_crise_se_voient(self, scene):
        for u in (scene["lea"], scene["max"], scene["intrus"]):
            DernierePositionUtilisateur.objects.create(utilisateur=u, location=Point(-0.5, 44.9), environment="PROD")
        ids = {str(p["utilisateur"]) for p in _client(scene["lea"]).get(reverse("positions_equipes")).data}
        # Max est dans une autre équipe, mais sur la même crise ; l'intrus non.
        assert str(scene["max"].id) in ids and str(scene["intrus"].id) not in ids


@pytest.mark.django_db
class TestSynchronisation:
    def test_le_marqueur_est_synchronisable(self, scene):
        from core import sync_outbox
        _entrant(scene, "MESHCORE", "Léa: S:🔥:0:44.85000,-0.57000:fumée")
        payload = sync_outbox.construire_payload(MarqueurTerrain.objects.get(), "MarqueurTerrain")
        assert "MarqueurTerrain" in sync_outbox.MUTABLE
        assert payload["emoji"] == "🔥" and payload["note"] == "fumée" and payload["crise_id"] == str(scene["crise"].id)
