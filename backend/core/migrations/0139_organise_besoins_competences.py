from django.db import migrations

# Réorganisation des besoins/compétences existants (données réelles, pas de seed sur base vide) :
# pose `Besoin.nature`, regroupe besoins et compétences en catégories/sous-catégories (parent),
# nettoie quelques compétences qui n'étaient pas des savoir-faire humains, et amorce les
# correspondances besoin<->matériel (nouvelle table BesoinMateriel) en plus de besoin<->compétence
# déjà existant. Voir la proposition validée avec l'utilisateur (session du 2026-09-10).

# --- Besoins : nouvelles catégories (parents purement groupants, nature=None) ---
BESOIN_NOUVELLES_CATEGORIES = [
    "Secours & soins",
    "Hébergement & alimentation",
    "Nettoyage & déblaiement",
    "Engins agricoles / chantier",
    "Pompage & citernes",
    "Énergie & télécom",
]

# (nom_besoin, nom_parent_ou_None, nature_ou_None)
BESOIN_RATTACHEMENTS = [
    ("Accompagnement administratif", None, "COMPETENCE"),
    ("Autre", None, None),
    ("Transport", None, "MIXTE"),
    ("Transport d'animaux", "Transport", "MIXTE"),
    ("Soutien aux animaux", None, "MIXTE"),
    ("Hébergement d'urgence pour animaux", "Soutien aux animaux", "MIXTE"),
    ("Interprétariat / traduction", None, "COMPETENCE"),
    ("Anglais", "Interprétariat / traduction", "COMPETENCE"),
    ("Français", "Interprétariat / traduction", "COMPETENCE"),
    ("Espagnol", "Interprétariat / traduction", "COMPETENCE"),
    ("Italien", "Interprétariat / traduction", "COMPETENCE"),

    ("Soins médicaux", "Secours & soins", "COMPETENCE"),
    ("Soutien psychologique", "Secours & soins", "COMPETENCE"),
    ("Assistance immédiate", "Secours & soins", "MIXTE"),

    ("Hébergement", "Hébergement & alimentation", "MIXTE"),
    ("Nourriture et eau", "Hébergement & alimentation", "MATERIEL"),

    ("Nettoyage - déblaiement", "Nettoyage & déblaiement", "MIXTE"),

    ("Broyeur", "Engins agricoles / chantier", "MATERIEL"),
    ("Bulldozer à lame", "Engins agricoles / chantier", "MATERIEL"),
    ("Cover crop", "Engins agricoles / chantier", "MATERIEL"),
    ("Déchaumeur", "Engins agricoles / chantier", "MATERIEL"),
    ("Manitou", "Engins agricoles / chantier", "MATERIEL"),

    ("Pompage", "Pompage & citernes", "MATERIEL"),
    ("Cuve / citerne mobile", "Pompage & citernes", "MATERIEL"),

    ("Groupe électrogène", "Énergie & télécom", "MATERIEL"),
    ("Starlink / connexion satellite", "Énergie & télécom", "MATERIEL"),
    ("Télécommunication", "Énergie & télécom", "MATERIEL"),
]

# Besoin renommé (catch-all matériel, trop vague tel quel)
BESOIN_RENOMMAGE = {"Matériel": "Matériel divers (à préciser)"}

# Nouveau besoin (langue manquante, souvent demandée)
BESOIN_NOUVEAU = [("Arabe", "Interprétariat / traduction", "COMPETENCE")]

# --- Compétences : nouvelles catégories groupantes ---
COMPETENCE_NOUVELLES_CATEGORIES = [
    "Secours & sécurité",
    "Coordination & encadrement",
    "Technique",
    "Santé & accompagnement",
]

# Renommages : clarifie qu'il s'agit bien d'un savoir-faire humain, pas d'un objet/besoin
COMPETENCE_RENOMMAGES = {
    "accueil": "Accueil",
    "secourisme": "Secourisme",
    "Engin de forage": "Conduite d'engins de forage",
    "Radio": "Opérateur radio",
    "Hébergement": "Organisation de l'accueil / hébergement",
    "Traducteur": "Interprétariat / traduction",
}

