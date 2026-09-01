from django.db import migrations

# Précise la sous-catégorie "Cuve" existante (seedée en 0042) sans renommer sa valeur stockée
# ailleurs par du code (contrairement à TypeMateriel.CUVE côté Offer, RequestType.type n'est
# utilisé que pour l'affichage/la sélection — aucun code ne le compare par chaîne).
CUVE_NOUVEAU_LIBELLE = "Cuve / citerne mobile"
CUVE_NOUVELLE_DESCRIPTION = "Stockage ou transport d'eau ou de carburant — précisez lequel dans la description de votre demande."

# Nouvelles sous-catégories : (nom_parent, [(nom_enfant, description), ...])
SOUS_CATEGORIES = [
    ("Matériel", [
        ("Engin/machine tracté(e)", "Engin ou machine tractée par un tracteur : bulldozer à lame, broyeur, déchaumeur, cover crop..."),
    ]),
    ("Transport", [
        ("Transport d'animaux", "Précisez le type d'animaux (domestiques, élevage...) dans la description de votre demande."),
    ]),
]


def get_or_create_pair(RequestType, Besoin, RequestTypeBesoin, nom, description, parent_request_type):
    request_type, _ = RequestType.objects.update_or_create(
        type=nom,
        defaults={"description": description, "parent": parent_request_type},
    )
    besoin, _ = Besoin.objects.update_or_create(
        nom=nom,
        defaults={"description": description, "actif": True},
    )
    RequestTypeBesoin.objects.get_or_create(request_type=request_type, besoin=besoin)
    return request_type


def seed(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    Besoin = apps.get_model("core", "Besoin")
    RequestTypeBesoin = apps.get_model("core", "RequestTypeBesoin")

    RequestType.objects.filter(type="Cuve").update(
        type=CUVE_NOUVEAU_LIBELLE, description=CUVE_NOUVELLE_DESCRIPTION
    )
    Besoin.objects.filter(nom="Cuve").update(
        nom=CUVE_NOUVEAU_LIBELLE, description=CUVE_NOUVELLE_DESCRIPTION
    )

    for parent_nom, enfants in SOUS_CATEGORIES:
        parent_request_type = RequestType.objects.filter(type=parent_nom).first()
        if parent_request_type is None:
            # Le parent (ex: "Transport") est censé déjà exister (seedé en 0030/entrypoint) ;
            # filet de sécurité si l'ordre de seed a changé entre-temps.
            parent_request_type, _ = RequestType.objects.get_or_create(type=parent_nom)
        for nom, description in enfants:
            get_or_create_pair(RequestType, Besoin, RequestTypeBesoin, nom, description, parent_request_type)


def unseed(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    Besoin = apps.get_model("core", "Besoin")

    RequestType.objects.filter(type=CUVE_NOUVEAU_LIBELLE).update(type="Cuve", description="Stockage d'eau ou de carburant.")
    Besoin.objects.filter(nom=CUVE_NOUVEAU_LIBELLE).update(nom="Cuve", description="Stockage d'eau ou de carburant.")

    noms = [nom for _, enfants in SOUS_CATEGORIES for nom, _ in enfants]
    RequestType.objects.filter(type__in=noms).delete()
    Besoin.objects.filter(nom__in=noms).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0094_ajoute_cuve_contenu_engin_tracte_transport_animaux"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
