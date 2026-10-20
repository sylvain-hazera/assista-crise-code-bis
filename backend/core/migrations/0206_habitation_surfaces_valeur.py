from django.db import migrations, models


class Migration(migrations.Migration):
    # Surfaces (habitable/non habitable, totale/impactée) et valeur indicative (DVF) sur le
    # référencement des dégâts (Habitation) -- demande utilisateur du 20/10/2026. Champs additifs,
    # tous optionnels, aucune donnée touchée.
    dependencies = [
        ("core", "0205_corrige_classement_besoins_competences"),
    ]

    operations = [
        migrations.AddField(model_name="habitation", name="surface_habitable_totale",
                            field=models.FloatField(blank=True, null=True, help_text="Surface habitable totale (m²).")),
        migrations.AddField(model_name="habitation", name="surface_habitable_impactee",
                            field=models.FloatField(blank=True, null=True, help_text="Surface habitable impactée (m²).")),
        migrations.AddField(model_name="habitation", name="surface_non_habitable_totale",
                            field=models.FloatField(blank=True, null=True, help_text="Surface non habitable totale (annexes, garage, local…) (m²).")),
        migrations.AddField(model_name="habitation", name="surface_non_habitable_impactee",
                            field=models.FloatField(blank=True, null=True, help_text="Surface non habitable impactée (m²).")),
        migrations.AddField(model_name="habitation", name="valeur_estimee",
                            field=models.DecimalField(blank=True, null=True, decimal_places=2, max_digits=12, help_text="Valeur indicative du bien (€), ex. DVF.")),
        migrations.AddField(model_name="habitation", name="valeur_source",
                            field=models.CharField(blank=True, null=True, max_length=40, help_text="Origine de la valeur (ex: DVF, saisie manuelle).")),
    ]
