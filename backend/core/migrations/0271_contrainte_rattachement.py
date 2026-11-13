"""Pose la contrainte d'unicité des rattachements, après le dédoublonnage de 0269.

Séparée de 0269 délibérément. Dans la même migration, PostgreSQL refusait l'opération :

    cannot ALTER TABLE "core_contactinstitution" because it has pending trigger events

Les `DELETE` du dédoublonnage laissent des événements de déclencheur en attente dans la
transaction, et un `ALTER TABLE` y est interdit. Django ouvre une transaction par migration :
séparer suffit à ce que les suppressions soient validées d'abord.

La contrainte **n'interdit pas la multi-appartenance** : une personne à la fois dans une mairie
et dans une association a deux lignes, avec deux institutions différentes. Seule la répétition
de la MÊME paire est refusée.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0270_help_text_institution_active"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="contactinstitution",
            constraint=models.UniqueConstraint(
                fields=("institution", "utilisateur", "environment"),
                name="uq_rattachement_par_personne_et_institution",
            ),
        ),
    ]
