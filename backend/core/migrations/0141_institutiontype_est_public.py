from django.db import migrations, models


CODES_PUBLICS = [
    "mairie", "epci", "gendarmerie", "prefecture", "sous_pref", "cg", "cr",
    "police_municipale", "ars_antenne", "chu", "sdis",
]


def marquer_types_publics(apps, schema_editor):
    """Association/entreprise/AASC restent privées (valeur par défaut du champ, False) : une
    association doit être mandatée (implication ACTEUR validée) avant d'agir sur une crise,
    même agréée sécurité civile (AASC) — décision explicite de l'utilisateur, pas une
    supposition. Seules les collectivités/services publics sont marqués publics ici."""
    InstitutionType = apps.get_model('core', 'InstitutionType')
    InstitutionType.objects.filter(code__in=CODES_PUBLICS).update(est_public=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0140_seed_point_type_cellule_crise'),
    ]

    operations = [
        migrations.AddField(
            model_name='institutiontype',
            name='est_public',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(marquer_types_publics, migrations.RunPython.noop),
    ]
