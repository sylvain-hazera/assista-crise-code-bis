"""Canaux de crise alignés et messagerie interne (23/11/2026). Règle de Sylvain : « je préfère des
messages qui tombent dans un pot commun et à trier manuellement que des messages perdus »."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core import conversations as conv
from core.canaux_locaux import canaux_de_crise
from core.models import (
    CanalMeshCore, CanalMeshtastic, Crisis, DossierCommentaire, GenreConversation, MessageCanalMeshCore,
    MessageCanalMeshtastic, MessageConversation, Team, UserRole,
)
from core.routage_canaux import lire_adresse, proposer_indicatif


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def scene(db, create_user):
    crise = Crisis.objects.create(name="Inondation Gier", type="INONDATION", location=Point(4.51, 45.47, srid=4326))
    alpha = Team.objects.create(name="Équipe Alpha", indicatif="ALPHA")
    bravo = Team.objects.create(name="Bravo")
    alpha.assigned_crises.add(crise)
    bravo.assigned_crises.add(crise)
    membre = create_user(username="membre-canal@test.fr", email="membre-canal@test.fr", type=UserRole.SIMPLE_USER)
    alpha.members.add(membre)
    regul = create_user(username="regul-canal@test.fr", email="regul-canal@test.fr", type=UserRole.SIMPLE_USER)
    bravo.regulateur = regul
    bravo.save()
    pont = create_user(username="pont-canal@assista-crise.local", email="pont-canal@assista-crise.local", type="ADMIN")
    mt, mc = canaux_de_crise(crise, "PROD")
    return {"crise": crise, "alpha": alpha, "bravo": bravo, "membre": membre, "regul": regul,
            "pont": _client(pont), "mt": mt, "mc": mc}


def _recevoir(scene, protocole, contenu, canal=None):
    nom_url = "messagecanalmeshtastic-list" if protocole == "MESHTASTIC" else "messagecanalmeshcore-list"
    canal = canal or (scene["mt"] if protocole == "MESHTASTIC" else scene["mc"])
    r = scene["pont"].post(reverse(nom_url), {"canal": str(canal.id), "direction": "ENTRANT", "contenu": contenu}, format="json")
    assert r.status_code in (200, 201), r.data      # 200 : copie d'un message déjà reçu


def _textes(conversation):
    return [m.texte for m in conversation.messages.all()]


@pytest.mark.django_db
class TestRangement:
    def test_le_canal_de_crise_a_son_jumeau_meshcore(self, scene):
        assert scene["mc"].nom == "#" + scene["mt"].nom.lower() and scene["mc"].crise == scene["crise"]
        assert scene["mc"].cle_partagee_hex == CanalMeshCore.derive_cle_publique(scene["mc"].nom)

    def test_adresse_a_une_equipe(self, scene):
        _recevoir(scene, "MESHTASTIC", "@ALPHA rendez-vous au pont")
        equipe = conv.conversation_equipe(scene["alpha"], scene["crise"])
        assert _textes(equipe) == ["rendez-vous au pont"]
        # Le fil du canal, lui, a tout.
        assert _textes(conv.conversation_crise(scene["crise"])) == ["@ALPHA rendez-vous au pont"]

    def test_adresse_a_la_cellule(self, scene):
        _recevoir(scene, "MESHCORE", "Léa: @PC besoin d'un groupe électrogène")
        cellule = conv.conversation_crise(scene["crise"], GenreConversation.CELLULE)
        [m] = cellule.messages.all()
        assert m.texte == "besoin d'un groupe électrogène" and m.auteur_libre == "Léa"

    def test_sans_adresse_ou_adresse_inconnue_le_pot_commun(self, scene):
        _recevoir(scene, "MESHTASTIC", "qui est sur la D88 ?")
        _recevoir(scene, "MESHTASTIC", "@ZOULOU on arrive")
        a_trier = conv.conversation_crise(scene["crise"], GenreConversation.A_TRIER)
        assert _textes(a_trier) == ["qui est sur la D88 ?", "@ZOULOU on arrive"]

    def test_l_ancien_canal_d_equipe_arrive_dans_la_conversation_de_l_equipe(self, scene):
        ancien = CanalMeshtastic.objects.create(nom="Alpha", equipe=scene["alpha"], psk_hex="ab" * 16)
        _recevoir(scene, "MESHTASTIC", "on rentre", canal=ancien)
        assert _textes(conv.conversation_equipe(scene["alpha"], scene["crise"])) == ["on rentre"]

    def test_relais_vers_l_autre_protocole_sans_boucle(self, scene):
        _recevoir(scene, "MESHTASTIC", "@ALPHA rendez-vous au pont")
        [relais] = MessageCanalMeshCore.objects.filter(canal=scene["mc"], direction="SORTANT")
        assert relais.contenu.endswith("@ALPHA rendez-vous au pont") and relais.statut == "EN_ATTENTE"
        # La passerelle MeshCore réentend la recopie : écho, ni rangée ni re-relayée.
        _recevoir(scene, "MESHCORE", "Passerelle: " + relais.contenu)
        assert MessageCanalMeshtastic.objects.filter(canal=scene["mt"], direction="SORTANT").count() == 0
        assert len(_textes(conv.conversation_equipe(scene["alpha"], scene["crise"]))) == 1

    def test_deux_passerelles_un_seul_message(self, scene):
        _recevoir(scene, "MESHTASTIC", "qui est sur la D88 ?")
        _recevoir(scene, "MESHTASTIC", "qui est sur la D88 ?")
        a_trier = conv.conversation_crise(scene["crise"], GenreConversation.A_TRIER)
        [m] = a_trier.messages.all()
        assert len(m.recu_par) == 1      # même compte de pont : une seule provenance

    def test_lire_adresse_et_indicatifs(self):
        assert lire_adresse("@alpha, on arrive") == ("ALPHA", "on arrive")
        assert lire_adresse("on arrive") == (None, "on arrive")
        assert proposer_indicatif("Équipe Alpha") == "ALPHA"
        assert proposer_indicatif("Alpha", {"ALPHA"}) == "ALPHA2"


@pytest.mark.django_db
class TestEnvoi:
    def test_ecrire_a_l_equipe_part_sur_le_canal_de_crise_prefixe(self, scene):
        r = _client(scene["membre"]).post(reverse("team-messagerie-unifiee", args=[scene["alpha"].id]),
                                          {"texte": "on arrive", "deja_emis_radio": "MESHCORE"}, format="json")
        assert r.status_code == 200, r.data
        [mt] = MessageCanalMeshtastic.objects.filter(canal=scene["mt"], direction="SORTANT")
        [mc] = MessageCanalMeshCore.objects.filter(canal=scene["mc"], direction="SORTANT")
        assert mt.contenu == "@ALPHA on arrive" and mt.statut == "EN_ATTENTE"
        assert mc.statut == "ENVOYE"                  # le téléphone l'a déjà émis
        assert r.data["messages"][-1]["texte"] == "on arrive" and r.data["indicatif"] == "ALPHA"

    def test_une_equipe_sans_indicatif_en_recoit_un(self, scene):
        _client(scene["regul"]).post(reverse("team-messagerie-unifiee", args=[scene["bravo"].id]),
                                     {"texte": "point à 18h"}, format="json")
        scene["bravo"].refresh_from_db()
        assert scene["bravo"].indicatif == "BRAVO"
        assert MessageCanalMeshtastic.objects.get(canal=scene["mt"]).contenu == "@BRAVO point à 18h"

    def test_le_message_est_chiffre_en_base(self, scene):
        from django.db import connection
        _client(scene["membre"]).post(reverse("team-messagerie-unifiee", args=[scene["alpha"].id]),
                                      {"texte": "texte-tres-reconnaissable"}, format="json")
        with connection.cursor() as c:
            c.execute("select texte from core_messageconversation")
            assert all("reconnaissable" not in (ligne[0] or "") for ligne in c.fetchall())


@pytest.mark.django_db
class TestPotCommun:
    def test_a_defaut_d_equipe_transmissions_la_regulation_trie(self, scene):
        _recevoir(scene, "MESHTASTIC", "qui est sur la D88 ?")
        m = MessageConversation.objects.get(conversation__genre=GenreConversation.A_TRIER)
        url = reverse("conversation-ranger", args=[m.id])
        assert _client(scene["membre"]).post(url, {"classer": True}, format="json").status_code == 403
        r = _client(scene["regul"]).post(url, {"equipe": str(scene["alpha"].id)}, format="json")
        assert r.status_code == 200, r.data
        assert _textes(conv.conversation_equipe(scene["alpha"], scene["crise"])) == ["qui est sur la D88 ?"]
        assert _client(scene["regul"]).post(url, {"classer": True}, format="json").status_code == 400   # déjà rangé

    def test_l_equipe_transmissions_trie_quand_elle_existe(self, scene, create_user):
        trans = Team.objects.create(name="Transmissions", transmissions=True)
        trans.assigned_crises.add(scene["crise"])
        op = create_user(username="trans-canal@test.fr", email="trans-canal@test.fr", type=UserRole.SIMPLE_USER)
        trans.members.add(op)
        assert conv.peut_trier(op, scene["crise"]) and not conv.peut_trier(scene["membre"], scene["crise"])

    def test_vers_un_dossier(self, scene):
        from core.models import Dossier
        _recevoir(scene, "MESHTASTIC", "cave inondée rue Haute")
        m = MessageConversation.objects.get(conversation__genre=GenreConversation.A_TRIER)
        dossier = Dossier.objects.create(numero="DOS-CANAL-1", crise=scene["crise"], equipe=scene["alpha"], titre="Cave")
        r = _client(scene["regul"]).post(reverse("conversation-ranger", args=[m.id]), {"dossier": str(dossier.id)}, format="json")
        assert r.status_code == 200, r.data
        assert "cave inondée rue Haute" in DossierCommentaire.objects.get(dossier=dossier).commentaire


@pytest.mark.django_db
class TestTelephones:
    def test_ce_qu_un_telephone_a_entendu_remonte_et_se_range(self, scene):
        corps = {"appareil": "Tablette", "messages": [
            {"identifiant": "a1", "protocole": "MESHTASTIC", "canal": scene["mt"].nom, "auteur": "Léa",
             "texte": "@ALPHA mur fissuré", "entendu_le": "2026-11-23T10:00:00Z"},
            {"identifiant": "a2", "protocole": "MESHCORE", "canal": scene["mc"].nom, "texte": "Max: perdu le réseau"},
        ]}
        client = _client(scene["membre"])
        r = client.post(reverse("radio-entendus"), corps, format="json")
        assert r.status_code == 200 and r.data["acceptes"] == ["a1", "a2"]
        client.post(reverse("radio-entendus"), corps, format="json")          # renvoi : rien de doublé
        [m] = conv.conversation_equipe(scene["alpha"], scene["crise"]).messages.all()
        assert m.texte == "mur fissuré" and m.source == "TELEPHONE_RADIO" and m.auteur_libre == "Léa"
        assert _textes(conv.conversation_crise(scene["crise"], GenreConversation.A_TRIER)) == ["perdu le réseau"]
        # Ce qu'un téléphone remonte après coup n'est pas relayé sur l'autre protocole.
        assert not MessageCanalMeshCore.objects.filter(direction="SORTANT").exists()

    def test_le_plan_radio_de_la_crise(self, scene):
        r = _client(scene["membre"]).get(reverse("radio-plan"), {"crise": str(scene["crise"].id)})
        assert r.status_code == 200, r.data
        assert r.data["meshtastic"][-1] == {"nom": scene["mt"].nom, "psk_hex": "01", "role": "crise"}
        assert r.data["meshcore"][0]["nom"] == scene["mc"].nom and r.data["version"]


@pytest.mark.django_db
class TestConversations:
    def test_mes_conversations(self, scene):
        _recevoir(scene, "MESHTASTIC", "@ALPHA on arrive")
        r = _client(scene["membre"]).get(reverse("conversations"))
        assert r.status_code == 200
        genres = {c["genre"] for c in r.data}
        assert {"EQUIPE", "CRISE"} <= genres and "A_TRIER" not in genres
        equipe = next(c for c in r.data if c["genre"] == "EQUIPE")
        assert equipe["non_lus"] == 1 and equipe["indicatif"] == "ALPHA"
        r = _client(scene["membre"]).get(reverse("conversation-messages", args=[equipe["id"]]))
        assert r.data["messages"][0]["texte"] == "on arrive"
        assert _client(scene["membre"]).get(reverse("conversations")).data[0]["non_lus"] == 0

    def test_on_n_ecrit_pas_dans_le_pot_commun_et_on_ne_lit_pas_ce_qui_n_est_pas_a_soi(self, scene, create_user):
        a_trier = conv.conversation_crise(scene["crise"], GenreConversation.A_TRIER)
        url = reverse("conversation-messages", args=[a_trier.id])
        assert _client(scene["regul"]).post(url, {"texte": "x"}, format="json").status_code == 403
        etranger = create_user(username="etranger-canal@test.fr", email="etranger-canal@test.fr", type=UserRole.SIMPLE_USER)
        equipe = conv.conversation_equipe(scene["alpha"], scene["crise"])
        assert _client(etranger).get(reverse("conversation-messages", args=[equipe.id])).status_code == 403


@pytest.mark.django_db
def test_import_de_l_historique_idempotent(scene, monkeypatch):
    from django.core.management import call_command
    from core import matrix
    from core.models import SalonMatrixEquipe
    SalonMatrixEquipe.objects.create(equipe=scene["alpha"], crise=scene["crise"], room_id="!crue:test")
    monkeypatch.setattr(matrix, "lister_messages_salon", lambda room_id, limite=30: [
        {"event_id": "$e1", "texte": "ok", "horodatage": 1_700_000_000_000, "expediteur_id": str(scene["membre"].id), "urgent": False},
        {"event_id": "$e2", "texte": "ok", "horodatage": 1_700_000_001_000, "expediteur_id": str(scene["membre"].id), "urgent": False},
    ])
    ancien = CanalMeshtastic.objects.create(nom="Alpha", equipe=scene["alpha"], psk_hex="ab" * 16)
    MessageCanalMeshtastic.objects.create(canal=ancien, direction="ENTRANT", contenu="reçu 5/5")
    call_command("importer_messagerie")
    call_command("importer_messagerie")
    textes = [m.texte for m in conv.conversation_equipe(scene["alpha"], scene["crise"]).messages.order_by("emis_le")]
    assert textes.count("ok") == 2 and textes.count("reçu 5/5") == 1


@pytest.mark.django_db
def test_le_pot_commun_de_la_crise_pour_le_pilotage(scene):
    _recevoir(scene, "MESHTASTIC", "qui est sur la D88 ?")
    url = reverse("conversation-a-trier")
    assert _client(scene["membre"]).get(url, {"crise": str(scene["crise"].id)}).status_code == 403
    r = _client(scene["regul"]).get(url, {"crise": str(scene["crise"].id)})
    assert r.status_code == 200 and r.data["trie_par"] == "REGULATION"
    assert [m["texte"] for m in r.data["messages"]] == ["qui est sur la D88 ?"]
    assert {e["indicatif"] for e in r.data["equipes"]} >= {"ALPHA"}


@pytest.mark.django_db
def test_mes_equipes_donne_le_canal_de_crise_et_l_indicatif(scene):
    r = _client(scene["membre"]).get(reverse("team-mes-equipes"))
    assert r.status_code == 200
    alpha = next(e for e in r.data if e["id"] == str(scene["alpha"].id))
    assert alpha["canal_crise"] == {"crise": str(scene["crise"].id), "meshtastic": scene["mt"].nom,
                                    "meshcore": scene["mc"].nom, "indicatif": "ALPHA"}


@pytest.mark.django_db
def test_le_message_emis_par_la_radio_du_telephone_n_est_pas_double(scene):
    # La passerelle entend le téléphone émettre « @ALPHA on arrive » pendant la coupure…
    _recevoir(scene, "MESHTASTIC", "@ALPHA on arrive")
    # … puis le téléphone, de retour sur le réseau, remet le message qu'il a déjà émis.
    r = _client(scene["membre"]).post(reverse("team-messagerie-unifiee", args=[scene["alpha"].id]),
                                      {"texte": "on arrive", "deja_emis_radio": "MESHTASTIC"}, format="json")
    assert r.status_code == 200
    [m] = conv.conversation_equipe(scene["alpha"], scene["crise"]).messages.all()
    assert m.auteur == scene["membre"]
