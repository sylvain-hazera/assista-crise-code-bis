"""Adresse de serveur Matrix à saisir dans Element X, propre à une institution.

Distinct du `server_name` de Synapse, et c'est tout l'intérêt : Synapse n'a qu'un seul
`server_name`, inscrit dans chaque identifiant d'utilisateur et de salon, et il ne sait pas en
héberger deux — les comptes restent donc `@…:matrix.assista-crise.fr`. Mais le POINT D'ENTRÉE
peut porter le domaine du partenaire, et le proxy sert déjà `matrix.reserve-resilience.org` vers
le même Synapse, avec son propre certificat.

Les deux usages de MATRIX_SERVER_NAME étaient confondus avant ce jour — construire l'identité
(core/matrix.py:matrix_user_id) et indiquer l'adresse à taper (le mail d'enrôlement) — ce qui
faisait croire que rien n'était personnalisable. Seul le second devient per-institution.

Vide par défaut : aucune institution ne change de comportement.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0249_relecture_et_modeles_messages'),
    ]

    operations = [
        migrations.AddField(
            model_name='institution',
            name='matrix_hostname',
            field=models.CharField(blank=True, help_text="Adresse de serveur Matrix à saisir dans Element X (ex: matrix.exemple.org). Vide = adresse partagée. Le domaine doit être servi par le proxy et couvert par son certificat, sinon Element ne s'y connecte pas.", max_length=255),
        ),
    ]
