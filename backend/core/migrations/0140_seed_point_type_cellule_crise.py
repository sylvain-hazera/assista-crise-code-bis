from django.db import migrations

# Nouveau thème de point demandé : le wizard de démarrage de crise propose "cellule de crise"
# comme premier élément stratégique (à côté de HEBERGEMENT/"Centre d'accueil des personnes" et
# REGROUPEMENT_MOYENS déjà existants, voir 0044) — n'existait nulle part jusqu'ici.
NEW_POINT_TYPES = [
    ("CELLULE_CRISE", "Cellule de crise"),
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
        ("core", "0139_organise_besoins_competences"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
