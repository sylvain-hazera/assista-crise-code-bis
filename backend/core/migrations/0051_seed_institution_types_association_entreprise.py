from django.db import migrations

INSTITUTION_TYPES = [
    ("association", "Association"),
    ("entreprise", "Entreprise"),
]


def seed_institution_types(apps, schema_editor):
    InstitutionType = apps.get_model("core", "InstitutionType")
    for code, libelle in INSTITUTION_TYPES:
        InstitutionType.objects.get_or_create(code=code, defaults={"libelle": libelle, "actif": True})


def remove_institution_types(apps, schema_editor):
    InstitutionType = apps.get_model("core", "InstitutionType")
    InstitutionType.objects.filter(code__in=[code for code, _ in INSTITUTION_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0050_crisis_zone_secteurs"),
    ]

    operations = [
        migrations.RunPython(seed_institution_types, remove_institution_types),
    ]
