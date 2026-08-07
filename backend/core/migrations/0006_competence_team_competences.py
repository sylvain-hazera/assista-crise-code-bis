from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        (
            "core",
            "0005_information_deletion_token_offer_deletion_token_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="Competence",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        editable=False,
                        serialize=False,
                    ),
                ),
                (
                    "nom",
                    models.CharField(
                        max_length=100,
                        unique=True,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "active",
                    models.BooleanField(
                        default=True,
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="team",
            name="competences",
            field=models.ManyToManyField(
                blank=True,
                related_name="equipes",
                to="core.competence",
            ),
        ),
    ]
