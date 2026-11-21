"""Relie les offres « Bénévolat » et « Matériel » aux thèmes que les institutions écoutent.

Constaté le 21/11/2026 en jouant le parcours d'un bénévole externe : en production, l'offre
« Bénévolat » n'était reliée à AUCUN thème (types-a-lecoute ne la proposait donc jamais, sauf
repli quand rien n'est écouté), et « Matériel » ne l'était qu'à « Matériel divers » : une
mairie qui écoute « Pompage & citernes » ne voyait jamais arriver l'offre d'une pompe.

Additif et réexécutable : un lien n'est créé que si le type et le besoin existent et que le
lien manque. Rien n'est retiré à l'annulation (les liens ont pu être repris à la main depuis).
"""
from django.db import migrations

LIENS = {
    "Bénévolat": [
        "Nettoyage - déblaiement", "Assistance immédiate", "Nourriture et eau",
        "Accompagnement administratif",
    ],
    "Matériel": [
        "Pompage", "Cuve / citerne mobile", "Groupe électrogène", "Starlink / connexion satellite",
        "Télécommunication", "Broyeur", "Bulldozer à lame", "Cover crop", "Déchaumeur", "Manitou",
    ],
}


def relier(apps, schema_editor=None):
    OfferType = apps.get_model("core", "OfferType")
    Besoin = apps.get_model("core", "Besoin")
    Lien = apps.get_model("core", "OfferTypeBesoin")
    crees = 0
    for type_nom, besoins in LIENS.items():
        for offre in OfferType.objects.filter(type=type_nom):
            for besoin in Besoin.objects.filter(nom__in=besoins):
                if not Lien.objects.filter(offer_type=offre, besoin=besoin).exists():
                    Lien.objects.create(offer_type=offre, besoin=besoin)
                    crees += 1
    return crees


class Migration(migrations.Migration):
    dependencies = [("core", "0366_competences_fiche_benevole")]
    operations = [migrations.RunPython(relier, migrations.RunPython.noop)]
