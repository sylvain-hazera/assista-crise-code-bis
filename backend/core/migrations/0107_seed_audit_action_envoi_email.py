from django.db import migrations

AUDIT_ACTIONS = [
    ("ENVOI_EMAIL", "Envoi d'email"),
]


def seed_audit_actions(apps, schema_editor):
    AuditAction = apps.get_model("core", "AuditAction")
    for code, libelle in AUDIT_ACTIONS:
        AuditAction.objects.update_or_create(
            code=code,
            defaults={"libelle": libelle, "actif": True},
        )


def remove_audit_actions(apps, schema_editor):
    AuditAction = apps.get_model("core", "AuditAction")
    AuditAction.objects.filter(code__in=[code for code, _ in AUDIT_ACTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0106_commune_departement_code_commune_epci_code_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_audit_actions, remove_audit_actions),
    ]
