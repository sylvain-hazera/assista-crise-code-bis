import uuid
import os
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.gis.db import models as gis_models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from core.validators import validate_image_file
from .validators import validate_image_file

class UserRole(models.TextChoices):
    """Rôles des utilisateurs"""
    ADMINISTRATOR = "ADMIN", "Administrateur"
    LOCAL_AUTHORITY = "AUT_LOCALE", "Autorité locale"
    ORGANIZED_RESCUE = "SECOURS", "Secours organisés"
    REGULATEUR = "REGULATEUR", "Régulateur de crise"
    SIMPLE_USER = "UTIL_SIMPLE", "Utilisateur"


class Status(models.TextChoices):
    """Statuts des demandes, offres et informations"""
    UNPROCESSED = "NON_TRAITEE", "Non traitée"
    IN_PROGRESS = "EN_COURS", "En cours de traitement"
    PROCESSED = "TRAITEE", "Traitée"
    AVAILABLE = "DISPONIBLE", "Disponible"
    UNAVAILABLE = "INDISPONIBLE", "Indisponible"


class Environment(models.TextChoices):
    """Zone de démonstration : PROD et DEMO partagent le même backend/frontend, mais jamais
    les mêmes crises/offres/demandes/signalements. Le vocabulaire partagé (types, compétences,
    catalogue matériel...) n'a pas ce champ et reste unique aux deux zones."""
    PROD = "PROD", "Production"
    DEMO = "DEMO", "Démonstration"


class EnvironmentScopedModel(models.Model):
    """Base commune à toutes les données "de contenu" isolées entre PROD et DEMO — voir
    Environment. `EnvironmentScopedViewSetMixin` (views.py) filtre automatiquement dessus."""
    environment = models.CharField(max_length=4, choices=Environment.choices, default=Environment.PROD)

    class Meta:
        abstract = True


class Commune(models.Model):
    """Référentiel commune (code INSEE) — nom et centroïde résolus à la demande depuis
    geo.api.gouv.fr et conservés durablement. Remplace le cache Django (LocMemCache puis
    FileBasedCache) précédemment utilisé par geo_lookup.py : cette donnée est quasi-permanente
    (une commune ne change pratiquement jamais de nom/position), mérite d'être sauvegardée avec
    le reste de la base (le cache fichier ne l'était pas) et ne doit pas expirer arbitrairement.
    Vocabulaire partagé PROD/DEMO, comme MaterielCatalogue/Competence : pas de champ
    `environment`, une commune n'a pas de sens à exister "en double" par zone."""

    code = models.CharField(max_length=10, primary_key=True)
    nom = models.CharField(max_length=255, null=True, blank=True)
    centre_latitude = models.FloatField(null=True, blank=True)
    centre_longitude = models.FloatField(null=True, blank=True)
    # departement_code/epci_code/population : référentiel administratif complet, chargé en
    # masse depuis geo.api.gouv.fr (voir core/management/commands/import_communes.py) —
    # distinct du reverse-géocodage à la demande ci-dessus (qui ne résout qu'une commune à la
    # fois, au moment où un point GPS la traverse). Sert à scoper la consultation des offres de
    # bénévoles par secteur (mairie -> commune, communauté de communes -> EPCI, SDIS/
    # gendarmerie/préfecture -> département) sans jointure géographique en lecture.
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    population = models.PositiveIntegerField(null=True, blank=True)
    # Aléas naturels/technologiques recensés sur la commune (API Géorisques, gaspar/risques) —
    # {"num_risque", "libelle_risque_long"} par entrée, jamais recalculé en lecture (voir
    # geo_lookup.commune_risques). Alimente la section "diagnostic des risques" attendue par un
    # PCS/DICRIM (voir Institution.secteur_nom pour le même principe de dénormalisation).
    risques_territoire = models.JSONField(default=list, blank=True)
    date_maj = models.DateTimeField(auto_now=True)
    # Distinct de date_maj (mise à jour seulement en cas de succès) : posé à CHAQUE tentative,
    # réussie ou non — voir geo_lookup.RETRY_COOLDOWN. Sans lui, un code sans correspondance
    # (coordonnées de test imprécises, zone sans adresse répertoriée...) serait retenté à
    # chaque lecture, indéfiniment : mesuré en direct, 119 points non résolus sur 225 en DEMO
    # suffisaient à ajouter ~15-20s à /api/demandes/ (un appel externe par point non résolu, à
    # chaque requête).
    derniere_tentative = models.DateTimeField(null=True, blank=True)
    # Cooldown séparé de derniere_tentative ci-dessus : l'API Géorisques (gaspar/risques) est un
    # service externe distinct de geo.api.gouv.fr (nom/centroïde/departement), avec sa propre
    # disponibilité — un échec sur l'un ne doit jamais bloquer une nouvelle tentative sur l'autre.
    derniere_tentative_risques = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.nom or self.code


class PointCommune(models.Model):
    """Résultat d'un reverse-géocodage (point GPS -> commune), arrondi à 4 décimales (~11m) —
    voir Commune pour le nom/centroïde une fois résolu. Beaucoup de points distincts peuvent
    partager la même commune, d'où la normalisation en deux tables plutôt que dupliquer le nom
    à chaque point."""

    lat = models.FloatField()
    lon = models.FloatField()
    commune = models.ForeignKey(Commune, on_delete=models.CASCADE, null=True, blank=True, related_name="points")
    date_maj = models.DateTimeField(auto_now=True)
    # Voir Commune.derniere_tentative — même logique de cooldown pour un point sans résultat.
    derniere_tentative = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lat", "lon"], name="uq_point_commune"),
        ]

    def __str__(self) -> str:
        return f"({self.lat}, {self.lon}) -> {self.commune_id or '?'}"


class User(AbstractUser):
    """Modèle utilisateur personnalisé"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    photo = models.ImageField(upload_to="photos/", null=True, blank=True, validators=[validate_image_file])
    type = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.SIMPLE_USER,
    )
    demo_role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        null=True, blank=True,
        help_text="Rôle appliqué en zone de démonstration. Null = aucun accès à la démo. "
                   "Réglé manuellement par un administrateur, jamais hérité de `type`.",
    )
    postal_code = models.CharField(max_length=5, null=True, blank=True)
    enabled = models.BooleanField(default=True)

    # Renseignements institutionnels déclarés à l'inscription, conservés jusqu'à la confirmation
    # de l'email (clic sur le lien d'activation) : le rattachement à une institution ne doit se
    # faire qu'une fois la possession de la boîte mail prouvée, jamais à la simple soumission
    # du formulaire d'inscription.
    pending_institution_name = models.CharField(max_length=255, null=True, blank=True)
    pending_institution_type = models.CharField(max_length=100, null=True, blank=True)
    pending_commune_name = models.CharField(max_length=255, null=True, blank=True)
    pending_commune_code = models.CharField(max_length=20, null=True, blank=True)

    institution = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="utilisateurs"
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']
    
    email = models.EmailField(unique=True)

    affected_crisis = models.ForeignKey(
        "Crisis",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="victims"
    )
    viewed_requests = models.ManyToManyField(
        "Request",
        blank=True,
        related_name="viewing_users"
    )

    viewed_informations = models.ManyToManyField(
        "Information",
        blank=True,
        related_name="viewing_users"
    )

    viewed_offers = models.ManyToManyField(
        "Offer",
        blank=True,
        related_name="viewing_users"
    )

    validator = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="validated_users"
    )

    def __str__(self) -> str:
        return self.username


class TypeCrise(models.TextChoices):
    
    INCENDIE = "INCENDIE", "Incendie"
    INONDATION = "INONDATION", "Inondation"
    ACCIDENT = "ACCIDENT", "Accident"
    CATASTROPHE_NATURELLE = "CATASTROPHE_NATURELLE", "Catastrophe naturelle"
    AUTRE = "AUTRE", "Autre"

class Crisis(EnvironmentScopedModel):
    """Modèle représentant une crise"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    type = models.CharField(
        max_length=50,
        choices=TypeCrise.choices,
        default=TypeCrise.AUTRE,
    )
    description = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos/crises/", null=True, blank=True)
    location = gis_models.PointField(srid=4326)
    radius = models.IntegerField(default=10)
    zone = gis_models.PolygonField(srid=4326, null=True, blank=True)

    # Zone composée à partir de communes/départements ajoutés un par un : le frontend
    # récupère le contour officiel de chaque commune/département (geo.api.gouv.fr), le
    # bufferise du rayon `radius` (km) puis fait l'union du tout — indépendant de `zone`
    # (le polygone dessiné à la main) pour ne pas complexifier ce mécanisme existant, déjà
    # utilisé tel quel par Team/DelegationCompetence. `zone_departements`/`zone_communes`
    # ne servent qu'à mémoriser la composition (recalcul/retrait ultérieur côté frontend) ;
    # la géométrie effective est `zone_secteurs`.
    zone_departements = models.JSONField(
        default=list, blank=True,
        help_text="Codes département ajoutés à la zone de crise (ex: ['38', '73']).",
    )
    zone_communes = models.JSONField(
        default=list, blank=True,
        help_text="Codes commune INSEE ajoutés à la zone de crise (ex: ['38185']).",
    )
    zone_secteurs = gis_models.MultiPolygonField(
        srid=4326, null=True, blank=True,
        help_text="Union des contours de zone_departements/zone_communes, bufferisés de `radius` km.",
    )
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)

    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="declared_crises",
    )

    validator = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="validated_crises"
    )

    class Meta:
        verbose_name_plural = "Crisis"

    def __str__(self) -> str:
        return self.name


class TypeImplication(models.TextChoices):
    IMPLIQUE = "IMPLIQUE", "Impliquée"
    ACTEUR = "ACTEUR", "Acteur opérationnel"


