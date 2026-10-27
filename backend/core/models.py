import hashlib
import uuid
import os
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.gis.db import models as gis_models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from core.validators import validate_image_file
from .validators import validate_image_file, validate_identity_document_file
from .crypto_fields import EncryptedTextField, EncryptedEmailField, EncryptedJSONField, blind_index
from .file_crypto import get_encrypted_file_storage

# Nom de fichier stocké = UUID : pas de collision, pas de fuite via le nom d'origine, pas de
# dépassement de max_length (100). Une fonction par champ : upload_to doit être une fonction nommée
# pour les migrations.
def secure_user_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/{uuid.uuid4()}{extension}"


# Logo public (en-tête du site) : préfixe non bloqué par proxy/nginx.conf. Ne jamais y ranger un
# fichier sensible.
def institution_branding_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"branding/{uuid.uuid4()}{extension}"


def secure_crisis_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/crises/{uuid.uuid4()}{extension}"


def secure_demande_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/demandes/{uuid.uuid4()}{extension}"


def secure_demande_galerie_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/demandes/galerie/{uuid.uuid4()}{extension}"


def secure_information_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/informations/{uuid.uuid4()}{extension}"


def secure_offre_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/offres/{uuid.uuid4()}{extension}"


def secure_offre_galerie_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/offres/galerie/{uuid.uuid4()}{extension}"


def secure_recherche_personne_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"recherches/{uuid.uuid4()}{extension}"


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
    """PROD et DEMO partagent le backend mais jamais les données de contenu ; le vocabulaire
    partagé (types, compétences, catalogue) n'a pas ce champ."""
    PROD = "PROD", "Production"
    DEMO = "DEMO", "Démonstration"


class EnvironmentScopedModel(models.Model):
    """Base commune à toutes les données "de contenu" isolées entre PROD et DEMO — voir
    Environment. `EnvironmentScopedViewSetMixin` (views.py) filtre automatiquement dessus."""
    environment = models.CharField(max_length=4, choices=Environment.choices, default=Environment.PROD)

    class Meta:
        abstract = True


class Commune(models.Model):
    """Référentiel des communes (code INSEE) : nom, centroïde, codes administratifs, risques.
    Partagé PROD/DEMO."""

    code = models.CharField(max_length=10, primary_key=True)
    nom = models.CharField(max_length=255, null=True, blank=True)
    centre_latitude = models.FloatField(null=True, blank=True)
    centre_longitude = models.FloatField(null=True, blank=True)
    # Chargés en masse par import_communes : scoping par secteur sans jointure géographique.
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    population = models.PositiveIntegerField(null=True, blank=True)
    # Risques Géorisques de la commune, alimentés par geo_lookup.commune_risques (diagnostic
    # PCS/DICRIM).
    risques_territoire = models.JSONField(default=list, blank=True)
    date_maj = models.DateTimeField(auto_now=True)
    # Posé à chaque tentative de résolution, réussie ou non (geo_lookup.RETRY_COOLDOWN) : évite de
    # rappeler l'API externe à chaque lecture pour un code introuvable.
    derniere_tentative = models.DateTimeField(null=True, blank=True)
    # Cooldown distinct : Géorisques est un service séparé de geo.api.gouv.fr.
    derniere_tentative_risques = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.nom or self.code


class PointCommune(models.Model):
    """Cache du reverse-géocodage point GPS -> commune, arrondi à 4 décimales (~11 m)."""

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


class UserManager(DjangoUserManager):
    """email est chiffré : la connexion résout l'utilisateur par email_bidx."""

    def get_by_natural_key(self, username):
        return self.get(email_bidx=blind_index(username))


class User(AbstractUser):
    """Modèle utilisateur personnalisé"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = EncryptedTextField(null=True, blank=True)
    photo = models.ImageField(upload_to=secure_user_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
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
    postal_code = EncryptedTextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)

    # Renseignements institutionnels de l'inscription, appliqués seulement après confirmation de
    # l'email.
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

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    # Chiffré ; l'unicité porte sur email_bidx.
    email = EncryptedEmailField()
    # Index aveugle de email (unique), rempli par save(). Migrations 0182 (remplissage) et 0183
    # (contrainte).
    email_bidx = models.CharField(max_length=64, unique=True, editable=False, db_index=True)

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

    # Candidature à la réserve d'une institution en marque blanche (résolue depuis le Host,
    # core/branding.py), vérifiée par son responsable (UserViewSet.verifier_reserve).
    souhaite_rejoindre_reserve = models.BooleanField(default=False)
    reserve_verifiee = models.BooleanField(default=False)
    reserve_institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="candidats_reserve",
    )

    def save(self, *args, **kwargs):
        self.email_bidx = blind_index(self.email)
        super().save(*args, **kwargs)

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
    photo = models.ImageField(upload_to=secure_crisis_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326)
    radius = models.IntegerField(default=10)
    zone = gis_models.PolygonField(srid=4326, null=True, blank=True)

    # Zone composée de communes/départements (contours geo.api.gouv.fr bufferisés de radius km,
    # puis unis côté frontend). zone_departements/zone_communes mémorisent la composition ; la
    # géométrie effective est zone_secteurs. Indépendant de zone (polygone dessiné).
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
    # Crise créée pour des essais (demande utilisateur du 20/10) : reste ouverte et pleinement
    # utilisable, mais ignorée par le monitoring -- sinon "crise active sans demande d'aide"
    # alerte en permanence sur des crises de test que personne ne veut clôturer (la clôture
    # déclenche la purge RGPD à 30 jours, voir cleanup_crises).
    essai = models.BooleanField(default=False)

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
        indexes = [
            models.Index(fields=["-start_date"]),
            # GIN pour les recherches zone_communes__contains / zone_departements__contains
            # (_crisis_zone_resolver).
            GinIndex(fields=["zone_communes"]),
            GinIndex(fields=["zone_departements"]),
        ]

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
    """Rattachement d'une institution à une crise : impliquée (sa commune est touchée) et/ou
    acteur opérationnel. Les deux peuvent coexister."""

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

    # EN_ATTENTE seulement pour une déclaration ACTEUR d'une institution non AUT_LOCALE (voir
    # ImplicationInstitutionViewSet.valider/refuser).
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


class ContributionZoneCommune(EnvironmentScopedModel):
    """Provenance d'une commune de Crisis.zone_communes. institution vide : retirable par
    quiconque édite la crise ; renseignée : seule cette institution (ou un administrateur) peut
    la retirer. Un seul propriétaire par commune et par crise : le premier contributeur fait
    foi."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(Crisis, on_delete=models.CASCADE, related_name="contributions_zone_communes")
    commune_code = models.CharField(max_length=10)
    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="contributions_zone_crises",
    )
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["crise", "commune_code"], name="uq_contribution_zone_crise_commune"),
        ]

    def __str__(self):
        return f"{self.commune_code} sur {self.crise} ({self.institution or 'sans propriétaire'})"


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
    """Champs communs aux offres et demandes d'hébergement ; l'adresse du logement utilise
    location/commune_code."""

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
    # Jamais supprimé (FK PROTECT) : actif=False masque le type du formulaire public.
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
    description = EncryptedTextField(null=True, blank=True)
    photo = models.ImageField(upload_to=secure_demande_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
    # Nullable : une demande d'hébergement n'a qu'une zone de recherche.
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    commune_code = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Code commune INSEE résolu à la saisie de l'adresse (autocomplete), "
                   "utilisé pour le matching géographique avec les zones d'intervention des équipes. "
                   "Pour une demande d'hébergement : première commune de zone_recherche_communes.",
    )
    # Dénormalisés depuis commune_code à la création : vue par secteur sans jointure géographique.
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    # Zone de recherche d'un logement : codes INSEE et rayon optionnel.
    zone_recherche_communes = models.JSONField(default=list, blank=True)
    zone_recherche_rayon_km = models.PositiveIntegerField(null=True, blank=True)
    # Places en plus du conducteur (même notion sur Offer et MaterielPoint).
    nombre_places_assises = models.PositiveIntegerField(null=True, blank=True)
    first_name_request = EncryptedTextField()
    last_name_request = EncryptedTextField()
    email_request = EncryptedEmailField()
    # Index aveugle : rapprochement exact avec un compte existant (resolve_or_invite_demandeur).
    email_request_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    phone_request = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    # Lien de modification seule (deletion_token permet de désactiver).
    edition_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
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

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            # Index du niveau de zone le plus courant (une mairie filtre sur sa commune).
            models.Index(fields=["commune_code"]),
        ]

    def save(self, *args, **kwargs):
        self.email_request_bidx = blind_index(self.email_request) if self.email_request else None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class RequestPhoto(EnvironmentScopedModel):
    """Photos supplémentaires d'une demande (jusqu'à 9, 10 avec Request.photo), mêmes droits que
    la photo principale, servies par une action preview."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="photos")

    image = models.ImageField(upload_to=secure_demande_galerie_photo_path, max_length=255, validators=[validate_image_file])

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
    photo = models.ImageField(upload_to=secure_information_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
    first_name_information = EncryptedTextField()
    last_name_information = EncryptedTextField()
    email_information = EncryptedEmailField()
    # Voir User.email_bidx pour le raisonnement -- recherche EXACTE le cas échéant.
    email_information_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    phone_information = EncryptedTextField()
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
    # Lien de modification seule (deletion_token permet de désactiver).
    edition_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
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

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            # Voir le commentaire équivalent sur Request.Meta.indexes -- même lacune, même
            # correctif.
            models.Index(fields=["commune_code"]),
        ]

    def save(self, *args, **kwargs):
        self.email_information_bidx = blind_index(self.email_information) if self.email_information else None
        super().save(*args, **kwargs)

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
    # Les engins sont des entrées du catalogue partagé (MaterielCatalogue, catégorie ENGIN), pas
    # des choix figés.
    AUTRE = "AUTRE", "Autre"


class CuveContenu(models.TextChoices):
    """Précision quand TypeMateriel.CUVE est choisi. Libellé « Cuve » inchangé : affecter_stock
    résout le catalogue par ce libellé."""
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
    description = EncryptedTextField(null=True, blank=True)
    photo = models.ImageField(upload_to=secure_offre_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    # Résolus à la création depuis location : vue par secteur sans reverse-géocodage en lecture.
    commune_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    epci_code = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    region_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    first_name_offer = EncryptedTextField()
    last_name_offer = EncryptedTextField()
    email_offer = EncryptedEmailField()
    # Voir User.email_bidx pour le raisonnement -- utilisé par resolve_or_invite_benevole pour
    # rapprocher cette offre d'un compte User existant (recherche EXACTE).
    email_offer_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    # Nullable côté modèle (pas de backfill à imposer aux offres déjà existantes) mais requis
    # côté formulaire public pour toute nouvelle soumission, même pattern que User.phone_number.
    phone_offer = EncryptedTextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    # Lien limité au fil de messages et à l'édition de l'offre (OfferReponsePublicView).
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

    # Offre d'hébergement : accueil de sinistrés et/ou d'intervenants (cases indépendantes).
    # L'accueil d'intervenants est opt-in et doit être validé par un régulateur
    # (accueil_intervenants_valide_par, null = en attente).
    accueil_sinistres = models.BooleanField(default=True)
    accueil_intervenants = models.BooleanField(default=False)
    accueil_intervenants_valide_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Régulateur ayant validé cette offre pour l'accueil d'intervenants -- "
                   "null tant que la validation n'a pas eu lieu, même si accueil_intervenants "
                   "est coché (le régulateur doit confirmer avant que l'offre soit exploitable).",
    )
    accueil_intervenants_valide_le = models.DateTimeField(null=True, blank=True)

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

    # Dépôt groupé (entreprise, association) : organisation_nom identifie le déposant, groupe_id
    # étiquette les lignes d'une même soumission (pas de modèle de lot).
    organisation_nom = EncryptedTextField(blank=True, null=True)
    groupe_id = models.UUIDField(null=True, blank=True)

    # Précisions par catégorie d'offre (OfferType.type) ; les champs d'hébergement viennent de
    # HebergementDetailsMixin.
    numero_adeli_rpps = EncryptedTextField(null=True, blank=True)
    transport_type = models.CharField(max_length=20, choices=TypeTransportOffre.choices, null=True, blank=True)
    materiel_type = models.CharField(max_length=20, choices=TypeMateriel.choices, null=True, blank=True)
    # Si materiel_type == AUTRE : entrée du catalogue partagé, réutilisable ensuite par tous.
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

    # Déclaré une fois par l'offreur et reporté sur chacune de ses offres avec présence physique.
    diplome_secourisme = models.BooleanField(default=False)

    # Même principe que diplome_secourisme.
    ancien_sapeur_pompier = models.BooleanField(default=False)

    # Offre de matériel : à aller chercher ou déposé par l'offreur.
    materiel_livraison = models.CharField(max_length=20, choices=LivraisonMateriel.choices, null=True, blank=True)

    # Engagement de conformité coché par l'offreur (permis, assurance, contrôle technique…),
    # conservé pour trace ; la plateforme ne vérifie rien.
    confirmation_reglementaire = models.BooleanField(default=False)

    # Texte libre : une ou plusieurs plaques si l'offreur propose plusieurs véhicules sous la
    # même ligne d'offre. Vide pour un engin ne circulant jamais sur la voie publique.
    immatriculation = EncryptedTextField(null=True, blank=True)

    # Si transport_type == PERSONNES : places en plus du conducteur.
    nombre_places_assises = models.PositiveIntegerField(null=True, blank=True)

    # Mission active de l'équipe au moment de l'affectation en ressource
    # (TeamViewSet.assigner_ressource).
    mission = models.ForeignKey(
        "Mission",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="offres",
    )

    # Vrai si l'offreur peut être resollicité au-delà de cette crise (ex: un agriculteur
    # qui prête son matériel ponctuellement pour d'autres interventions futures).
    renouvelable = models.BooleanField(default=False)

    # L'offreur accompagne-t-il ce qu'il propose (à nourrir, à suivre) ? Null pour les offres
    # antérieures au champ.
    presence_physique = models.BooleanField(null=True, blank=True)

    # Matériel exploité par l'offreur : nombre d'accompagnants (dimensionner l'accueil). None si la
    # question n'a pas été posée.
    accompagne = models.BooleanField(null=True, blank=True)
    nombre_accompagnants = models.PositiveIntegerField(null=True, blank=True)

    # Compétences déclarées par le bénévole, rapprochées de PointOperationnel.competences_requises.
    competences = models.ManyToManyField("Competence", blank=True, related_name="offres")

    class Meta:
        indexes = [
            # Tri par défaut et pagination de la table la plus volumineuse (cible 300 à 400 k
            # lignes).
            models.Index(fields=["-created_at"]),
        ]

    def save(self, *args, **kwargs):
        self.email_offer_bidx = blind_index(self.email_offer) if self.email_offer else None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class OfferMessage(EnvironmentScopedModel):
    """Fil de discussion entre une équipe et le propriétaire d'une offre, qui répond sans compte
    via le lien reçu par email (Offer.reponse_token)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="messages")
    # Rempli quand le message vient d'un membre de l'équipe ; null quand il vient du
    # propriétaire de l'offre (jamais les deux à la fois).
    auteur_equipe = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_offres_envoyes",
    )
    contenu = models.TextField()
    date_creation = models.DateTimeField(auto_now_add=True)

    # False pour un message du propriétaire : alimente les « Retours externes » de la cellule de
    # crise.
    lu_par_institution = models.BooleanField(default=False)

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

    image = models.ImageField(upload_to=secure_offre_galerie_photo_path, max_length=255, validators=[validate_image_file])

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
    """Créneau de disponibilité (jour, moment) d'un bénévole pour une offre ; pas de ligne =
    indisponible."""

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

    # Regroupement sur un seul niveau (non contraint en base, respecté par le formulaire).
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sous_competences",
    )

    def __str__(self):
        return self.nom

