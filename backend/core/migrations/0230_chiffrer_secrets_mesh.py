"""Chiffrement au repos des secrets et des messages du domaine mesh.

Huit colonnes étaient lisibles dans un `pg_dump` : clés de canaux MeshCore et Meshtastic, mot de
passe du broker MQTT, clé privée X25519, et le contenu des quatre modèles de message mesh. Elles
n'étaient protégées qu'au niveau de l'API (`write_only` dans les serializers), pas au repos --
contraire à la règle du projet et à DOCUMENTATION.md § 10.1, qui liste pourtant « messages mesh »
dans le périmètre chiffré. `AlerteMeshSOS.contenu`, de même nature et de même origine, était déjà
chiffré : c'était une incohérence, pas un choix.

Deux conséquences traitées hors migration, dans le même lot :
  - Fernet n'est pas déterministe, donc aucun `filter()` SQL ne peut plus porter sur ces colonnes.
    Les deux seuls appels concernés passent en comparaison Python (`verifier_alertes_sismiques`
    pour la diffusion séisme, et `signaler_canaux_detectes` pour la garde anti-doublon du canal
    « Public », dont l'échec silencieux aurait recréé ce canal à chaque appel).
  - `EncryptedTextField` garde son `max_length` pour la validation du serializer alors que la
    colonne devient TEXT -- convention déjà en place dans le projet (`nom_noeud`, `long_name`).

Les lignes antérieures restent lisibles sans cette migration : `from_db_value` renvoie la valeur
brute sur `InvalidToken`. La réécriture ci-dessous n'est donc pas nécessaire au fonctionnement,
elle sert à ce qu'aucun secret ne subsiste en clair en base. Elle est idempotente (relire une
valeur déjà chiffrée la déchiffre, puis la réécrit) et réversible.
"""
from django.db import connection, migrations

import core.crypto_fields


# (modèle, champ) -- l'ordre n'a pas d'importance, chaque champ est traité indépendamment.
CHAMPS_CHIFFRES = [
    ("CanalMeshCore", "cle_partagee_hex"),
    ("CanalMeshtastic", "psk_hex"),
    ("CompagnonMeshtastic", "mqtt_password"),
    ("CompagnonMeshtastic", "x25519_private_key_hex"),
    ("MessageMeshLog", "contenu"),
    ("MessageCanalMeshCore", "contenu"),
    ("MessageMeshtasticLog", "contenu"),
    ("MessageCanalMeshtastic", "contenu"),
]


def _lignes_a_traiter(Modele, champ):
    """Lignes dont le champ porte une valeur : NULL et chaîne vide sont laissés tels quels par
    `get_prep_value`, les réécrire ne servirait à rien."""
    return (
        Modele.objects.exclude(**{champ: ""})
        .exclude(**{f"{champ}__isnull": True})
        .only("pk", champ)
        .iterator(chunk_size=500)
    )


def chiffrer(apps, schema_editor):
    """`QuerySet.update()` plutôt que `obj.save()` : passe par `get_prep_value` (donc chiffre) sans
    déclencher les `save()` personnalisés -- celui de CompagnonMeshtastic génère une clé X25519
    quand le champ est vide, ce qu'on ne veut surtout pas ici."""
    for nom_modele, champ in CHAMPS_CHIFFRES:
        Modele = apps.get_model("core", nom_modele)
        for objet in _lignes_a_traiter(Modele, champ):
            # getattr renvoie le clair (valeur brute si la ligne n'était pas chiffrée, valeur
            # déchiffrée sinon) ; update le rechiffre.
            Modele.objects.filter(pk=objet.pk).update(**{champ: getattr(objet, champ)})


def dechiffrer(apps, schema_editor):
    """Remet le clair en base pour que le retour arrière du schéma (TEXT -> varchar) ne laisse pas
    des chiffrés illisibles, ni ne dépasse la longueur des colonnes restaurées. Écriture en SQL
    direct : passer par l'ORM rechiffrerait la valeur qu'on vient de déchiffrer."""
    for nom_modele, champ in CHAMPS_CHIFFRES:
        Modele = apps.get_model("core", nom_modele)
        table = Modele._meta.db_table
        colonne = Modele._meta.get_field(champ).column
        with connection.cursor() as curseur:
            for objet in _lignes_a_traiter(Modele, champ):
                curseur.execute(
                    f'UPDATE "{table}" SET "{colonne}" = %s WHERE "id" = %s',
                    [getattr(objet, champ), str(objet.pk)],
                )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0229_implication_communes_acceptees"),
    ]

    operations = [
        migrations.AlterField(
            model_name="canalmeshcore",
            name="cle_partagee_hex",
            field=core.crypto_fields.EncryptedTextField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="canalmeshtastic",
            name="psk_hex",
            field=core.crypto_fields.EncryptedTextField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="compagnonmeshtastic",
            name="mqtt_password",
            field=core.crypto_fields.EncryptedTextField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="compagnonmeshtastic",
            name="x25519_private_key_hex",
            field=core.crypto_fields.EncryptedTextField(blank=True, editable=False, max_length=64),
        ),
        migrations.AlterField(
            model_name="messagemeshlog",
            name="contenu",
            field=core.crypto_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="messagecanalmeshcore",
            name="contenu",
            field=core.crypto_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="messagemeshtasticlog",
            name="contenu",
            field=core.crypto_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="messagecanalmeshtastic",
            name="contenu",
            field=core.crypto_fields.EncryptedTextField(),
        ),
        # Après les AlterField : l'état du modèle porte alors le champ chiffré, donc
        # get_prep_value / from_db_value s'appliquent dans les deux fonctions ci-dessus.
        migrations.RunPython(chiffrer, dechiffrer),
    ]
