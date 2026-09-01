from django.db import migrations

# Contrairement au SDIS (0087), l'AASC n'a pas de correspondance dans l'annuaire officiel de
# l'administration — c'est une association privée agréée, pas un service public. Validation à
# l'inscription en mode "accès limité" (voir auth_validation.requires_limited_access), jamais
# via l'annuaire/open-data.
INSTITUTION_TYPES = [
    ("aasc", "AASC (Association agréée de sécurité civile)"),
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
        ("core", "0088_dossier_important"),
    ]

    operations = [
        migrations.RunPython(seed_institution_types, remove_institution_types),
    ]