class StatutImplication(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de validation"
    VALIDEE = "VALIDEE", "Validée"
    REFUSEE = "REFUSEE", "Refusée"


class ImplicationInstitution(EnvironmentScopedModel):
    """Rattachement d'une institution à une crise : impliquée (sa commune est concernée)
    et/ou acteur opérationnel (elle gère des moyens sur cette crise, ex: un point de
    collecte). Les deux statuts peuvent coexister pour une même institution/crise."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(
        Crisis,
        on_delete=models.CASCADE,
        related_name="implications"
    )

    institution = models.ForeignKey(
        "Institution",
        on_delete=models.CASCADE,
        related_name="implications_crises"
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="implications_declarees"
    )

    type_implication = models.CharField(
        max_length=20,
        choices=TypeImplication.choices
    )

    commentaire = models.TextField(blank=True, null=True)

    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    responsable = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="implications_responsable",
        help_text="Personne responsable/régulatrice pour l'institution sur cette crise.",
    )

    themes = models.ManyToManyField(
        "Besoin",
        blank=True,
        related_name="implications_institutions",
        help_text="Besoins sur lesquels l'institution est à l'écoute pour cette crise.",
    )

    # VALIDEE par défaut : ne change rien pour IMPLIQUE (jamais soumise à validation) ni pour
    # ACTEUR déclarée par une institution AUT_LOCALE (auto-validée). Seule
    # ImplicationInstitutionViewSet.perform_create pose EN_ATTENTE, et seulement pour une
    # déclaration ACTEUR d'une institution non-AUT_LOCALE (association/AASC...) — voir
    # ImplicationInstitutionViewSet.valider/refuser pour la suite du workflow.
    statut = models.CharField(
        max_length=20, choices=StatutImplication.choices, default=StatutImplication.VALIDEE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["crise", "institution", "type_implication"],
                name="uq_implication_crise_institution_type"
            )
        ]

    def __str__(self):
        return f"{self.institution} - {self.crise} ({self.type_implication})"


class DureeHebergement(models.TextChoices):
    TEMPORAIRE = "TEMPORAIRE", "Temporaire"
    LONGUE_DUREE = "LONGUE_DUREE", "Longue durée"


class TypeLoyer(models.TextChoices):
    GRATUIT = "GRATUIT", "Gratuit"
    NEGOCIE = "NEGOCIE", "Loyer négocié (du fait de la situation)"
    MARCHE = "MARCHE", "Loyer au prix du marché"


class TypeLogement(models.TextChoices):
    MAISON = "MAISON", "Maison"
    APPARTEMENT = "APPARTEMENT", "Appartement"
    STUDIO = "STUDIO", "Studio"
    COLOCATION = "COLOCATION", "Colocation"
    CHAMBRE = "CHAMBRE", "Chambre"


class NiveauLogement(models.TextChoices):
    PLAIN_PIED = "PLAIN_PIED", "Plain-pied"
    ETAGE = "ETAGE", "Étage"


class AccesEtage(models.TextChoices):
    ESCALIER = "ESCALIER", "Escalier"
    ASCENSEUR = "ASCENSEUR", "Ascenseur"


class HebergementDetailsMixin(models.Model):
    """Champs communs à une offre et une demande d'hébergement — un logement proposé ou
    recherché partage exactement le même vocabulaire (voir Offer/Request). L'adresse du
    logement lui-même n'a pas de champ dédié ici : elle utilise `location`/`commune_code`,
    déjà propres à chaque Offer/Request (voir propose-help-form/request-help-form, qui posent
    un sélecteur d'adresse spécifique à la ligne Hébergement quand elle diffère de celle du
    déclarant, sinon retombent sur cette dernière)."""

    hebergement_duree = models.CharField(max_length=20, choices=DureeHebergement.choices, null=True, blank=True)
    type_loyer = models.CharField(max_length=20, choices=TypeLoyer.choices, null=True, blank=True)
    # Posés uniquement quand type_loyer == NEGOCIE ou MARCHE.
    loyer_montant_min = models.PositiveIntegerField(null=True, blank=True)
    loyer_montant_max = models.PositiveIntegerField(null=True, blank=True)
    type_logement = models.CharField(max_length=20, choices=TypeLogement.choices, null=True, blank=True)
    niveau_logement = models.CharField(max_length=20, choices=NiveauLogement.choices, null=True, blank=True)
    # Posé uniquement quand niveau_logement == ETAGE.
    acces_etage = models.CharField(max_length=20, choices=AccesEtage.choices, null=True, blank=True)
    nombre_pieces = models.PositiveIntegerField(null=True, blank=True)
    nombre_chambres = models.PositiveIntegerField(null=True, blank=True)
    capacite_adultes = models.PositiveIntegerField(null=True, blank=True)
    capacite_enfants = models.PositiveIntegerField(null=True, blank=True)
    animaux_acceptes = models.BooleanField(default=False)
    jardin = models.BooleanField(default=False)
    pmr_compatible = models.BooleanField(default=False)

    class Meta:
        abstract = True


class RequestType(models.Model):
    """Types de demandes d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    # Même patron que OfferType.actif : jamais de suppression réelle (FK PROTECT depuis
    # Request), seulement un masquage du formulaire public pour les types qu'on ne veut plus
    # proposer (ex: "Soins médicaux", voir migration de données associée).
    actif = models.BooleanField(default=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sous_categories",
        help_text="Catégorie parente si ce type est une précision d'un besoin plus large "
                   "(ex: 'Groupe électrogène' sous 'Matériel', 'Anglais' sous "
                   "'Interprétariat / traduction').",
    )

    def __str__(self) -> str:
        return self.type


class Request(HebergementDetailsMixin, EnvironmentScopedModel):
    """Demandes d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos/demandes/", null=True, blank=True, validators=[validate_image_file])
    # Nullable (contrairement à l'origine) : une demande d'hébergement n'a pas d'adresse
    # précise à donner, seulement une zone de recherche (voir zone_recherche_communes) —
    # même assouplissement déjà fait pour Offer.location. team_zone_specificity et
    # annotate_distance_from_crisis gèrent déjà l'absence de location sans erreur.
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    commune_code = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Code commune INSEE résolu à la saisie de l'adresse (autocomplete), "
                   "utilisé pour le matching géographique avec les zones d'intervention des équipes. "
                   "Pour une demande d'hébergement : première commune de zone_recherche_communes.",
    )
    # Dénormalisés depuis commune_code (voir RequestViewSet.perform_create), même principe que
    # sur Offer : permet vue_secteur (EPCI/département/région) sans jointure géographique en
    # lecture.
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    # Zone de recherche d'un logement (demande d'hébergement uniquement) : une ou plusieurs
    # communes saisies manuellement, avec un rayon optionnel — remplace l'adresse précise,
    # inadaptée à une recherche de logement (on ne sait pas encore où on va vivre). Même
    # convention que Team.communes/Crisis.zone_communes (JSONField de codes INSEE).
    zone_recherche_communes = models.JSONField(default=list, blank=True)
    zone_recherche_rayon_km = models.PositiveIntegerField(null=True, blank=True)
    # Demande de transport (request_type de type "Transport") impliquant un véhicule : combien
    # de personnes il peut transporter en plus du conducteur — voir Offer.nombre_places_assises
    # et MaterielPoint.nombre_places_assises pour les deux autres rubriques véhicules de l'app.
    # Pas de champ transport_type ici contrairement à Offer : optionnel, sans condition d'affichage.
    nombre_places_assises = models.PositiveIntegerField(null=True, blank=True)
    first_name_request = models.CharField(max_length=60)
    last_name_request = models.CharField(max_length=80)
    email_request = models.EmailField()
    phone_request = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNPROCESSED,
    )
    actif = models.BooleanField(
        default=True,
        help_text="False = désactivée par son auteur ou un acteur institutionnel — reste "
                   "visible dans l'historique jusqu'à la clôture de la crise rattachée, "
                   "où elle est définitivement purgée. Ne masque jamais les demandes actives.",
    )

    request_type = models.ForeignKey(
        RequestType, on_delete=models.PROTECT, related_name="requests"
    )
    crisis = models.ForeignKey(
        "Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_requests",
    )

    def __str__(self) -> str:
        return self.title


class RequestPhoto(EnvironmentScopedModel):
    """Photos additionnelles d'une demande d'aide, au-delà de la photo principale
    (`Request.photo`, inchangée — la première/celle désignée par le demandeur reste stockée
    là, aucun autre code ne bouge) : jusqu'à 9 de plus, 10 au total avec la principale. Même
    régime de confidentialité que `Request.photo` (voir user_can_view_photo), servies via une
    action preview dédiée plutôt qu'une URL brute d'image."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="photos")

    image = models.ImageField(upload_to="photos/demandes/galerie/", validators=[validate_image_file])

    ordre = models.PositiveIntegerField(default=0)

    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "date_ajout"]

    def __str__(self) -> str:
        return f"Photo galerie — {self.request.title}"


class InformationType(models.Model):
    """Types d'informations"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return self.type


class Information(EnvironmentScopedModel):
    """Informations partagées"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    photo = models.ImageField(upload_to="photos/informations/", null=True, blank=True, validators=[validate_image_file])
    first_name_information = models.CharField(max_length=60)
    last_name_information = models.CharField(max_length=80)
    email_information = models.EmailField()
    phone_information = models.CharField(max_length=20)
    location = gis_models.PointField(srid=4326)
    commune_code = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Code commune INSEE résolu à la saisie de l'adresse (autocomplete), symétrique "
                   "à Request.commune_code — utilisé pour la vue mairie (filtrage par commune).",
    )
    azimuth = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(360)],
        help_text="Azimut (0-360°, 0=Nord) capturé par la boussole du téléphone au moment "
                   "de la photo — direction vers laquelle l'appareil pointait, pour situer "
                   "ce que montre le signalement (ex: quel côté de la route est inondé).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    actif = models.BooleanField(
        default=True,
        help_text="False = désactivée par son auteur ou un acteur institutionnel — reste "
                   "visible dans l'historique jusqu'à la clôture de la crise rattachée, "
                   "où elle est définitivement purgée. Ne masque jamais les signalements actifs.",
    )

    information_type = models.ForeignKey(
        InformationType, on_delete=models.PROTECT, related_name="informations"
    )
    crisis = models.ForeignKey(
        "Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="informations"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_informations",
    )

    def __str__(self) -> str:
        return self.title


