from django.db import migrations

# Nouveaux types demandés : "point de transit" et "point de regroupement des moyens".
# "point de collecte" existe déjà (COLLECTE). "centre d'accueil des personnes" est le même
# concept que le HEBERGEMENT déjà seedé (0026) — on renomme juste son libellé pour matcher le
# vocabulaire métier demandé, sans toucher au code technique (ne casse rien de l'existant).
NEW_POINT_TYPES = [
    ("TRANSIT", "Point de transit"),
    ("REGROUPEMENT_MOYENS", "Point de regroupement des moyens"),
]

RENAMED_LIBELLE = ("HEBERGEMENT", "Centre d'accueil des personnes")


def seed(apps, schema_editor):
    PointType = apps.get_model("core", "PointType")
    for code, libelle in NEW_POINT_TYPES:
        PointType.objects.update_or_create(
            code=code,
            defaults={"libelle": libelle, "actif": True},
        )

    code, libelle = RENAMED_LIBELLE
    PointType.objects.filter(code=code).update(libelle=libelle)


def unseed(apps, schema_editor):
    PointType = apps.get_model("core", "PointType")
    PointType.objects.filter(code__in=[code for code, _ in NEW_POINT_TYPES]).delete()
    PointType.objects.filter(code="HEBERGEMENT").update(libelle="Centre d'hébergement")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0043_point_operationnel_fields"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
