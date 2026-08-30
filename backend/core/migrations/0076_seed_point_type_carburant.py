from django.db import migrations

# Nouveau thème de point demandé : une équipe doit pouvoir se rattacher à un point de
# ravitaillement carburant, en plus du point de regroupement des moyens déjà existant
# (REGROUPEMENT_MOYENS, voir 0044) — pour "faire le plein" avant/pendant une mission.
NEW_POINT_TYPES = [
    ("CARBURANT", "Point de ravitaillement carburant"),
]


def seed(apps, schema_editor):
    PointType = apps.get_model("core", "PointType")
    for code, libelle in NEW_POINT_TYPES:
        PointType.objects.update_or_create(
            code=code,
            defaults={"libelle": libelle, "actif": True},
        )


def unseed(apps, schema_editor):
    PointType = apps.get_model("core", "PointType")
    PointType.objects.filter(code__in=[code for code, _ in NEW_POINT_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0075_team_delegation"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
