"""Vérifie que les secrets et les messages du domaine mesh sont bien chiffrés AU REPOS.

Pourquoi en SQL brut et pas via l'ORM : l'ORM déchiffre à la lecture (`from_db_value`), donc un
test écrit avec l'ORM passerait même si la colonne était en clair. Le seul test qui prouve quelque
chose lit la colonne sans passer par le champ Django -- c'est ce que verrait un `pg_dump`.

Ces huit colonnes n'étaient protégées que par `write_only` côté serializer avant le 06/11/2026
(migration 0230), alors que DOCUMENTATION.md § 10.1 les range dans le périmètre chiffré.

Les deux dernières classes verrouillent la conséquence la plus dangereuse du chiffrement : Fernet
n'étant pas déterministe, un `filter()` SQL sur ces colonnes ne trouve plus jamais rien -- et
échoue en silence, sans erreur.
"""
import pytest
from django.db import connection

from core.management.commands.verifier_alertes_sismiques import Command
from core.models import (
    CanalMeshCore, CanalMeshtastic, CompagnonMeshtastic, MessageCanalMeshCore,
    MessageCanalMeshtastic, MessageMeshLog, MessageMeshtasticLog, CompagnonMeshCore,
    DirectionMessageMesh,
)


def colonne_brute(instance, nom_champ):
    """Valeur réellement stockée en base, sans conversion par le champ Django."""
    meta = type(instance)._meta
    with connection.cursor() as curseur:
        curseur.execute(
            f'SELECT "{meta.get_field(nom_champ).column}" FROM "{meta.db_table}" WHERE "id" = %s',
            [str(instance.pk)],
        )
        return curseur.fetchone()[0]


@pytest.mark.django_db
class TestSecretsChiffresAuRepos:

    def test_cle_de_canal_meshcore(self):
        canal = CanalMeshCore.objects.create(nom='Équipe test', cle_partagee_hex='ab' * 16)
        brut = colonne_brute(canal, 'cle_partagee_hex')
        assert 'ab' * 16 not in brut
        assert brut.startswith('gAAAAA')          # en-tête Fernet v1
        assert CanalMeshCore.objects.get(pk=canal.pk).cle_partagee_hex == 'ab' * 16

    def test_psk_de_canal_meshtastic(self):
        canal = CanalMeshtastic.objects.create(nom='EquipeTest', psk_hex='cd' * 16)
        assert 'cd' * 16 not in colonne_brute(canal, 'psk_hex')
        assert CanalMeshtastic.objects.get(pk=canal.pk).psk_hex == 'cd' * 16

    def test_mot_de_passe_mqtt(self):
        compagnon = CompagnonMeshtastic.objects.create(
            nom='Compagnon test', node_num=424242, mqtt_password='motdepasse-broker',
        )
        assert 'motdepasse-broker' not in colonne_brute(compagnon, 'mqtt_password')
        assert CompagnonMeshtastic.objects.get(pk=compagnon.pk).mqtt_password == 'motdepasse-broker'

    def test_cle_privee_x25519_generee_par_save(self):
        """La clé est générée dans `save()` : le test prouve que le chiffrement n'a pas cassé cette
        génération, et que la clé reste exploitable (`x25519_public_key_hex` la dérive)."""
        compagnon = CompagnonMeshtastic.objects.create(nom='Compagnon PKI', node_num=424243)
        privee = compagnon.x25519_private_key_hex
        assert len(privee) == 64
        assert privee not in colonne_brute(compagnon, 'x25519_private_key_hex')
        relu = CompagnonMeshtastic.objects.get(pk=compagnon.pk)
        assert relu.x25519_private_key_hex == privee
        assert len(relu.x25519_public_key_hex) == 64

    @pytest.mark.parametrize('modele', [
        MessageMeshLog, MessageCanalMeshCore, MessageMeshtasticLog, MessageCanalMeshtastic,
    ])
    def test_contenu_des_messages(self, modele):
        """Les quatre modèles de message mesh, comme AlerteMeshSOS qui l'était déjà : un message
        peut contenir un nom, une position ou une blessure."""
        secret = 'Victime au 12 rue des Lilas, jambe cassée'
        champs = {'direction': DirectionMessageMesh.SORTANT, 'contenu': secret}
        if modele in (MessageMeshLog, MessageMeshtasticLog):
            champs['compagnon'] = (
                CompagnonMeshCore.objects.create(nom='C')
                if modele is MessageMeshLog
                else CompagnonMeshtastic.objects.create(nom='C', node_num=999001)
            )
            if modele is MessageMeshtasticLog:
                champs['contact_node_num'] = 999002   # non nul sur ce modèle
        else:
            champs['canal'] = (
                CanalMeshCore.objects.create(nom='c', cle_partagee_hex='11' * 16)
                if modele is MessageCanalMeshCore
                else CanalMeshtastic.objects.create(nom='c', psk_hex='22' * 16)
            )
        message = modele.objects.create(**champs)
        assert secret not in colonne_brute(message, 'contenu')
        assert 'Lilas' not in colonne_brute(message, 'contenu')
        assert modele.objects.get(pk=message.pk).contenu == secret


@pytest.mark.django_db
class TestLesFiltresNeCassentPas:
    """Fernet n'est pas déterministe : deux lignes de même clé ont deux chiffrés différents. Tout
    `filter()` SQL sur ces colonnes est donc définitivement cassé -- ces tests le prouvent, et
    verrouillent les deux appels qui ont dû passer en comparaison Python."""

    def test_un_filter_sql_sur_une_cle_ne_trouve_rien(self):
        """Le piège, rendu explicite : si ce test se met à échouer, c'est que le champ a été
        déchiffré, et les deux comparaisons Python du lot peuvent redevenir du SQL."""
        CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, actif=True,
        )
        assert not CanalMeshCore.objects.filter(
            cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT
        ).exists()

    def test_deux_canaux_de_meme_cle_ont_deux_chiffres_differents(self):
        a = CanalMeshCore.objects.create(nom='A', cle_partagee_hex='ff' * 16)
        b = CanalMeshCore.objects.create(nom='B', cle_partagee_hex='ff' * 16)
        assert colonne_brute(a, 'cle_partagee_hex') != colonne_brute(b, 'cle_partagee_hex')
        assert a.cle_partagee_hex == b.cle_partagee_hex == 'ff' * 16

    def test_la_diffusion_seisme_retrouve_le_canal_public(self):
        """Régression directe : avec le `filter(cle_partagee_hex=...)` d'origine, cette liste
        serait vide et les alertes sismiques ne partiraient plus, sans aucune erreur."""
        canal = CanalMeshCore.objects.create(
            nom='Public', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, actif=True,
        )
        CanalMeshCore.objects.create(nom='Privé', cle_partagee_hex='ab' * 16, actif=True)
        CanalMeshCore.objects.create(
            nom='Public inactif', cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT, actif=False,
        )

        noms, _ = Command()._diffuser_emcom_meshcore('Seisme M4.2 test')

        assert noms == ['Public']
        messages = MessageCanalMeshCore.objects.filter(canal=canal)
        assert messages.count() == 1
        assert messages.first().contenu == 'Seisme M4.2 test'
