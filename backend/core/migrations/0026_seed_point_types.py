from django.db import migrations

POINT_TYPES = [
    ("COLLECTE", "Point de collecte"),
    ("HEBERGEMENT", "Centre d'hébergement"),
    ("SECOURS", "Poste de secours"),
    ("DISTRIBUTION", "Point de distribution eau/nourriture"),
    ("AUTRE", "Autre"),
]


def seed_point_types(apps, schema_editor):
    PointType = apps.get_model("core", "PointType")
    for code, libelle in POINT_TYPES:
        PointType.objects.update_or_create(
            code=code,
            defaults={"libelle": libelle, "actif": True},
        )


def remove_point_types(apps, schema_editor):
    PointType = apps.get_model("core", "PointType")
    PointType.objects.filter(code__in=[code for code, _ in POINT_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_crisis_implication_point_responsable"),
    ]

    operations = [
        migrations.RunPython(seed_point_types, remove_point_types),
    ]
