import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import core.crypto_fields


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0277_campagne_ciblage_large"),
    ]

    operations = [
        migrations.AddField(
            model_name="satellite",
            name="agent_mise_a_jour_vu",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="VersionSatellite",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("commit", models.CharField(help_text="Numéro de commit complet (40 caractères).", max_length=40, unique=True)),
                ("libelle", models.CharField(blank=True, help_text="Ce que cette version apporte, en quelques mots. Affiché dans la liste.", max_length=120)),
                ("signature", models.TextField()),
                ("date_publication", models.DateTimeField(auto_now_add=True)),
                ("retiree", models.BooleanField(default=False)),
                ("publiee_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-date_publication"]},
        ),
        migrations.CreateModel(
            name="MiseAJourSatellite",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("statut", models.CharField(choices=[("DEMANDEE", "Demandée"), ("EN_COURS", "En cours"), ("REUSSIE", "Réussie"), ("ECHOUEE", "Échouée"), ("ANNULEE", "Annulée"), ("EXPIREE", "Expirée")], default="DEMANDEE", max_length=10)),
                ("date_demande", models.DateTimeField(auto_now_add=True)),
                ("date_debut", models.DateTimeField(blank=True, null=True)),
                ("date_fin", models.DateTimeField(blank=True, null=True)),
                ("etape", models.CharField(blank=True, max_length=200)),
                ("journal", core.crypto_fields.EncryptedTextField(blank=True)),
                ("version_avant", models.CharField(blank=True, max_length=50)),
                ("malgre_crise", models.BooleanField(default=False)),
                ("demandee_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("satellite", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mises_a_jour", to="core.satellite")),
                ("version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="mises_a_jour", to="core.versionsatellite")),
            ],
            options={"ordering": ["-date_demande"]},
        ),
        migrations.AddConstraint(
            model_name="miseajoursatellite",
            constraint=models.UniqueConstraint(condition=models.Q(("statut__in", ["DEMANDEE", "EN_COURS"])), fields=("satellite",), name="uq_une_mise_a_jour_ouverte_par_satellite"),
        ),
    ]
