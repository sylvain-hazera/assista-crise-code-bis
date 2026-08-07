from django.db import migrations

AUDIT_ACTIONS = [
    ("CREATION", "Création"),
    ("MODIFICATION", "Modification"),
    ("SUPPRESSION", "Suppression"),
    ("CONNEXION", "Connexion"),
    ("LECTURE", "Lecture / consultation"),
    ("ACQUITTEMENT", "Acquittement"),
    ("TELECHARGEMENT", "Téléchargement de document"),
    ("DELEGATION_COMPETENCE", "Délégation de compétence"),
    ("PRISE_PERMANENCE", "Prise de permanence"),
    ("FIN_PERMANENCE", "Fin de permanence"),
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
        ("core", "0022_institutiondomaine_contactinstitution"),
    ]

    operations = [
        migrations.RunPython(seed_audit_actions, remove_audit_actions),
    ]
