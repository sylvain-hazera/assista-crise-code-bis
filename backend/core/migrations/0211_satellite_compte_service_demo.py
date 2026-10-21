from django.db import migrations


def donner_acces_demo(apps, schema_editor):
    # Comptes de service des satellites déjà approuvés : même droit que ceux créés désormais par
    # SatelliteViewSet.valider (demo_role), pour recopier la zone de démonstration.
    Satellite = apps.get_model("core", "Satellite")
    User = apps.get_model("core", "User")
    ids = Satellite.objects.exclude(compte_service=None).values_list("compte_service_id", flat=True)
    User.objects.filter(pk__in=list(ids), demo_role__isnull=True).update(demo_role="UTIL_SIMPLE")


class Migration(migrations.Migration):
    # Satellites : copie de la zone de démonstration (21/10/2026, voir core/sync_referentiel.py
    # et synchroniser_entrant). Ne touche que les comptes de service des satellites.
    dependencies = [
        ("core", "0210_auditlog_index_tracabilite"),
    ]

    operations = [
        migrations.RunPython(donner_acces_demo, migrations.RunPython.noop),
    ]
