from django.db import migrations


def backfill_secteur_codes(apps, schema_editor):
    """Peuple epci_code/departement_code/region_code (ajoutés en 0113) pour les demandes créées
    AVANT cette migration, qui n'ont donc que commune_code — pur lookup en base sur Commune
    (déjà importée pour toute commune ayant une demande), aucun appel réseau."""
    Request = apps.get_model("core", "Request")
    Commune = apps.get_model("core", "Commune")

    communes_par_code = {
        c.code: c for c in Commune.objects.filter(
            code__in=Request.objects.exclude(commune_code__isnull=True)
            .exclude(commune_code="").values_list("commune_code", flat=True).distinct()
        )
    }

    a_mettre_a_jour = []
    for demande in Request.objects.exclude(commune_code__isnull=True).exclude(commune_code=""):
        commune = communes_par_code.get(demande.commune_code)
        if not commune:
            continue
        demande.epci_code = commune.epci_code
        demande.departement_code = commune.departement_code
        demande.region_code = commune.region_code
        a_mettre_a_jour.append(demande)

    Request.objects.bulk_update(a_mettre_a_jour, ["epci_code", "departement_code", "region_code"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0113_request_secteur_codes'),
    ]

    operations = [
        migrations.RunPython(backfill_secteur_codes, migrations.RunPython.noop),
    ]
