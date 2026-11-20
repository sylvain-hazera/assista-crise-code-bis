from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0358_cellule_suivi_tobac"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImageRadarEstimee",
            fields=[
                ("minutes", models.PositiveSmallIntegerField(primary_key=True, serialize=False)),
                ("heure_base", models.DateTimeField(help_text="Heure de l'image observée dont elle est extrapolée.")),
                ("largeur", models.PositiveIntegerField()),
                ("hauteur", models.PositiveIntegerField()),
                ("projdef", models.CharField(max_length=300)),
                ("x0", models.FloatField()),
                ("y0", models.FloatField()),
                ("grille", models.BinaryField()),
                ("releve_le", models.DateTimeField()),
            ],
        ),
    ]