class BesoinNature(models.TextChoices):
    """Ce qu'un besoin mobilise pour être satisfait — sert à savoir quelle(s)
    correspondance(s) proposer (BesoinCompetence et/ou BesoinMateriel)."""
    COMPETENCE = "COMPETENCE", "Compétence (savoir-faire humain)"
    MATERIEL = "MATERIEL", "Matériel"
    MIXTE = "MIXTE", "Compétence et matériel"


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

    # Regroupement sur un seul niveau, comme Competence.parent.
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sous_besoins",
    )

    # Compétence humaine, matériel ou les deux : détermine les correspondances proposées
    # (BesoinCompetence, BesoinMateriel).
    nature = models.CharField(
        max_length=20, choices=BesoinNature.choices, null=True, blank=True,
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

class BesoinMateriel(models.Model):
    """Correspondance besoin -> matériel de catalogue — équivalent de BesoinCompetence pour
    les besoins de nature MATERIEL/MIXTE (voir BesoinNature)."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    besoin = models.ForeignKey(
        "Besoin",
        on_delete=models.CASCADE,
        related_name="materiels"
    )

    materiel = models.ForeignKey(
        "MaterielCatalogue",
        on_delete=models.PROTECT,
        related_name="besoins",
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.besoin.nom} -> {self.materiel.nom}"

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

    # Fermé par défaut : une association n'agit sur une crise qu'après validation d'une autorité
    # locale ; vrai pour les services publics.
    est_public = models.BooleanField(default=False)

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

    # Posée au rattachement d'un compte AUT_LOCALE (institution_attachment.py) : vue mairie.
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

    # Saisi à la main dans l'édition de l'institution, jamais recalculé.
    commune_code_postal = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Code postal de la commune de l'institution — utile pour distinguer des "
                   "communes homonymes, jamais recalculé automatiquement.",
    )

    # Dénormalisés par save() à chaque changement de commune_code.
    epci_code = models.CharField(max_length=10, null=True, blank=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True)
    region_code = models.CharField(max_length=3, null=True, blank=True)

    class SecteurNiveau(models.TextChoices):
        COMMUNE = "commune", "Communal"
        EPCI = "epci", "Intercommunal (EPCI)"
        DEPARTEMENT = "departement", "Départemental"
        REGION = "region", "Régional"
        NATIONAL = "national", "National"

    # Force le niveau de secteur (comptes de test uniquement) ; null = niveau déduit du type.
    secteur_override = models.CharField(
        max_length=20, choices=SecteurNiveau.choices, null=True, blank=True,
        help_text="Force le niveau de secteur (vue_secteur) pour cette institution, quel que "
                   "soit son type — usage test uniquement, laisser vide sinon.",
    )

    # Niveau effectif et nom lisible, dénormalisés avec les codes ci-dessus (affichage « Ma zone
    # est : »).
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
        if self.commune_code and self.type_id:
            type_code = (self.type.code or "").upper()
            if type_code in TYPES_COLLECTIVITE_TERRITORIALE:
                _assurer_zone_mon_territoire(self)

    actif = models.BooleanField(
        default=True
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    # Convention de sous-traitance RGPD (art. 28), acceptée une fois par institution par son
    # premier compte autorité locale ; convention_version identifie le texte accepté
    # (core/convention_sous_traitance.py).
    convention_sous_traitance_acceptee_le = models.DateTimeField(null=True, blank=True)
    convention_sous_traitance_acceptee_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="conventions_sous_traitance_acceptees",
    )
    convention_sous_traitance_version = models.CharField(max_length=10, blank=True)

    # Marque blanche (core/branding.py) ; vide = valeurs Assista-Crise. En clair : informations
    # publiques.
    nom_affichage = models.CharField(
        max_length=255, blank=True,
        help_text="Nom affiché en marque blanche (header, emails...). Vide = utilise `nom`.",
    )
    logo = models.ImageField(
        upload_to=institution_branding_path, max_length=255, null=True, blank=True,
        validators=[validate_image_file],
    )
    couleur_primaire = models.CharField(max_length=7, blank=True, help_text="Couleur hex, ex: #3c4d81.")
    couleur_secondaire = models.CharField(max_length=7, blank=True, help_text="Couleur hex, ex: #2ea3f2.")
    police_titre = models.CharField(max_length=100, blank=True, help_text="Police Google Fonts pour les titres, ex: Quicksand.")
    police_texte = models.CharField(max_length=100, blank=True, help_text="Police Google Fonts pour le texte courant, ex: Open Sans.")
    email_reply_to = models.EmailField(blank=True, help_text="Reply-To des emails envoyés au nom de cette institution.")

    # Affiche la case « rejoindre la réserve » à l'inscription quand le Host résout vers cette
    # institution.
    reserve_active = models.BooleanField(default=False)

    def __str__(self):
        return self.nom


class InstitutionWebDomaine(EnvironmentScopedModel):
    """Nom d'hôte web (marque blanche) résolu vers cette institution par core/branding.py.
    Distinct d'InstitutionDomaine (domaine email, rattachement automatique). Déclarer chaque
    Host réellement visité, y compris un CNAME."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="domaines_web")
    hostname = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.hostname


class JournalCollectivite(EnvironmentScopedModel):
    """Main courante de la Vue Ma Collectivité : entrées immuables (pas de route update/delete)
    et journalisées dans AuditLog."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="journal_entries")
    # Rattaché à une crise : une institution peut être impliquée sur plusieurs crises. Nullable
    # depuis le backfill (migrations 0119/0120).
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


class OfferTypeBesoin(models.Model):
    """Lien OfferType -> Besoin (pendant de RequestTypeBesoin) : filtre les offres proposées
    selon les thèmes à l'écoute (besoins_ecoute.py)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offer_type = models.ForeignKey(OfferType, on_delete=models.CASCADE, related_name="besoins")

    besoin = models.ForeignKey(Besoin, on_delete=models.CASCADE, related_name="offer_types")

    def __str__(self):
        return f"{self.offer_type} -> {self.besoin}"


class InformationTypeBesoin(models.Model):
    """Pont InformationType -> Besoin, mirror de RequestTypeBesoin -- même rôle que
    OfferTypeBesoin pour le formulaire public "signaler"."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    information_type = models.ForeignKey(InformationType, on_delete=models.CASCADE, related_name="besoins")

    besoin = models.ForeignKey(Besoin, on_delete=models.CASCADE, related_name="information_types")

    def __str__(self):
        return f"{self.information_type} -> {self.besoin}"


class AffectationCompetence(EnvironmentScopedModel):
    """Affecte une compétence à une équipe pour une crise donnée."""

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

    # Besoin précis à l'origine du dossier, capturé à la création (une compétence peut servir
    # plusieurs besoins) : classe le dossier en ressource ou moyen.
    besoin = models.ForeignKey(
        "Besoin",
        on_delete=models.SET_NULL,
        related_name="dossiers",
        null=True,
        blank=True,
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

    habitation = models.ForeignKey(
        "Habitation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dossiers",
        help_text="Habitation à l'origine de ce dossier, si créé depuis le module "
                   "d'estimation des dégâts (rattachement accepté ou dégâts constatés).",
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

    # Urgence signalée par un participant, qui notifie les régulateurs
    # (DossierViewSet.marquer_important).
    important = models.BooleanField(default=False)
    date_signalement_important = models.DateTimeField(null=True, blank=True)

    # Version utilisée par la synchronisation satellite pour détecter un conflit
    # (core/sync_outbox.py).
    modifie_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.numero} - {self.titre}"


class Mission(EnvironmentScopedModel):
    """Objectif opérationnel auquel des équipes sont affectées et sous lequel des dossiers sont
    regroupés."""

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

    # Nullable : une mission courante d'équipe peut exister sans crise.
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

    # Modèle de plan d'origine : évite de recréer la mission si le plan est réactivé.
    modele_origine = models.ForeignKey(
        "PlanMissionModele",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="missions_instanciees",
    )

    # Voir Dossier.modifie_le — même rôle pour la synchronisation local -> central.
    modifie_le = models.DateTimeField(auto_now=True)

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
        max_length=255,
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

    habitation = models.ForeignKey(
        "Habitation",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents"
    )

    def __str__(self):
        return str(self.id)


class ConfigurationAlerteSismique(EnvironmentScopedModel):
    """Diffusion automatique des séismes proches sur les canaux mesh de l'institution (commande
    verifier_alertes_sismiques, lancée par cron). Source : API FDSN BCSF-Rénass. Centre =
    centroïde de Institution.commune_code. magnitude_min de 3.5 (séisme ressenti) par choix du
    porteur ; monter vers 4 pour ne garder que les risques de dégâts."""

    institution = models.OneToOneField(
        "Institution", on_delete=models.CASCADE, related_name="configuration_alerte_sismique",
    )
    actif = models.BooleanField(default=False)
    rayon_km = models.PositiveIntegerField(default=100)
    magnitude_min = models.FloatField(default=3.5)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Alerte sismique {self.institution.nom} ({'active' if self.actif else 'inactive'})"


class SeismeDiffuse(EnvironmentScopedModel):
    """Séisme déjà diffusé (anti-doublon entre deux cycles). institution vide = diffusion
    communautaire Fr_EMCOM."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="seismes_diffuses",
    )

    # Identifiant de l'événement dans le catalogue, unique par institution.
    event_id = models.CharField(max_length=64)

    magnitude = models.FloatField()
    lieu = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()
    date_evenement = models.DateTimeField()
    date_diffusion = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institution", "event_id"], name="uq_seisme_diffuse_institution_event"),
        ]

    def __str__(self):
        return f"M{self.magnitude} {self.lieu} -> {self.institution.nom}"


class CategorieInterlocuteurPCS(models.TextChoices):
    """Catégories types d'un annuaire de crise PCS/PICS."""
    PREFECTURE = "PREFECTURE", "Préfecture (SIDPC/COD)"
    SOUS_PREFECTURE = "SOUS_PREFECTURE", "Sous-préfecture"
    GENDARMERIE_POLICE = "GENDARMERIE_POLICE", "Gendarmerie / Police"
    SDIS = "SDIS", "SDIS (secours)"
    SAMU = "SAMU", "SAMU"
    ARS = "ARS", "ARS (santé)"
    SERVICES_ETAT = "SERVICES_ETAT", "Services de l'État (DDT/DREAL...)"
    ELU_PERSONNEL_COMMUNAL = "ELU_PERSONNEL_COMMUNAL", "Élu ou personnel communal"
    EPCI_INTERCOMMUNALITE = "EPCI_INTERCOMMUNALITE", "Intercommunalité / EPCI (PICS)"
    GESTIONNAIRE_RESEAU = "GESTIONNAIRE_RESEAU", "Gestionnaire de réseau (élec./gaz/eau)"
    ETABLISSEMENT_SENSIBLE = "ETABLISSEMENT_SENSIBLE", "Établissement sensible (école, EHPAD...)"
    ASSOCIATION_SECURITE_CIVILE = "ASSOCIATION_SECURITE_CIVILE", "Association agréée de sécurité civile"
    MEDIA = "MEDIA", "Média local"
    AUTRE = "AUTRE", "Autre"


class ModeAlertePCS(models.TextChoices):
    """Canal d'alerte préféré d'un interlocuteur PCS. TELEPHONE est manuel ; SMS et API_TIERCE
    sont réservés (aucun envoi implémenté, voir core/alertes_pcs.py)."""
    EMAIL = "EMAIL", "Email"
    MATRIX = "MATRIX", "Message Matrix"
    TELEPHONE = "TELEPHONE", "Téléphone (manuel uniquement)"
    SMS = "SMS", "SMS (pas encore disponible)"
    API_TIERCE = "API_TIERCE", "Intégration tierce (Intramuros, Facebook...) -- pas encore disponible"
    AUCUN = "AUCUN", "Aucun envoi automatique"


