from django.db import migrations, models


class Migration(migrations.Migration):
    # Installation d'un satellite en une commande (20/10/2026) : le jeton porte le profil choisi
    # par l'administrateur, et le satellite reçoit un secret (haché ici) pour récupérer seul ses
    # identifiants après validation. Champs additifs, aucune donnée touchée.
    dependencies = [
        ("core", "0206_habitation_surfaces_valeur"),
    ]

    operations = [
        migrations.AddField(
            model_name="jetonenrolementsatellite", name="profil",
            field=models.CharField(choices=[("GW", "Passerelle uniquement"), ("FULL", "Suite complète")], default="GW", max_length=4),
        ),
        migrations.AddField(
            model_name="satellite", name="secret_recuperation_hash",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
