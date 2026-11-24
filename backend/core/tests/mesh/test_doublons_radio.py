"""Un message radio entendu par plusieurs relais ou plusieurs radios n'apparaît qu'une fois
(24/11/2026), comme sur les vrais clients ; deux messages identiques à deux instants restent deux."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import conversations as conv
from core.canaux_locaux import canaux_de_crise
from core.models import Crisis, GenreConversation, MessageCanalMeshCore, MessageCanalMeshtastic

URL_MC, URL_MT = "messagecanalmeshcore-list", "messagecanalmeshtastic-list"


@pytest.fixture
def scene(db, create_user):
    crise = Crisis.objects.create(name="Crue du Gier", type="INONDATION", location=Point(4.51, 45.47, srid=4326))
    mt, mc = canaux_de_crise(crise, "PROD")
    ponts = []
    for n in range(2):
        client = APIClient()
        client.force_authenticate(user=create_user(username=f"pont-{n}@assista-crise.local",
                                                   email=f"pont-{n}@assista-crise.local", type="ADMIN"))
        ponts.append(client)
    return {"crise": crise, "mt": mt, "mc": mc, "ponts": ponts}


def _poster(client, url, canal, contenu, **extra):
    return client.post(reverse(url), {"canal": str(canal.id), "direction": "ENTRANT", "contenu": contenu, **extra},
                       format="json")


@pytest.mark.django_db
class TestMeshCore:
    def test_meme_identite_radio_un_seul_message_et_deux_radios_dans_recu_par(self, scene):
        premier = _poster(scene["ponts"][0], URL_MC, scene["mc"], "Léa: route coupée", cle_radio="1764000000:abcd1234")
        copie = _poster(scene["ponts"][1], URL_MC, scene["mc"], "Léa: route coupée", cle_radio="1764000000:abcd1234")
        assert premier.status_code == 201 and copie.status_code == 200
        assert copie.data["id"] == premier.data["id"]
        assert MessageCanalMeshCore.objects.filter(canal=scene["mc"]).count() == 1
        [m] = conv.conversation_crise(scene["crise"], GenreConversation.A_TRIER).messages.all()
        assert len(m.recu_par) == 2
        assert "cle_radio" not in premier.data and "empreinte_radio" not in premier.data

    def test_meme_texte_autre_horodatage_deux_messages(self, scene):
        _poster(scene["ponts"][0], URL_MC, scene["mc"], "Léa: OK", cle_radio="1764000000:aaaa0000")
        _poster(scene["ponts"][0], URL_MC, scene["mc"], "Léa: OK", cle_radio="1764000060:bbbb1111")
        assert MessageCanalMeshCore.objects.filter(canal=scene["mc"]).count() == 2

    def test_sans_identite_meme_texte_dans_les_deux_minutes(self, scene):
        _poster(scene["ponts"][0], URL_MC, scene["mc"], "Léa: on monte au col")
        _poster(scene["ponts"][1], URL_MC, scene["mc"], "Léa: on monte au col")
        assert MessageCanalMeshCore.objects.filter(canal=scene["mc"]).count() == 1
        # Plus de deux minutes après : un nouveau message.
        MessageCanalMeshCore.objects.filter(canal=scene["mc"]).update(date_creation=timezone.now() - datetime.timedelta(minutes=3))
        _poster(scene["ponts"][1], URL_MC, scene["mc"], "Léa: on monte au col")
        assert MessageCanalMeshCore.objects.filter(canal=scene["mc"]).count() == 2

    def test_l_identite_est_gardee_en_hmac(self, scene):
        _poster(scene["ponts"][0], URL_MC, scene["mc"], "Léa: x", cle_radio="1764000000:abcd1234")
        empreinte = MessageCanalMeshCore.objects.get(canal=scene["mc"]).empreinte_radio
        assert empreinte and "1764000000" not in empreinte and len(empreinte) == 64


@pytest.mark.django_db
def test_meshtastic_meme_noeud_meme_texte_un_seul_message(scene):
    a = _poster(scene["ponts"][0], URL_MT, scene["mt"], "route coupée", contact_node_num=1234)
    b = _poster(scene["ponts"][1], URL_MT, scene["mt"], "route coupée", contact_node_num=1234)
    c = _poster(scene["ponts"][1], URL_MT, scene["mt"], "route coupée", contact_node_num=999)
    assert (a.status_code, b.status_code, c.status_code) == (201, 200, 201)
    assert MessageCanalMeshtastic.objects.filter(canal=scene["mt"]).count() == 2


@pytest.mark.django_db
def test_les_doublons_de_l_import_d_historique(scene):
    import io

    from django.core.management import call_command

    conversation = conv.conversation_crise(scene["crise"])
    instant = timezone.now()
    garde, _ = conv.ecrire(conversation, "point à 18h", auteur_libre="Léa", origine="meshcore:1", emis_le=instant,
                           recu_par=["pont-a"], dedupliquer=False)
    conv.ecrire(conversation, "point à 18h", auteur_libre="Léa", origine="meshtastic:1",
                emis_le=instant + datetime.timedelta(milliseconds=2), recu_par=["pont-b"], dedupliquer=False)
    conv.ecrire(conversation, "point à 18h", auteur_libre="Léa", origine="meshtastic:2",
                emis_le=instant + datetime.timedelta(hours=1), dedupliquer=False)      # un autre message

    sortie = io.StringIO()
    call_command("dedoublonner_messagerie", stdout=sortie)
    assert "1 doublon(s). Rien n'est supprimé" in sortie.getvalue() and conversation.messages.count() == 3
    call_command("dedoublonner_messagerie", "--appliquer", stdout=io.StringIO())
    assert conversation.messages.count() == 2
    garde.refresh_from_db()
    assert garde.recu_par == ["pont-a", "pont-b"]
