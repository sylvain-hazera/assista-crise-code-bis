"""Code de main courante pour l'envoi de masse d'une campagne de disponibilité.

`audit_log` cherche son `AuditAction` par code et **avale l'absence** en journalisant une
erreur : un code non semé ne fait donc pas échouer l'action, il la rend simplement invisible
dans la main courante. C'est le pire des deux mondes pour un envoi à plusieurs centaines de
personnes — l'acte a lieu, et rien ne le trace.

Distinct d'`ENVOI_EMAIL`, qui trace UN message : ce qu'on veut retrouver ici, c'est la décision
de solliciter un effectif entier, avec son périmètre et son bilan.
"""
from django.db import migrations

AUDIT_ACTIONS = [
    ("ENVOI_MASSE", "Envoi de masse (campagne)"),
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
        ("core", "0256_campagnes_disponibilite"),
    ]

    operations = [
        migrations.RunPython(seed_audit_actions, remove_audit_actions),
    ]
