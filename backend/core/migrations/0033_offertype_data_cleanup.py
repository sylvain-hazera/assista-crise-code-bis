from django.db import migrations


def rename_and_deactivate(apps, schema_editor):
    OfferType = apps.get_model("core", "OfferType")
    OfferType.objects.filter(type="Soins médicaux").update(type="Soins médicaux et paramédicaux")
    # Pas de suppression : des Offer réelles référencent ce type via une FK PROTECT.
    OfferType.objects.filter(type="Assistance immédiate").update(actif=False)


def revert(apps, schema_editor):
    OfferType = apps.get_model("core", "OfferType")
    OfferType.objects.filter(type="Soins médicaux et paramédicaux").update(type="Soins médicaux")
    OfferType.objects.filter(type="Assistance immédiate").update(actif=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_offer_hebergement_duree_offer_materiel_type_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_and_deactivate, revert),
    ]
