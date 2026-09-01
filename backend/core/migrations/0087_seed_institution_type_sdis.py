from django.db import migrations

# Code aligné sur le token "sdis" déjà géré par la validation automatique de compte
# (auth_validation.py : open-data communes/{code}/sdis, SPECIFIC_TYPE_DOMAIN_TOKENS,
# regex sdis*.fr) — le mécanisme existait déjà côté backend, seul le type lui-même n'était
# jamais seedé (et absent du formulaire d'inscription).
INSTITUTION_TYPES = [
    ("sdis", "SDIS (Service départemental d'incendie et de secours)"),
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
        ("core", "0086_rename_requesttype_assistance_immediate"),
    ]

    operations = [
        migrations.RunPython(seed_institution_types, remove_institution_types),
    ]
