from django.db import migrations


def deactivate(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    # Pas de suppression : des Request réelles référencent ce type via une FK PROTECT.
    RequestType.objects.filter(type="Soins médicaux").update(actif=False)


def revert(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    RequestType.objects.filter(type="Soins médicaux").update(actif=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0084_requesttype_actif"),
    ]

    operations = [
        migrations.RunPython(deactivate, revert),
    ]
