import uuid

from django.db import migrations, models
import django.db.models.deletion


def reprendre_slots(apps, schema_editor):
    """Chaque canal garde le slot qu'il avait sur la DERNIÈRE radio qui l'a déclaré ; l'autre
    radio le retrouvera tel quel au prochain passage de son pont (_trouver_canal_existant_ou_libre
    reconnaît la clé déjà configurée, sans réécrire la radio)."""
    CanalMeshCore = apps.get_model('core', 'CanalMeshCore')
    ProvisionCanalMeshCore = apps.get_model('core', 'ProvisionCanalMeshCore')
    for canal in CanalMeshCore.objects.filter(compagnon__isnull=False, canal_idx__isnull=False):
        if ProvisionCanalMeshCore.objects.filter(compagnon_id=canal.compagnon_id, canal_idx=canal.canal_idx).exists():
            continue
        ProvisionCanalMeshCore.objects.create(canal=canal, compagnon_id=canal.compagnon_id, canal_idx=canal.canal_idx)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0213_compagnonmeshtastic_satellite'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProvisionCanalMeshCore',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canal_idx', models.PositiveSmallIntegerField()),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('canal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='provisions', to='core.canalmeshcore')),
                ('compagnon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='provisions_canaux', to='core.compagnonmeshcore')),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('canal', 'compagnon'), name='provision_canal_compagnon_unique'),
                    models.UniqueConstraint(fields=('compagnon', 'canal_idx'), name='provision_slot_compagnon_unique'),
                ],
            },
        ),
        migrations.RunPython(reprendre_slots, migrations.RunPython.noop),
        migrations.RemoveField(model_name='canalmeshcore', name='canal_idx'),
        migrations.RemoveField(model_name='canalmeshcore', name='compagnon'),
    ]