class StatutNotificationPCS(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    ENVOYE_AUTO = "ENVOYE_AUTO", "Envoyé automatiquement"
    ECHEC_AUTO = "ECHEC_AUTO", "Échec de l'envoi automatique"
    # Accusé de réception cliqué par le destinataire (CONFIRME_MANUEL : coché par la mairie).
    CONFIRME_PAR_CONTACT = "CONFIRME_PAR_CONTACT", "Confirmé par le contact lui-même"
    CONFIRME_MANUEL = "CONFIRME_MANUEL", "Confirmé manuellement"


class ReponseContactPCS(models.TextChoices):
    """Réponse rapide proposée sur la page publique d'accusé de réception."""
    PAS_DE_RAPPEL = "PAS_DE_RAPPEL", "Pas besoin de me rappeler"
    MERCI_RAPPELER = "MERCI_RAPPELER", "Merci de me rappeler pour échanger sur la situation"
    AUTRE = "AUTRE", "Autre (voir commentaire)"


class InterlocuteurAlertePCS(EnvironmentScopedModel):
    """Annuaire partagé des interlocuteurs à prévenir à l'activation d'un PCS/PICS : un même
    contact (ex. SIDPC) est rattachable par plusieurs communes. Scopé PROD/DEMO car utilisé pour
    de vrais envois. nom, email, téléphone et notes chiffrés ; organisme en clair."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institutions = models.ManyToManyField(
        "Institution", related_name="interlocuteurs_alerte_pcs", blank=True,
    )

    # Département de l'institution créatrice : borne la recherche d'un contact existant (?q=), sans
    # être une contrainte.
    departement_code = models.CharField(max_length=3, null=True, blank=True)

    categorie = models.CharField(
        max_length=30, choices=CategorieInterlocuteurPCS.choices, default=CategorieInterlocuteurPCS.AUTRE,
    )

    nom = EncryptedTextField()
    organisme = models.CharField(max_length=255, blank=True)
    email = EncryptedEmailField(null=True, blank=True)
    telephone = EncryptedTextField(null=True, blank=True)
    notes = EncryptedTextField(null=True, blank=True)

    # Compte applicatif éventuel (envoi Matrix). SET_NULL : la fiche survit au compte.
    utilisateur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="interlocuteurs_alerte_pcs",
    )

    mode_alerte = models.CharField(max_length=20, choices=ModeAlertePCS.choices, default=ModeAlertePCS.EMAIL)

    actif = models.BooleanField(default=True)
    ordre = models.PositiveIntegerField(default=0)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "categorie"]

    def __str__(self):
        return f"{self.nom} ({self.organisme or self.get_categorie_display()})"


class NotificationAlertePCS(EnvironmentScopedModel):
    """Une ligne par (crise, interlocuteur), créée à la déclaration de la crise : checklist et
    suivi des envois. Les champs *_snapshot figent l'historique si l'annuaire change.
    token_confirmation : accusé de réception sans compte (AccuserReceptionAlertePCSPublicView)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(Crisis, on_delete=models.CASCADE, related_name="notifications_alerte_pcs")

    interlocuteur = models.ForeignKey(
        InterlocuteurAlertePCS, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications",
    )
    nom_snapshot = EncryptedTextField()
    organisme_snapshot = models.CharField(max_length=255, blank=True)
    categorie_snapshot = models.CharField(max_length=30, choices=CategorieInterlocuteurPCS.choices)
    institution_nom_snapshot = models.CharField(max_length=255, blank=True)

    canal_tente = models.CharField(max_length=20, choices=ModeAlertePCS.choices)

    statut = models.CharField(max_length=20, choices=StatutNotificationPCS.choices, default=StatutNotificationPCS.EN_ATTENTE)
    detail_erreur = models.TextField(null=True, blank=True)

    token_confirmation = models.CharField(max_length=64, unique=True)
    # Texte réellement envoyé, conservé pour trace.
    message_envoye = models.TextField(null=True, blank=True)

    reponse_contact = models.CharField(max_length=20, choices=ReponseContactPCS.choices, null=True, blank=True)
    commentaire_contact = EncryptedTextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_envoi_auto = models.DateTimeField(null=True, blank=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)

    # Seulement pour CONFIRME_MANUEL.
    confirme_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications_pcs_confirmees",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["crise", "interlocuteur"], name="uq_notification_pcs_crise_interlocuteur"),
        ]

    def __str__(self):
        return f"{self.nom_snapshot} / {self.crise.name} ({self.statut})"


# Collectivités territoriales au sens strict (pas les services de l'État de même niveau) :
# Zone « Mon territoire » automatique et accès aux fonctions PCS/PICS.
TYPES_COLLECTIVITE_TERRITORIALE = {"MAIRIE", "EPCI", "CG", "CR"}


def _assurer_zone_mon_territoire(institution) -> None:
    """Crée ou met à jour la Zone « Mon territoire » d'une collectivité ; n'échoue jamais (une
    panne réseau ne bloque pas l'enregistrement de l'institution)."""
    from .geo_lookup import communes_de_secteur
    try:
        niveau = institution.secteur_niveau_effectif
        if niveau == "commune":
            communes = [institution.commune_code] if institution.commune_code else []
        else:
            code = {
                "epci": institution.epci_code,
                "departement": institution.departement_code,
                "region": institution.region_code,
            }.get(niveau)
            communes = communes_de_secteur(niveau, code) if code else []
        zone, created = Zone.objects.get_or_create(
            institution=institution, nom="Mon territoire",
            defaults={"communes": communes, "environment": institution.environment},
        )
        if not created and zone.communes != communes:
            zone.communes = communes
            zone.save(update_fields=["communes"])
    except Exception:
        pass


class Zone(EnvironmentScopedModel):
    """Zone nommée d'une institution, réutilisable par équipes, points et plans."""

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


class StatutEvaluationHabitation(models.TextChoices):
    NON_EVALUEE = "NON_EVALUEE", "Non évaluée"
    PAS_DE_DEGATS = "PAS_DE_DEGATS", "Pas de dégâts"
    DEGATS_FAIBLES = "DEGATS_FAIBLES", "Dégâts faibles"
    DEGATS_FORTS = "DEGATS_FORTS", "Dégâts forts"


class StatutChantierHabitation(models.TextChoices):
    A_DEBLAYER = "A_DEBLAYER", "À déblayer"
    NETTOYAGE_EN_COURS = "NETTOYAGE_EN_COURS", "Nettoyage / déblaiement en cours"
    TERMINE = "TERMINE", "Chantier terminé"


class Habitation(EnvironmentScopedModel):
    """Bâtiment référencé pour l'estimation des dégâts (couleur = statut_evaluation, puis
    statut_chantier). Alimenté par import CSV (ImportHabitationsView)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, null=True, blank=True,
        related_name="habitations",
        help_text="Crise à laquelle ce référencement est rattaché, si applicable.",
    )

    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="habitations",
        help_text="Regroupement (quartier/secteur) pour le filtrage de la vue de suivi.",
    )

    adresse = EncryptedTextField()

    # Dénormalisé pour réutiliser zone_scoping.py (filtrage par commune/secteur de
    # l'institution) tel quel, comme Request/Offer -- voir SECTEUR_CHAMP_PAR_NIVEAU.
    commune_code = models.CharField(max_length=10, blank=True, null=True)
    commune_nom = models.CharField(max_length=255, blank=True, null=True)

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    parcelle_cadastrale = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="Identifiant cadastral (ex: 33333000BK0034) -- IGN APICarto cadastre si absent de la BAN.",
    )

    ban_id = models.CharField(
        max_length=64, blank=True, null=True,
        help_text="Identifiant BAN de l'adresse, pour rafraîchissement/déduplication ultérieurs.",
    )

    statut_evaluation = models.CharField(
        max_length=20,
        choices=StatutEvaluationHabitation.choices,
        default=StatutEvaluationHabitation.NON_EVALUEE,
    )

    statut_chantier = models.CharField(
        max_length=20,
        choices=StatutChantierHabitation.choices,
        null=True, blank=True,
        help_text="Uniquement pertinent si statut_evaluation indique des dégâts.",
    )

    evalue_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="habitations_evaluees",
    )

    date_derniere_evaluation = models.DateTimeField(null=True, blank=True)

    # Surfaces (m²) -- totales et part impactée par les dégâts (demande utilisateur du 20/10/2026).
    surface_habitable_totale = models.FloatField(null=True, blank=True, help_text="Surface habitable totale (m²).")
    surface_habitable_impactee = models.FloatField(null=True, blank=True, help_text="Surface habitable impactée (m²).")
    surface_non_habitable_totale = models.FloatField(null=True, blank=True, help_text="Surface non habitable totale (annexes, garage, local…) (m²).")
    surface_non_habitable_impactee = models.FloatField(null=True, blank=True, help_text="Surface non habitable impactée (m²).")

    # Valeur indicative du bien (€), typiquement issue de DVF (valeurs foncières open data) --
    # jamais une expertise, toujours affichée comme indicative (voir vue DVF).
    valeur_estimee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                         help_text="Valeur indicative du bien (€), ex. DVF.")
    valeur_source = models.CharField(max_length=40, null=True, blank=True,
                                     help_text="Origine de la valeur (ex: DVF, saisie manuelle).")

    date_creation = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.adresse


class HabitationCommentaire(EnvironmentScopedModel):
    """Échanges sur une habitation entre agents et rattachés acceptés (propriétaire, locataire)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    habitation = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="commentaires")

    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    commentaire = models.TextField()

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.habitation.adresse}"


class HabitationHistorique(EnvironmentScopedModel):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    habitation = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="historique")

    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    evenement = models.CharField(max_length=255)

    commentaire = models.TextField(blank=True, null=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.evenement


class TypeLienHabitation(models.TextChoices):
    PROPRIETAIRE = "PROPRIETAIRE", "Propriétaire"
    LOCATAIRE = "LOCATAIRE", "Locataire"


class StatutRattachementHabitation(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    ACCEPTE = "ACCEPTE", "Accepté"
    REFUSE = "REFUSE", "Refusé"


class RattachementHabitation(EnvironmentScopedModel):
    """Demande de rattachement (propriétaire ou locataire) à une habitation, sans compte
    obligatoire ; suivi par lien magique ou compte. Pas d'unicité stricte : la vue refuse
    seulement un doublon EN_ATTENTE."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    habitation = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="rattachements")

    # Rempli si le demandeur avait déjà un compte au moment de la demande, ou dès qu'il se
    # connecte avec l'email correspondant -- jamais requis pour déposer la demande elle-même.
    utilisateur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rattachements_habitations",
    )

    nom_demandeur = EncryptedTextField(max_length=255)
    email_demandeur = EncryptedEmailField()
    # Index aveugle : anti-doublon et rapprochement avec un compte.
    email_demandeur_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    telephone_demandeur = EncryptedTextField(blank=True, null=True)

    type_lien = models.CharField(max_length=20, choices=TypeLienHabitation.choices)

    statut = models.CharField(
        max_length=20,
        choices=StatutRattachementHabitation.choices,
        default=StatutRattachementHabitation.EN_ATTENTE,
    )

    message = EncryptedTextField(
        blank=True, null=True,
        help_text="Complément fourni par le demandeur (justificatif à venir, précisions...).",
    )

    date_demande = models.DateTimeField(auto_now_add=True)

    traite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rattachements_habitations_traites",
    )
    date_traitement = models.DateTimeField(null=True, blank=True)
    motif_refus = EncryptedTextField(blank=True, null=True)

    # Justificatif optionnel (titre, bail, facture). Champ direct plutôt que Document, qui exige un
    # compte.
    justificatif = models.ImageField(
        upload_to=secure_document_path, max_length=255, null=True, blank=True,
        validators=[validate_image_file],
    )

    def save(self, *args, **kwargs):
        self.email_demandeur_bidx = blind_index(self.email_demandeur) if self.email_demandeur else None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nom_demandeur} ({self.type_lien}) -> {self.habitation.adresse}"


class PieceIdentiteReserve(EnvironmentScopedModel):
    """Permis ou pièce d'identité d'un candidat à une réserve en marque blanche (exigence
    d'assurance du partenaire). Fichier chiffré au repos (core/file_crypto.py,
    FILE_ENCRYPTION_KEY). Préfixe documents/ bloqué par proxy/nginx.conf : ne pas le changer
    sans ajouter le blocage correspondant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pieces_identite_reserve")

    permis_recto = models.FileField(
        storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255,
        null=True, blank=True, validators=[validate_identity_document_file],
    )
    permis_verso = models.FileField(
        storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255,
        null=True, blank=True, validators=[validate_identity_document_file],
    )

    date_depot = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pièce identité réserve — {self.utilisateur}"


class ModuleDegatsCrise(EnvironmentScopedModel):
    """Activation du module « Estimation des dégâts » par une institution pour une crise
    (désactivé par défaut). zone restreint les bâtiments chargeables."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="modules_degats")

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="modules_degats_actives",
    )

    actif = models.BooleanField(default=True)

    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name="modules_degats",
        help_text="Zone où les points doivent être chargés -- vide = pas de restriction posée.",
    )

    active_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    date_activation = models.DateTimeField(auto_now_add=True)

    date_desactivation = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["crise", "institution"], name="uq_module_degats_crise_institution",
            )
        ]

    def __str__(self):
        return f"{self.institution.nom} — {self.crise.name} ({'actif' if self.actif else 'inactif'})"


# --- Simulation d'inondation (planification préventive) ---
# Cache de calcul : ne jamais écrire dans Habitation.statut_evaluation depuis une simulation
# (hypothèse, pas constat). Calcul : core/inondation.py.


class GrilleAltimetrieCommune(EnvironmentScopedModel):
    """Grille régulière de points (altitude IGN) couvrant une commune -- le relief ne change
    jamais, un seul calcul par commune suffit durablement (voir inondation.grille_altitude_commune)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    commune_code = models.CharField(max_length=10)

    points = models.JSONField(help_text="[{lon, lat, altitude}] -- grille régulière, voir pas_metres.")

    pas_metres = models.IntegerField()

    date_calcul = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "environment"], name="uq_grille_altimetrie_commune_environment",
            )
        ]

    def __str__(self):
        return f"Grille altimétrique — {self.commune_code}"


class GrilleRuissellementCommune(EnvironmentScopedModel):
    """Grille d'accumulation de flux (ruissellement) d'une commune, calculée depuis la grille
    d'altitude (core/ruissellement.py)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    commune_code = models.CharField(max_length=10)

    points = models.JSONField(help_text="[{lon, lat, accumulation}] -- grille régulière, voir pas_metres.")

    pas_metres = models.IntegerField()

    date_calcul = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "environment"], name="uq_grille_ruissellement_commune_environment",
            )
        ]

    def __str__(self):
        return f"Grille ruissellement — {self.commune_code}"


class PalierInondationSimule(EnvironmentScopedModel):
    """Zone inondée simulée pour un niveau d'eau, précalculée par paliers pour le curseur du
    frontend. polygone vide = rien d'inondé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    commune_code = models.CharField(max_length=10)

    niveau_metres = models.FloatField()

    polygone = gis_models.MultiPolygonField(srid=4326, null=True, blank=True)

    date_calcul = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "niveau_metres", "environment"],
                name="uq_palier_inondation_commune_niveau_environment",
            )
        ]

    def __str__(self):
        return f"{self.commune_code} — {self.niveau_metres}m"


