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
    
    INCEDIE = "INCEDIE", "Incendie"
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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["crise", "institution", "type_implication"],
                name="uq_implication_crise_institution_type"
            )
        ]

    def __str__(self):
        return f"{self.institution} - {self.crise} ({self.type_implication})"


class RequestType(models.Model):
    """Types de demandes d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
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


class Request(EnvironmentScopedModel):
    """Demandes d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos/demandes/", null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326)
    commune_code = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Code commune INSEE résolu à la saisie de l'adresse (autocomplete), "
                   "utilisé pour le matching géographique avec les zones d'intervention des équipes.",
    )
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


class DureeHebergement(models.TextChoices):
    TEMPORAIRE = "TEMPORAIRE", "Temporaire"
    LONGUE_DUREE = "LONGUE_DUREE", "Longue durée"


class TypeTransportOffre(models.TextChoices):
    PERSONNES = "PERSONNES", "Transport de personnes"
    MATERIEL = "MATERIEL", "Transport de matériel"


class TypeMateriel(models.TextChoices):
    CUVE = "CUVE", "Cuve"
    POMPE = "POMPE", "Pompe"
    ETUVE = "ETUVE", "Étuve"
    CHAMBRE_FROIDE = "CHAMBRE_FROIDE", "Chambre froide"
    REMORQUE = "REMORQUE", "Remorque"
    AUTRE = "AUTRE", "Autre"


class TypeSoutien(models.TextChoices):
    PROFESSIONNEL = "PROFESSIONNEL", "Professionnel de santé"
    SECOURISTE = "SECOURISTE", "Secouriste (y compris santé mentale)"


class Offer(EnvironmentScopedModel):
    """Offres d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos/offres/", null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    first_name_offer = models.CharField(max_length=60)
    last_name_offer = models.CharField(max_length=80)
    email_offer = models.EmailField()
    # Nullable côté modèle (pas de backfill à imposer aux offres déjà existantes) mais requis
    # côté formulaire public pour toute nouvelle soumission, même pattern que User.phone_number.
    phone_offer = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
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

    # Précisions spécifiques à certaines catégories (OfferType.type), une seule
    # s'applique en pratique selon le type choisi — voir propose-help-form.
    hebergement_duree = models.CharField(max_length=20, choices=DureeHebergement.choices, null=True, blank=True)
    numero_adeli_rpps = models.CharField(max_length=50, null=True, blank=True)
    transport_type = models.CharField(max_length=20, choices=TypeTransportOffre.choices, null=True, blank=True)
    materiel_type = models.CharField(max_length=20, choices=TypeMateriel.choices, null=True, blank=True)
    soutien_type = models.CharField(max_length=20, choices=TypeSoutien.choices, null=True, blank=True)

    # Vrai si l'offreur peut être resollicité au-delà de cette crise (ex: un agriculteur
    # qui prête son matériel ponctuellement pour d'autres interventions futures).
    renouvelable = models.BooleanField(default=False)

    # Déclarées par le bénévole à la soumission de l'offre (propose-help-form) — permet de
    # filtrer les candidats lors du recrutement sur un point opérationnel (PointOperationnel.
    # competences_requises est le pendant côté besoin, celui-ci est côté offre).
    competences = models.ManyToManyField("Competence", blank=True, related_name="offres")

    def __str__(self) -> str:
        return self.title


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

    actif = models.BooleanField(
        default=True
    )

    date_creation = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.nom


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

    crise = models.ForeignKey(
        "Crisis",
        on_delete=models.CASCADE,
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

class Team(EnvironmentScopedModel):
    """Équipes de gestion de crise"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=7, default='#3b82f6')  # hex color
    created_at = models.DateTimeField(auto_now_add=True)

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

    def __str__(self) -> str:
        return self.name


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

    def __str__(self):
        return self.nom


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


class StatutMateriel(models.TextChoices):
    EN_TRANSIT = "EN_TRANSIT", "En transit"
    SUR_PLACE = "SUR_PLACE", "Sur place"
    RETIRE = "RETIRE", "Retiré"


class MaterielCatalogue(models.Model):
    """Vocabulaire partagé et extensible des besoins matériel/logistique (lit, nourriture,
    eau...) — même esprit que Competence/InformationType (voir TagLikeViewSetMixin) : n'importe
    quel centre peut ajouter une entrée, immédiatement réutilisable par tous les autres.
    Remplace l'ancien TypeMateriel (TextChoices figé), trop rigide pour ce besoin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=100, unique=True)

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

    commentaire = models.TextField(blank=True, null=True)

    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_maj"]
        constraints = [
            models.UniqueConstraint(fields=["point", "item"], name="uq_materielpoint_point_item"),
        ]

    def __str__(self) -> str:
        return f"{self.item.nom} ({self.point.nom})"


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
        "Crisis", on_delete=models.CASCADE, null=True, blank=True,
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