class OfferType(models.Model):
    """Types d'offres d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.type


class TypeTransportOffre(models.TextChoices):
    PERSONNES = "PERSONNES", "Transport de personnes"
    MATERIEL = "MATERIEL", "Transport de matériel"
    ANIMAUX = "ANIMAUX", "Transport d'animaux"


class TypeMateriel(models.TextChoices):
    CUVE = "CUVE", "Cuve"
    POMPE = "POMPE", "Pompe"
    ETUVE = "ETUVE", "Étuve"
    CHAMBRE_FROIDE = "CHAMBRE_FROIDE", "Chambre froide"
    REMORQUE = "REMORQUE", "Remorque"
    # Pas d'entrée générique "Engin tracté" ici : chaque engin (bulldozer à lame, broyeur,
    # déchaumeur, cover crop, manitou...) est une entrée à part du catalogue partagé
    # (MaterielCatalogue.categorie == ENGIN, voir propose-help-form) plutôt qu'un choix figé —
    # cohérent avec le "Autre" ci-dessous, et extensible sans migration de schéma.
    AUTRE = "AUTRE", "Autre"


class CuveContenu(models.TextChoices):
    """Précision posée uniquement quand TypeMateriel.CUVE est choisi — le libellé de
    TypeMateriel.CUVE reste volontairement "Cuve" (pas "Cuve / citerne mobile") pour ne pas
    fragmenter le catalogue partagé déjà seedé sous ce nom (voir affecter_stock, qui résout
    l'item catalogue par get_materiel_type_display())."""
    EAU = "EAU", "Eau"
    CARBURANT = "CARBURANT", "Carburant"


class TypeSoutien(models.TextChoices):
    PROFESSIONNEL = "PROFESSIONNEL", "Professionnel de santé"
    SECOURISTE = "SECOURISTE", "Secouriste (y compris santé mentale)"


class LivraisonMateriel(models.TextChoices):
    A_RECUPERER = "A_RECUPERER", "À récupérer sur place"
    LIVRAISON_POSSIBLE = "LIVRAISON_POSSIBLE", "Peut être déposé dans un centre de regroupement"


class Offer(HebergementDetailsMixin, EnvironmentScopedModel):
    """Offres d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos/offres/", null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    # Résolus une seule fois à la création (voir OfferViewSet.perform_create), à partir de
    # `location` — même rôle que Request.commune_code/Information.commune_code, ajouté ici
    # pour la "vue secteur" (mairie/EPCI/département) sans reverse-géocoder chaque offre à
    # chaque requête (l'ancien vue_mairie le faisait ligne par ligne, voir son commentaire).
    commune_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    first_name_offer = models.CharField(max_length=60)
    last_name_offer = models.CharField(max_length=80)
    email_offer = models.EmailField()
    # Nullable côté modèle (pas de backfill à imposer aux offres déjà existantes) mais requis
    # côté formulaire public pour toute nouvelle soumission, même pattern que User.phone_number.
    phone_offer = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    # Distinct de deletion_token (portées différentes : celui-ci ne permet ni suppression ni
    # accès à autre chose que le fil de messages/l'édition de cette offre) — voir OfferMessage
    # et OfferReponsePublicView. Généré à la création, même patron que deletion_token.
    reponse_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    actif = models.BooleanField(
        default=True,
        help_text="False = désactivée par son auteur ou un acteur institutionnel — reste "
                   "visible dans l'historique jusqu'à la clôture de la crise rattachée, "
                   "où elle est définitivement purgée. Ne masque jamais les offres actives.",
    )

    offer_type = models.ForeignKey(
        OfferType, on_delete=models.PROTECT, related_name="offers"
    )
    crisis = models.ForeignKey(
        "Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="offers"
    )

    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_offers",
    )

    # Dépôt groupé (entreprise/association déposant plusieurs personnes/véhicules en une seule
    # visite du formulaire public, voir propose-help-form) : organisation_nom identifie qui
    # dépose (distinct de first_name_offer/last_name_offer, la personne physique), groupe_id
    # est partagé par toutes les lignes d'une même soumission — simple étiquette de
    # regroupement pour le tableau de bord régulateur (ReportingComponent), pas une FK vers un
    # modèle de lot : un dépôt groupé n'a pas de cycle de vie propre au-delà de la sélection.
    organisation_nom = models.CharField(max_length=150, blank=True, null=True)
    groupe_id = models.UUIDField(null=True, blank=True)

    # Précisions spécifiques à certaines catégories (OfferType.type), une seule
    # s'applique en pratique selon le type choisi — voir propose-help-form. hebergement_duree
    # et les autres champs Hébergement viennent de HebergementDetailsMixin (base de la classe).
    numero_adeli_rpps = models.CharField(max_length=50, null=True, blank=True)
    transport_type = models.CharField(max_length=20, choices=TypeTransportOffre.choices, null=True, blank=True)
    materiel_type = models.CharField(max_length=20, choices=TypeMateriel.choices, null=True, blank=True)
    # Posé uniquement quand materiel_type == AUTRE : précise le matériel via le catalogue
    # partagé (recherche ou création façon hashtag, voir MaterielCatalogue/TagLikeViewSetMixin)
    # plutôt que de laisser "Autre" sans plus de détail — un matériel tapé une fois ("lits de
    # camp") devient proposable à tout le monde ensuite.
    materiel_catalogue = models.ForeignKey(
        "MaterielCatalogue", on_delete=models.SET_NULL, null=True, blank=True, related_name="offres"
    )
    # Posé uniquement quand materiel_type == CUVE : une cuve/citerne mobile d'eau ne se prête
    # ni ne se cherche comme une cuve à carburant, malgré le même type structurel.
    cuve_contenu = models.CharField(max_length=20, choices=CuveContenu.choices, null=True, blank=True)
    # Posé uniquement quand transport_type == ANIMAUX : le type d'animal (chiens, chevaux,
    # bétail...) change radicalement les moyens requis, pas de liste fermée pertinente ici.
    transport_animaux_precision = models.CharField(max_length=255, null=True, blank=True)
    quantite = models.PositiveIntegerField(null=True, blank=True)
    unite = models.CharField(max_length=20, null=True, blank=True)
    soutien_type = models.CharField(max_length=20, choices=TypeSoutien.choices, null=True, blank=True)

    # Déclaré une seule fois par l'offreur (case globale du formulaire public, voir
    # ProposeHelpFormComponent "Vos qualifications") et reporté sur chacune de ses offres où il
    # est physiquement présent — avant ce correctif, la case était répétée à l'identique sur
    # chaque ligne d'offre concernée (Hébergement/Transport/Autre), pouvant apparaître plusieurs
    # fois dans un même dépôt groupé sans que rien n'empêche des réponses contradictoires d'une
    # ligne à l'autre pour une seule et même personne.
    diplome_secourisme = models.BooleanField(default=False)

    # Même principe que diplome_secourisme ci-dessus : case globale côté formulaire, reportée
    # sur chaque offre où l'offreur est physiquement présent. Une expérience de sapeur-pompier
    # (même ancienne) est une information utile au régulateur, distincte d'un diplôme de
    # secourisme grand public (PSC1/SST).
    ancien_sapeur_pompier = models.BooleanField(default=False)

    # Uniquement pour une offre de type Matériel : le régulateur qui organise la collecte doit
    # savoir s'il faut envoyer quelqu'un chercher le matériel, ou si l'offreur peut lui-même le
    # déposer dans un centre de regroupement des moyens.
    materiel_livraison = models.CharField(max_length=20, choices=LivraisonMateriel.choices, null=True, blank=True)

    # Uniquement pour Transport/Matériel (voir propose-help-form) : rappel obligatoire (permis/
    # CACES, assurance, contrôle technique, sobriété, plaque d'immatriculation) coché
    # explicitement par l'offreur — l'engagement de conformité lui-même, pas une vérification
    # effective par la plateforme. Conservé pour trace/audit (ex: en cas de contrôle sur un
    # laissez-passer délivré sur la base de cette offre).
    confirmation_reglementaire = models.BooleanField(default=False)

    # Texte libre : une ou plusieurs plaques si l'offreur propose plusieurs véhicules sous la
    # même ligne d'offre. Vide pour un engin ne circulant jamais sur la voie publique.
    immatriculation = models.CharField(max_length=100, null=True, blank=True)

    # Pertinent quand transport_type == PERSONNES : combien de personnes le véhicule peut
    # transporter en plus du conducteur — même colonne "Nb de places" que le tableau "Véhicules
    # détenus par la commune" d'un PCS (voir aussi Request.nombre_places_assises et
    # MaterielPoint.nombre_places_assises pour les deux autres rubriques véhicules de l'app).
    nombre_places_assises = models.PositiveIntegerField(null=True, blank=True)

    # Posé quand l'offre est ajoutée comme "ressource" à une équipe (voir
    # TeamViewSet.assigner_ressource) : rattache l'offre à la mission active de cette équipe au
    # moment de l'affectation, miroir de Dossier.mission.
    mission = models.ForeignKey(
        "Mission",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="offres",
    )

    # Vrai si l'offreur peut être resollicité au-delà de cette crise (ex: un agriculteur
    # qui prête son matériel ponctuellement pour d'autres interventions futures).
    renouvelable = models.BooleanField(default=False)

    # L'offreur est-il physiquement présent avec ce qu'il propose ? Distinction demandée
    # explicitement (ex: un hébergement prêté n'implique jamais de présence, alors qu'un
    # camion proposé "avec chauffeur" implique de le nourrir/suivre sa disponibilité comme un
    # membre d'équipe) — voir TeamViewSet.assigner_ressource. Null pour les offres antérieures
    # à ce champ (inconnu, pas de fausse certitude rétroactive) ; toujours posé explicitement
    # par propose-help-form pour les nouvelles.
    presence_physique = models.BooleanField(null=True, blank=True)

    # Déclarées par le bénévole à la soumission de l'offre (propose-help-form) — permet de
    # filtrer les candidats lors du recrutement sur un point opérationnel (PointOperationnel.
    # competences_requises est le pendant côté besoin, celui-ci est côté offre).
    competences = models.ManyToManyField("Competence", blank=True, related_name="offres")

    def __str__(self) -> str:
        return self.title


class OfferMessage(EnvironmentScopedModel):
    """Fil de discussion entre une équipe (ex: équipe hébergement mettant en relation demandes
    et offres de logement) et le propriétaire d'une offre — ex: préciser les modalités d'un
    logement proposé. Le propriétaire n'a en général pas de compte : il répond et édite son
    offre via le lien reçu par email (voir Offer.reponse_token et OfferReponsePublicView),
    même esprit qu'EngagementRessourcePublicView pour les ressources affectées."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="messages")
    # Rempli quand le message vient d'un membre de l'équipe ; null quand il vient du
    # propriétaire de l'offre (jamais les deux à la fois).
    auteur_equipe = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_offres_envoyes",
    )
    contenu = models.TextField()
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_creation"]

    def __str__(self) -> str:
        expediteur = self.auteur_equipe.email if self.auteur_equipe_id else "propriétaire de l'offre"
        return f"Message sur « {self.offer.title} » de {expediteur}"


class OfferPhoto(EnvironmentScopedModel):
    """Photos additionnelles d'une offre d'aide, au-delà de la photo principale (`Offer.photo`,
    inchangée) — même patron que RequestPhoto (voir son docstring)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="photos")

    image = models.ImageField(upload_to="photos/offres/galerie/", validators=[validate_image_file])

    ordre = models.PositiveIntegerField(default=0)

    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "date_ajout"]

    def __str__(self) -> str:
        return f"Photo galerie — {self.offer.title}"


class Creneau(models.TextChoices):
    MATIN = "MATIN", "Matin"
    MIDI = "MIDI", "Midi"
    SOIR = "SOIR", "Soir"
    NUIT = "NUIT", "Nuit"


class DisponibiliteOffre(EnvironmentScopedModel):
    """Créneau de disponibilité (jour + matin/midi/soir/nuit) déclaré par un bénévole pour une
    offre d'aide. Une ligne = un créneau où la personne est disponible ; l'absence de ligne pour
    un (date, créneau) donné vaut indisponible."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offer = models.ForeignKey(
        Offer,
        on_delete=models.CASCADE,
        related_name="disponibilites",
    )

    date = models.DateField()

    creneau = models.CharField(max_length=10, choices=Creneau.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["offer", "date", "creneau"],
                name="uq_dispo_offre_date_creneau",
            )
        ]
        ordering = ["date", "creneau"]

    def __str__(self) -> str:
        return f"{self.offer.title} - {self.date} ({self.creneau})"


class Competence(models.Model):
    """Compétences mobilisables lors d'une crise"""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    nom = models.CharField(
        max_length=100,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    active = models.BooleanField(
        default=True
    )

    # Optionnel : regroupe des compétences plus fines sous un thème générique (ex: "Secourisme"
    # -> "PSC1", "PSE1") pour l'affichage en menu déroulant côté équipe (voir TeamsComponent) —
    # jamais plus d'un niveau (une sous-compétence ne peut pas elle-même avoir des enfants,
    # non contraint en base pour rester simple, à respecter côté formulaire).
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sous_competences",
    )

    def __str__(self):
        return self.nom