class AdresseSimuleeInondation(EnvironmentScopedModel):
    """Adresse BAN scannée : altitude et plus petit niveau d'eau qui l'atteint (null = jamais
    dans la plage testée)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    commune_code = models.CharField(max_length=10)

    ban_id = models.CharField(max_length=64, null=True, blank=True)

    adresse = models.TextField()

    location = gis_models.PointField(srid=4326)

    altitude_metres = models.FloatField(null=True, blank=True)

    seuil_inondation_metres = models.FloatField(null=True, blank=True)

    date_calcul = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.adresse


class StatutTacheInondation(models.TextChoices):
    EN_COURS = "EN_COURS", "En cours"
    TERMINEE = "TERMINEE", "Terminée"
    ECHEC = "ECHEC", "Échec"


class TypeTacheInondation(models.TextChoices):
    # Grille d'altitude et paliers : calcul borné.
    PALIERS = "PALIERS", "Relief et paliers d'eau"
    # Scan BAN des adresses : non borné (grandes villes), séparé pour que les paliers restent
    # utilisables s'il échoue.
    ADRESSES = "ADRESSES", "Adresses BAN"
    # Accumulation de flux (crue éclair) : même grille, algorithme différent.
    RUISSELLEMENT = "RUISSELLEMENT", "Ruissellement"


class TacheSimulationInondation(EnvironmentScopedModel):
    """État de la dernière tâche Celery par (commune, environnement, type) : empêche un double
    lancement et survit à un changement de page."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    commune_code = models.CharField(max_length=10)

    type_tache = models.CharField(max_length=20, choices=TypeTacheInondation.choices, default=TypeTacheInondation.PALIERS)

    statut = models.CharField(max_length=20, choices=StatutTacheInondation.choices, default=StatutTacheInondation.EN_COURS)

    erreur = models.TextField(blank=True, null=True)

    date_lancement = models.DateTimeField(auto_now_add=True)

    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "environment", "type_tache"],
                name="uq_tache_simulation_inondation_commune_environment_type",
            )
        ]

    def __str__(self):
        return f"{self.commune_code} — {self.type_tache} — {self.statut}"


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

    # Institution responsable, dont les référents sont prévenus à la création. Nullable pour un
    # compte sans institution.
    institution = models.ForeignKey(
        "Institution",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="teams",
    )
    # Délégataire courant (historique dans TeamDelegation). SET_NULL : sa suppression ne bloque
    # pas.
    institution_delegataire = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="teams_deleguees",
    )

    # Équipe de tête à laquelle celle-ci est rattachée comme ressource (arbre de profondeur libre).
    # Lien organisationnel : l'équipe garde son autonomie.
    equipe_parente = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sous_equipes",
    )

    est_equipe_rcsc = models.BooleanField(
        default=False,
        help_text="Marque cette équipe comme LA Réserve Communale de Sécurité Civile (RCSC) de "
                   "son institution (mairie) -- pas une Institution à part : une RCSC est "
                   "placée sous l'autorité du maire, \"une équipe dans l'équipe\". Toute "
                   "sous-équipe atteinte via equipe_parente hérite de ce statut sans avoir à "
                   "cocher elle-même ce champ (voir vulnerabilites.equipes_rcsc) -- une RCSC "
                   "scindée en sous-groupes reste UNE RCSC. Sans rapport avec Institution."
                   "reserve_active/User.souhaite_rejoindre_reserve (réserve CITOYENNE de "
                   "bénévoles marque blanche, un tout autre dispositif) -- nom volontairement "
                   "distinct pour ne jamais confondre les deux.",
    )

    leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="led_teams"
    )
    # Pilote l'équipe depuis le centre de crise ; choisi parmi les régulateurs
    # (AffectationRoleOperationnel).
    regulateur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="teams_regulees"
    )

    # Début de l'engagement continu (affiché en cellule de crise), None = au repos. Toujours
    # manuel : pas d'inférence depuis l'activité.
    engagement_debut = models.DateTimeField(null=True, blank=True)
    # Mission courante de l'équipe (une seule), distincte de Mission.equipes ; l'historique est
    # dans AuditLog.
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

    # Thèmes de l'équipe, même vocabulaire que ImplicationInstitution.themes.
    themes = models.ManyToManyField(
        "Besoin",
        blank=True,
        related_name="equipes"
    )

    # Zone d'intervention : départements, puis communes, puis polygone. Le matching utilise le
    # niveau le plus précis renseigné.
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

    # Zones nommées de l'institution, sans effet sur le matching géographique.
    zone_principale = models.ForeignKey(
        "Zone",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="equipes",
    )

    def __str__(self) -> str:
        return self.name


class TeamDelegation(EnvironmentScopedModel):
    """Historique des délégations d'une équipe (état courant : Team.institution_delegataire)."""
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
    """Progression d'une ressource affectée à une équipe (confirmée, en route, arrivée), recréée
    à chaque affectation. Mise à jour par l'équipe (sans ordre imposé) ou par la personne via
    son lien email (ordre strict)."""
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
    """Dernière position connue d'un utilisateur, capturée seulement quand le navigateur l'a
    déjà obtenue (jamais de traçage continu). Une ligne par utilisateur et environnement."""

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

    # Crise ciblée par la notification, pour y naviguer au clic.
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


class TypeDemandeMobilisation(models.TextChoices):
    MISE_A_DISPOSITION = "MISE_A_DISPOSITION", "Se mettre à disposition"
    SE_RENDRE_A = "SE_RENDRE_A", "Se rendre à un endroit précis"


class StatutDemandeMobilisation(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVOQUEE = "REVOQUEE", "Révoquée"


class DemandeMobilisation(EnvironmentScopedModel):
    """Demande formelle d'une institution à une personne ou institution de se mettre à
    disposition ou de se rendre quelque part. Jamais présentée comme une réquisition légale
    (pouvoir réservé au préfet et au maire). jeton_verification prévu pour une future
    attestation PDF. Cible : exactement un utilisateur, une institution ou une offre (validé par
    le serializer)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, related_name="demandes_mobilisation",
    )

    institution_emettrice = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="demandes_mobilisation_emises",
    )
    # Qui a effectivement cliqué (pour la main courante/la future attestation) — distinct de
    # l'institution émettrice elle-même.
    emetteur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes_mobilisation_creees",
    )

    cible_utilisateur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes_mobilisation_recues",
    )
    cible_institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes_mobilisation_recues",
    )
    cible_offre = models.ForeignKey(
        "Offer", on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes_mobilisation_recues",
    )

    type_demande = models.CharField(max_length=25, choices=TypeDemandeMobilisation.choices)

    # SE_RENDRE_A uniquement : point opérationnel si possible, sinon texte libre.
    point_operationnel = models.ForeignKey(
        "PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="demandes_mobilisation",
    )
    lieu_texte = models.CharField(max_length=255, blank=True)

    motif = models.TextField(blank=True)

    statut = models.CharField(
        max_length=15, choices=StatutDemandeMobilisation.choices, default=StatutDemandeMobilisation.ACTIVE,
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_revocation = models.DateTimeField(null=True, blank=True)

    jeton_verification = models.CharField(max_length=64, unique=True, null=True, blank=True)

    def __str__(self):
        return f"Demande {self.get_type_demande_display()} — {self.institution_emettrice.nom}"


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

    nom = EncryptedTextField(max_length=255)

    prenom = EncryptedTextField(max_length=255)

    age = models.IntegerField()

    photo = models.ImageField(
        upload_to=secure_recherche_personne_photo_path,
        max_length=255,
        blank=True,
        null=True,
        validators=[validate_image_file],
    )

    description = EncryptedTextField(
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

    adresse = EncryptedTextField(
        blank=True,
        null=True
    )

    ehpad_nom = EncryptedTextField(
        max_length=255,
        blank=True,
        null=True
    )

    ehpad_adresse = EncryptedTextField(
        blank=True,
        null=True
    )

    contact_nom = EncryptedTextField(
        max_length=255
    )

    createur = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="recherches_personnes"
    )

    contact_email = EncryptedEmailField()

    contact_telephone = EncryptedTextField(
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

    commentaire_retrouvee = EncryptedTextField(
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
        max_length=255,
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
        max_length=255,
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

class StatutSecteurRecherche(models.TextChoices):
    A_FAIRE = "A_FAIRE", "À faire"
    EN_COURS = "EN_COURS", "En cours"
    FOUILLE = "FOUILLE", "Fouillé"


class SecteurRecherche(EnvironmentScopedModel):
    """Secteur de recherche SAR : découpe la zone d'une RecherchePersonne en polygones affectés
    aux équipes, pour suivre ce qui a déjà été fouillé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    recherche_personne = models.ForeignKey(
        RecherchePersonne, on_delete=models.CASCADE, related_name="secteurs_recherche",
    )

    nom = models.CharField(max_length=100)

    polygone = gis_models.PolygonField(srid=4326)

    equipe = models.ForeignKey(
        "Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="secteurs_recherche",
    )

    statut = models.CharField(
        max_length=10, choices=StatutSecteurRecherche.choices, default=StatutSecteurRecherche.A_FAIRE,
    )

    commentaire = EncryptedTextField(blank=True, null=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nom} ({self.statut})"


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

    # Zone et responsabilité de la personne pour ce rôle (catalogue Zone de l'institution).
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

    # Secteur délégué : toute la crise (champs vides), départements, communes ou polygone, comme
    # Team.
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

    # Catégories du catalogue masquées dans le stock des centres de ce type (liste d'exclusion ;
    # vide = aucune restriction).
    categories_materiel_exclues = models.JSONField(default=list, blank=True)

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

    # Null = capacité inconnue ; sert à la saturation affichée aux personnes cherchant un centre
    # d'accueil.
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

    # Équipes de gestion supplémentaires (roulements, spécialités), en plus de equipe.
    equipes_gestion = models.ManyToManyField(
        "Team",
        blank=True,
        related_name="points_geres_specialite",
        help_text="Équipes supplémentaires tenant ce point (par spécialité), en plus de `equipe`.",
    )

    # Équipes ravitaillées par ce point (repas, repos, carburant).
    equipes_ravitaillement = models.ManyToManyField(
        "Team",
        blank=True,
        related_name="points_ravitaillement",
        help_text="Équipes de terrain ravitaillées par ce point (repas, repos, carburant...).",
    )

    # Responsables supplémentaires, en plus de responsable ; les contacts affichés sont l'union des
    # deux.
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

    # Animaux acceptés dans ce centre d'accueil.
    accepte_animaux = models.BooleanField(default=False)

    def __str__(self):
        return self.nom

    def responsables_effectifs(self) -> list:
        """Union dédoublonnée des responsables (responsable, responsables, chefs des équipes de
        gestion) : contact affiché et notifications."""
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
    """Créneau de disponibilité d'un membre de l'équipe responsable d'un point."""

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
    """Dispositif préparé d'une institution (ex. « Plan canicule ») regroupant équipes, points
    et zones existants, activable sur une crise (PlanViewSet.activer)."""

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

    risques = models.ManyToManyField(
        "RisqueCommunal", blank=True, related_name="plans",
        help_text="Risques communaux (déjà déclarés par l'institution, voir RisqueCommunal) que "
                   "ce dispositif couvre -- jamais le catalogue RisqueMajeurType directement, "
                   "toujours la déclaration propre à l'institution.",
    )

    contacts_internes = models.ManyToManyField(
        "ContactInstitution", blank=True, related_name="plans",
        help_text="Contacts internes de l'institution (déjà déclarés, voir ContactInstitution) "
                   "mobilisables sur ce dispositif.",
    )

    interlocuteurs = models.ManyToManyField(
        "InterlocuteurAlertePCS", blank=True, related_name="plans",
        help_text="Interlocuteurs externes à prévenir (annuaire partagé, voir "
                   "InterlocuteurAlertePCS) rattachés à ce dispositif.",
    )

    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self) -> str:
        return self.nom


class PlanMissionModele(EnvironmentScopedModel):
    """Modèle de mission d'une équipe d'un Plan : instancie une Mission et un Dossier à
    l'activation. Le stock n'a pas besoin de modèle : il reste sur son point."""

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

    # Référent (pas forcément membre) seul rattaché au dossier instancié.
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
    """Catégories du catalogue matériel : ENGIN pour le formulaire public, les autres pour le
    stock des centres (filtrées par PointType.categories_materiel_exclues)."""
    ENGIN = "ENGIN", "Engin agricole / chantier / spécial"
    NETTOYAGE = "NETTOYAGE", "Nettoyage et remise en état"
    POMPAGE = "POMPAGE", "Pompage et évacuation d'eau"
    DEBLAI_MANUTENTION = "DEBLAI_MANUTENTION", "Déblaiement et manutention"
    ENERGIE_ECLAIRAGE = "ENERGIE_ECLAIRAGE", "Énergie et éclairage"
    PROTECTION_BATIMENTS = "PROTECTION_BATIMENTS", "Protection des bâtiments"
    OUTILLAGE_TERRAIN = "OUTILLAGE_TERRAIN", "Outillage et équipement de terrain"
    PROTECTION_INDIVIDUELLE = "PROTECTION_INDIVIDUELLE", "Protection individuelle"
    ACCUEIL_HEBERGEMENT = "ACCUEIL_HEBERGEMENT", "Accueil et hébergement d'urgence"
    DIVERS = "DIVERS", "Divers / consommables"


