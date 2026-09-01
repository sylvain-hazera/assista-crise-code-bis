from django.db import migrations

# Rubrique "Engins agricoles / chantiers / spéciaux" (voir propose-help-form) : liste à cocher
# dédiée, extensible en direct par les utilisateurs (voir MaterielCatalogueViewSet, patron
# hashtag) — ce seed ne pose que le socle initial.
ENGINS = [
    "Bulldozer à lame",
    "Broyeur",
    "Déchaumeur",
    "Cover crop",
    "Manitou",
]

# Côté demandes, l'entrée générique "Engin/machine tracté(e)" (posée en 0095, jamais utilisée en
# pratique — déployée quelques minutes avant ce correctif) est remplacée par les mêmes noms
# précis que côté offres, cohérence avec la liste à cocher ci-dessus.
GENERIQUE_REMPLACEE = "Engin/machine tracté(e)"


def seed(apps, schema_editor):
    MaterielCatalogue = apps.get_model("core", "materielcatalogue")
    RequestType = apps.get_model("core", "RequestType")
    Besoin = apps.get_model("core", "Besoin")
    RequestTypeBesoin = apps.get_model("core", "RequestTypeBesoin")

    for nom in ENGINS:
        existing = MaterielCatalogue.objects.filter(nom__iexact=nom).first()
        if existing:
            existing.categorie = "ENGIN"
            existing.save(update_fields=["categorie"])
        else:
            MaterielCatalogue.objects.create(nom=nom, categorie="ENGIN")

    RequestType.objects.filter(type=GENERIQUE_REMPLACEE).delete()
    Besoin.objects.filter(nom=GENERIQUE_REMPLACEE).delete()

    materiel = RequestType.objects.filter(type="Matériel").first()
    if materiel is None:
        materiel, _ = RequestType.objects.get_or_create(type="Matériel")

    for nom in ENGINS:
        request_type, _ = RequestType.objects.update_or_create(
            type=nom, defaults={"description": "", "parent": materiel},
        )
        besoin, _ = Besoin.objects.update_or_create(
            nom=nom, defaults={"description": "", "actif": True},
        )
        RequestTypeBesoin.objects.get_or_create(request_type=request_type, besoin=besoin)


def unseed(apps, schema_editor):
    MaterielCatalogue = apps.get_model("core", "materielcatalogue")
    RequestType = apps.get_model("core", "RequestType")
    Besoin = apps.get_model("core", "Besoin")

    MaterielCatalogue.objects.filter(nom__in=ENGINS, categorie="ENGIN").update(categorie=None)
    RequestType.objects.filter(type__in=ENGINS).delete()
    Besoin.objects.filter(nom__in=ENGINS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0096_engins_catalogue_categorie_et_retrait_engin_tracte"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
