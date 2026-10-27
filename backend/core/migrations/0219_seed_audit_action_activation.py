from django.db import migrations

# Deux trous de la table de référence des actions, constatés le 27/10/2026 quand la main
# courante a refusé une ligne : `audit_log` cherche l'action par son code et laisse passer
# l'action métier en cas d'absence, donc le manque ne se voyait que dans les logs.
#
# ACTIVATION est appelé depuis le démarrage d'une crise (activation des points opérationnels,
# CriseViewSet) : cette trace n'a jamais été écrite depuis sa mise en service.
AUDIT_ACTIONS = [
    ("ACTIVATION", "Activation"),
]

# IMPORT_LISTE ne concerne plus seulement les fichiers : l'estimation BAN des habitations et
# l'import open data des sites sensibles passent par des API publiques. Le libellé s'affiche
# tel quel dans le journal, il doit rester vrai.
LIBELLE_IMPORT_LISTE = "Import d'une liste (fichier ou base publique)"
ANCIEN_LIBELLE_IMPORT_LISTE = "Import d'une liste (CSV/XLS)"


def seed_audit_actions(apps, schema_editor):
    AuditAction = apps.get_model("core", "AuditAction")
    for code, libelle in AUDIT_ACTIONS:
        AuditAction.objects.update_or_create(
            code=code,
            defaults={"libelle": libelle, "actif": True},
        )
    AuditAction.objects.filter(code="IMPORT_LISTE").update(libelle=LIBELLE_IMPORT_LISTE)


def remove_audit_actions(apps, schema_editor):
    AuditAction = apps.get_model("core", "AuditAction")
    AuditAction.objects.filter(code__in=[code for code, _ in AUDIT_ACTIONS]).delete()
    AuditAction.objects.filter(code="IMPORT_LISTE").update(
        libelle=ANCIEN_LIBELLE_IMPORT_LISTE)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0218_alter_sitesensible_categorie"),
    ]

    operations = [
        migrations.RunPython(seed_audit_actions, remove_audit_actions),
    ]