class MaterielCatalogue(models.Model):
    """Catalogue partagé et extensible des besoins matériels (remplace l'ancien TypeMateriel
    figé)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=100, unique=True)

    # Catégorie fixe utilisée pour filtrer le stock des centres (distincte de parent).
    categorie = models.CharField(max_length=30, choices=MaterielCatalogueCategorie.choices, null=True, blank=True)

    # Regroupement libre sur un seul niveau, comme Besoin.parent.
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sous_materiels",
    )

    # Masque une entrée obsolète sans la supprimer.
    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.nom


class NiveauStock(models.TextChoices):
    NUL = "NUL", "Nul"
    FAIBLE = "FAIBLE", "Faible"
    OK = "OK", "OK"
    EN_TROP = "EN_TROP", "En trop"


class MaterielPoint(EnvironmentScopedModel):
    """Stock d'un item sur un point : jauge qualitative (niveau_stock) et suivi quantitatif
    optionnel. Une ligne par (point, item)."""

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

    # Véhicule : places en plus du conducteur.
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
    """Apport de matériel à une ligne de stock ; la quantité totale est la somme des
    contributions non RETIRE."""

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
    fournisseur_nom = EncryptedTextField(max_length=140, blank=True)

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
    # Intervenant logé pour une mission longue.
    INTERVENANT = "INTERVENANT", "Intervenant mobilisé (logement multi-jours)"
    AUTRE = "AUTRE", "Autre"


class RegistrePresence(EnvironmentScopedModel):
    """Registre de présence d'un point : qui est accueilli et depuis quand. nombre = taille du
    groupe ; présents = somme des lignes sans date_depart."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    point = models.ForeignKey(
        PointOperationnel,
        on_delete=models.CASCADE,
        related_name="registre_presences",
    )

    type_personne = models.CharField(max_length=30, choices=TypePersonneAccueillie.choices)

    nom = EncryptedTextField(max_length=255, blank=True)

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


class AffectationLogementIntervenant(EnvironmentScopedModel):
    """Réservation d'un logement (centre ou offre validée, exactement l'un des deux) pour un
    intervenant. Nouvelle ligne à chaque réaffectation : le logement actuel est la plus récente."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    intervenant = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="affectations_logement",
    )
    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, related_name="affectations_logement",
    )
    # CASCADE : un SET_NULL violerait la contrainte « exactement une cible ».
    point = models.ForeignKey(
        PointOperationnel, on_delete=models.CASCADE, null=True, blank=True,
        related_name="affectations_logement",
        help_text="Centre d'hébergement -- exclusif avec `offre`.",
    )
    offre = models.ForeignKey(
        "Offer", on_delete=models.CASCADE, null=True, blank=True,
        related_name="affectations_logement",
        help_text="Offre de particulier validée pour l'accueil d'intervenants -- exclusif avec `point`.",
    )
    affecte_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(point__isnull=False, offre__isnull=True)
                    | models.Q(point__isnull=True, offre__isnull=False)
                ),
                name="affectation_logement_point_xor_offre",
            ),
        ]

    def __str__(self) -> str:
        cible = self.point.nom if self.point_id else (self.offre.title if self.offre_id else "?")
        return f"Logement de {self.intervenant} pour {self.crise.name} : {cible}"


class EtatMateriel(models.TextChoices):
    DISPONIBLE = "DISPONIBLE", "Disponible"
    INDISPONIBLE = "INDISPONIBLE", "Indisponible (besoin de maintenance)"
    EN_REPARATION = "EN_REPARATION", "En réparation"
    HORS_SERVICE = "HORS_SERVICE", "Hors service"


class SuiviMaterielEvenement(EnvironmentScopedModel):
    """Historique d'état et de maintenance d'une offre de matériel ; l'état actuel est
    l'événement le plus récent. Pièces jointes via Document."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offre = models.ForeignKey("Offer", on_delete=models.CASCADE, related_name="suivi_evenements")

    etat = models.CharField(max_length=20, choices=EtatMateriel.choices)

    commentaire = models.TextField(blank=True, null=True)

    # Texte libre (pas d'annuaire de réparateurs).
    reparateur_nom = EncryptedTextField(max_length=255, blank=True, null=True)
    reparateur_contact = EncryptedTextField(max_length=255, blank=True, null=True)
    lieu_reparation = models.CharField(max_length=255, blank=True, null=True)
    date_reparation = models.DateField(null=True, blank=True)
    cout_reparation = models.PositiveIntegerField(
        null=True, blank=True, help_text="Coût en euros, montant entier (même convention que HebergementDetailsMixin.loyer_montant_*).",
    )

    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"{self.get_etat_display()} — {self.offre.title}"


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
    """« Je suis en sécurité » : auto-déclaration publique ou saisie par le secrétariat d'un
    centre. Aucune donnée de santé : regime_alimentaire_specifique est un simple indicateur. Ne
    pas ajouter de champ médical sans accord du porteur."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE,
        related_name="declarations_securite",
    )

    type_declarant = models.CharField(
        max_length=20, choices=TypeDeclarant.choices, default=TypeDeclarant.PERSONNE_SEULE,
    )

    # Où et comment la personne est en sécurité (type_declarant dit qui est concerné).
    situation = models.CharField(
        max_length=20, choices=SituationDeclarant.choices, default=SituationDeclarant.RELOGE,
    )

    nom_referent = EncryptedTextField(max_length=80)
    prenom_referent = EncryptedTextField(max_length=60)
    contact_referent = EncryptedTextField(
        max_length=255,
        help_text="Email ou téléphone de la personne qui se présente/déclare — elle-même pour "
                   "une personne seule, le référent désigné pour une famille ou un groupe.",
    )

    nombre_adultes = models.PositiveIntegerField(default=1)
    nombre_enfants = models.PositiveIntegerField(default=0)

    # Âges des enfants seulement, jamais de nom.
    ages_enfants = EncryptedJSONField(default=list, blank=True)

    # Optionnelle (inutile pour EN_CENTRE).
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    commune_code = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Code commune INSEE résolu à la saisie de l'adresse (autocomplete), même "
                   "usage qu'Information.commune_code.",
    )
    # Dénormalisés depuis commune_code pour le filtrage par zone.
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

    commentaire = EncryptedTextField(blank=True, null=True)

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


class RisqueMajeurType(models.Model):
    """Catalogue partagé et extensible des risques majeurs (chaque commune a sa propre liste).
    generalites : texte générique type DICRIM ; le local est dans RisqueCommunal."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=100, unique=True)
    generalites = models.TextField(blank=True, help_text="Description générique du risque, indépendante de la commune.")
    actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom


class RisqueCommunal(EnvironmentScopedModel):
    """Déclaration d'une institution sur un risque : état des lieux et enjeux locaux."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="risques_communaux")
    risque_type = models.ForeignKey(RisqueMajeurType, on_delete=models.PROTECT, related_name="declarations_communales")
    etat_des_lieux = models.TextField(blank=True)
    enjeux = models.TextField(blank=True)
    actif = models.BooleanField(default=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["institution", "risque_type"], name="uq_risque_communal_institution_type")]

    def __str__(self):
        return f"{self.risque_type.nom} / {self.institution.nom}"


class SourceSiteSensible(models.TextChoices):
    """D'où vient une ligne de SiteSensible. Chaque valeur correspond à un connecteur de
    core/opendata/, sauf SAISIE (ajout manuel par un agent)."""
    ANNUAIRE_EDUCATION = "ANNUAIRE_EDUCATION", "Annuaire de l'éducation nationale"
    FINESS = "FINESS", "FINESS (Agence du numérique en santé)"
    ICPE = "ICPE", "Installations classées (Géorisques)"
    EQUIPEMENTS_SPORTIFS = "EQUIPEMENTS_SPORTIFS", "Équipements sportifs (ministère des Sports)"
    SIRENE = "SIRENE", "Annuaire des entreprises (SIRENE / INSEE)"
    SAISIE = "SAISIE", "Saisie manuelle"


class CategorieSiteSensible(models.TextChoices):
    """Ce qu'est le site. Deux choses à ne pas confondre avec elle : son STATUT (proposé, retenu,
    écarté), et son rôle — `est_enjeu` / `est_ressource`, qui disent s'il faut le protéger, s'en
    servir, ou les deux."""
    ENSEIGNEMENT = "ENSEIGNEMENT", "Établissement d'enseignement"
    PETITE_ENFANCE = "PETITE_ENFANCE", "Accueil du jeune enfant"
    SOINS = "SOINS", "Structure de soins ou médico-sociale"
    INDUSTRIE = "INDUSTRIE", "Site industriel ou installation classée"
    # Les élevages sortent de la même API que les sites industriels, mais ne se planifient pas
    # pareil : la protection des animaux est une mission possible du plan de sauvegarde
    # (évacuation d'un cheptel, inondation, feu, coupure électrique longue qui arrête traite et
    # ventilation). Les mélanger aux usines les rendait invisibles.
    ELEVAGE = "ELEVAGE", "Élevage ou détention d'animaux"
    VETERINAIRE = "VETERINAIRE", "Soins aux animaux"
    HEBERGEMENT = "HEBERGEMENT", "Hébergement (hôtel, camping, village vacances)"
    RASSEMBLEMENT = "RASSEMBLEMENT", "Équipement recevant du public"
    MOYENS = "MOYENS", "Moyens et travaux (transport, engins, bâchage)"
    APPROVISIONNEMENT = "APPROVISIONNEMENT", "Approvisionnement (alimentation, carburant, repas)"
    FUNERAIRE = "FUNERAIRE", "Opérateur funéraire"
    AUTRE = "AUTRE", "Autre"


class StatutSiteSensible(models.TextChoices):
    """Décision de la mairie sur une proposition. PROPOSE est l'état de sortie de tout import :
    rien n'entre jamais directement au plan sans qu'un agent l'ait regardé."""
    PROPOSE = "PROPOSE", "Proposé — à vérifier"
    RETENU = "RETENU", "Retenu au plan de sauvegarde"
    ECARTE = "ECARTE", "Écarté"


class SiteSensible(EnvironmentScopedModel):
    """Enjeu du territoire à connaître avant la crise : école, EHPAD, site industriel, élevage,
    gymnase…

    Pré-alimenté depuis des bases publiques nationales (voir core/opendata/) et TOUJOURS déposé
    en PROPOSE : une base ouverte se trompe et vieillit (FINESS garde des pharmacies fermées
    depuis 2009, le recensement des équipements sportifs classe les écluses du canal de Nantes à
    Brest en « installation sportive »). La mairie reste seule juge de ce qui entre à son plan de
    sauvegarde — l'open data lui épargne la saisie, jamais la vérification.

    `attributs` conserve le brut utile de la source (statut Seveso, régime ICPE, public/privé,
    restauration, internat…) sans imposer une colonne par source : seules les notions communes à
    toutes les sources sont des champs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="sites_sensibles",
    )

    # Dénormalisé comme sur Habitation : permet de filtrer sans jointure, et de garder la trace
    # de la commune d'origine même si l'institution change de périmètre.
    commune_code = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    commune_nom = models.CharField(max_length=255, blank=True, null=True)

    source = models.CharField(
        max_length=25, choices=SourceSiteSensible.choices, default=SourceSiteSensible.SAISIE,
    )

    source_id = models.CharField(
        max_length=64, blank=True,
        help_text="Identifiant stable dans la source (UAI, n° FINESS, code AIOT, n° RES) : "
                  "permet de ré-importer sans dupliquer ni perdre la décision déjà prise.",
    )

    categorie = models.CharField(
        max_length=20, choices=CategorieSiteSensible.choices,
        default=CategorieSiteSensible.AUTRE,
    )

    nom = models.CharField(max_length=255)

    # Adresse d'établissement, jamais le domicile d'un particulier : pas de chiffrement,
    # contrairement à Habitation.adresse. Les sources qui diffusent des adresses personnelles
    # (assistantes maternelles) sont délibérément hors de ce paquet.
    # Chiffrée comme toute adresse du projet (§ 10.1). Même une liste d'enjeux communaux finit
    # par contenir des adresses de personnes : un exploitant en nom propre recensé via SIRENE
    # est enregistré chez lui. On ne stocke rien en clair, la règle ne souffre pas d'exception
    # « parce que c'est un établissement ».
    adresse = EncryptedTextField(blank=True, null=True)

    # Point utilisable par la carte et par la création d'un point opérationnel — vide pour une
    # personne en nom propre : des coordonnées GPS désignent son domicile aussi sûrement que
    # l'adresse. Les siennes vivent dans `donnees_personnelles`, chiffrées.
    location = gis_models.PointField(srid=4326, null=True, blank=True)

    telephone = models.CharField(max_length=30, blank=True, null=True)

    # Vrai quand la source désigne une personne physique et non une société (SIRENE : nature
    # juridique 1000, entrepreneur individuel). Ce qui change alors : l'adresse et les
    # coordonnées ne sortent de l'API que par l'action « dévoiler », qui laisse une ligne de
    # main courante, et le site ne peut pas devenir un point opérationnel — celui-ci est public.
    personne_physique = models.BooleanField(default=False)

    # Ce qu'on ne montre qu'après un dévoilement tracé : {"latitude": …, "longitude": …}.
    donnees_personnelles = EncryptedJSONField(default=dict, blank=True)

    effectif_estime = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Personnes présentes à estimer par la commune (élèves, résidents, salariés) : "
                  "aucune source ouverte ne le donne de façon fiable.",
    )

    attributs = models.JSONField(default=dict, blank=True)

    # Deux questions différentes, posées à deux moments différents de la crise : « qui est
    # menacé ? » et « avec quoi j'agis ? ». Deux booléens et non une catégorie, parce que les
    # cas qui comptent sont les deux à la fois : un camping, c'est 200 personnes à évacuer ET
    # 200 lits ; une ferme, c'est un cheptel à sauver ET un tracteur avec une cuve.
    # Pré-positionnés par le connecteur selon la catégorie, corrigeables par l'agent.
    est_enjeu = models.BooleanField(default=True)
    est_ressource = models.BooleanField(default=False)

    statut = models.CharField(
        max_length=10, choices=StatutSiteSensible.choices, default=StatutSiteSensible.PROPOSE,
    )

    commentaire = models.TextField(blank=True, null=True)

    valide_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sites_sensibles_valides",
    )

    # Rempli quand la commune transforme le site en point opérationnel (un gymnase retenu devient
    # le centre d'accueil qu'on ouvrira le jour J, nom, adresse et coordonnées déjà renseignés).
    # SET_NULL et pas CASCADE : supprimer un point ne doit pas effacer l'enjeu du territoire.
    point_operationnel = models.ForeignKey(
        "PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sites_sensibles",
    )

    # Date de la donnée source telle qu'annoncée par le producteur, pas la date d'import : c'est
    # elle qui dit à l'agent à quel point l'information peut être périmée.
    date_source = models.DateField(null=True, blank=True)

    date_import = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categorie", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "source", "source_id", "environment"],
                condition=~models.Q(source_id=""),
                name="uq_site_sensible_institution_source_id",
            )
        ]

    def __str__(self):
        return f"{self.nom} ({self.get_categorie_display()})"


class StatutImportOpenData(models.TextChoices):
    EN_COURS = "EN_COURS", "En cours"
    TERMINEE = "TERMINEE", "Terminé"
    ECHEC = "ECHEC", "Échec"


class ImportOpenData(EnvironmentScopedModel):
    """Dernier import d'une source ouverte pour une institution : date, résultat, erreur.

    Sert deux choses à l'écran : dire quand une source a été consultée pour la dernière fois (une
    base publique vieillit, l'agent doit savoir sur quoi il travaille), et porter l'état de
    l'import FINESS, qui tourne en Celery et peut durer une minute — l'état vit ici et pas dans le
    navigateur, pour que changer de page ne le perde pas (même raisonnement que
    TacheSimulationInondation)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="imports_open_data",
    )

    source = models.CharField(max_length=25, choices=SourceSiteSensible.choices)

    statut = models.CharField(
        max_length=10, choices=StatutImportOpenData.choices,
        default=StatutImportOpenData.EN_COURS,
    )

    # {"crees": 12, "mis_a_jour": 0, "inchanges": 2, "total": 14} — tel que rendu par
    # sites_sensibles.enregistrer_proposes.
    resultat = models.JSONField(default=dict, blank=True)

    erreur = models.TextField(blank=True, null=True)

    date_lancement = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "source", "environment"],
                name="uq_import_open_data_institution_source",
            )
        ]

    def __str__(self):
        return f"{self.get_source_display()} / {self.institution.nom} — {self.statut}"


