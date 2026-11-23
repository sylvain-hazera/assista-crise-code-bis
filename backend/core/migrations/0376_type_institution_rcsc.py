"""Type d'institution « Réserve communale de sécurité civile » (23/11/2026, core/rcsc.py)."""
from django.db import migrations


def creer(apps, schema_editor):
    InstitutionType = apps.get_model("core", "InstitutionType")
    if not InstitutionType.objects.filter(code__iexact="rcsc").exists():
        InstitutionType.objects.create(code="rcsc", libelle="Réserve communale de sécurité civile (RCSC)")


class Migration(migrations.Migration):
    dependencies = [("core", "0375_message_terrain_dossier")]
    operations = [migrations.RunPython(creer, migrations.RunPython.noop)]
