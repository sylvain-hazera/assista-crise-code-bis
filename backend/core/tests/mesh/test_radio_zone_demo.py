"""Radio en zone démo (22/10/2026, décision : les vraies radios relaient aussi la démo) : les
ponts n'envoient pas d'en-tête X-Environment, leurs files d'envoi et accusés doivent donc couvrir
les deux zones (ACTIONS_PONTS_RADIO) -- sans quoi les messages de l'équipe de démo CAI restaient
en attente pour toujours. Le reste de l'API garde son cloisonnement PROD / DEMO."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    CanalMeshCore,
    CompagnonMeshCore,
    ProvisionCanalMeshCore,
    CanalMeshtastic,
    MessageCanalMeshCore,
    MessageCanalMeshtastic,
)


@pytest.fixture
def pont(create_user):
    """Compte de service d'un pont : aucun en-tête X-Environment, comme en vrai."""
    compte = create_user(username="pont-demo@assista-crise.local", email="pont-demo@assista-crise.local", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=compte)
    return client


@pytest.fixture
def compagnon_meshcore(db):
    return CompagnonMeshCore.objects.create(nom="Bureau", connexion_type="TCP", dernier_etat="CONNECTE")


@pytest.fixture
def canal_meshcore_demo(compagnon_meshcore):
    canal = CanalMeshCore.objects.create(nom="Équipe CAI", environment="DEMO")
    ProvisionCanalMeshCore.objects.create(canal=canal, compagnon=compagnon_meshcore, canal_idx=11)
    return canal


@pytest.fixture
def canal_meshtastic_demo(db):
    return CanalMeshtastic.objects.create(nom="EquipeCAI", psk_hex="00" * 16, environment="DEMO")


@pytest.mark.django_db
class TestFilesDesPontsCouvrentLaDemo:

    def test_meshcore_message_de_demo_dans_la_file_puis_accuse(self, pont, canal_meshcore_demo, compagnon_meshcore):
        message = MessageCanalMeshCore.objects.create(
            canal=canal_meshcore_demo, direction="SORTANT", contenu="[Démo] recois tu le mesh ?", environment="DEMO",
        )

        file = pont.get(reverse('messagecanalmeshcore-a-envoyer'), {"compagnon": str(compagnon_meshcore.id)})
        assert [m["id"] for m in file.data] == [str(message.id)]
        assert file.data[0]["canal_idx"] == 11

        reponse = pont.patch(reverse('messagecanalmeshcore-detail', args=[message.id]), {"statut": "ENVOYE"}, format="json")
        assert reponse.status_code == 200, reponse.data
        message.refresh_from_db()
        assert message.statut == "ENVOYE"

    def test_meshtastic_cle_du_canal_de_demo_fournie_et_message_dans_la_file(self, pont, canal_meshtastic_demo):
        message = MessageCanalMeshtastic.objects.create(
            canal=canal_meshtastic_demo, direction="SORTANT", contenu="[Démo] recois tu le mesh ?", environment="DEMO",
        )

        cles = pont.get(reverse('canalmeshtastic-avec-cle'))
        assert str(canal_meshtastic_demo.id) in [c["id"] for c in cles.data]

        file = pont.get(reverse('messagecanalmeshtastic-a-envoyer'), {"canal": str(canal_meshtastic_demo.id)})
        assert [m["id"] for m in file.data] == [str(message.id)]

        reponse = pont.patch(reverse('messagecanalmeshtastic-detail', args=[message.id]), {"statut": "ENVOYE"}, format="json")
        assert reponse.status_code == 200, reponse.data

    def test_reponse_radio_sur_canal_de_demo_rangee_en_demo(self, pont, canal_meshcore_demo, canal_meshtastic_demo):
        for nom_url, canal in (("messagecanalmeshcore-list", canal_meshcore_demo),
                               ("messagecanalmeshtastic-list", canal_meshtastic_demo)):
            reponse = pont.post(reverse(nom_url), {"canal": str(canal.id), "direction": "ENTRANT", "contenu": "reçu 5/5"}, format="json")
            assert reponse.status_code == 201, reponse.data

        assert MessageCanalMeshCore.objects.get(direction="ENTRANT").environment == "DEMO"
        assert MessageCanalMeshtastic.objects.get(direction="ENTRANT").environment == "DEMO"


