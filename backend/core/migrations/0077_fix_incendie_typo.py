from django.db import migrations, models

# Faute de frappe historique sur le code technique du type de crise "Incendie" : "INCEDIE" au
# lieu de "INCENDIE" (le libellé humain affiché, lui, a toujours été correct). Corrige les
# crises déjà enregistrées avec l'ancien code avant de changer les choix du champ, pour ne
# jamais laisser une valeur en base hors de la liste des choix valides.
OLD_CODE = "INCEDIE"
NEW_CODE = "INCENDIE"


def fix_typo(apps, schema_editor):
    Crisis = apps.get_model("core", "Crisis")
    Crisis.objects.filter(type=OLD_CODE).update(type=NEW_CODE)


def revert_typo(apps, schema_editor):
    Crisis = apps.get_model("core", "Crisis")
    Crisis.objects.filter(type=NEW_CODE).update(type=OLD_CODE)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0076_seed_point_type_carburant"),
    ]

    operations = [
        migrations.RunPython(fix_typo, revert_typo),
        migrations.AlterField(
            model_name="crisis",
            name="type",
            field=models.CharField(
                choices=[
                    ("INCENDIE", "Incendie"),
                    ("INONDATION", "Inondation"),
                    ("ACCIDENT", "Accident"),
                    ("CATASTROPHE_NATURELLE", "Catastrophe naturelle"),
                    ("AUTRE", "Autre"),
                ],
                default="AUTRE",
                max_length=50,
            ),
        ),
    ]
