from django.db import migrations


class Migration(migrations.Migration):
    """Recrée l'index unique partiel `uq_contact_principal_institution` : présent dans l'état
    Django depuis la migration 0022, mais absent de la base de production (constatée manquante
    en base, sans doute suite à une restauration/synchronisation d'état qui n'a pas rejoué le
    SQL d'origine) — la contrainte "un seul contact principal par institution" n'était donc pas
    réellement appliquée. `IF NOT EXISTS` rend l'opération sûre à rejouer, y compris sur une
    base où l'index existe déjà correctement."""

    dependencies = [
        ("core", "0059_offer_competences"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'CREATE UNIQUE INDEX IF NOT EXISTS "uq_contact_principal_institution" '
                'ON "core_contactinstitution" ("institution_id") WHERE "contact_principal";'
            ),
            reverse_sql=(
                'DROP INDEX IF EXISTS "uq_contact_principal_institution";'
            ),
        ),
    ]
