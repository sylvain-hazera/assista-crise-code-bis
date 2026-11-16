"""Chiffre le contenu du journal de bord (JournalCollectivite.contenu).

Le journal de bord est écrit par la cellule de crise : il cite des personnes, des adresses, des
décisions. Il était stocké en clair, à l'écart de la règle du projet, et il reçoit désormais les
messages des équipes qu'on y porte. Même patron que 0230 (secrets mesh) : réexécutable (une
valeur déjà chiffrée est déchiffrée à la lecture, puis réécrite) et réversible.
"""
from django.db import connection, migrations

import core.crypto_fields


def _lignes(Modele):
    return Modele.objects.exclude(contenu="").only("pk", "contenu").iterator(chunk_size=500)


def chiffrer(apps, schema_editor):
    Journal = apps.get_model("core", "JournalCollectivite")
    for entree in _lignes(Journal):
        # getattr rend le clair (brut si la ligne ne l'était pas encore, déchiffré sinon) ;
        # update le rechiffre, sans toucher à date_creation.
        Journal.objects.filter(pk=entree.pk).update(contenu=entree.contenu)


def dechiffrer(apps, schema_editor):
    """SQL direct : repasser par l'ORM rechiffrerait ce qu'on vient de déchiffrer."""
    Journal = apps.get_model("core", "JournalCollectivite")
    table = Journal._meta.db_table
    with connection.cursor() as curseur:
        for entree in _lignes(Journal):
            curseur.execute(f'UPDATE "{table}" SET "contenu" = %s WHERE "id" = %s', [entree.contenu, str(entree.pk)])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0301_dossier_pcs"),
    ]

    operations = [
        migrations.AlterField(
            model_name="journalcollectivite",
            name="contenu",
            field=core.crypto_fields.EncryptedTextField(),
        ),
        migrations.RunPython(chiffrer, dechiffrer),
    ]