class Besoin(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    nom = models.CharField(
        max_length=150,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    actif = models.BooleanField(
        default=True
    )

    def __str__(self):
        return self.nom

class BesoinCompetence(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    besoin = models.ForeignKey(
        "Besoin",
        on_delete=models.CASCADE,
        related_name="competences"
    )


    competence = models.ForeignKey(
        "Competence",
        on_delete=models.PROTECT,
        related_name="besoins",
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.besoin.nom} -> {self.competence.nom}"

class InstitutionType(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    code = models.CharField(
        max_length=50,
        unique=True
    )

    libelle = models.CharField(
        max_length=255
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    actif = models.BooleanField(
        default=True
    )

    def __str__(self):
        return self.libelle


class Institution(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    nom = models.CharField(
        max_length=255,
        unique=True
    )

    type = models.ForeignKey(
        InstitutionType,
        on_delete=models.PROTECT,
        related_name="institutions"
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    telephone = models.CharField(
        max_length=30,
        blank=True,
        null=True
    )

    email = models.EmailField(
        blank=True,
        null=True
    )

    adresse = models.TextField(
        blank=True,
        null=True
    )

    # Renseignée à l'attachement d'un utilisateur AUT_LOCALE (voir institution_attachment.py) à
    # partir des informations d'inscription/annuaire — permet la "vue mairie" scopée par
    # commune (contrairement à User.pending_commune_*, qui n'est que transitoire).
    commune_code = models.CharField(
        max_length=10,
        blank=True,
        null=True
    )

    commune_nom = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    # Contrairement à commune_code/commune_nom (déjà renseignés à l'attachement d'un compte
    # AUT_LOCALE), pas dénormalisé automatiquement — saisi manuellement quand une commune est
    # choisie dans le formulaire d'édition de l'institution (voir InstitutionsComponent),
    # jamais recalculé depuis le référentiel Commune interne (qui n'a pas ce champ).
    commune_code_postal = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Code postal de la commune de l'institution — utile pour distinguer des "
                   "communes homonymes, jamais recalculé automatiquement.",
    )

    # Dénormalisés depuis commune_code (voir Institution.save()) : le secteur réel d'une
    # institution EPCI/département/région ne doit jamais être recalculé en base Commune à
    # chaque appel de vue_secteur — juste lu ici. Résolus une seule fois, à chaque changement
    # de commune_code.
    epci_code = models.CharField(max_length=10, null=True, blank=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True)
    region_code = models.CharField(max_length=3, null=True, blank=True)

    class SecteurNiveau(models.TextChoices):
        COMMUNE = "commune", "Communal"
        EPCI = "epci", "Intercommunal (EPCI)"
        DEPARTEMENT = "departement", "Départemental"
        REGION = "region", "Régional"
        NATIONAL = "national", "National"

    # Force le niveau de secteur de vue_secteur pour CETTE institution, indépendamment de son
    # type — pensé pour un compte de test (simuler un secteur national/régional pour une
    # mairie, par exemple), jamais posé automatiquement. Null = comportement normal (niveau
    # déduit du type d'institution, voir SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION).
    secteur_override = models.CharField(
        max_length=20, choices=SecteurNiveau.choices, null=True, blank=True,
        help_text="Force le niveau de secteur (vue_secteur) pour cette institution, quel que "
                   "soit son type — usage test uniquement, laisser vide sinon.",
    )

    # Dénormalisés en même temps que epci_code/departement_code/region_code ci-dessus : le
    # niveau EFFECTIF (secteur_override s'il est posé, sinon déduit du type) et son nom lisible
    # ("Nouvelle-Aquitaine", "Grenoble"...) — affichés tels quels par "Ma zone est :" (voir
    # UserSerializer.get_ma_zone), jamais recalculés à la lecture.
    secteur_niveau_effectif = models.CharField(max_length=20, null=True, blank=True)
    secteur_nom = models.CharField(max_length=255, null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.commune_code:
            from .geo_lookup import commune_from_code, commune_secteur_codes, epci_nom_from_code
            from .geo_reference import DEPARTEMENTS, REGIONS, SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION

            secteur = commune_secteur_codes(self.commune_code)
            self.epci_code = secteur.get("epci_code")
            self.departement_code = secteur.get("departement_code")
            self.region_code = secteur.get("region_code")

            type_code = (self.type.code or "").upper() if self.type_id else ""
            niveau = self.secteur_override or SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION.get(type_code, "commune")
            self.secteur_niveau_effectif = niveau
            if niveau == "commune":
                self.secteur_nom = self.commune_nom or commune_from_code(self.commune_code)
            elif niveau == "epci":
                self.secteur_nom = epci_nom_from_code(self.epci_code)
            elif niveau == "departement":
                self.secteur_nom = DEPARTEMENTS.get(self.departement_code)
            elif niveau == "region":
                self.secteur_nom = REGIONS.get(self.region_code)
            elif niveau == "national":
                self.secteur_nom = "France entière"
        super().save(*args, **kwargs)

    actif = models.BooleanField(
        default=True
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.nom


class JournalCollectivite(EnvironmentScopedModel):
    """Une entrée du "journal de bord" de la Vue Ma Collectivité — texte libre saisi par un
    membre de l'institution (typiquement le secrétaire de mairie), immuable une fois créée
    (aucune route update/delete n'existe côté ViewSet — voir JournalCollectiviteViewSet) et
    systématiquement journalisée dans AuditLog (voir perform_create), pour former une vraie
    main courante horodatée."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="journal_entries")
    # Une institution peut être impliquée sur plusieurs crises actives simultanément (voir
    # ImplicationInstitution) : le journal de bord doit être rattaché à UNE crise précise, pas
    # juste à l'institution — sinon des entrées de crises différentes se mélangent dans le même
    # flux. Passé nullable transitoirement le temps de la migration de backfill (voir
    # 0119_journalcollectivite_crise.py / 0120_backfill_journal_collectivite_crise.py).
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="journal_entries")
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="journal_entries")
    contenu = models.TextField()
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.institution.nom} — {self.date_creation:%d/%m/%Y %H:%M}"


class RoleOperationnel(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    code = models.CharField(
        max_length=50,
        unique=True
    )

    libelle = models.CharField(
        max_length=255
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    actif = models.BooleanField(
        default=True
    )

    def __str__(self):
        return self.libelle


class InstitutionCompetence(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="competences"
    )

    competence = models.ForeignKey(
        Competence,
        on_delete=models.CASCADE,
        related_name="institutions"
    )

    active = models.BooleanField(
        default=True
    )

    date_debut = models.DateTimeField(
        auto_now_add=True
    )

    date_fin = models.DateTimeField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    class Meta:

        constraints = [

            models.UniqueConstraint(
                fields=[
                    "institution",
                    "competence"
                ],
                name=
                "uq_institution_competence"
            )

        ]

    def __str__(self):

        return (
            f"{self.institution.nom}"
            f" - "
            f"{self.competence.nom}"
        )




class RequestTypeBesoin(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    request_type = models.ForeignKey(
        RequestType,
        on_delete=models.CASCADE,
        related_name="besoins"
    )

    besoin = models.ForeignKey(
        Besoin,
        on_delete=models.CASCADE,
        related_name="request_types"
    )

    def __str__(self):
        return f"{self.request_type} -> {self.besoin}"

class AffectationCompetence(EnvironmentScopedModel):
    """
    Affecte une compétence à une équipe
    pour une crise donnée.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    crise = models.ForeignKey(
        "Crisis",
        on_delete=models.CASCADE,
        related_name="affectations_competences"
    )

    competence = models.ForeignKey(
        "Competence",
        on_delete=models.CASCADE,
        related_name="affectations"
    )

    equipe = models.ForeignKey(
        "Team",
        on_delete=models.CASCADE,
        related_name="affectations"
    )

    active = models.BooleanField(
        default=True
    )

    date_debut = models.DateTimeField(
        auto_now_add=True
    )

    date_fin = models.DateTimeField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    def __str__(self):
        return (
            f"{self.crise.name} - "
            f"{self.competence.nom} - "
            f"{self.equipe.name}"
        )

class Dossier(EnvironmentScopedModel):

    class Priorite(models.TextChoices):
        URGENTE = "URGENTE", "Urgente"
        NORMALE = "NORMALE", "Normale"
        BASSE = "BASSE", "Basse"

    class Statut(models.TextChoices):

        EN_ATTENTE_DISTRIBUTION = (
            "EN_ATTENTE_DISTRIBUTION",
             "En attente de distribution"
        )
        NOUVEAU = "NOUVEAU", "Nouveau"
        EN_ATTENTE_AFFECTATION = (
            "EN_ATTENTE_AFFECTATION",
            "En attente d'affectation"
        )
        AFFECTE = "AFFECTE", "Affecté"
        EN_COURS = "EN_COURS", "En cours"
        RESOLU = "RESOLU", "Résolu"
        CLOTURE = "CLOTURE", "Clôturé"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    numero = models.CharField(
        max_length=50,
        unique=True
    )

    crise = models.ForeignKey(
        "Crisis",
        on_delete=models.CASCADE,
        related_name="dossiers"
    )

    competence = models.ForeignKey(
        "Competence",
        on_delete=models.PROTECT,
        related_name="dossiers",
        null=True,
        blank=True
    )

    equipe = models.ForeignKey(
        "Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dossiers"
    )

    mission = models.ForeignKey(
        "Mission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dossiers",
        help_text="Mission à laquelle ce dossier est rattaché, si affecté en tant que tel "
                   "(affectation groupée de demandes). Une mission peut regrouper plusieurs "
                   "équipes ; l'équipe précise pour CE dossier reste `equipe` ci-dessus.",
    )

    demande = models.ForeignKey(
        "Request",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dossiers",
        help_text="Demande d'aide à l'origine de ce dossier, si affecté depuis une demande.",
    )

    information = models.ForeignKey(
        "Information",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dossiers",
        help_text="Signalement divers à l'origine de ce dossier, si affecté depuis un signalement.",
    )

    titre = models.CharField(
        max_length=255
    )

    description = models.TextField()

    statut = models.CharField(
        max_length=50,
        choices=Statut.choices,
        default=Statut.NOUVEAU
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    date_affectation = models.DateTimeField(
        null=True,
        blank=True
    )

    date_resolution = models.DateTimeField(
        null=True,
        blank=True
    )

    date_cloture = models.DateTimeField(
        null=True,
        blank=True
    )

    priorite = models.CharField(
        max_length=10,
        choices=Priorite.choices,
        default=Priorite.NORMALE,
        help_text="Priorité de traitement, réglable par le chef d'équipe pour trier ses dossiers.",
    )

    ordre = models.PositiveIntegerField(
        default=0,
        help_text="Ordre d'intervention manuel au sein de son équipe (le plus petit en premier) "
                   "— permet à un chef d'équipe de terrain d'organiser sa tournée.",
    )

    # Posé par un participant du dossier (souvent un bénévole terrain) pour signaler une
    # urgence au régulateur sans attendre le prochain point — voir TeamViewSet ou
    # DossierViewSet.marquer_important, qui notifie les régulateurs concernés (même recherche
    # que populate_dossier_participants_and_notify, via _regulateurs_pour_dossier).
    important = models.BooleanField(default=False)
    date_signalement_important = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.numero} - {self.titre}"


class Mission(EnvironmentScopedModel):
    """Objectif opérationnel (ex: "dégager les routes secteur nord") auquel une ou plusieurs
    équipes sont affectées et sous lequel des dossiers peuvent être regroupés. Champs
    volontairement minimaux : la vue dédiée (quelles équipes, où, font quoi) et d'éventuels
    champs supplémentaires (secteur géographique...) viennent dans un second temps, en ajouts
    nullables, sans casser cette forme initiale."""

    class Statut(models.TextChoices):
        EN_PREPARATION = "EN_PREPARATION", "En préparation"
        EN_COURS = "EN_COURS", "En cours"
        TERMINEE = "TERMINEE", "Terminée"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    titre = models.CharField(
        max_length=255
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    # Nullable : une mission "courante" d'équipe (voir Team.mission_active) se crée souvent en
    # texte libre, sans crise précise identifiée dès le départ. SET_NULL plutôt que CASCADE
    # devenu incohérent avec le caractère optionnel : la suppression d'une crise ne doit plus
    # emporter les missions qui n'en dépendent pas forcément.
    crise = models.ForeignKey(
        "Crisis",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="missions"
    )

    equipes = models.ManyToManyField(
        "Team",
        blank=True,
        related_name="missions"
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.EN_PREPARATION
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    date_cloture = models.DateTimeField(
        null=True,
        blank=True
    )

    # Modèle de plan à l'origine de cette mission, si instanciée automatiquement à l'activation
    # d'un plan (voir PlanViewSet.activer/PlanMissionModele) — sert à ne pas la recréer si le
    # plan est réactivé sur la même crise (même équipe ré-ajoutée après coup, par exemple).
    modele_origine = models.ForeignKey(
        "PlanMissionModele",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="missions_instanciees",
    )

    def __str__(self):
        return self.titre


class DossierCommentaire(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        related_name="commentaires"
    )

    auteur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    commentaire = models.TextField()

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.dossier.numero}"

class DossierHistorique(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        related_name="historique"
    )

    auteur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    evenement = models.CharField(
        max_length=255
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.evenement

def secure_document_path(instance, filename):

    extension = os.path.splitext(
        filename
    )[1].lower()

    return (
        f"documents/"
        f"{uuid.uuid4()}"
        f"{extension}"
    )

class Document(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    fichier = models.FileField(
        upload_to=secure_document_path,
        validators=[validate_image_file]
    )

    auteur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    date_upload = models.DateTimeField(
        auto_now_add=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    sha256 = models.CharField(
        max_length=64,
        blank=True,
        null=True
    )

    metadata_publiques = models.JSONField(
        default=dict,
        blank=True
    )

    metadata_privees = models.JSONField(
        default=dict,
        blank=True
    )

    demande = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents"
    )

    offre = models.ForeignKey(
        Offer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents"
    )

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents"
    )

    def __str__(self):
        return str(self.id)


class Zone(EnvironmentScopedModel):
    """Zone nommée propre à une institution (ex: "Quartier Nord", "Centre-ville") — permet de
    référencer une même zone depuis plusieurs équipes/points plutôt que de redessiner sa
    géométrie à chaque fois. Distincte de la géométrie brute déjà portée individuellement par
    `Team.zone_precise`/`Crisis.zone` : sert de catalogue partagé pour un Plan (voir plus bas)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution",
        on_delete=models.PROTECT,
        related_name="zones",
    )

    nom = models.CharField(max_length=255)

    description = models.TextField(blank=True, null=True)

    communes = models.JSONField(
        default=list, blank=True,
        help_text="Liste de codes commune INSEE (ex: ['38185']).",
    )

    zone_precise = gis_models.PolygonField(
        srid=4326, null=True, blank=True,
        help_text="Zone dessinée à la main, plus précise que la liste de communes.",
    )

    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self) -> str:
        return self.nom


class Team(EnvironmentScopedModel):
    """Équipes de gestion de crise"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=7, default='#3b82f6')  # hex color
    created_at = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(
        default=True,
        help_text="False = désactivée par un acteur institutionnel — reste dans l'historique "
                   "indéfiniment (une équipe peut couvrir plusieurs crises), pas de purge "
                   "automatique à la clôture d'une crise contrairement à Offer/Request/"
                   "Information.",
    )

    # Institution de rattachement : une équipe ne doit jamais rester livrée à elle-même — voir
    # `_notify_institution_referent_of_team` (views.py) qui prévient le·s référent·s
    # (ContactInstitution) de l'institution à la création. Nullable pour ne pas bloquer la
    # création d'équipe pour un compte sans institution renseignée (auto-complété depuis
    # `request.user.institution` sinon).
    institution = models.ForeignKey(
        "Institution",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="teams",
    )
    # Institution délégataire courante (état courant, pointeur — l'historique complet des
    # délégations vit dans TeamDelegation) : une association peut opérer l'équipe au quotidien
    # pour le compte de l'institution responsable, qui garde seule la main sur ce rattachement
    # (voir TeamViewSet.definir_delegation/retirer_delegation). SET_NULL et non PROTECT : la
    # suppression d'une institution délégataire ne doit pas bloquer, contrairement à
    # `institution` (le responsable) qui reste structurant.
    institution_delegataire = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="teams_deleguees",
    )

    # Équipe "de tête" à laquelle celle-ci est rattachée comme une ressource (ex: l'équipe
    # d'une entreprise avec ses camions, rattachée à l'équipe de secteur qui la coordonne) —
    # voir TeamViewSet.rattacher_equipe/detacher_equipe. Arbre à profondeur illimitée, un seul
    # champ auto-référentiel suffit (`sous_equipes` donne les enfants directs). Rester
    # rattachée n'affecte jamais l'autonomie opérationnelle de l'équipe (institution, mission,
    # points, dossiers restent les siens propres) — c'est un lien organisationnel, pas une
    # fusion, exactement comme une offre assignée en ressource ne devient pas l'équipe.
    equipe_parente = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sous_equipes",
    )

    leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="led_teams"
    )
    # Distinct du leader (chef d'équipe terrain) : le régulateur pilote l'équipe depuis le
    # centre de crise. Alimenté depuis les utilisateurs ayant le rôle REGULATEUR via
    # AffectationRoleOperationnel, pas une simple promotion du leader.
    regulateur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="teams_regulees"
    )
    # Mission "courante" de l'équipe (singulière) : distincte du M2M Mission.equipes (utilisé
    # par la page Missions, où une mission peut réunir plusieurs équipes). Redéfinir cette
    # mission remplace la précédente — une équipe n'a qu'une mission active à la fois, son
    # historique reste dans AuditLog plutôt que dans plusieurs missions actives simultanées.
    mission_active = models.ForeignKey(
        "Mission",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="equipes_actives"
    )
    members = models.ManyToManyField(
        User,
        blank=True,
        related_name="teams"
    )
    assigned_crises = models.ManyToManyField(
        "Crisis",
        blank=True,
        related_name="assigned_teams"
    )
    assigned_offers = models.ManyToManyField(
        "Offer",
        blank=True,
        related_name="assigned_teams"
    )
    assigned_requests = models.ManyToManyField(
        "Request",
        blank=True,
        related_name="assigned_teams"
    )
    assigned_informations = models.ManyToManyField(
        "Information",
        blank=True,
        related_name="assigned_teams"
    )
    
    competences = models.ManyToManyField(
        Competence,
        blank=True,
        related_name="equipes"
    )

    # Thèmes déclarés pour cette équipe (ex: "Hébergement") — même vocabulaire que les
    # "Thèmes à l'écoute" d'une institution actrice (ImplicationInstitution.themes), pensé pour
    # être réutilisable par d'autres vues dédiées futures (équipe soins, équipe transport...),
    # pas seulement la vue de correspondance hébergement/relogement qui l'utilise en premier.
    themes = models.ManyToManyField(
        "Besoin",
        blank=True,
        related_name="equipes"
    )

    # Zone d'intervention, du plus large au plus précis : une équipe déclare des
    # départements (niveau de base), peut affiner avec des communes, peut affiner encore
    # avec un polygone dessiné à la main. Le matching d'une demande utilise le niveau le
    # plus précis renseigné (voir la logique d'auto-affectation dans RequestViewSet).
    departements = models.JSONField(
        default=list, blank=True,
        help_text="Liste de codes département (ex: ['38', '73']).",
    )
    communes = models.JSONField(
        default=list, blank=True,
        help_text="Liste de codes commune INSEE (ex: ['38185']), plus précis que le département.",
    )
    zone_precise = gis_models.PolygonField(
        srid=4326, null=True, blank=True,
        help_text="Zone dessinée à la main, la plus précise des trois niveaux.",
    )

    # Référence vers le catalogue de zones nommées de l'institution (voir Zone) — purement
    # additif, n'interfère pas avec departements/communes/zone_precise ci-dessus qui restent la
    # source de vérité pour le matching géographique existant.
    zone_principale = models.ForeignKey(
        "Zone",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="equipes",
    )

    def __str__(self) -> str:
        return self.name


class TeamDelegation(EnvironmentScopedModel):
    """Historique des délégations d'une équipe à une institution/association opérant pour le
    compte de l'institution responsable — voir Team.institution_delegataire (pointeur "état
    courant" mis à jour en même temps qu'une ligne est créée/close ici)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="delegations")
    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="delegations_equipes_recues",
    )
    active = models.BooleanField(default=True)
    date_debut = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    commentaire = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date_debut"]

    def __str__(self) -> str:
        return f"{self.team.name} → {self.institution.nom}"


class StatutEngagementRessource(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation"
    CONFIRME = "CONFIRME", "Confirmé"
    DECLINE = "DECLINE", "Décliné"
    EN_TRANSIT = "EN_TRANSIT", "En transit"
    ARRIVE = "ARRIVE", "Arrivé / à disposition"


class EngagementRessource(EnvironmentScopedModel):
    """Suivi de la progression réelle d'une ressource (Offer) affectée à une équipe (voir
    TeamViewSet.assigner_ressource) : a-t-elle confirmé sa venue, est-elle en route, est-elle
    arrivée ? Créé/renouvelé à chaque affectation, jamais partagé entre deux affectations
    successives — une réaffectation repart d'un engagement neuf, comme Offer.mission. Deux
    canaux de mise à jour volontairement distincts : TeamViewSet.definir_statut_ressource
    (équipe/régulateur, sans contrainte de séquence) et EngagementRessourcePublicView (la
    personne/l'entreprise elle-même via le lien reçu par email, séquence stricte)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.OneToOneField(Offer, on_delete=models.CASCADE, related_name="engagement")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="engagements_ressources")
    statut = models.CharField(
        max_length=20, choices=StatutEngagementRessource.choices, default=StatutEngagementRessource.EN_ATTENTE,
    )
    token_confirmation = models.CharField(max_length=64, unique=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    date_transit = models.DateTimeField(null=True, blank=True)
    date_arrivee = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.offer.title} → {self.team.name} ({self.get_statut_display()})"


class DernierePositionUtilisateur(EnvironmentScopedModel):
    """Dernière position connue d'un utilisateur, capturée de façon opportuniste — quand le
    navigateur a déjà obtenu sa géolocalisation pour une autre raison (consultation de la
    carte, saisie d'une adresse...), jamais par un traçage continu en tâche de fond. Sert
    uniquement à visualiser approximativement où se trouvent les équipes sur le terrain, sans
    prétention de précision à la minute près : un seul enregistrement par utilisateur et par
    environnement (PROD/DEMO), écrasé à chaque nouvelle capture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="positions")
    location = gis_models.PointField(srid=4326)
    horodatage = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("utilisateur", "environment")

    def __str__(self) -> str:
        return f"Position de {self.utilisateur} ({self.horodatage})"


class DossierParticipant(EnvironmentScopedModel):

    class Role(models.TextChoices):
        DEMANDEUR = "DEMANDEUR", "Demandeur"
        OFFRANT = "OFFRANT", "Offrant"
        REGULATION = "REGULATION", "Régulation"
        EQUIPE = "EQUIPE", "Équipe"
        OBSERVATEUR = "OBSERVATEUR", "Observateur"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        related_name="participants"
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="dossiers_participes"
    )

    role = models.CharField(
        max_length=30,
        choices=Role.choices
    )

    date_ajout = models.DateTimeField(
        auto_now_add=True
    )

    date_derniere_vue = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        unique_together = (
            "dossier",
            "utilisateur",
            "role"
        )

class Notification(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications"
    )

    dossier = models.ForeignKey(
        Dossier,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True
    )

    # Lien facultatif vers une crise, pour les notifications hors-contexte dossier qui mènent
    # à une action sur une crise précise (ex: déclaration ACTEUR en attente de validation, voir
    # ImplicationInstitutionViewSet.perform_create) — permet au frontend de naviguer directement
    # vers cette crise au clic (admin-layout.component), plutôt que de se contenter d'informer.
    crise = models.ForeignKey(
        Crisis,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True
    )

    titre = models.CharField(
        max_length=255
    )

    message = models.TextField()

    lu = models.BooleanField(
        default=False
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

def secure_recherche_photo_path(
    instance,
    filename
):

    extension = os.path.splitext(
        filename
    )[1].lower()

    return (
        f"recherches/"
        f"{uuid.uuid4()}"
        f"{extension}"
    )

class RecherchePersonne(EnvironmentScopedModel):

    class Source(models.TextChoices):
        DOMICILE = "DOMICILE", "Domicile"
        EHPAD = "EHPAD", "EHPAD"

    class Statut(models.TextChoices):
        RECHERCHE = "RECHERCHE", "Recherche"
        RETROUVEE = "RETROUVEE", "Retrouvée"
        ARCHIVEE = "ARCHIVEE", "Archivée"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    nom = models.CharField(max_length=255)

    prenom = models.CharField(max_length=255)

    age = models.IntegerField()

    photo = models.ImageField(
        upload_to="recherches/",
        blank=True,
        null=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    source = models.CharField(
        max_length=20,
        choices=Source.choices
    )

    ville = models.CharField(
        max_length=255
    )

    adresse = models.TextField(
        blank=True,
        null=True
    )

    ehpad_nom = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    ehpad_adresse = models.TextField(
        blank=True,
        null=True
    )

    contact_nom = models.CharField(
        max_length=255
    )

    createur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="recherches_personnes"
    )

    contact_email = models.EmailField()

    contact_telephone = models.CharField(
        max_length=50
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.RECHERCHE
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    date_retrouvee = models.DateTimeField(
        null=True,
        blank=True
    )

    retrouve_par = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="personnes_retrouvees"
    )

    commentaire_retrouvee = models.TextField(
        blank=True,
        null=True
    )

    vue_publique = models.BooleanField(
        default=True
    )

    crise = models.ForeignKey(
        Crisis,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recherches_personnes"
    )


class RecherchePersonneCommentaire(
    EnvironmentScopedModel
):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    recherche = models.ForeignKey(
        RecherchePersonne,
        on_delete=models.CASCADE,
        related_name="commentaires"
    )

    auteur = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    commentaire = models.TextField()

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

class RecherchePersonneHistorique(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    recherche = models.ForeignKey(
        RecherchePersonne,
        on_delete=models.CASCADE,
        related_name="historique"
    )

    auteur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    evenement = models.CharField(
        max_length=255
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.evenement

class RecherchePersonnePhoto(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    recherche = models.ForeignKey(
        RecherchePersonne,
        on_delete=models.CASCADE,
        related_name="photos"
    )

    fichier = models.ImageField(
        upload_to=secure_recherche_photo_path,
        validators=[validate_image_file]
    )

    auteur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    commentaire = models.CharField(
        max_length=255,
        blank=True
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):

        return (
            f"{self.recherche.nom} "
            f"{self.recherche.prenom}"
        )


class RecherchePersonneCommentairePhoto(
    EnvironmentScopedModel
):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    commentaire = models.ForeignKey(
        RecherchePersonneCommentaire,
        on_delete=models.CASCADE,
        related_name="photos"
    )

    fichier = models.ImageField(
        upload_to=secure_recherche_photo_path,
        validators=[validate_image_file]
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

class RecherchePersonneLecture(
    EnvironmentScopedModel
):

    recherche = models.ForeignKey(
        RecherchePersonne,
        on_delete=models.CASCADE,
        related_name="lectures"
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="lectures_recherches"
    )

    date_derniere_lecture = models.DateTimeField(
        null=True,
        blank=True
    )

    date_dernier_acquittement = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        unique_together = (
            "recherche",
            "utilisateur"
        )

class RecherchePersonneLectureHistorique(
    EnvironmentScopedModel
):

    recherche = models.ForeignKey(
        RecherchePersonne,
        on_delete=models.CASCADE,
        related_name="historique_lectures"
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="historique_lectures_recherches"
    )

    class ActionLecture(
        models.TextChoices
    ):
        LECTURE = "LECTURE", "Lecture"
        ACQUITTEMENT = "ACQUITTEMENT", "Acquittement"

    action = models.CharField(
        max_length=20,
        choices=ActionLecture.choices
    )

    date_action = models.DateTimeField(
        auto_now_add=True
    )

class AffectationRoleOperationnel(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="affectations_roles"
    )

    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="affectations_roles"
    )

    competence = models.ForeignKey(
        Competence,
        on_delete=models.CASCADE,
        related_name="affectations_roles",
        null=True,
        blank=True,
        help_text="Thème sur lequel cette personne opère. Peut rester vide juste après "
                   "l'activation du compte, avant que les thèmes ne soient précisés.",
    )

    role = models.ForeignKey(
        RoleOperationnel,
        on_delete=models.PROTECT,
        related_name="affectations"
    )

    actif = models.BooleanField(
        default=True
    )

    date_debut = models.DateTimeField(
        auto_now_add=True
    )

    date_fin = models.DateTimeField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    # Optionnels : zone d'intervention et responsabilité de la personne pour ce rôle, saisis
    # dans l'onglet "Régulateurs / thèmes" des Institutions — réutilisent Zone (catalogue
    # partagé de l'institution, voir Zone.__doc__) plutôt qu'un système de zone ad-hoc dupliqué
    # ici, cohérent avec la zone d'intervention d'une équipe (Team.zone_precise en plus, pas
    # dupliqué non plus : le dessin libre reste propre à chaque affectation via zone_precise
    # ci-dessous).
    zone = models.ForeignKey(
        "Zone", on_delete=models.SET_NULL, null=True, blank=True, related_name="affectations_roles",
    )
    zone_precise = gis_models.PolygonField(
        srid=4326, null=True, blank=True,
        help_text="Dessin optionnel, propre à cette affectation — indépendant de Zone.zone_precise "
                   "si `zone` est aussi renseignée (ex: un périmètre plus fin que la zone cataloguée).",
    )
    responsabilite = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Intitulé libre du périmètre de responsabilité (ex: \"Coordination hébergement "
                   "secteur nord\") — distinct du rôle (fonction) et du thème (compétence).",
    )

    class Meta:

        constraints = [

            models.UniqueConstraint(
                fields=[
                    "utilisateur",
                    "institution",
                    "competence",
                    "role"
                ],
                name=(
                    "uq_affectation_role"
                )
            )

        ]

    def __str__(self):

        return (
            f"{self.utilisateur} - "
            f"{self.role.libelle}"
        )

class DisponibiliteOperationnelle(
    EnvironmentScopedModel
):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    affectation = models.ForeignKey(
        AffectationRoleOperationnel,
        on_delete=models.CASCADE,
        related_name="disponibilites"
    )

    disponible = models.BooleanField(
        default=True
    )

    date_debut = models.DateTimeField(
        auto_now_add=True
    )

    date_fin = models.DateTimeField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    class Meta:

        ordering = [
            "-date_debut"
        ]

        constraints = [

            models.UniqueConstraint(
                fields=[
                    "affectation"
                ],
                condition=models.Q(
                    date_fin__isnull=True
                ),
                name="uq_disponibilite_active"
            )

        ]

    def __str__(self):

        return (
            f"{self.affectation} - "
            f"{'DISPONIBLE' if self.disponible else 'NON_DISPONIBLE'}"
        )


class DelegationCompetence(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    institution_source = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="delegations_emises"
    )

    institution_cible = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="delegations_recues"
    )

    competence = models.ForeignKey(
        Competence,
        on_delete=models.CASCADE,
        related_name="delegations"
    )

    crise = models.ForeignKey(
        Crisis,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="delegations_competences"
    )

    active = models.BooleanField(
        default=True
    )

    date_debut = models.DateTimeField(
        auto_now_add=True
    )

    date_fin = models.DateTimeField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    # Secteur de la délégation, du plus large au plus précis — même triptyque que Team
    # (voir plus haut) : la mairie peut déléguer une compétence sur toute la crise (les 3
    # champs restent vides), ou la restreindre à des départements, des communes, ou un
    # polygone dessiné à la main.
    departements = models.JSONField(
        default=list, blank=True,
        help_text="Liste de codes département (ex: ['38', '73']).",
    )
    communes = models.JSONField(
        default=list, blank=True,
        help_text="Liste de codes commune INSEE (ex: ['38185']), plus précis que le département.",
    )
    zone_precise = gis_models.PolygonField(
        srid=4326, null=True, blank=True,
        help_text="Zone dessinée à la main, la plus précise des trois niveaux.",
    )

    class Meta:

        constraints = [

            models.UniqueConstraint(
                fields=[
                    "institution_source",
                    "institution_cible",
                    "competence",
                    "crise"
                ],
                name=(
                    "uq_delegation_competence"
                )
            )

        ]

    def __str__(self):

        if self.crise:

            return (
                f"{self.institution_source.nom}"
                f" -> "
                f"{self.institution_cible.nom}"
                f" ({self.competence.nom})"
                f" [{self.crise.name}]"
            )

        return (
            f"{self.institution_source.nom}"
            f" -> "
            f"{self.institution_cible.nom}"
            f" ({self.competence.nom})"
        )

class PointType(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    code = models.CharField(
        max_length=50,
        unique=True
    )

    libelle = models.CharField(
        max_length=255
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    actif = models.BooleanField(
        default=True
    )

    def __str__(self):
        return self.libelle

class PointOperationnel(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    nom = models.CharField(
        max_length=255
    )

    type = models.ForeignKey(
        PointType,
        on_delete=models.PROTECT,
        related_name="points"
    )

    crise = models.ForeignKey(
        Crisis,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="points_operationnels"
    )

    responsable = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="points_geres"
    )

    adresse = models.TextField(
        blank=True,
        null=True
    )

    location = gis_models.PointField(
        srid=4326,
        null=True,
        blank=True
    )

    obligatoire = models.BooleanField(
        default=False
    )

    # Nullable = capacité non renseignée (pas "zéro place") — utilisé pour calculer la
    # saturation dans le popup public "trouver un centre d'accueil" (personnes_presentes vs
    # capacite_accueil), voir PointOperationnelViewSet.centres_accueil.
    capacite_accueil = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    actif = models.BooleanField(
        default=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    description = models.TextField(
        blank=True,
        null=True,
        help_text="Description du point (distincte de `commentaire`, qui reste des notes de suivi)."
    )

    date_ouverture = models.DateTimeField(
        null=True,
        blank=True
    )

    date_fermeture = models.DateTimeField(
        null=True,
        blank=True
    )

    competences_requises = models.ManyToManyField(
        "Competence",
        blank=True,
        related_name="points_operationnels",
        help_text="Compétences/thèmes nécessaires pour tenir ce point.",
    )

    equipe = models.ForeignKey(
        "Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="points_operationnels",
        help_text="Équipe responsable de la tenue de ce point.",
    )

    # Un point peut être tenu par plusieurs équipes selon la spécialité (roulement jour/nuit,
    # secours/logistique...), en plus (ou à la place, pour un point neuf) de `equipe` ci-dessus
    # — conservé tel quel pour ne rien casser des usages existants (minimap, actions equipe...).
    # La "vue opérationnelle" additionne les deux, dédoublonnées.
    equipes_gestion = models.ManyToManyField(
        "Team",
        blank=True,
        related_name="points_geres_specialite",
        help_text="Équipes supplémentaires tenant ce point (par spécialité), en plus de `equipe`.",
    )

    # Relation intrinsèquement plusieurs-à-plusieurs : une équipe de terrain peut se ravitailler
    # (repas, repos, carburant...) sur plusieurs points, et un point peut ravitailler plusieurs
    # équipes — voir PointOperationnelViewSet.vue_operationnelle.
    equipes_ravitaillement = models.ManyToManyField(
        "Team",
        blank=True,
        related_name="points_ravitaillement",
        help_text="Équipes de terrain ravitaillées par ce point (repas, repos, carburant...).",
    )

    # Plusieurs responsables possibles (roulement jour/nuit, spécialités), en plus de
    # `responsable` ci-dessus — conservé tel quel pour les mêmes raisons que `equipe`. Le
    # contact affiché/notifié (comparaison de stocks, demande de transfert) est l'union des
    # deux, dédoublonnée.
    responsables = models.ManyToManyField(
        User,
        blank=True,
        related_name="points_responsable_secondaire",
        help_text="Responsables supplémentaires de ce point, en plus de `responsable`.",
    )

    # Référence vers le catalogue de zones nommées de l'institution (voir Zone) — purement
    # additif, sans lien avec `location` (position précise du point lui-même).
    zone = models.ForeignKey(
        "Zone",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="points_operationnels",
    )

    def __str__(self):
        return self.nom

    def responsables_effectifs(self) -> list:
        """Union dédoublonnée de tous les responsables de ce point : `responsable` (champ
        historique) + `responsables` (M2M) + chefs des équipes de gestion (`equipe` +
        `equipes_gestion`) — utilisée pour l'affichage contact (comparaison de stocks) et le
        ciblage des notifications (demande de transfert)."""
        vus = {}
        if self.responsable_id:
            vus[self.responsable_id] = self.responsable
        for u in self.responsables.all():
            vus[u.id] = u
        equipes = list(self.equipes_gestion.all())
        if self.equipe_id:
            equipes.append(self.equipe)
        for equipe in equipes:
            if equipe.leader_id and equipe.leader_id not in vus:
                vus[equipe.leader_id] = equipe.leader
        return list(vus.values())


class DisponibilitePointEquipe(EnvironmentScopedModel):
    """Créneau de disponibilité (jour + matin/midi/soir/nuit) d'un membre de l'équipe
    responsable d'un point opérationnel — même principe que DisponibiliteOffre (jour+créneau),
    mais scopé Point×membre plutôt que Offer : DisponibiliteOperationnelle (simple toggle
    scopé Institution+Competence) et DisponibiliteOffre (couplée à une Offer individuelle) ont
    une sémantique différente et ne sont pas transposables sans les dénaturer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    point = models.ForeignKey(
        PointOperationnel,
        on_delete=models.CASCADE,
        related_name="disponibilites_equipe",
    )

    membre = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="disponibilites_points",
    )

    date = models.DateField()

    creneau = models.CharField(max_length=10, choices=Creneau.choices)

    affectation = models.ForeignKey(
        "AffectationPointBenevole",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="creneaux",
        help_text=(
            "Renseigné uniquement pour un créneau créé via le recrutement individuel depuis "
            "une offre d'aide — permet d'afficher son statut de confirmation. Nul pour un "
            "créneau auto-déclaré par un membre d'équipe (considéré confirmé d'office)."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["point", "membre", "date", "creneau"],
                name="uq_dispo_point_equipe",
            )
        ]
        ordering = ["date", "creneau"]

    def __str__(self) -> str:
        return f"{self.point.nom} - {self.membre.email} - {self.date} ({self.creneau})"


class Plan(EnvironmentScopedModel):
    """Dispositif pré-enregistré d'une institution (ex: "Plan canicule", "PCS général") :
    regroupe un sous-ensemble de ses équipes/points/zones déjà existants, préparé à l'avance et
    activable sur une crise réelle le jour J (voir PlanViewSet.activer). Ne duplique jamais les
    équipes/points/stocks eux-mêmes — ce sont les mêmes objets, déjà utilisables indépendamment
    de toute crise (Team.institution, PointOperationnel.crise nullable, MaterielPoint sans FK
    crise), simplement regroupés ici sous un nom pour être activés ensemble en un geste."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution",
        on_delete=models.PROTECT,
        related_name="plans",
    )

    nom = models.CharField(max_length=255)

    description = models.TextField(blank=True, null=True)

    zones = models.ManyToManyField(Zone, blank=True, related_name="plans")

    equipes = models.ManyToManyField("Team", blank=True, related_name="plans")

    points = models.ManyToManyField(
        "PointOperationnel", blank=True, related_name="plans",
    )

    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self) -> str:
        return self.nom


class PlanMissionModele(EnvironmentScopedModel):
    """Modèle de mission pré-enregistré dans un Plan, propre à l'une de ses équipes (ex: pour
    l'équipe "Surveillance du niveau de la crue", la mission "Patrouille le long des berges") —
    à l'activation de cette équipe sur une crise réelle (PlanViewSet.activer), instancie une
    vraie Mission + un Dossier sans demande/signalement d'origine, même principe que
    TeamViewSet.creer_dossier (mission proactive, pas déclenchée par une demande de citoyen).

    Le stock (MaterielPoint), lui, n'a jamais besoin d'être "modélisé" séparément : il n'est
    jamais lié à une crise (voir MaterielPoint/Plan ci-dessus), donc du stock entré à l'avance
    sur un point encore "prévu" (crise vide) reste sur ce même point une fois celui-ci activé —
    aucune réplication à faire, contrairement à une mission qui n'existe pas encore avant
    l'activation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="missions_modeles")

    equipe = models.ForeignKey(
        "Team", on_delete=models.CASCADE, related_name="missions_modeles_plan",
        help_text="Doit être l'une des équipes du plan — vérifié à la création (voir "
                   "PlanMissionModeleViewSet.perform_create), pas de contrainte DB (l'équipe "
                   "peut être ajoutée au plan après coup).",
    )

    titre = models.CharField(max_length=255)

    description = models.TextField(blank=True, null=True)

    # Pas forcément un membre de l'équipe (ex: un élu référent) — la mission instanciée ne
    # rattache QUE ce référent comme participant équipe du dossier, jamais tous les membres de
    # l'équipe automatiquement (contrairement à TeamViewSet.creer_dossier).
    referent = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="missions_modeles_referent",
        help_text="Personne désignée pour cette mission à l'activation (pas forcément un "
                   "membre de l'équipe) — optionnel.",
    )

    priorite = models.CharField(max_length=10, choices=Dossier.Priorite.choices, default=Dossier.Priorite.NORMALE)

    class Meta:
        ordering = ["titre"]

    def __str__(self) -> str:
        return f"{self.titre} ({self.equipe.name})"


class StatutMateriel(models.TextChoices):
    EN_TRANSIT = "EN_TRANSIT", "En transit"
    SUR_PLACE = "SUR_PLACE", "Sur place"
    RETIRE = "RETIRE", "Retiré"


class MaterielCatalogueCategorie(models.TextChoices):
    """Regroupement optionnel d'entrées du catalogue pour des listes à cocher dédiées (voir
    propose-help-form, rubrique "Engins agricoles / chantiers / spéciaux") — un item sans
    catégorie (None) reste un matériel "Autre" générique, cherché/ajouté normalement."""
    ENGIN = "ENGIN", "Engin agricole / chantier / spécial"


class MaterielCatalogue(models.Model):
    """Vocabulaire partagé et extensible des besoins matériel/logistique (lit, nourriture,
    eau...) — même esprit que Competence/InformationType (voir TagLikeViewSetMixin) : n'importe
    quel centre peut ajouter une entrée, immédiatement réutilisable par tous les autres.
    Remplace l'ancien TypeMateriel (TextChoices figé), trop rigide pour ce besoin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=100, unique=True)

    # Voir MaterielCatalogueCategorie — permet de proposer certaines entrées dans une liste à
    # cocher dédiée plutôt que dans la recherche générique "Autre matériel".
    categorie = models.CharField(max_length=20, choices=MaterielCatalogueCategorie.choices, null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.nom


class NiveauStock(models.TextChoices):
    NUL = "NUL", "Nul"
    FAIBLE = "FAIBLE", "Faible"
    OK = "OK", "OK"
    EN_TROP = "EN_TROP", "En trop"


class MaterielPoint(EnvironmentScopedModel):
    """État du stock d'un item du catalogue sur un point opérationnel — à la fois une jauge
    qualitative (`niveau_stock`, comparable directement entre centres pour organiser une
    navette) et, si besoin, un suivi quantitatif précis d'un objet en transit (`quantite`/
    `unite`/`statut`, hérité du modèle initial). Une seule ligne par (point, item) : on met à
    jour le niveau plutôt que d'empiler des doublons."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    point = models.ForeignKey(
        PointOperationnel,
        on_delete=models.CASCADE,
        related_name="materiels",
    )

    item = models.ForeignKey(
        MaterielCatalogue,
        on_delete=models.PROTECT,
        related_name="stocks",
    )

    niveau_stock = models.CharField(max_length=10, choices=NiveauStock.choices, default=NiveauStock.NUL)

    nom = models.CharField(
        max_length=255, blank=True,
        help_text="Précision libre optionnelle (ex: « 5kVA » pour un groupe électrogène).",
    )

    quantite = models.PositiveIntegerField(default=1)

    unite = models.CharField(max_length=20, default="unité")

    statut = models.CharField(max_length=20, choices=StatutMateriel.choices, default=StatutMateriel.SUR_PLACE)

    responsable = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="materiels_geres",
    )

    # Pertinent quand item est un véhicule (stock détenu par la municipalité) : même colonne
    # "Nb de places" que le tableau "Véhicules détenus par la commune" d'un PCS, sans conditionner
    # à une catégorie de catalogue dédiée — voir Offer.nombre_places_assises pour le même champ
    # côté offres, et Request.nombre_places_assises côté demandes.
    nombre_places_assises = models.PositiveIntegerField(null=True, blank=True)

    commentaire = models.TextField(blank=True, null=True)

    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_maj"]
        constraints = [
            models.UniqueConstraint(fields=["point", "item"], name="uq_materielpoint_point_item"),
        ]

    def __str__(self) -> str:
        return f"{self.item.nom} ({self.point.nom})"


class ContributionMateriel(EnvironmentScopedModel):
    """Un apport individuel de matériel à une ligne de stock (MaterielPoint) — qui a fourni
    quoi, quand, combien. Contrairement à MaterielPoint (une seule ligne par (point, item),
    état courant), plusieurs contributions peuvent s'accumuler sur la même ligne : la quantité
    totale affichée (voir MaterielPointSerializer.quantite_totale) est la somme des
    contributions dont le statut n'est pas RETIRE."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    materiel_point = models.ForeignKey(
        MaterielPoint,
        on_delete=models.CASCADE,
        related_name="contributions",
    )

    # Nullable : un apport manuel (stock déjà présent, non issu d'une offre publique) n'a pas
    # d'offre à référencer.
    offre = models.ForeignKey(
        "Offer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contributions_materiel",
    )

    # Dénormalisé : reste lisible même sans offre liée, ou si l'offre est supprimée par la
    # suite — l'attribution "à qui appartient ce matériel" ne doit jamais disparaître avec elle.
    fournisseur_nom = models.CharField(max_length=140, blank=True)

    quantite = models.PositiveIntegerField(default=1)

    unite = models.CharField(max_length=20, default="unité")

    statut = models.CharField(max_length=20, choices=StatutMateriel.choices, default=StatutMateriel.SUR_PLACE)

    # Qui a enregistré l'apport côté centre (pas forcément la même personne que le fournisseur).
    responsable = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contributions_enregistrees",
    )

    commentaire = models.TextField(blank=True, null=True)

    date_reception = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_reception"]

    def __str__(self) -> str:
        return f"{self.fournisseur_nom or 'Anonyme'} → {self.materiel_point}"


class TypePersonneAccueillie(models.TextChoices):
    EVACUE = "EVACUE", "Personne évacuée"
    POMPIER = "POMPIER", "Pompier"
    BENEVOLE_AUTRE_EQUIPE = "BENEVOLE_AUTRE_EQUIPE", "Bénévole d'une autre équipe"
    AUTRE = "AUTRE", "Autre"


class RegistrePresence(EnvironmentScopedModel):
    """Registre de présence ("secrétariat") d'un point opérationnel : qui est actuellement
    accueilli (personne évacuée, pompier, bénévole d'une autre équipe...) et depuis quand.
    `nombre` permet d'enregistrer un lot en une ligne (ex: une famille de 4) sans multiplier
    les entrées. `personnes_presentes` (voir PointOperationnelSerializer) = somme de `nombre`
    des lignes sans `date_depart`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    point = models.ForeignKey(
        PointOperationnel,
        on_delete=models.CASCADE,
        related_name="registre_presences",
    )

    type_personne = models.CharField(max_length=30, choices=TypePersonneAccueillie.choices)

    nom = models.CharField(max_length=255, blank=True)

    nombre = models.PositiveIntegerField(default=1)

    date_arrivee = models.DateTimeField(auto_now_add=True)

    date_depart = models.DateTimeField(null=True, blank=True)

    commentaire = models.TextField(blank=True, null=True)

    enregistre_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registres_presences_enregistres",
    )

    class Meta:
        ordering = ["-date_arrivee"]

    def __str__(self) -> str:
        return f"{self.get_type_personne_display()} ({self.point.nom})"


class TypeDeclarant(models.TextChoices):
    PERSONNE_SEULE = "PERSONNE_SEULE", "Personne seule"
    FAMILLE = "FAMILLE", "Famille"
    GROUPE = "GROUPE", "Groupe"


class SituationDeclarant(models.TextChoices):
    RELOGE = "RELOGE", "En sécurité / relogé"
    EN_CENTRE = "EN_CENTRE", "En centre d'accueil"
    BESOIN_CENTRE = "BESOIN_CENTRE", "En sécurité, cherche un centre d'accueil"
    HORS_ZONE = "HORS_ZONE", "En sécurité, hors zone"


class DeclarationSecurite(EnvironmentScopedModel):
    """"Je suis en sécurité" : une personne (ou un référent pour une famille/un groupe) se
    déclare en sécurité — soit elle-même (formulaire public, ex: en vacances loin du site,
    "ne me cherchez pas pour l'évacuation"), soit enregistrée par un opérateur (secrétariat
    d'un centre d'accueil faisant le recensement à l'entrée). Standalone : ne référence pas
    obligatoirement un avis de recherche (RecherchePersonne) existant, une auto-déclaration
    n'a le plus souvent aucun avis de recherche associé.

    Aucune donnée de santé : `regime_alimentaire_specifique` est un simple indicateur binaire
    (peut couvrir un motif médical comme un diabète, ou un choix personnel comme le
    végétarisme) — jamais un champ décrivant une pathologie ou une allergie. Ne pas ajouter de
    champ santé/médical ici sans revalider explicitement avec le porteur du produit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE,
        related_name="declarations_securite",
    )

    type_declarant = models.CharField(
        max_length=20, choices=TypeDeclarant.choices, default=TypeDeclarant.PERSONNE_SEULE,
    )

    # Distincte de type_declarant (qui décrit QUI est concerné — personne seule/famille/
    # groupe) : situation décrit OÙ/COMMENT la personne se déclare en sécurité. BESOIN_CENTRE
    # ne pose pas centre_accueil à la création (la personne n'en a pas encore choisi un — le
    # formulaire public lui propose ensuite une liste de suggestions, purement indicative,
    # sans créer de second enregistrement).
    situation = models.CharField(
        max_length=20, choices=SituationDeclarant.choices, default=SituationDeclarant.RELOGE,
    )

    nom_referent = models.CharField(max_length=80)
    prenom_referent = models.CharField(max_length=60)
    contact_referent = models.CharField(
        max_length=255,
        help_text="Email ou téléphone de la personne qui se présente/déclare — elle-même pour "
                   "une personne seule, le référent désigné pour une famille ou un groupe.",
    )

    nombre_adultes = models.PositiveIntegerField(default=1)
    nombre_enfants = models.PositiveIntegerField(default=0)

    # Liste simple d'âges (ex: [12, 7, 3]), PAS de nom ni d'autre identifiant — même principe
    # que regime_alimentaire_specifique (indicateur utile, jamais de PII enfant lourde). Ne
    # contraint pas la longueur à nombre_enfants côté modèle (saisie plus tard, correction
    # possible) — le formulaire (secrétariat) affiche autant de lignes d'âge que
    # nombre_enfants.
    ages_enfants = models.JSONField(default=list, blank=True)

    # Optionnelle : utile pour situer une auto-déclaration (ex: RELOGE ailleurs), mais pas
    # pertinente pour EN_CENTRE (le centre choisi fait déjà foi) ni exigible dans tous les cas
    # (BESOIN_CENTRE, saisie opérateur rapide au secrétariat...). Même patron qu'Information.
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    commune_code = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Code commune INSEE résolu à la saisie de l'adresse (autocomplete), même "
                   "usage qu'Information.commune_code.",
    )
    # Dénormalisés depuis commune_code (voir DeclarationSecuriteViewSet.perform_create), même
    # principe que Request.epci_code/departement_code/region_code — nécessaires pour exclure
    # une déclaration hors zone de compétence (zone_scoping.object_in_viewer_zone) au-delà du
    # seul niveau commune.
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)

    # Rempli seulement si c'est une entrée en centre d'accueil (pas une simple auto-déclaration
    # "je ne suis pas sur place") — déclenche la création d'une ligne RegistrePresence associée.
    centre_accueil = models.ForeignKey(
        "PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="declarations_securite",
    )

    regime_alimentaire_specifique = models.BooleanField(
        default=False,
        help_text="Au moins une personne du groupe a un régime alimentaire spécifique "
                   "(diabétique, végétarien...) — jamais une donnée de santé en soi. Se "
                   "rapprocher des équipes sur place pour le préciser.",
    )

    commentaire = models.TextField(blank=True, null=True)

    declare_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="declarations_securite_enregistrees",
        help_text="Opérateur ayant enregistré la déclaration (secrétariat du centre) — vide "
                   "si auto-déclaration publique par la personne elle-même.",
    )

    registre_presence = models.OneToOneField(
        RegistrePresence, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="declaration_securite",
    )

    date_declaration = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_declaration"]

    def __str__(self) -> str:
        return f"{self.prenom_referent} {self.nom_referent} ({self.get_type_declarant_display()})"


class StatutAffectation(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation"
    EN_VALIDATION = "EN_VALIDATION", "En attente de validation par le régulateur"
    CONFIRME = "CONFIRME", "Confirmé"
    DECLINE = "DECLINE", "Décliné"


class AffectationPointBenevole(EnvironmentScopedModel):
    """Recrutement d'un bénévole individuel (pas forcément membre de l'équipe du point) sur un
    point opérationnel, depuis une offre d'aide déposée sur la plateforme — avec confirmation
    par email (lien oui/non, jeton opaque comme Offer.deletion_token, pas de compte requis)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    point = models.ForeignKey(
        PointOperationnel,
        on_delete=models.CASCADE,
        related_name="affectations_benevoles",
    )

    benevole = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="affectations_points",
    )

    offer = models.ForeignKey(
        "Offer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="affectations_points",
    )

    statut = models.CharField(max_length=15, choices=StatutAffectation.choices, default=StatutAffectation.EN_ATTENTE)

    date_attendue = models.DateTimeField(help_text="Horaire auquel le bénévole est attendu sur le point.")

    point_transit = models.ForeignKey(
        PointOperationnel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Point de transit obligatoire à indiquer au bénévole (route fermée, contrôle d'accès...).",
    )

    token_confirmation = models.CharField(max_length=64, unique=True)

    date_reponse = models.DateTimeField(null=True, blank=True)

    affecte_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="affectations_creees",
    )

    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"{self.benevole.email} -> {self.point.nom} ({self.get_statut_display()})"


