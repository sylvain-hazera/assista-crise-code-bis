from django.db import migrations

# Codes alignés sur `type_service_local` tel que renvoyé par l'annuaire officiel de
# l'administration (api-lannuaire.service-public.gouv.fr) : une future création automatique
# d'institution via ce canal (voir institution_attachment.resolve_or_create_institution_from_
# annuaire) réutilisera directement ces lignes au lieu d'en dupliquer de nouvelles.
INSTITUTION_TYPES = [
    ("gendarmerie", "Gendarmerie"),
    ("prefecture", "Préfecture"),
    ("sous_pref", "Sous-préfecture"),
    ("cg", "Conseil départemental"),
    ("cr", "Conseil régional"),
    ("epci", "Communauté de communes / Métropole"),
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
        ("core", "0051_seed_institution_types_association_entreprise"),
    ]

    operations = [
        migrations.RunPython(seed_institution_types, remove_institution_types),
    ]
