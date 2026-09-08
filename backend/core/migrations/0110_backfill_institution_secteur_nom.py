from django.db import migrations


def backfill_secteur_nom(apps, schema_editor):
    """Ré-exécute Institution.save() (méthode réelle, pas le manager historique — la logique de
    calcul de secteur_niveau_effectif/secteur_nom vit dans core.models.Institution, la version
    historique n'a pas cette méthode) sur toute institution ayant déjà un commune_code, pour que
    les deux champs ajoutés en 0109 soient peuplés sans attendre une prochaine modification
    manuelle de chaque institution.

    .only(...) restreint la requête aux champs déjà présents au moment de CETTE migration
    (jusqu'à 0109 inclus, dont dépend celle-ci) — sans ça, le modèle live (importé ci-dessous,
    nécessaire pour appeler .save()) inclut tout champ ajouté PLUS TARD à Institution, que
    Django tente alors de SELECT ici où il n'existe pas encore lors d'un rejeu complet des
    migrations depuis zéro (ex: création d'une base de test) — reproduit puis corrigé en
    ajoutant Institution.commune_code_postal (voir migration 0123) après celle-ci. Les champs
    qu'Institution.save() écrit (epci_code, secteur_niveau_effectif...) restent à jour dans
    l'UPDATE malgré .only() : Django les considère non différés dès qu'on leur assigne une
    valeur, indépendamment de la liste ci-dessous."""
    from core.models import Institution

    champs_disponibles_a_cette_migration = ["id", "commune_code", "commune_nom", "secteur_override", "type"]
    qs = Institution.objects.only(*champs_disponibles_a_cette_migration)
    for institution in qs.filter(commune_code__isnull=False).exclude(commune_code=""):
        institution.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0109_institution_secteur_niveau_effectif_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_secteur_nom, migrations.RunPython.noop),
    ]
