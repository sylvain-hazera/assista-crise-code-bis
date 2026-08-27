from django.db import migrations

# Codes alignés sur `type_service_local` (police municipale, ARS) tel que renvoyé par
# l'annuaire officiel de l'administration — voir 0052 pour la même logique. "chu" n'a pas
# d'équivalent générique pour un hôpital non universitaire dans ce jeu de données ; conservé
# tel quel, la vérification (recherche-entreprises.api.gouv.fr) fonctionne pour tout hôpital
# public quel que soit ce code.
INSTITUTION_TYPES = [
    ("police_municipale", "Police municipale"),
    ("ars_antenne", "ARS (Agence régionale de santé)"),
    ("chu", "CHU / Hôpital"),
]


def seed_institution_types(apps, schema_editor):
    InstitutionType = apps.get_model("core", "InstitutionType")
    for code, libelle in INSTITUTION_TYPES:
        InstitutionType.objects.get_or_create(code=code, defaults={"libelle": libelle, "actif": True})


def remove_institution_types(apps, schema_editor):
    InstitutionType = apps.get_model("core", "InstitutionType")
    InstitutionType.objects.filter(code__in=[code for code, _ in INSTITUTION_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0052_seed_institution_types_officiels"),
    ]

    operations = [
        migrations.RunPython(seed_institution_types, remove_institution_types),
    ]
