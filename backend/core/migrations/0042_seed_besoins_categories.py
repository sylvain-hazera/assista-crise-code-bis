from django.db import migrations

# Nouvelles catégories de premier niveau (RequestType + Besoin en miroir, comme les 8
# catégories déjà en place) — décidées avec l'utilisateur : eau potable et garde d'enfants
# écartées, le reste retenu.
TOP_LEVEL = [
    ("Accompagnement administratif", "Aide aux démarches urgentes, papiers perdus."),
    ("Soutien aux animaux", "Assistance aux animaux de compagnie ou d'élevage."),
    ("Hébergement d'urgence pour animaux", "Accueil temporaire d'animaux, distinct de l'hébergement des personnes."),
    ("Interprétariat / traduction", "Aide à la communication dans une langue étrangère."),
]

# Sous-catégories : (nom_parent, [(nom_enfant, description), ...])
SOUS_CATEGORIES = [
    ("Matériel", [
        ("Groupe électrogène", "Production électrique d'appoint."),
        ("Starlink / connexion satellite", "Connexion internet indépendante du réseau local."),
        ("Télécommunication", "Moyens de communication (radio, téléphonie...)."),
        ("Pompage", "Évacuation d'eau (inondation, cave, etc.)."),
        ("Cuve", "Stockage d'eau ou de carburant."),
    ]),
    ("Interprétariat / traduction", [
        ("Anglais", "Interprétariat/traduction en anglais."),
        ("Français", "Interprétariat/traduction en français."),
        ("Espagnol", "Interprétariat/traduction en espagnol."),
        ("Italien", "Interprétariat/traduction en italien."),
    ]),
]


def get_or_create_pair(RequestType, Besoin, RequestTypeBesoin, nom, description, parent_request_type=None):
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

    for nom, description in TOP_LEVEL:
        get_or_create_pair(RequestType, Besoin, RequestTypeBesoin, nom, description)

    for parent_nom, enfants in SOUS_CATEGORIES:
        parent_request_type = RequestType.objects.filter(type=parent_nom).first()
        if parent_request_type is None:
            # Le parent (ex: "Matériel") est censé déjà exister (seedé en 0030/entrypoint) ;
            # filet de sécurité si l'ordre de seed a changé entre-temps.
            parent_request_type, _ = RequestType.objects.get_or_create(type=parent_nom)
        for nom, description in enfants:
            get_or_create_pair(RequestType, Besoin, RequestTypeBesoin, nom, description, parent_request_type)


def unseed(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    Besoin = apps.get_model("core", "Besoin")

    noms = [nom for nom, _ in TOP_LEVEL]
    for _, enfants in SOUS_CATEGORIES:
        noms += [nom for nom, _ in enfants]

    RequestType.objects.filter(type__in=noms).delete()
    Besoin.objects.filter(nom__in=noms).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_requesttype_parent"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
