from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_affectationcompetence'),
    ]

    operations = [
        migrations.CreateModel(
            name='Dossier',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        editable=False,
                        serialize=False,
                    ),
                ),
                (
                    'numero',
                    models.CharField(
                        max_length=50,
                        unique=True,
                    ),
                ),
                (
                    'titre',
                    models.CharField(
                        max_length=255,
                    ),
                ),
                (
                    'description',
                    models.TextField(),
                ),
                (
                    'statut',
                    models.CharField(
                        max_length=50,
                        default='NOUVEAU',
                        choices=[
                            ('NOUVEAU', 'Nouveau'),
                            ('EN_ATTENTE_AFFECTATION', "En attente d'affectation"),
                            ('AFFECTE', 'Affecté'),
                            ('EN_COURS', 'En cours'),
                            ('RESOLU', 'Résolu'),
                            ('CLOTURE', 'Clôturé'),
                        ],
                    ),
                ),
                (
                    'date_creation',
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    'date_affectation',
                    models.DateTimeField(
                        null=True,
                        blank=True,
                    ),
                ),
                (
                    'date_resolution',
                    models.DateTimeField(
                        null=True,
                        blank=True,
                    ),
                ),
                (
                    'date_cloture',
                    models.DateTimeField(
                        null=True,
                        blank=True,
                    ),
                ),
                (
                    'competence',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='dossiers',
                        to='core.competence',
                    ),
                ),
                (
                    'crise',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='dossiers',
                        to='core.crisis',
                    ),
                ),
                (
                    'equipe',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='dossiers',
                        blank=True,
                        null=True,
                        to='core.team',
                    ),
                ),
            ],
        ),
    ]
