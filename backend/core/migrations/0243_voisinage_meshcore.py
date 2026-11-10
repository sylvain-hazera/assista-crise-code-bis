"""Liaisons MeshCore observées, et complétude du relevé de voisinage.

Deux tables neuves, rien à reprendre. La seconde existe parce que MeshCore sait dire combien de
voisins un répéteur a en tout (`neighbours_count`) : l'absence d'un voisin dans la liste peut
donc être une preuve, ce qui n'est jamais le cas côté Meshtastic."""

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0242_file_admin_meshcore'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiaisonMeshCore',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('emetteur_prefixe_hex', models.CharField(help_text="Préfixe de la clé publique du voisin entendu, tel que le répéteur l'a rendu.", max_length=64)),
                ('prefixe_octets', models.PositiveSmallIntegerField(default=4, help_text='Longueur du préfixe, en octets. 4 par défaut (pubkey_prefix_length). Deux préfixes de longueurs différentes ne se comparent pas.')),
                ('recepteur_pubkey_hex', models.CharField(help_text="Clé publique COMPLÈTE du répéteur interrogé : c'est nous qui l'avons choisi.", max_length=64)),
                ('source', models.CharField(choices=[('RF', 'Reçu par une passerelle MQTT (SNR mesuré)'), ('VOISINAGE', 'Déclaré par un rapport de voisinage (NeighborInfo)'), ('TRACEROUTE', "Saut d'un traceroute")], default='VOISINAGE', help_text="Mêmes sources que côté Meshtastic : un rapport de voisinage ne prouve pas la même chose qu'une réception directe.", max_length=10)),
                ('snr', models.FloatField(blank=True, null=True)),
                ('nombre', models.PositiveIntegerField(default=1)),
                ('premier_vu', models.DateTimeField(auto_now_add=True)),
                ('dernier_vu', models.DateTimeField()),
            ],
            options={
                'indexes': [models.Index(fields=['-dernier_vu'], name='core_liaiso_dernier_735651_idx'), models.Index(fields=['recepteur_pubkey_hex'], name='core_liaiso_recepte_09f647_idx')],
                'constraints': [models.UniqueConstraint(fields=('emetteur_prefixe_hex', 'recepteur_pubkey_hex', 'source', 'environment'), name='uq_liaison_meshcore_sens_source')],
            },
        ),
        migrations.CreateModel(
            name='ReleveVoisinageMeshCore',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('pubkey_hex', models.CharField(max_length=64)),
                ('total_annonce', models.PositiveIntegerField(help_text='`neighbours_count` : ce que le répéteur dit avoir de voisins.')),
                ('recus', models.PositiveIntegerField(help_text='`results_count` cumulé des pages reçues.')),
                ('prefixe_octets', models.PositiveSmallIntegerField(default=4)),
                ('date_releve', models.DateTimeField()),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('pubkey_hex', 'environment'), name='uq_releve_voisinage_meshcore_noeud')],
            },
        ),
    ]
