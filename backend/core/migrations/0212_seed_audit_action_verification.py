from django.db import migrations

# Vérification de fonctionnement (22/10/2026, voir SondeView) : la sonde de connectivité des
# satellites et toute supervision automatique, distinguées des consultations réelles.
AUDIT_ACTIONS = [
    ("VERIFICATION", "Vérification de fonctionnement"),
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
        ("core", "0211_satellite_compte_service_demo"),
    ]

    operations = [
        migrations.RunPython(seed_audit_actions, remove_audit_actions),
    ]
