# Merge migration + rename fields to English
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_crise_description'),
        ('core', '0004_utilisateur_code_postal_utilisateur_enable'),
    ]

    operations = [
        # Rename Crise fields to English
        migrations.RenameField(
            model_name='crise',
            old_name='nom',
            new_name='name',
        ),
        migrations.RenameField(
            model_name='crise',
            old_name='date_debut',
            new_name='start_date',
        ),
        migrations.RenameField(
            model_name='crise',
            old_name='date_fin',
            new_name='end_date',
        ),
        migrations.RenameField(
            model_name='crise',
            old_name='localisation',
            new_name='location',
        ),
        migrations.RenameField(
            model_name='crise',
            old_name='validateur',
            new_name='validator',
        ),
    ]