# Compétence à fusionner : (nom_a_supprimer, nom_cible) — tout ce qui référence la première est
# repointé sur la seconde avant suppression.
COMPETENCE_FUSIONS = [
    ("Animaux", "Soutien aux animaux"),
    ("traduction anglais", "Anglais"),  # "Anglais" est créé comme nouvelle sous-compétence ci-dessous
]

# (nom_competence, nom_parent_ou_None)
COMPETENCE_RATTACHEMENTS = [
    ("Coordination de crise", "Coordination & encadrement"),
    ("Encadrement d'équipe", "Coordination & encadrement"),
    ("Logistique", "Coordination & encadrement"),

    ("Électronique", "Technique"),
    ("Electronique", "Technique"),  # tolère la variante sans accent déjà en base
    ("Conduite d'engins de forage", "Technique"),
    ("Réparation", "Technique"),

    ("Évacuation", "Secours & sécurité"),
    ("Extinction bénévole du feu", "Secours & sécurité"),
    ("Formation aux gestes de secours", "Secours & sécurité"),
    ("Garde du Feu", "Secours & sécurité"),
    ("Sauvetage", "Secours & sécurité"),
    ("Secourisme", "Secours & sécurité"),

    ("Soins médicaux", "Santé & accompagnement"),
    ("Accueil", "Santé & accompagnement"),
    ("Organisation de l'accueil / hébergement", "Santé & accompagnement"),

    ("Nettoyage et déblaiement", None),
    ("Opérateur radio", None),
    ("Soutien aux animaux", None),
    ("Transport", None),
    ("Interprétariat / traduction", None),
]

# Nouvelles compétences (dont les langues, en miroir du côté Besoin)
COMPETENCE_NOUVELLES = [
    ("Soutien psychologique", "Santé & accompagnement"),
    ("Anglais", "Interprétariat / traduction"),
    ("Français", "Interprétariat / traduction"),
    ("Espagnol", "Interprétariat / traduction"),
    ("Italien", "Interprétariat / traduction"),
    ("Arabe", "Interprétariat / traduction"),
]

# --- Matériel catalogue : catégorie manquante ---
MATERIEL_CATEGORIE = {
    "Chambre froide": "DIVERS",
    "Cuve": "POMPAGE",
    "Étuve": "DIVERS",
    "Remorque": "DEBLAI_MANUTENTION",
}

# --- Correspondances besoin -> matériel (nouvelle table BesoinMateriel) ---
BESOIN_MATERIEL_LIENS = [
    ("Broyeur", ["Broyeur"]),
    ("Bulldozer à lame", ["Bulldozer à lame"]),
    ("Cover crop", ["Cover crop"]),
    ("Déchaumeur", ["Déchaumeur"]),
    ("Manitou", ["Manitou"]),
    ("Groupe électrogène", ["Groupe électrogène"]),
    ("Pompage", ["Motopompe d'épuisement", "Pompe", "Tuyaux d'aspiration et de refoulement"]),
    ("Cuve / citerne mobile", ["Cuve"]),
    ("Nourriture et eau", ["Eau", "Nourriture", "Repas", "Stockage froid alimentaire"]),
    ("Hébergement", ["Chaise", "Couverture", "Kit d'hygiène", "Lit", "Sac de couchage", "Table", "Tente / Barnum / Chapiteau"]),
    ("Nettoyage - déblaiement", [
        "Aspirateur à eau", "Balais et raclettes de chantier", "Nettoyeur haute pression",
        "Sacs poubelle grande capacité", "Seaux",
        "Brouette", "Diable de manutention", "Pelle", "Pioche", "Tronçonneuse",
    ]),
    ("Assistance immédiate", ["Kit de premiers secours"]),
    ("Starlink / connexion satellite", ["Point télécom / Internet"]),
    ("Télécommunication", ["Talkie-walkie"]),
    ("Transport", ["Remorque"]),
]

