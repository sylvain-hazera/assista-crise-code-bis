from django.db import migrations


def rename(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    RequestType.objects.filter(type="Assistance immédiate").update(type="Assistance à évacuation")


def revert(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    RequestType.objects.filter(type="Assistance à évacuation").update(type="Assistance immédiate")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0085_deactivate_requesttype_soins_medicaux"),
    ]

    operations = [
        migrations.RunPython(rename, revert),
    ]