class AuditAction(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    code = models.CharField(
        max_length=100,
        unique=True
    )

    libelle = models.CharField(
        max_length=255
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    actif = models.BooleanField(
        default=True
    )

    def __str__(self):
        return self.libelle

class AuditLog(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    date_action = models.DateTimeField(
        auto_now_add=True
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )

    institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )

    adresse_ip = models.GenericIPAddressField(
        null=True,
        blank=True
    )

    user_agent = models.TextField(
        blank=True,
        null=True
    )

    action = models.ForeignKey(
        AuditAction,
        on_delete=models.PROTECT,
        related_name="logs"
    )


    objet_type = models.CharField(
        max_length=100
    )

    objet_id = models.UUIDField(
        null=True,
        blank=True
    )

    crise = models.ForeignKey(
        Crisis,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )

    ancien_etat = models.JSONField(
        null=True,
        blank=True
    )

    nouvel_etat = models.JSONField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    succes = models.BooleanField(
        default=True
    )

    couleur = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    icone = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    class Meta:

        ordering = [
            "-date_action"
        ]

    def __str__(self):

        return (
            f"{self.date_action} - "
            f"{self.action}"
        )


class ContactInstitution(EnvironmentScopedModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="contacts"
    )

    utilisateur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="institutions"
    )

    fonction = models.CharField(
        max_length=255,
        blank=True
    )

    contact_principal = models.BooleanField(
        default=False
    )

    actif = models.BooleanField(
        default=True
    )

    # Zone de l'institution (catalogue Zone, voir plus haut) que ce contact couvre/représente —
    # ex: préparation PCS/PICS, un référent différent par quartier. Optionnel : la plupart des
    # contacts restent rattachés à l'institution entière, sans zone précise.
    zone = models.ForeignKey(
        Zone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        constraints = [

            models.UniqueConstraint(
                fields=["institution"],
                condition=models.Q(
                    contact_principal=True
                ),
                name="uq_contact_principal_institution"
            )

        ]

class InstitutionDomaine(EnvironmentScopedModel):

    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE
    )

    domaine = models.CharField(
        max_length=255,
        unique=True
    )

    valide = models.BooleanField(
        default=True
    )

