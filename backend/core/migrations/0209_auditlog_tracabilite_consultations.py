import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    # Traçabilité des consultations (21/10/2026, voir core/tracabilite.py) : quelles fiches une
    # requête a exposées, comment, dans quel périmètre de crise, par quel type de compte, avec
    # quels termes de recherche. Colonnes ajoutées vides (ou à False) : aucune réécriture de la
    # table (2,5 M de lignes) -- Postgres pose un défaut constant sans toucher aux lignes.
    # L'historique est complété à part, par lots : manage.py reprendre_main_courante.
    dependencies = [
        ("core", "0208_auditlog_index_main_courante"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditlog", name="objets_ids",
            field=django.contrib.postgres.fields.ArrayField(base_field=models.UUIDField(), blank=True, null=True, size=None),
        ),
        migrations.AddField(
            model_name="auditlog", name="exposition",
            field=models.CharField(blank=True, null=True, max_length=24, choices=[
                ("FICHE", "Fiche ouverte"), ("LISTE", "Liste (avec coordonnées)"),
                ("LISTE_SANS_COORDONNEES", "Liste (sans coordonnées)"), ("EXPORT", "Export"),
            ]),
        ),
        migrations.AddField(
            model_name="auditlog", name="perimetre",
            field=models.CharField(blank=True, null=True, max_length=10, choices=[
                ("CRISE", "Crise"), ("MULTI", "Plusieurs crises"), ("GENERAL", "Fonctionnement général"),
            ]),
        ),
        migrations.AddField(
            model_name="auditlog", name="compte_systeme",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="auditlog", name="recherche",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
