"""Brokers où des observateurs MeshCore republient ce qu'ils entendent.

Table neuve, rien à reprendre. Elle rend exploitable le décodeur de trames : un observateur
publie `{"raw": "<trame hex>"}`, c'est-à-dire exactement son entrée."""

import core.crypto_fields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0243_voisinage_meshcore'),
    ]

    operations = [
        migrations.CreateModel(
            name='SourceObservateurMeshCore',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('nom', models.CharField(max_length=100)),
                ('broker_host', models.CharField(max_length=255)),
                ('broker_port', models.PositiveIntegerField(default=1883)),
                ('mqtt_username', models.CharField(blank=True, max_length=100)),
                ('mqtt_password', core.crypto_fields.EncryptedTextField(blank=True, max_length=255)),
                ('mqtt_use_tls', models.BooleanField(default=False)),
                ('filtre_topic', models.CharField(default='meshcore/#', help_text="Filtre d'abonnement MQTT, ex. « meshcore/# » ou « meshcore/BOD/# ».", max_length=200)),
                ('actif', models.BooleanField(default=True)),
                ('derniere_connexion', models.DateTimeField(blank=True, null=True)),
                ('dernier_etat', models.CharField(blank=True, max_length=20, null=True)),
                ('derniere_erreur', models.TextField(blank=True, null=True)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('institution', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sources_observateurs_meshcore', to='core.institution')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('broker_host', 'broker_port', 'filtre_topic', 'environment'), name='uq_source_observateur_meshcore')],
            },
        ),
    ]
