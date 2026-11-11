"""Prénom du demandeur d'un rattachement d'habitation, séparé du nom.

Avant, `nom_demandeur` portait l'identité entière et le compte créé à l'acceptation était
fabriqué en coupant cette chaîne au premier espace : « Jean Pierre Dupont » donnait le prénom
« Jean » et le patronyme « Pierre Dupont », sans que rien ne le signale.

Aucune reprise de données : on NE découpe PAS les lignes existantes. Couper au premier espace
est précisément ce qui produisait l'erreur, et le faire une fois pour toutes en base la rendrait
définitive. Les demandes antérieures gardent donc un prénom vide, et les deux propriétés
`identite_demandeur` / `salutation_demandeur` retombent sur le seul nom.
"""
import core.crypto_fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0245_cartographie_meshcore_publique'),
    ]

    operations = [
        migrations.AddField(
            model_name='rattachementhabitation',
            name='prenom_demandeur',
            field=core.crypto_fields.EncryptedTextField(blank=True, max_length=255),
        ),
    ]