# --- Correspondances besoin -> compétence à ajouter (au-delà des 3 déjà en base) ---
BESOIN_COMPETENCE_LIENS = [
    ("Soins médicaux", "Soins médicaux"),
    ("Soutien psychologique", "Soutien psychologique"),
    ("Assistance immédiate", "Secourisme"),
    ("Interprétariat / traduction", "Interprétariat / traduction"),
    ("Anglais", "Anglais"),
    ("Français", "Français"),
    ("Espagnol", "Espagnol"),
    ("Italien", "Italien"),
    ("Arabe", "Arabe"),
    ("Soutien aux animaux", "Soutien aux animaux"),
    ("Transport", "Transport"),
    ("Transport d'animaux", "Transport"),
]


def organiser(apps, schema_editor):
    Besoin = apps.get_model("core", "Besoin")
    Competence = apps.get_model("core", "Competence")
    BesoinCompetence = apps.get_model("core", "BesoinCompetence")
    BesoinMateriel = apps.get_model("core", "BesoinMateriel")
    MaterielCatalogue = apps.get_model("core", "MaterielCatalogue")
    InstitutionCompetence = apps.get_model("core", "InstitutionCompetence")
    AffectationCompetence = apps.get_model("core", "AffectationCompetence")
    Dossier = apps.get_model("core", "Dossier")
    AffectationRoleOperationnel = apps.get_model("core", "AffectationRoleOperationnel")
    DelegationCompetence = apps.get_model("core", "DelegationCompetence")

    # --- Besoins ---
    for nom in BESOIN_NOUVELLES_CATEGORIES:
        Besoin.objects.get_or_create(nom=nom, defaults={"actif": True})

    for ancien, nouveau in BESOIN_RENOMMAGE.items():
        Besoin.objects.filter(nom=ancien).update(nom=nouveau)

    for nom, parent_nom, nature in BESOIN_NOUVEAU:
        Besoin.objects.get_or_create(nom=nom, defaults={"actif": True, "nature": nature})

    for nom, parent_nom, nature in BESOIN_RATTACHEMENTS:
        besoin = Besoin.objects.filter(nom=nom).first()
        if besoin is None:
            continue
        besoin.parent = Besoin.objects.filter(nom=parent_nom).first() if parent_nom else None
        besoin.nature = nature
        besoin.save(update_fields=["parent", "nature"])

    for nom, parent_nom, nature in BESOIN_NOUVEAU:
        besoin = Besoin.objects.filter(nom=nom).first()
        if besoin is not None:
            besoin.parent = Besoin.objects.filter(nom=parent_nom).first() if parent_nom else None
            besoin.nature = nature
            besoin.save(update_fields=["parent", "nature"])

    # --- Compétences ---
    for nom in COMPETENCE_NOUVELLES_CATEGORIES:
        Competence.objects.get_or_create(nom=nom, defaults={"active": True})

    for ancien, nouveau in COMPETENCE_RENOMMAGES.items():
        Competence.objects.filter(nom=ancien).exclude(nom=nouveau).update(nom=nouveau)

    def _repointe_unique(qs, source, cible, champs_unicite):
        # Pour les modèles à contrainte d'unicité incluant `competence` (InstitutionCompetence,
        # AffectationRoleOperationnel) : un simple .update() planterait si une ligne équivalente
        # existe déjà pour la cible — on répercute ligne par ligne, en supprimant le doublon
        # plutôt que de planter la migration.
        for ligne in qs.filter(competence=source):
            doublon = qs.filter(competence=cible, **{c: getattr(ligne, c + "_id", getattr(ligne, c)) for c in champs_unicite if c != "competence"}).exclude(pk=ligne.pk).exists()
            if doublon:
                ligne.delete()
            else:
                ligne.competence = cible
                ligne.save(update_fields=["competence"])

    for a_supprimer, cible in COMPETENCE_FUSIONS:
        source = Competence.objects.filter(nom=a_supprimer).first()
        if source is None:
            continue
        # "Anglais" (cible de la fusion "traduction anglais") est créée juste après si besoin.
        cible_obj, _ = Competence.objects.get_or_create(nom=cible, defaults={"active": True})
        # Repointe TOUTES les FK/M2M vers la compétence supprimée avant de la supprimer — la
        # plupart sont en CASCADE (pas juste BesoinCompetence qui est en PROTECT), donc une
        # suppression directe aurait silencieusement effacé des affectations/déclarations
        # réelles au lieu de les préserver sous le nouveau nom.
        BesoinCompetence.objects.filter(competence=source).update(competence=cible_obj)
        _repointe_unique(InstitutionCompetence.objects, source, cible_obj, ["institution"])
        AffectationCompetence.objects.filter(competence=source).update(competence=cible_obj)
        Dossier.objects.filter(competence=source).update(competence=cible_obj)
        _repointe_unique(AffectationRoleOperationnel.objects, source, cible_obj, ["utilisateur", "institution", "role"])
        DelegationCompetence.objects.filter(competence=source).update(competence=cible_obj)
        for offre in source.offres.all():
            offre.competences.add(cible_obj)
            offre.competences.remove(source)
        source.delete()

    for nom, parent_nom in COMPETENCE_NOUVELLES:
        Competence.objects.get_or_create(nom=nom, defaults={"active": True})

    for nom, parent_nom in COMPETENCE_RATTACHEMENTS + COMPETENCE_NOUVELLES:
        competence = Competence.objects.filter(nom=nom).first()
        if competence is None:
            continue
        competence.parent = Competence.objects.filter(nom=parent_nom).first() if parent_nom else None
        competence.save(update_fields=["parent"])

    # --- Matériel catalogue : catégorie manquante ---
    for nom, categorie in MATERIEL_CATEGORIE.items():
        MaterielCatalogue.objects.filter(nom=nom, categorie__isnull=True).update(categorie=categorie)

    # --- Correspondances besoin <-> matériel ---
    for besoin_nom, materiels_noms in BESOIN_MATERIEL_LIENS:
        besoin = Besoin.objects.filter(nom=besoin_nom).first()
        if besoin is None:
            continue
        for materiel_nom in materiels_noms:
            materiel = MaterielCatalogue.objects.filter(nom=materiel_nom).first()
            if materiel is None:
                continue
            BesoinMateriel.objects.get_or_create(besoin=besoin, materiel=materiel)

    # --- Correspondances besoin <-> compétence (repointe aussi le lien historique
    # "Hébergement d'urgence pour animaux -> Animaux", déjà migré vers "Soutien aux animaux"
    # par la fusion ci-dessus) ---
    for besoin_nom, competence_nom in BESOIN_COMPETENCE_LIENS:
        besoin = Besoin.objects.filter(nom=besoin_nom).first()
        competence = Competence.objects.filter(nom=competence_nom).first()
        if besoin is None or competence is None:
            continue
        BesoinCompetence.objects.get_or_create(besoin=besoin, competence=competence)


def revenir(apps, schema_editor):
    # Pas de retour arrière automatique fin : cette migration ne fait que réorganiser des
    # données existantes (renommages, rattachements, liens) sans rien qui casserait un
    # rollback de schéma — seules les catégories/compétences purement créées ici sont
    # retirées pour rester propre si on annule ce chantier précis.
    Besoin = apps.get_model("core", "Besoin")
    Competence = apps.get_model("core", "Competence")

    Besoin.objects.filter(nom__in=BESOIN_NOUVELLES_CATEGORIES).delete()
    Besoin.objects.filter(nom__in=[n for n, _, _ in BESOIN_NOUVEAU]).delete()
    for ancien, nouveau in BESOIN_RENOMMAGE.items():
        Besoin.objects.filter(nom=nouveau).update(nom=ancien)

    Competence.objects.filter(nom__in=COMPETENCE_NOUVELLES_CATEGORIES).delete()
    Competence.objects.filter(nom__in=[n for n, _ in COMPETENCE_NOUVELLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0138_besoin_nature_besoin_materiel"),
    ]

    operations = [
        migrations.RunPython(organiser, revenir),
    ]