class TypeVulnerabilite(models.Model):
    """Catalogue des besoins fonctionnels des personnes vulnérables (évacuation, alerte). Jamais
    de donnée de santé (RGPD art. 9) : catalogue à cocher, volontairement sans notes libres."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=150, unique=True)
    description = models.TextField(
        blank=True,
        help_text="Description fonctionnelle/opérationnelle uniquement -- jamais un diagnostic médical.",
    )
    actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom


class ModeConsentementVulnerabilite(models.TextChoices):
    VOLONTAIRE = "VOLONTAIRE", "Démarche volontaire de la personne ou de son représentant légal"
    TIERS_AVEC_ACCORD = "TIERS_AVEC_ACCORD", "Signalée par un tiers, accord de la personne recueilli"
    TIERS_SANS_ACCORD_FORMEL = "TIERS_SANS_ACCORD_FORMEL", "Signalée par un tiers, accord pas encore recueilli -- à confirmer"


class PersonneVulnerable(EnvironmentScopedModel):
    """Registre communal des personnes vulnérables (art. L121-6-1 du CASF), permanent, radié par
    actif=False. Donnée très sensible : accès uniquement via core/vulnerabilites.py.
    Identifiants chiffrés."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution_declarante = models.ForeignKey(
        "Institution", on_delete=models.PROTECT, related_name="personnes_vulnerables",
    )

    commune_code = models.CharField(
        max_length=10,
        help_text="Dénormalisé (même convention que Habitation.commune_code) pour permettre le "
                   "filtrage par compétence/délégation sans jointure.",
    )
    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="personnes_vulnerables",
        help_text="Quartier/secteur optionnel (catalogue Zone de l'institution déclarante).",
    )

    nom = EncryptedTextField()
    prenom = EncryptedTextField()
    adresse = EncryptedTextField()
    telephone = EncryptedTextField(null=True, blank=True)

    categories = models.ManyToManyField(
        TypeVulnerabilite, related_name="personnes", blank=True,
        help_text="Catégories fonctionnelles cochées -- voir TypeVulnerabilite.__doc__ (jamais de diagnostic).",
    )

    contact_aidant_nom = EncryptedTextField(null=True, blank=True)
    contact_aidant_telephone = EncryptedTextField(null=True, blank=True)

    mode_consentement = models.CharField(
        max_length=30, choices=ModeConsentementVulnerabilite.choices,
    )
    demandeur_consentement = models.CharField(
        max_length=255, blank=True,
        help_text="Texte libre (pas de FK) : souvent un tiers non-institutionnel (voisin, CCAS "
                   "cité par son nom) -- une FK obligerait à créer un faux contact institutionnel.",
    )
    date_consentement = models.DateField(null=True, blank=True)

    actif = models.BooleanField(
        default=True,
        help_text="False = radiée (décès, déménagement, retrait du consentement) -- jamais "
                   "supprimée physiquement, même patron que RisqueCommunal.actif.",
    )

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="personnes_vulnerables_creees",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [models.Index(fields=["commune_code"])]

    def __str__(self):
        return f"Personne vulnérable ({self.commune_code})"


class StatutAffectation(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation"
    EN_VALIDATION = "EN_VALIDATION", "En attente de validation par le régulateur"
    CONFIRME = "CONFIRME", "Confirmé"
    DECLINE = "DECLINE", "Décliné"


class AffectationPointBenevole(EnvironmentScopedModel):
    """Recrutement d'un bénévole sur un point depuis son offre, confirmé par lien email sans
    compte."""

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

    # ── Traçabilité des consultations (21/10/2026, voir core/tracabilite.py) ───────────────
    # Retrouver, à partir d'une fiche, qui l'a vue, quand et comment : les champs ci-dessous
    # sont remplis par AuditTraceMiddleware d'après la réponse elle-même.

    class Exposition(models.TextChoices):
        FICHE = "FICHE", "Fiche ouverte"
        LISTE = "LISTE", "Liste (avec coordonnées)"
        LISTE_SANS_COORDONNEES = "LISTE_SANS_COORDONNEES", "Liste (sans coordonnées)"
        EXPORT = "EXPORT", "Export"

    class Perimetre(models.TextChoices):
        CRISE = "CRISE", "Crise"
        MULTI = "MULTI", "Plusieurs crises"
        GENERAL = "GENERAL", "Fonctionnement général"

    # Identifiants des fiches renvoyées par la requête (toutes celles d'une liste, la fiche
    # seule, ou celles d'un export) : « qui a vu cette fiche » = objets_ids @> [id]. Une seule
    # ligne par requête, même pour une liste de plusieurs milliers de fiches.
    objets_ids = ArrayField(models.UUIDField(), null=True, blank=True)
    exposition = models.CharField(max_length=24, choices=Exposition.choices, null=True, blank=True)
    # Rattachement : une crise (champ `crise`), plusieurs, ou le fonctionnement général.
    # Null = non déterminable (historique antérieur au 21/10/2026, lectures de listes surtout).
    perimetre = models.CharField(max_length=10, choices=Perimetre.choices, null=True, blank=True)
    # Ponts radio, satellites, automates (voir tracabilite.est_compte_systeme) : posé à
    # l'écriture pour que la case « Masquer les comptes système » reste servie par un index.
    compte_systeme = models.BooleanField(default=False)
    # Termes et filtres de recherche de la requête (sans secrets ni pagination).
    recherche = models.JSONField(null=True, blank=True)

    class Meta:

        ordering = [
            "-date_action"
        ]

        # Table la plus volumineuse du projet (2,5 M de lignes / 570 Mo au 21/10/2026, alimentée
        # à chaque requête /api/ par AuditTraceMiddleware) : sans index, TOUTE lecture de la main
        # courante faisait un parcours complet de la table (523 Mo lus par affichage de page,
        # mesuré), ce qui écrasait au passage le cache disque de toute l'application.
        # `environment` en tête (et pas seulement `-date_action`) : la zone DEMO ne pèse que
        # 0,2 % des lignes, sans elle un affichage en DEMO parcourrait tout l'index avant de
        # trouver ses 4 000 lignes. Un index par colonne filtrable de la page Main courante,
        # toujours terminé par `-date_action` qui est le tri imposé (voir Meta.ordering) :
        # Postgres sert alors filtre + tri + LIMIT par le seul index.
        indexes = [
            models.Index(fields=["environment", "-date_action"], name="auditlog_env_date_idx"),
            models.Index(fields=["environment", "action", "-date_action"], name="auditlog_env_action_idx"),
            models.Index(fields=["environment", "utilisateur", "-date_action"], name="auditlog_env_user_idx"),
            models.Index(fields=["environment", "institution", "-date_action"], name="auditlog_env_inst_idx"),
            # Sert deux usages : l'historique d'une fiche précise (?objet_type=&objet_id=, le
            # widget présent sur de nombreux écrans — 550 ms de parcours complet avant) et, par
            # son seul préfixe objet_type, le filtre « Type d'objet » de la main courante.
            models.Index(fields=["objet_type", "objet_id", "environment", "-date_action"], name="auditlog_objet_idx"),
            # Traçabilité des consultations (migration 0210) : « qui a vu cette fiche »,
            # filtres crise / périmètre / adresse IP (plages comprises : Postgres sert
            # `adresse_ip <<= réseau` par cet index), case « Masquer les comptes système » et
            # recherche dans les termes cherchés -- ces deux derniers en index partiels, qui ne
            # contiennent que les lignes concernées.
            GinIndex(fields=["objets_ids"], name="auditlog_objets_gin"),
            # « Qui a vu cette fiche » cherche objet_id OU objets_ids : sans index sur objet_id
            # seul (auditlog_objet_idx commence par objet_type), Postgres parcourait toute la
            # table -- 1,3 s pour une fiche rarement vue, 0,3 ms avec (mesuré le 21/10/2026).
            models.Index(fields=["objet_id"], name="auditlog_objet_id_idx"),
            models.Index(fields=["environment", "crise", "-date_action"], name="auditlog_env_crise_idx"),
            models.Index(fields=["environment", "perimetre", "-date_action"], name="auditlog_env_perim_idx"),
            models.Index(fields=["environment", "adresse_ip", "-date_action"], name="auditlog_env_ip_idx"),
            models.Index(fields=["environment", "-date_action"], name="auditlog_humains_idx",
                         condition=models.Q(compte_systeme=False)),
            models.Index(fields=["environment", "-date_action"], name="auditlog_recherche_idx",
                         condition=models.Q(recherche__isnull=False)),
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

    # Zone de l'institution couverte par ce contact (optionnelle).
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


class MeshCoreConnexionType(models.TextChoices):
    TCP = "TCP", "TCP (réseau)"
    SERIE = "SERIE", "Série (USB)"
    BLE = "BLE", "Bluetooth (BLE)"


class CompagnonMeshCore(EnvironmentScopedModel):
    """Companion MeshCore servant de passerelle, piloté par meshcore-bridge (pas un nœud
    personnel : voir NoeudMeshUtilisateur). principal = utilisé par défaut pour les envois."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="compagnons_meshcore",
    )

    nom = models.CharField(max_length=100)

    connexion_type = models.CharField(max_length=10, choices=MeshCoreConnexionType.choices)

    # Un seul groupe de champs est renseigné selon connexion_type.
    tcp_host = models.CharField(max_length=255, null=True, blank=True)
    tcp_port = models.PositiveIntegerField(null=True, blank=True, default=5000)
    serie_device = models.CharField(max_length=255, null=True, blank=True, help_text="ex: /dev/ttyUSB0")
    ble_adresse = models.CharField(max_length=64, null=True, blank=True)

    pubkey_hex = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Renseigné par le service-pont après la première connexion réussie.",
    )

    # Position saisie à la main : carte, et choix futur du companion le plus proche.
    location = gis_models.PointField(srid=4326, null=True, blank=True)

    principal = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    # Étiquette régionale communautaire (ex. « fr-naq »), sans existence dans le protocole ;
    # utilisée par core.routage_mesh.
    region_tag = models.CharField(max_length=20, blank=True)

    derniere_connexion = models.DateTimeField(null=True, blank=True)
    dernier_etat = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Rapporté par le service-pont : CONNECTE / DECONNECTE / ERREUR.",
    )
    derniere_erreur = models.TextField(null=True, blank=True)

    # Batterie du companion (valeur brute du firmware, unité non confirmée, probablement mV).
    derniere_batterie_niveau = models.PositiveIntegerField(null=True, blank=True)
    derniere_batterie_date = models.DateTimeField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} ({self.connexion_type})"


class NoeudMeshUtilisateur(EnvironmentScopedModel):
    """Associe la clé publique d'un nœud de terrain à un compte, pour identifier l'expéditeur."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    utilisateur = models.ForeignKey("User", on_delete=models.CASCADE, related_name="noeuds_meshcore")

    pubkey_hex = models.CharField(max_length=64, unique=True)

    nom_noeud = EncryptedTextField(max_length=100, blank=True)

    actif = models.BooleanField(default=True)

    date_association = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.utilisateur.email} — {self.pubkey_hex[:12]}…"


class DirectionMessageMesh(models.TextChoices):
    ENTRANT = "ENTRANT", "Reçu du mesh"
    SORTANT = "SORTANT", "Envoyé vers le mesh"


class StatutMessageMesh(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente d'envoi"
    ENVOYE = "ENVOYE", "Envoyé"
    RECU = "RECU", "Reçu"
    ECHEC = "ECHEC", "Échec"


class ProtocoleMesh(models.TextChoices):
    MESHCORE = "MESHCORE", "MeshCore"
    MESHTASTIC = "MESHTASTIC", "Meshtastic"


class AlerteMeshSOS(EnvironmentScopedModel):
    """Message mesh entrant suspecté d'urgence (mot-clé SOS ou canal d'urgence). Ne crée jamais
    de demande automatiquement : notifie les administrateurs pour vérification humaine."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    protocole = models.CharField(max_length=10, choices=ProtocoleMesh.choices)

    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="alertes_sos_mesh",
    )

    # Vide pour un message privé (DM) -- un canal seulement.
    canal_nom = models.CharField(max_length=100, null=True, blank=True)

    # Clé d'anti-rafale (pas une FK : l'expéditeur n'est pas toujours connu).
    expediteur_identifiant = models.CharField(max_length=64, null=True, blank=True)
    # Chiffrés : un message peut contenir nom, position ou blessure.
    expediteur_nom = EncryptedTextField(max_length=100, blank=True)
    contenu = EncryptedTextField()
    mot_cle_detecte = models.CharField(max_length=50)

    notification_envoyee = models.BooleanField(default=False)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SOS mesh « {self.mot_cle_detecte} » ({self.protocole}, {self.date_creation:%d/%m %H:%M})"


class MessageMeshLog(EnvironmentScopedModel):
    """Journal des DM MeshCore (cloisonnement par equipe)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshCore, on_delete=models.CASCADE, related_name="messages")

    direction = models.CharField(max_length=10, choices=DirectionMessageMesh.choices)

    contact_pubkey_hex = models.CharField(
        max_length=64,
        help_text="Clé publique du correspondant (émetteur si entrant, destinataire si sortant).",
    )

    expediteur = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_meshcore_envoyes",
        help_text="Résolu via NoeudMeshUtilisateur quand connu.",
    )

    # Équipe de l'expéditeur figée à la réception : seuls son leader et son régulateur voient le
    # message.
    equipe = models.ForeignKey(
        "Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_meshcore",
    )

    contenu = models.TextField()

    statut = models.CharField(max_length=12, choices=StatutMessageMesh.choices, default=StatutMessageMesh.EN_ATTENTE)

    erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_envoi = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"[{self.direction}] {self.contact_pubkey_hex[:12]}… — {self.statut}"


