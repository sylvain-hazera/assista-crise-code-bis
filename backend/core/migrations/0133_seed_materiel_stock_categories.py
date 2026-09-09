from django.db import migrations

# Catégorise le catalogue matériel existant (0055) et ajoute un socle de départ pour les 9
# nouvelles catégories (0132) — extensible en direct par les centres, comme tout le catalogue
# (voir TagLikeViewSetMixin). Regroupement librement inspiré des réserves de matériel des
# associations de sécurité civile, généralisé pour un stock communal courant (pas de matériel
# hyper-spécifique type engin de recherche/poste médical).
EXISTANTS_A_CATEGORISER = {
    "Pompe": "POMPAGE",
    "Lit": "ACCUEIL_HEBERGEMENT",
    "Table": "ACCUEIL_HEBERGEMENT",
    "Chaise": "ACCUEIL_HEBERGEMENT",
    "Tente / Barnum / Chapiteau": "ACCUEIL_HEBERGEMENT",
    "Repas": "DIVERS",
    "Nourriture": "DIVERS",
    "Eau": "DIVERS",
    "Stockage froid alimentaire": "DIVERS",
    "Alimentation électrique": "ENERGIE_ECLAIRAGE",
    "Point télécom / Internet": "OUTILLAGE_TERRAIN",
}

NOUVEAUX_ITEMS = {
    "NETTOYAGE": [
        "Balais et raclettes de chantier",
        "Seaux",
        "Sacs poubelle grande capacité",
        "Nettoyeur haute pression",
        "Aspirateur à eau",
    ],
    "POMPAGE": [
        "Motopompe d'épuisement",
        "Tuyaux d'aspiration et de refoulement",
    ],
    "DEBLAI_MANUTENTION": [
        "Tronçonneuse",
        "Pelle",
        "Pioche",
        "Brouette",
        "Diable de manutention",
    ],
    "ENERGIE_ECLAIRAGE": [
        "Groupe électrogène",
        "Projecteur d'éclairage",
        "Lampe torche ou frontale",
        "Rallonge électrique",
    ],
    "PROTECTION_BATIMENTS": [
        "Bâche de protection",
        "Kit de fixation pour bâches",
        "Film d'étanchéité provisoire",
    ],
    "OUTILLAGE_TERRAIN": [
        "Caisse à outils multifonctions",
        "Corde",
        "Échelle télescopique",
        "Signalisation et balisage de chantier",
        "Talkie-walkie",
    ],
    "PROTECTION_INDIVIDUELLE": [
        "Gants de manutention",
        "Bottes",
        "Waders",
        "Tenue imperméable",
    ],
    "ACCUEIL_HEBERGEMENT": [
        "Couverture",
        "Sac de couchage",
        "Kit d'hygiène",
    ],
    "DIVERS": [
        "Kit de premiers secours",
        "Piles et batteries de rechange",
    ],
}

# Un centre d'accueil des personnes n'a pas vocation à proposer du matériel de déblaiement
# (tronçonneuses, pelles...) dans son propre stock — voir PointType.categories_materiel_exclues.
EXCLUSIONS_PAR_TYPE = {
    "HEBERGEMENT": ["DEBLAI_MANUTENTION"],
}


def seed(apps, schema_editor):
    MaterielCatalogue = apps.get_model("core", "MaterielCatalogue")
    PointType = apps.get_model("core", "PointType")

    for nom, categorie in EXISTANTS_A_CATEGORISER.items():
        MaterielCatalogue.objects.filter(nom__iexact=nom).update(categorie=categorie)

    for categorie, noms in NOUVEAUX_ITEMS.items():
        for nom in noms:
            existing = MaterielCatalogue.objects.filter(nom__iexact=nom).first()
            if existing:
                existing.categorie = categorie
                existing.save(update_fields=["categorie"])
            else:
                MaterielCatalogue.objects.create(nom=nom, categorie=categorie)

    for code, exclues in EXCLUSIONS_PAR_TYPE.items():
        PointType.objects.filter(code=code).update(categories_materiel_exclues=exclues)


def unseed(apps, schema_editor):
    MaterielCatalogue = apps.get_model("core", "MaterielCatalogue")
    PointType = apps.get_model("core", "PointType")

    MaterielCatalogue.objects.filter(nom__in=EXISTANTS_A_CATEGORISER.keys()).update(categorie=None)
    tous_nouveaux = [nom for noms in NOUVEAUX_ITEMS.values() for nom in noms]
    MaterielCatalogue.objects.filter(nom__in=tous_nouveaux).delete()
    for code in EXCLUSIONS_PAR_TYPE:
        PointType.objects.filter(code=code).update(categories_materiel_exclues=[])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0132_materiel_categories_stock"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
