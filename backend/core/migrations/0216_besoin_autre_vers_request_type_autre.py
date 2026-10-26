from django.db import migrations

# « Autre » existait côté offre et côté signalement (voir 0174_seed_offer_information_besoins)
# mais pas côté demande d'aide : 0042_seed_besoins_categories avait mappé les RequestType par
# nom, et « Autre » n'avait alors aucun Besoin homonyme à relier.
#
# Conséquence constatée en production le 26/10/2026 : une mairie déclarée actrice avec le seul
# thème « Autre » (cas réel, crise « FDF » / Rion-des-Landes) rendait toute demande d'aide
# impossible pour le public sur sa crise, alors que les offres et les signalements passaient.


def relier_autre(apps, schema_editor):
    Besoin = apps.get_model("core", "Besoin")
    RequestType = apps.get_model("core", "RequestType")
    RequestTypeBesoin = apps.get_model("core", "RequestTypeBesoin")

    besoin = Besoin.objects.filter(nom="Autre").first()
    request_type = RequestType.objects.filter(type="Autre").first()
    # Rien à faire si l'un des deux a été renommé ou supprimé entre-temps : une correspondance
    # de référentiel ne doit jamais faire échouer un déploiement.
    if not besoin or not request_type:
        return

    RequestTypeBesoin.objects.get_or_create(request_type=request_type, besoin=besoin)


def defaire(apps, schema_editor):
    Besoin = apps.get_model("core", "Besoin")
    RequestType = apps.get_model("core", "RequestType")
    RequestTypeBesoin = apps.get_model("core", "RequestTypeBesoin")

    besoin = Besoin.objects.filter(nom="Autre").first()
    request_type = RequestType.objects.filter(type="Autre").first()
    if besoin and request_type:
        RequestTypeBesoin.objects.filter(request_type=request_type, besoin=besoin).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0215_noms_canaux_meshtastic_11_octets"),
    ]

    operations = [
        migrations.RunPython(relier_autre, defaire),
    ]
