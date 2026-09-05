from django.db import migrations


def backfill_secteur_nom(apps, schema_editor):
    """Ré-exécute Institution.save() (méthode réelle, pas le manager historique — la logique de
    calcul de secteur_niveau_effectif/secteur_nom vit dans core.models.Institution, la version
    historique n'a pas cette méthode) sur toute institution ayant déjà un commune_code, pour que
    les deux champs ajoutés en 0109 soient peuplés sans attendre une prochaine modification
    manuelle de chaque institution."""
    from core.models import Institution

    for institution in Institution.objects.filter(commune_code__isnull=False).exclude(commune_code=""):
        institution.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0109_institution_secteur_niveau_effectif_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_secteur_nom, migrations.RunPython.noop),
    ]
