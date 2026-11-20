"""Le radar par mosaïque (20/11/2026) : métropole et La Réunion côte à côte.

Les images observées et estimées avaient leur heure (ou leur échéance) pour clé : deux mosaïques
publiées à la même heure se seraient écrasées. Ces deux tables ne gardent qu'une heure d'images,
remplacées toutes les cinq minutes : on les recrée plutôt que de déplacer leur clé (l'heure
perdue se reconstitue d'elle-même). Les cellules gagnent leur zone.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0363_synchronisation_des_biens"),
    ]

    operations = [
        migrations.DeleteModel(name="ImageRadarOrage"),
        migrations.DeleteModel(name="ImageRadarEstimee"),
        migrations.CreateModel(
            name="ImageRadarOrage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("zone", models.CharField(default="METROPOLE", max_length=12)),
                ("heure", models.DateTimeField()),
                ("largeur", models.PositiveIntegerField()),
                ("hauteur", models.PositiveIntegerField()),
                ("projdef", models.CharField(max_length=300)),
                ("x0", models.FloatField()),
                ("y0", models.FloatField()),
                ("grille", models.BinaryField()),
                ("radars", models.JSONField(blank=True, default=list)),
                ("radars_absents", models.JSONField(blank=True, default=list)),
                ("images_par_fenetre", models.JSONField(blank=True, default=dict)),
                ("releve_le", models.DateTimeField()),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("zone", "heure"), name="image_radar_zone_heure")]},
        ),
        migrations.CreateModel(
            name="ImageRadarEstimee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("zone", models.CharField(default="METROPOLE", max_length=12)),
                ("minutes", models.PositiveSmallIntegerField()),
                ("heure_base", models.DateTimeField(help_text="Heure de l'image observée dont elle est extrapolée.")),
                ("largeur", models.PositiveIntegerField()),
                ("hauteur", models.PositiveIntegerField()),
                ("projdef", models.CharField(max_length=300)),
                ("x0", models.FloatField()),
                ("y0", models.FloatField()),
                ("grille", models.BinaryField()),
                ("releve_le", models.DateTimeField()),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("zone", "minutes"), name="image_radar_estimee_zone_minutes")]},
        ),
        migrations.AddField(
            model_name="celluleorage",
            name="zone",
            field=models.CharField(db_index=True, default="METROPOLE", max_length=12),
        ),
    ]