@pytest.mark.django_db
def test_lecture_par_l_interface_reste_cloisonnee(create_user, canal_meshcore_demo):
    MessageCanalMeshCore.objects.create(canal=canal_meshcore_demo, direction="SORTANT", contenu="démo", environment="DEMO")
    admin = create_user(username="admin-radio@test.fr", email="admin-radio@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=admin)

    reponse = client.get(reverse('messagecanalmeshcore-list'), {"canal": str(canal_meshcore_demo.id)})

    assert reponse.status_code == 200
    assert len(reponse.data) == 0          # en PROD, rien de la démo


@pytest.mark.django_db
def test_messagerie_unifiee_masque_l_echo_de_nos_messages(create_user):
    from core.models import SalonMatrixEquipe, Team
    admin = create_user(username="admin-echo@test.fr", email="admin-echo@test.fr", type="ADMIN")
    equipe = Team.objects.create(name="CAI")
    SalonMatrixEquipe.objects.create(equipe=equipe)            # sans room_id : pas d'appel Matrix
    canal = CanalMeshtastic.objects.create(nom="EquipeCAI", equipe=equipe, psk_hex="00" * 16)
    MessageCanalMeshtastic.objects.create(canal=canal, direction="SORTANT", contenu="recois tu le mesh ?", statut="ENVOYE")
    MessageCanalMeshtastic.objects.create(canal=canal, direction="ENTRANT", contenu="Sylvain Moi : recois tu le mesh ?")
    MessageCanalMeshtastic.objects.create(canal=canal, direction="ENTRANT", contenu="Jean : reçu 5/5")
    client = APIClient()
    client.force_authenticate(user=admin)

    reponse = client.get(reverse('team-messagerie-unifiee', args=[equipe.id]))

    assert reponse.status_code == 200, reponse.data
    assert [m["texte"] for m in reponse.data["messages"]] == ["recois tu le mesh ?", "Jean : reçu 5/5"]


@pytest.mark.django_db
def test_message_deja_emis_par_la_radio_du_telephone_n_est_pas_rediffuse(create_user):
    """Application mobile, retour de réseau : le message a déjà voyagé sur le canal MeshCore
    par la radio de l'intervenant. Le pont MeshCore ne doit pas le réémettre ; le pont
    Meshtastic, lui, doit encore le porter à ceux qui sont sur l'autre réseau."""
    from core.models import SalonMatrixEquipe, Team
    membre = create_user(username="terrain-radio@test.fr", email="terrain-radio@test.fr", type="ADMIN")
    equipe = Team.objects.create(name="Alpha radio")
    equipe.members.add(membre)
    SalonMatrixEquipe.objects.create(equipe=equipe)            # sans room_id : pas d'appel Matrix
    meshtastic = CanalMeshtastic.objects.create(nom="AlphaMT", equipe=equipe, psk_hex="00" * 16)
    meshcore = CanalMeshCore.objects.create(nom="#alpha", equipe=equipe)
    client = APIClient()
    client.force_authenticate(user=membre)
    url = reverse('team-messagerie-unifiee', args=[equipe.id])

    reponse = client.post(url, {"texte": "Nous sommes sur place", "deja_emis_radio": "meshcore"}, format="json")

    assert reponse.status_code == 200
    assert MessageCanalMeshCore.objects.get(canal=meshcore).statut == "ENVOYE"
    assert MessageCanalMeshtastic.objects.get(canal=meshtastic).statut == "EN_ATTENTE"

    # Sans le drapeau, ou avec une valeur inconnue, rien ne change : tout part par les ponts.
    client.post(url, {"texte": "Second message", "deja_emis_radio": "n-importe-quoi"}, format="json")
    assert MessageCanalMeshCore.objects.filter(canal=meshcore, statut="EN_ATTENTE").count() == 1
    assert MessageCanalMeshtastic.objects.filter(canal=meshtastic, statut="EN_ATTENTE").count() == 2

    # Deux radios sur le même téléphone (23/11/2026) : déjà émis sur les deux réseaux.
    client.post(url, {"texte": "Troisieme", "deja_emis_radio": "MESHTASTIC,MESHCORE"}, format="json")
    assert MessageCanalMeshCore.objects.filter(canal=meshcore, statut="ENVOYE").count() == 2
    assert MessageCanalMeshtastic.objects.filter(canal=meshtastic, statut="ENVOYE").count() == 1
