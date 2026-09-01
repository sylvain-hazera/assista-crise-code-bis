from django.db import migrations

# RESPONSABLE/REGULATEUR sont utilisés par la logique de rattachement automatique à une
# institution (voir institution_attachment.assign_default_institution_role, et le nouveau flux
# de confirmation self-service UserViewSet.confirmer_institution/creer_mon_institution) — avant
# ce correctif, ces deux lignes n'existaient qu'en PROD par effet de bord (auto-créées la
# première fois qu'un rôle par défaut était posé) : un environnement neuf (démo, dev, CI) n'en
# avait aucune, laissant la liste de rôles proposée à l'inscription vide.
ROLES = [
    ("RESPONSABLE", "Responsable"),
    ("REGULATEUR", "Régulateur"),
]


def seed_roles(apps, schema_editor):
    RoleOperationnel = apps.get_model("core", "RoleOperationnel")
    for code, libelle in ROLES:
        RoleOperationnel.objects.get_or_create(code=code, defaults={"libelle": libelle})


def remove_roles(apps, schema_editor):
    RoleOperationnel = apps.get_model("core", "RoleOperationnel")
    RoleOperationnel.objects.filter(code__in=[code for code, _ in ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0092_galerie_photos_offres_demandes"),
    ]

    operations = [
        migrations.RunPython(seed_roles, remove_roles),
    ]
