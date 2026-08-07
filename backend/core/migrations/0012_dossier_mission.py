from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import core.validators
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_fix_affectationcompetence'),
    ]

    operations = [

        migrations.CreateModel(
            name='Document',
            fields=[
                ('id', models.UUIDField(
                    primary_key=True,
                    default=uuid.uuid4,
                    editable=False
                )),
                ('fichier', models.FileField(
                    upload_to='documents/',
                    validators=[core.validators.validate_image_file]
                )),
                ('date_upload', models.DateTimeField(auto_now_add=True)),
                ('commentaire', models.TextField(
                    blank=True,
                    null=True
                )),
                ('sha256', models.CharField(
                    max_length=64,
                    blank=True,
                    null=True
                )),
                ('metadata_publiques', models.JSONField(
                    default=dict,
                    blank=True
                )),
                ('metadata_privees', models.JSONField(
                    default=dict,
                    blank=True
                )),
                ('auteur', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL
                )),
                ('demande', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents',
                    to='core.request'
                )),
                ('dossier', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents',
                    to='core.dossier'
                )),
                ('offre', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents',
                    to='core.offer'
                )),
            ],
        ),

        migrations.CreateModel(
            name='DossierCommentaire',
            fields=[
                ('id', models.UUIDField(
                    primary_key=True,
                    default=uuid.uuid4,
                    editable=False
                )),
                ('commentaire', models.TextField()),
                ('date_creation', models.DateTimeField(
                    auto_now_add=True
                )),
                ('auteur', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL
                )),
                ('dossier', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='commentaires',
                    to='core.dossier'
                )),
            ],
        ),

        migrations.CreateModel(
            name='DossierHistorique',
            fields=[
                ('id', models.UUIDField(
                    primary_key=True,
                    default=uuid.uuid4,
                    editable=False
                )),
                ('evenement', models.CharField(
                    max_length=255
                )),
                ('commentaire', models.TextField(
                    blank=True,
                    null=True
                )),
                ('date_creation', models.DateTimeField(
                    auto_now_add=True
                )),
                ('auteur', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL
                )),
                ('dossier', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='historique',
                    to='core.dossier'
                )),
            ],
        ),
    ]

