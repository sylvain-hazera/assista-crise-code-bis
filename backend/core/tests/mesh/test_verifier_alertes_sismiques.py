"""Couvre la diffusion communautaire EMCOM du management command verifier_alertes_sismiques --
voir sa docstring. Avant ce fichier, aucun test n'existait pour cette commande ; on se limite
ici à la partie ajoutée le 16/10 (diffusion MeshCore "Public" en plus de Meshtastic Fr_EMCOM),
pas à l'appel aux API sismiques externes (franceseisme.fr/EMSC), hors de portée d'un test
unitaire sans mock réseau dédié."""
import pytest
from django.utils import timezone

from core.management.commands.verifier_alertes_sismiques import Command
from core.models import (
    CanalMeshCore, CanalMeshtastic, CompagnonMeshCore, CompagnonMeshtastic,
    MessageCanalMeshCore, MessageCanalMeshtastic, SeismeDiffuse,
)

EVT = {
    "event_id": "fr-test-1", "date": timezone.now(), "latitude": 44.8, "longitude": -0.6,
    "magnitude": 4.2, "lieu": "near Bordeaux (France hexagonale)", "sources": {"FR"},
}


@pytest.mark.django_db
class TestDiffusionEmcom:

    def test_meshcore_public_recoit_le_meme_message_que_meshtastic_emcom(self):
        """Les deux canaux communautaires (Fr_EMCOM côté Meshtastic, Public côté MeshCore)
        reçoivent le même texte -- demande utilisateur du 16/10."""
        CompagnonMeshtastic.objects.create(nom='Compagnon test', node_num=12345)
        canal_mt = CanalMeshtastic.objects.create(nom='Fr_EMCOM', actif=True)
        canal_mc = CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, canal_idx=0, actif=True,
        )

        diffuse = Command()._diffuser_emcom(EVT)

        assert diffuse is True
        msg_mt = MessageCanalMeshtastic.objects.get(canal=canal_mt)
        msg_mc = MessageCanalMeshCore.objects.get(canal=canal_mc)
        assert msg_mt.contenu == msg_mc.contenu
        assert "4.2" in msg_mt.contenu and "Bordeaux" in msg_mt.contenu
        assert SeismeDiffuse.objects.filter(event_id="fr-test-1").count() == 1

    def test_meshcore_diffuse_meme_sans_canal_meshtastic(self):
        """Les deux diffusions sont indépendantes : l'absence de Fr_EMCOM ne doit jamais
        empêcher la diffusion MeshCore (ni l'inverse, voir le test symétrique ci-dessous)."""
        canal_mc = CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, canal_idx=0, actif=True,
        )

        diffuse = Command()._diffuser_emcom({**EVT, "event_id": "fr-test-2"})

        assert diffuse is True
        assert MessageCanalMeshCore.objects.filter(canal=canal_mc).exists()
        assert not MessageCanalMeshtastic.objects.exists()

    def test_meshtastic_diffuse_meme_sans_canal_meshcore_public(self):
        CompagnonMeshtastic.objects.create(nom='Compagnon test', node_num=12345)
        canal_mt = CanalMeshtastic.objects.create(nom='Fr_EMCOM', actif=True)

        diffuse = Command()._diffuser_emcom({**EVT, "event_id": "fr-test-3"})

        assert diffuse is True
        assert MessageCanalMeshtastic.objects.filter(canal=canal_mt).exists()
        assert not MessageCanalMeshCore.objects.exists()

    def test_aucun_canal_communautaire_ne_diffuse_rien(self):
        """Ni Fr_EMCOM ni Public n'existent (phase de test) : pas une erreur, juste rien à
        diffuser -- aucun SeismeDiffuse créé (sinon l'évènement serait marqué diffusé à tort,
        bloquant un futur passage une fois les canaux réellement créés)."""
        diffuse = Command()._diffuser_emcom({**EVT, "event_id": "fr-test-4"})

        assert diffuse is False
        assert not SeismeDiffuse.objects.exists()

    def test_canal_public_inactif_ignore(self):
        """Un canal MeshCore "Public" désactivé (actif=False) ne doit jamais recevoir de
        diffusion -- même garde que pour les canaux par institution."""
        CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, canal_idx=0, actif=False,
        )

        diffuse = Command()._diffuser_emcom({**EVT, "event_id": "fr-test-5"})

        assert diffuse is False
        assert not MessageCanalMeshCore.objects.exists()

    def test_un_canal_public_par_companion(self):
        """Plusieurs companions ayant chacun détecté le canal Public (voir
        signaler_canaux_detectes) reçoivent chacun leur propre message -- pas de risque de
        collision ici, contrairement à Meshtastic (MessageCanalMeshCore n'a pas de champ
        `compagnon`, chaque CanalMeshCore "Public" est déjà lié à SON companion)."""
        c1 = CompagnonMeshCore.objects.create(nom='Companion 1', connexion_type='TCP', tcp_host='127.0.0.1', tcp_port=5000)
        c2 = CompagnonMeshCore.objects.create(nom='Companion 2', connexion_type='TCP', tcp_host='127.0.0.1', tcp_port=5001)
        CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, canal_idx=0, actif=True, compagnon=c1,
        )
        CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, canal_idx=0, actif=True, compagnon=c2,
        )

        diffuse = Command()._diffuser_emcom({**EVT, "event_id": "fr-test-6"})

        assert diffuse is True
        assert MessageCanalMeshCore.objects.count() == 2
