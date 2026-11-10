"""Cartographie du réseau MeshCore public, importée d'une instance CoreScope.

Table neuve. Elle ne contient par construction que des répéteurs et des rooms : un companion
est l'appareil personnel de quelqu'un, et sa position souvent son domicile."""

import django.contrib.gis.db.models.fields
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0244_sources_observateurs_meshcore'),
    ]

    operations = [
        migrations.CreateModel(
            name='NoeudPublicMeshCore',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('instance', models.CharField(help_text="Instance d'origine, ex. « https://meshstats.serveurperso.in ».", max_length=255)),
                ('pubkey_hex', models.CharField(max_length=64)),
                ('nom', models.CharField(blank=True, max_length=100)),
                ('role', models.CharField(help_text='repeater ou room ; jamais companion.', max_length=20)),
                ('location', django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                ('premier_vu', models.DateTimeField(blank=True, null=True)),
                ('dernier_vu', models.DateTimeField(blank=True, null=True)),
                ('relais_actif', models.BooleanField(default=False)),
                ('relais_24h', models.PositiveIntegerField(default=0)),
                ('score_couverture', models.FloatField(blank=True, null=True)),
                ('score_redondance', models.FloatField(blank=True, null=True)),
                ('score_pont', models.FloatField(blank=True, null=True)),
                ('score_utilite', models.FloatField(blank=True, null=True)),
                ('note_utilite', models.CharField(blank=True, max_length=4)),
                ('taille_hash', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('date_import', models.DateTimeField()),
            ],
            options={
                'indexes': [models.Index(fields=['role'], name='core_noeudp_role_c30beb_idx'), models.Index(fields=['-dernier_vu'], name='core_noeudp_dernier_bc64f5_idx')],
                'constraints': [models.UniqueConstraint(fields=('instance', 'pubkey_hex', 'environment'), name='uq_noeud_public_meshcore')],
            },
        ),
    ]
