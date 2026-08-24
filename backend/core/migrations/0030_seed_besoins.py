from django.db import migrations

BESOINS = [
    ("Assistance immédiate", "Premiers secours, mise à l'abri, situation d'urgence."),
    ("Hébergement", "Logement temporaire pour les personnes sinistrées."),
    ("Nourriture et eau", "Distribution alimentaire et accès à l'eau potable."),
    ("Soins médicaux", "Prise en charge médicale ou paramédicale."),
    ("Transport", "Déplacement de personnes ou de matériel."),
    ("Matériel", "Prêt ou don de matériel (groupes électrogènes, bâches, outils...)."),
    ("Soutien psychologique", "Écoute et accompagnement psychologique."),
    ("Autre", "Besoin ne rentrant dans aucune autre catégorie."),
]


def seed_besoins(apps, schema_editor):
    Besoin = apps.get_model("core", "Besoin")
    for nom, description in BESOINS:
        Besoin.objects.update_or_create(
            nom=nom,
            defaults={"description": description, "actif": True},
        )


def remove_besoins(apps, schema_editor):
    Besoin = apps.get_model("core", "Besoin")
    Besoin.objects.filter(nom__in=[nom for nom, _ in BESOINS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_implicationinstitution_responsable_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_besoins, remove_besoins),
    ]
