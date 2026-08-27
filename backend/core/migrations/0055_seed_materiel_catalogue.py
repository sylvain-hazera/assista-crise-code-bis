from django.db import migrations

# Reprend les 6 anciennes valeurs de TypeMateriel (continuité) + les besoins demandés pour les
# centres d'accueil / points de regroupement des moyens. Purement un point de départ : la liste
# n'est pas figée, n'importe quel centre peut en ajouter (voir TagLikeViewSetMixin sur
# MaterielCatalogueViewSet).
ITEMS = [
    "Cuve",
    "Pompe",
    "Étuve",
    "Chambre froide",
    "Remorque",
    "Lit",
    "Table",
    "Chaise",
    "Repas",
    "Nourriture",
    "Eau",
    "Stockage froid alimentaire",
    "Alimentation électrique",
    "Tente / Barnum / Chapiteau",
    "Point télécom / Internet",
]


def seed_materiel_catalogue(apps, schema_editor):
    MaterielCatalogue = apps.get_model("core", "MaterielCatalogue")
    for nom in ITEMS:
        MaterielCatalogue.objects.get_or_create(nom=nom)


def remove_materiel_catalogue(apps, schema_editor):
    MaterielCatalogue = apps.get_model("core", "MaterielCatalogue")
    MaterielCatalogue.objects.filter(nom__in=ITEMS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0054_materiel_catalogue"),
    ]

    operations = [
        migrations.RunPython(seed_materiel_catalogue, remove_materiel_catalogue),
    ]
