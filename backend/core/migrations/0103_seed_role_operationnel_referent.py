from django.db import migrations

# "Référent" — personnel pré-enregistrable pour un Plan (dispositif) sans attendre l'activation
# d'une crise (voir AffectationRoleOperationnel, scopé Institution et non Crisis). Même patron
# que 0093_seed_role_operationnel_base.py (RESPONSABLE/REGULATEUR).
ROLES = [
    ("REFERENT", "Référent"),
]


def seed_roles(apps, schema_editor):
    RoleOperationnel = apps.get_model("core", "RoleOperationnel")
    for code, libelle in ROLES:
        RoleOperationnel.objects.get_or_create(code=code, defaults={"libelle": libelle})


def remove_roles(apps, schema_editor):
    RoleOperationnel = apps.get_model("core", "RoleOperationnel")
    RoleOperationnel.objects.filter(code__in=[code for code, _ in ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0102_plan_zone_dispositif"),
    ]

    operations = [
        migrations.RunPython(seed_roles, remove_roles),
    ]