class TypeCommandeMeshCore(models.TextChoices):
    ADVERT = "ADVERT", "Advert (annonce de présence)"
    FLOOD_ADVERT = "FLOOD_ADVERT", "Flood advert (annonce propagée)"


class StatutCommandeMeshCore(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    EXECUTEE = "EXECUTEE", "Exécutée"
    ECHEC = "ECHEC", "Échec"


class CommandeMeshCore(EnvironmentScopedModel):
    """Commande pour le companion du pont (ex. annonce), relevée périodiquement par le pont. Ne
    pilote pas un relais distant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    compagnon = models.ForeignKey(CompagnonMeshCore, on_delete=models.CASCADE, related_name="commandes")
    type_commande = models.CharField(max_length=20, choices=TypeCommandeMeshCore.choices)
    statut = models.CharField(max_length=12, choices=StatutCommandeMeshCore.choices, default=StatutCommandeMeshCore.EN_ATTENTE)
    erreur = models.TextField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_execution = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.get_type_commande_display()} — {self.compagnon.nom} ({self.statut})"


class StatutTraceroute(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente d'exécution"
    TERMINE = "TERMINE", "Terminé"
    ECHEC = "ECHEC", "Échec ou sans réponse"


class TracerouteMeshCore(EnvironmentScopedModel):
    """Traceroute MeshCore en diffusion : répéteurs traversés et SNR par saut. Chaque ligne est
    un instantané."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshCore, on_delete=models.CASCADE, related_name="traceroutes")

    # tag est un entier 32 bits non signé : dépasse PositiveIntegerField.
    tag = models.PositiveBigIntegerField(null=True, blank=True)

    statut = models.CharField(max_length=10, choices=StatutTraceroute.choices, default=StatutTraceroute.EN_ATTENTE)

    # [{"hash": "..", "snr": float}, ..., {"snr": float}] -- le dernier élément (sans "hash")
    # est la réception par notre propre companion, voir parsePacketPayload/TRACE_DATA côté lib.
    chemin = models.JSONField(null=True, blank=True)

    erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_reponse = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Traceroute {self.compagnon_id} ({self.statut})"


class RelaisMeshCore(EnvironmentScopedModel):
    """Répéteur MeshCore, importé automatiquement par synchroniser_contacts (par pubkey_hex) ou
    saisi à la main."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="relais_meshcore",
    )

    nom = models.CharField(max_length=100)

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    # Unique : l'import automatique fait un get_or_create par pubkey_hex.
    pubkey_hex = models.CharField(max_length=64, null=True, blank=True, unique=True)

    actif = models.BooleanField(default=True)

    commentaire = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nom


class CanalMeshCore(EnvironmentScopedModel):
    """Canal MeshCore (clé partagée), pour la coordination, jamais pour du contenu sensible.
    equipe en fait le canal privé d'une équipe (clé distribuée par DM). Le slot qu'il occupe sur
    chaque companion du pont est dans ProvisionCanalMeshCore ; chaque membre configure le sien."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="canaux_meshcore",
    )

    crise = models.ForeignKey(
        "Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="canaux_meshcore",
    )

    equipe = models.OneToOneField(
        "Team", on_delete=models.CASCADE, null=True, blank=True, related_name="canal_meshcore",
    )

    nom = models.CharField(max_length=100)

    # Clé de 16 octets, jamais renvoyée par l'API (write_only).
    cle_partagee_hex = models.CharField(max_length=64, null=True, blank=True)

    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def derive_cle_publique(nom: str) -> str:
        """Clé d'un canal public « #nom » : sha256(nom)[:16], comme le firmware."""
        return hashlib.sha256(nom.encode("utf-8")).hexdigest()[:32]

    # Clé du canal « Public » préconfiguré (slot 0) sur tout appareil MeshCore, publiée par le
    # projet : permet de le reconnaître automatiquement.
    SECRET_PUBLIC_PAR_DEFAUT = "8b3387e9c5cdea6ac9e5edbaa115cd72"

    @staticmethod
    def chan_hash_pour_secret(secret_hex: str) -> str:
        """chan_hash annoncé sur l'air pour un secret : sha256(secret)[0]."""
        return hashlib.sha256(bytes.fromhex(secret_hex)).hexdigest()[:2]

    def __str__(self):
        return self.nom


class ProvisionCanalMeshCore(models.Model):
    """Slot occupé par un canal sur UN companion (set_channel fait par son pont). Une ligne par
    (canal, companion) : le même canal a en général un slot différent sur chaque radio.

    Remplace les champs uniques CanalMeshCore.compagnon/canal_idx (22/10/2026) : avec deux
    companions (Bureau sur .114, satellite de la Loire), chaque pont voyait le canal noté sur
    l'autre radio, le réinstallait sur la sienne et s'en déclarait propriétaire -- environ 200
    réinstallations par heure et par radio depuis le 20/10, et des messages envoyés avec le slot
    de l'autre radio, donc sur le mauvais canal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    canal = models.ForeignKey("CanalMeshCore", on_delete=models.CASCADE, related_name="provisions")
    compagnon = models.ForeignKey("CompagnonMeshCore", on_delete=models.CASCADE, related_name="provisions_canaux")
    canal_idx = models.PositiveSmallIntegerField()

    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['canal', 'compagnon'], name='provision_canal_compagnon_unique'),
            models.UniqueConstraint(fields=['compagnon', 'canal_idx'], name='provision_slot_compagnon_unique'),
        ]

    def __str__(self):
        return f"{self.canal_id} sur le slot {self.canal_idx} de {self.compagnon_id}"


class CanalMeshCoreDetecte(EnvironmentScopedModel):
    """Canal capté sur l'air mais inconnu du companion (ancienne clé, canal tiers) : signalé en
    lecture seule. Une ligne par (compagnon, chan_hash)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(
        "CompagnonMeshCore", on_delete=models.CASCADE, related_name="canaux_detectes",
    )

    chan_hash = models.CharField(max_length=2)

    premiere_vue = models.DateTimeField(auto_now_add=True)
    derniere_vue = models.DateTimeField(auto_now=True)
    nombre_paquets = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = [('compagnon', 'chan_hash')]

    def __str__(self):
        return f"Canal détecté #{self.chan_hash} ({self.compagnon_id})"


class CanalMeshCoreObsolete(EnvironmentScopedModel):
    """Slot de canal à libérer après rotation de clé, après 48 h de grâce pour les messages en
    vol (libérer = set_channel avec un nom vide)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    canal = models.ForeignKey(
        "CanalMeshCore", on_delete=models.CASCADE, related_name="anciens_slots",
    )
    compagnon = models.ForeignKey(
        "CompagnonMeshCore", on_delete=models.CASCADE, related_name="slots_a_liberer",
    )
    canal_idx = models.PositiveSmallIntegerField()

    date_creation = models.DateTimeField(auto_now_add=True)
    supprimer_apres = models.DateTimeField()
    supprime = models.BooleanField(default=False)

    def __str__(self):
        return f"Slot {self.canal_idx} de {self.compagnon_id} à libérer après {self.supprimer_apres}"


class SalonMatrixEquipe(EnvironmentScopedModel):
    """Salon Matrix privé d'une équipe, activé à la demande
    (TeamViewSet.provisionner_salon_matrix). room_id vide tant que matrix-bridge ne l'a pas
    créé ; les membres sont ensuite resynchronisés en continu."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    equipe = models.OneToOneField(
        "Team", on_delete=models.CASCADE, related_name="salon_matrix",
    )

    room_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Identifiant Matrix du salon (ex: !abc123:matrix.assista-crise.local), posé par le pont à la création.",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    derniere_synchronisation = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Salon Matrix de {self.equipe.name}"


class TypeSalonInstitution(models.TextChoices):
    """PERMANENTS : personnel de l'institution ; BENEVOLES : membres de ses équipes actives."""
    PERMANENTS = "PERMANENTS", "Permanents"
    BENEVOLES = "BENEVOLES", "Bénévoles mobilisés"


class SalonMatrixInstitution(EnvironmentScopedModel):
    """Salons Matrix généraux d'une institution (permanents, bénévoles mobilisés), dont la
    composition est recalculée en continu par matrix-bridge."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="salons_matrix",
    )

    type = models.CharField(max_length=15, choices=TypeSalonInstitution.choices)

    room_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Identifiant Matrix du salon, posé par le pont à la création.",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    derniere_synchronisation = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institution', 'type'], name='unique_salon_matrix_institution_type'),
        ]

    def __str__(self):
        return f"Salon Matrix {self.get_type_display()} de {self.institution.nom}"


class HistoriquePositionUtilisateur(EnvironmentScopedModel):
    """Trace d'un partage de position live dans Element (MSC3489), alimentée par matrix-bridge :
    permet de rejouer un trajet."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="historique_positions_matrix")
    location = gis_models.PointField(srid=4326)
    horodatage = models.DateTimeField()

    class Meta:
        ordering = ["-horodatage"]
        indexes = [models.Index(fields=["utilisateur", "-horodatage"])]

    def __str__(self):
        return f"Position de {self.utilisateur} à {self.horodatage}"


class MessageCanalMeshCore(EnvironmentScopedModel):
    """Message posté sur un canal partagé — visibilité alignée sur le canal lui-même
    (institution/crise), pas de cloisonnement par équipe contrairement à MessageMeshLog."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    canal = models.ForeignKey(CanalMeshCore, on_delete=models.CASCADE, related_name="messages")

    direction = models.CharField(max_length=10, choices=DirectionMessageMesh.choices)

    expediteur = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_canal_meshcore_envoyes",
    )

    contact_pubkey_hex = models.CharField(max_length=64, null=True, blank=True)

    contenu = models.TextField()

    statut = models.CharField(max_length=12, choices=StatutMessageMesh.choices, default=StatutMessageMesh.EN_ATTENTE)

    erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.canal.nom}] {self.contenu[:40]}"


class TypeContactMeshCore(models.TextChoices):
    """Miroir de AdvType côté firmware MeshCore (packets.py) — valeurs entières d'origine
    conservées en commentaire pour retrouver la correspondance."""
    INCONNU = "INCONNU", "Inconnu"          # 0x00 NONE
    COMPANION = "COMPANION", "Companion"     # 0x01 CHAT
    REPEATER = "REPEATER", "Répéteur"        # 0x02 REPEATER
    ROOM = "ROOM", "Room server"             # 0x03 ROOM
    SENSOR = "SENSOR", "Capteur"             # 0x04 SENSOR


class ContactMeshCore(EnvironmentScopedModel):
    """Contact du répertoire d'un companion, synchronisé par le pont (jamais saisi à la main)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshCore, on_delete=models.CASCADE, related_name="contacts")

    pubkey_hex = models.CharField(max_length=64)

    nom = EncryptedTextField(max_length=100, blank=True)

    type_contact = models.CharField(max_length=12, choices=TypeContactMeshCore.choices, default=TypeContactMeshCore.INCONNU)

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    dernier_advert = models.DateTimeField(null=True, blank=True)

    # Nombre de sauts vers ce contact (None = aucun chemin connu, différent de 0) ; routage_mesh
    # préfère le moins de sauts.
    nombre_sauts = models.PositiveSmallIntegerField(null=True, blank=True)

    # Étiquette régionale assignée à la main, repli du routage.
    region_tag = models.CharField(max_length=20, blank=True)

    # Télémétrie relevée pendant une mission EN_COURS ; jamais effacée par une valeur absente.
    tension_batterie_v = models.FloatField(null=True, blank=True, help_text="Volts (canal LPP \"voltage\").")
    niveau_batterie_pct = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Pourcentage (canal LPP \"percentage\").")
    derniere_telemetrie = models.DateTimeField(null=True, blank=True)

    date_synchronisation = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["compagnon", "pubkey_hex"], name="uq_contact_meshcore_compagnon_pubkey"),
        ]

    def __str__(self):
        return f"{self.nom or self.pubkey_hex[:12]} ({self.type_contact})"


class MeshtasticConnexionType(models.TextChoices):
    MQTT = "MQTT", "Broker MQTT (réseau tiers, ex: Gaulix)"
    # Appareil réel joint en TCP (port 4403) via la lib meshtastic ; usage hors ligne.
    TCP = "TCP", "Connexion locale directe (réseau, sans internet)"
    # Appareil branché en USB sur l'hôte du pont (satellite).
    SERIE = "SERIE", "Connexion série (USB, sans internet)"


