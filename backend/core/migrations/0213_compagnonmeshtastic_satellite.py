from django.db import migrations, models
import django.db.models.deletion


def rattacher_existants(apps, schema_editor):
    """Companions déjà déclarés par un satellite avant ce champ : reconnus par le nom que leur
    donne enregistrer_depuis_satellite (« Satellite <nom du satellite> ») et l'institution."""
    CompagnonMeshtastic = apps.get_model('core', 'CompagnonMeshtastic')
    Satellite = apps.get_model('core', 'Satellite')
    for satellite in Satellite.objects.all():
        CompagnonMeshtastic.objects.filter(
            satellite__isnull=True, institution_id=satellite.institution_id, nom=f"Satellite {satellite.nom}",
        ).update(satellite=satellite)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0212_seed_audit_action_verification'),
    ]

    operations = [
        migrations.AddField(
            model_name='compagnonmeshtastic',
            name='satellite',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='compagnons_meshtastic', to='core.satellite'),
        ),
        migrations.RunPython(rattacher_existants, migrations.RunPython.noop),
    ]