class CompagnonMeshtastic(EnvironmentScopedModel):
    """Nœud Meshtastic : logiciel via un broker MQTT tiers (node_num choisi par nous,
    chiffrement réimplémenté dans meshtastic-bridge/crypto.py) ou appareil réel en TCP/série
    (géré par son firmware)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="compagnons_meshtastic",
    )

    # Satellite qui a déclaré ce companion (enregistrer_depuis_satellite) : la radio est branchée
    # sur CETTE machine, seul son pont peut l'ouvrir. Vide = companion du central (MQTT, TCP...).
    # Voir CompagnonMeshtasticViewSet.actifs_avec_identifiants.
    satellite = models.ForeignKey(
        "Satellite", on_delete=models.SET_NULL, null=True, blank=True, related_name="compagnons_meshtastic",
    )

    nom = models.CharField(max_length=100)

    connexion_type = models.CharField(max_length=10, choices=MeshtasticConnexionType.choices, default=MeshtasticConnexionType.MQTT)
    tcp_host = models.CharField(max_length=255, null=True, blank=True, help_text="IP/hostname du vrai appareil (mode TCP local uniquement).")
    tcp_port = models.PositiveIntegerField(null=True, blank=True, default=4403)
    serie_device = models.CharField(max_length=255, null=True, blank=True, help_text="ex: /dev/ttyUSB0 (mode SERIE uniquement).")

    node_num = models.PositiveBigIntegerField(
        unique=True,
        help_text="Identifiant 32 bits de cette identité logicielle sur le mesh Meshtastic (choisi à la création, pas dérivé d'un matériel).",
    )
    long_name = models.CharField(max_length=40, blank=True)
    short_name = models.CharField(max_length=4, blank=True)

    broker_host = models.CharField(max_length=255, default="mqtt.gaulix.fr")
    broker_port = models.PositiveIntegerField(default=1883)
    # Racine de topic du réseau relayé (Gaulix : « Traitement/msh/EU_868 », observé sur leur
    # broker).
    topic_racine = models.CharField(max_length=100, default="Traitement/msh/EU_868")

    mqtt_username = models.CharField(max_length=100, blank=True)
    # write_only côté serializer (comme x25519_private_key_hex) — jamais renvoyé en clair par
    # l'API une fois enregistré. Vide = pas d'authentification (cas de certains brokers publics).
    mqtt_password = models.CharField(max_length=255, blank=True)
    mqtt_use_tls = models.BooleanField(default=False)

    # Fermé par défaut : Gaulix ne relaie de façon fiable que le clair ; tant que ce n'est pas
    # coché, le pont envoie en clair.
    chiffrement_supporte = models.BooleanField(
        default=False,
        help_text="Décoché par défaut (cas Gaulix) : le pont force alors l'envoi en clair pour "
                   "ce broker, quel que soit le canal/la clé configurés.",
    )

    principal = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    # Paire X25519 générée à la création ; la clé privée n'est jamais exposée par l'API.
    x25519_private_key_hex = models.CharField(max_length=64, blank=True, editable=False)

    derniere_connexion = models.DateTimeField(null=True, blank=True)
    dernier_etat = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Rapporté par le service-pont : CONNECTE / DECONNECTE / ERREUR.",
    )
    derniere_erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.x25519_private_key_hex:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            cle_privee = X25519PrivateKey.generate()
            self.x25519_private_key_hex = cle_privee.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            ).hex()
        super().save(*args, **kwargs)

    @property
    def x25519_public_key_hex(self):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        cle_privee = X25519PrivateKey.from_private_bytes(bytes.fromhex(self.x25519_private_key_hex))
        return cle_privee.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        ).hex()

    def __str__(self):
        return f"{self.nom} (#{self.node_num:08x})"


class CanalMeshtastic(EnvironmentScopedModel):
    """Canal Meshtastic. nom doit correspondre exactement au canal des appareils (il compose le
    topic MQTT). psk_hex : vide = clair, 32/64 hex = AES128/256, ou un octet 01-0A = PSK par
    défaut du firmware. Jamais renvoyée par l'API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="canaux_meshtastic",
    )
    crise = models.ForeignKey(
        "Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="canaux_meshtastic",
    )
    equipe = models.OneToOneField(
        "Team", on_delete=models.CASCADE, null=True, blank=True, related_name="canal_meshtastic",
    )

    nom = models.CharField(max_length=100)
    psk_hex = models.CharField(max_length=64, null=True, blank=True)

    compagnon = models.ForeignKey(
        CompagnonMeshtastic, on_delete=models.SET_NULL, null=True, blank=True, related_name="canaux",
    )

    # Canal utilisé pour le topic MQTT d'un DM PKI (sans rôle cryptographique).
    principal = models.BooleanField(default=False)

    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nom


class ContactMeshtastic(EnvironmentScopedModel):
    """Nœud Meshtastic découvert passivement en écoutant le MQTT (paquets NodeInfo/Position
    décodés — jamais saisi à la main), répertoire brut équivalent à ContactMeshCore."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshtastic, on_delete=models.CASCADE, related_name="contacts")

    node_num = models.PositiveBigIntegerField()

    long_name = EncryptedTextField(max_length=40, blank=True)
    short_name = EncryptedTextField(max_length=4, blank=True)
    hardware_model = models.CharField(max_length=40, null=True, blank=True)
    # Clé publique annoncée par ce nœud, nécessaire aux DM chiffrés PKI.
    public_key_hex = models.CharField(max_length=64, blank=True)

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    dernier_advert = models.DateTimeField(null=True, blank=True)

    date_synchronisation = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["compagnon", "node_num"], name="uq_contact_meshtastic_compagnon_node_num"),
        ]

    def __str__(self):
        return f"{self.long_name or self.short_name or format(self.node_num, '08x')}"


class NoeudUtilisateurMeshtastic(EnvironmentScopedModel):
    """Correspondance entre un node_num Meshtastic de terrain et un compte utilisateur
    assista-crise, miroir de NoeudMeshUtilisateur (MeshCore)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    utilisateur = models.ForeignKey("User", on_delete=models.CASCADE, related_name="noeuds_meshtastic")

    node_num = models.PositiveBigIntegerField(unique=True)

    nom_noeud = EncryptedTextField(max_length=100, blank=True)

    actif = models.BooleanField(default=True)

    date_association = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.utilisateur.email} — {self.node_num:08x}"


class MessageMeshtasticLog(EnvironmentScopedModel):
    """Journal des DM Meshtastic, chiffrés avec la PSK du canal (pas encore de PKC)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshtastic, on_delete=models.CASCADE, related_name="messages")

    canal = models.ForeignKey(
        CanalMeshtastic, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_dm",
        help_text="Canal dont la PSK a servi à chiffrer ce DM.",
    )

    direction = models.CharField(max_length=10, choices=DirectionMessageMesh.choices)

    contact_node_num = models.PositiveBigIntegerField(
        help_text="Node num du correspondant (émetteur si entrant, destinataire si sortant).",
    )

    expediteur = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_meshtastic_envoyes",
        help_text="Résolu via NoeudUtilisateurMeshtastic quand connu.",
    )

    equipe = models.ForeignKey(
        "Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_meshtastic",
    )

    contenu = models.TextField()

    statut = models.CharField(max_length=12, choices=StatutMessageMesh.choices, default=StatutMessageMesh.EN_ATTENTE)

    erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_envoi = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"[{self.direction}] {self.contact_node_num:08x} — {self.statut}"


class MessageCanalMeshtastic(EnvironmentScopedModel):
    """Message posté sur un canal Meshtastic partagé — miroir de MessageCanalMeshCore."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    canal = models.ForeignKey(CanalMeshtastic, on_delete=models.CASCADE, related_name="messages")

    direction = models.CharField(max_length=10, choices=DirectionMessageMesh.choices)

    expediteur = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_canal_meshtastic_envoyes",
    )

    # Companion qui doit envoyer ce message, quand plusieurs servent le même canal (sinon ils se
    # disputent la file). None = premier disponible.
    compagnon = models.ForeignKey(
        "CompagnonMeshtastic", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_canal_cibles",
    )

    contact_node_num = models.PositiveBigIntegerField(null=True, blank=True)

    contenu = models.TextField()

    statut = models.CharField(max_length=12, choices=StatutMessageMesh.choices, default=StatutMessageMesh.EN_ATTENTE)

    erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.canal.nom}] {self.contenu[:40]}"


class ProfilSatellite(models.TextChoices):
    GW = "GW", "Passerelle uniquement"
    FULL = "FULL", "Suite complète"


class StatutEnrolementSatellite(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de validation"
    APPROUVE = "APPROUVE", "Approuvé"
    REVOQUE = "REVOQUE", "Révoqué"


class JetonEnrolementSatellite(EnvironmentScopedModel):
    """Jeton court à usage unique pour l'enrôlement d'un satellite. Les identifiants durables ne
    sont créés qu'après validation par un administrateur."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="jetons_enrolement_satellite",
    )

    jeton = models.CharField(max_length=64, unique=True)

    # Profil choisi par l'administrateur en générant le jeton (installation en une commande,
    # 20/10/2026) : le satellite n'a plus à le connaître ni à le ressaisir.
    profil = models.CharField(max_length=4, choices=ProfilSatellite.choices, default=ProfilSatellite.GW)

    expiration = models.DateTimeField()

    utilise = models.BooleanField(default=False)

    cree_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Jeton enrôlement {self.institution.nom} ({'utilisé' if self.utilise else 'en attente'})"


class Satellite(EnvironmentScopedModel):
    """Boîtier sur site (Raspberry Pi) : profil GW (pont radio) ou FULL (instance hors ligne).
    Le satellite initie toujours la connexion. L'état Actif/Inactif/Perdu est dérivé de
    dernier_contact à la lecture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="satellites")

    nom = models.CharField(max_length=100)

    profil = models.CharField(max_length=4, choices=ProfilSatellite.choices)

    statut_enrolement = models.CharField(
        max_length=12, choices=StatutEnrolementSatellite.choices,
        default=StatutEnrolementSatellite.EN_ATTENTE,
    )

    # Compte de service propre à ce satellite, créé à la validation, authentifié en JWT.
    compte_service = models.OneToOneField(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="satellite",
    )

    dernier_contact = models.DateTimeField(null=True, blank=True)

    version_logicielle = models.CharField(max_length=50, blank=True)

    # Secret remis au satellite à l'enrôlement (haché ici, jamais en clair) : lui permet de
    # récupérer SEUL ses identifiants une fois validé (SatelliteViewSet.recuperer_identifiants),
    # sans qu'un humain ait à les recopier -- usage unique, effacé à la récupération.
    secret_recuperation_hash = models.CharField(max_length=128, null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} ({self.institution.nom}) — {self.statut_enrolement}"


class ModeleSynchronisable(models.TextChoices):
    """Modèles synchronisés satellite -> central : Dossier (et son fil), DeclarationSecurite,
    Mission, MessageMeshLog. Jamais Request/Offer/Information."""
    DOSSIER = "Dossier", "Dossier"
    DOSSIER_COMMENTAIRE = "DossierCommentaire", "Commentaire de dossier"
    DOSSIER_HISTORIQUE = "DossierHistorique", "Historique de dossier"
    DECLARATION_SECURITE = "DeclarationSecurite", "Déclaration de sécurité"
    MISSION = "Mission", "Mission"
    MESSAGE_MESH_LOG = "MessageMeshLog", "Message mesh"


class ActionSynchronisation(models.TextChoices):
    CREATION = "CREATION", "Création"
    MODIFICATION = "MODIFICATION", "Modification"


class EtatEvenementSynchronisation(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    SYNCHRONISE = "SYNCHRONISE", "Synchronisé"
    CONFLIT = "CONFLIT", "En conflit — arbitrage requis"
    ERREUR = "ERREUR", "Erreur"


class EvenementSynchronisation(EnvironmentScopedModel):
    """Écriture locale à propager vers le central, créée par signal seulement si
    INSTANCE_SATELLITE_LOCALE, envoyée par la commande synchroniser_sortant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    modele = models.CharField(max_length=30, choices=ModeleSynchronisable.choices)
    objet_id = models.UUIDField()
    action = models.CharField(max_length=15, choices=ActionSynchronisation.choices)

    # Instantané des champs, construit par core/sync_outbox.py.
    payload = models.JSONField()

    # modifie_le connu avant la première écriture hors ligne : détection de conflit côté central.
    # Null pour les modèles en ajout seul.
    version_de_base = models.DateTimeField(null=True, blank=True)

    # Auteur local réel (l'auteur apparent côté central est le compte du satellite).
    auteur_local_email = models.CharField(max_length=255, blank=True)
    auteur_local_nom = models.CharField(max_length=255, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)

    etat = models.CharField(
        max_length=12, choices=EtatEvenementSynchronisation.choices,
        default=EtatEvenementSynchronisation.EN_ATTENTE,
    )
    synchronise_le = models.DateTimeField(null=True, blank=True)
    erreur = models.TextField(blank=True)

    class Meta:
        ordering = ["cree_le"]

    def __str__(self):
        return f"{self.action} {self.modele} {self.objet_id} — {self.etat}"


class StatutConflitSynchronisation(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente d'arbitrage"
    RESOLU_GARDE_CENTRAL = "RESOLU_GARDE_CENTRAL", "Résolu — version centrale conservée"
    RESOLU_GARDE_LOCAL = "RESOLU_GARDE_LOCAL", "Résolu — version locale appliquée"


class ConflitSynchronisation(EnvironmentScopedModel):
    """Conflit de synchronisation (objet modifié des deux côtés), jamais résolu
    automatiquement : un administrateur choisit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    satellite = models.ForeignKey(Satellite, on_delete=models.CASCADE, related_name="conflits_synchronisation")

    modele = models.CharField(max_length=30, choices=ModeleSynchronisable.choices)
    objet_id = models.UUIDField()

    payload_local = models.JSONField(help_text="Ce que le satellite tentait d'appliquer.")
    etat_central_au_conflit = models.JSONField(
        help_text="Instantané de l'état central au moment du conflit, pour comparaison.",
    )

    statut = models.CharField(
        max_length=25, choices=StatutConflitSynchronisation.choices,
        default=StatutConflitSynchronisation.EN_ATTENTE,
    )

    cree_le = models.DateTimeField(auto_now_add=True)
    resolu_le = models.DateTimeField(null=True, blank=True)
    resolu_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="conflits_synchronisation_resolus",
    )

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Conflit {self.modele} {self.objet_id} ({self.statut})"

