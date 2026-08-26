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

class Crisis(models.Model):
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


class ImplicationInstitution(models.Model):
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


class Request(models.Model):
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


class Information(models.Model):
    """Informations partagées"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    photo = models.ImageField(upload_to="photos/informations/", null=True, blank=True, validators=[validate_image_file])
    first_name_information = models.CharField(max_length=60)
    last_name_information = models.CharField(max_length=80)
    email_information = models.EmailField()
    phone_information = models.CharField(max_length=20)
    location = gis_models.PointField(srid=4326)
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


class Offer(models.Model):
    """Offres d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos/offres/", null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    first_name_offer = models.CharField(max_length=60)
    last_name_offer = models.CharField(max_length=80)
    email_offer = models.EmailField()
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

    def __str__(self) -> str:
        return self.title


class Creneau(models.TextChoices):
    MATIN = "MATIN", "Matin"
    MIDI = "MIDI", "Midi"
    SOIR = "SOIR", "Soir"
    NUIT = "NUIT", "Nuit"


class DisponibiliteOffre(models.Model):
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


class Institution(models.Model):

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


class InstitutionCompetence(models.Model):

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

class AffectationCompetence(models.Model):
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

class Dossier(models.Model):

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

    demande = models.ForeignKey(
        "Request",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dossiers",
        help_text="Demande d'aide à l'origine de ce dossier, si affecté depuis une demande.",
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

    def __str__(self):
        return f"{self.numero} - {self.titre}"

class DossierCommentaire(models.Model):

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

class DossierHistorique(models.Model):

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

class Document(models.Model):

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

class Team(models.Model):
    """Équipes de gestion de crise"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=7, default='#3b82f6')  # hex color
    created_at = models.DateTimeField(auto_now_add=True)

    leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="led_teams"
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

class DossierParticipant(models.Model):

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

class Notification(models.Model):

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

class RecherchePersonne(models.Model):

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
    models.Model
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

class RecherchePersonneHistorique(models.Model):

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

class RecherchePersonnePhoto(models.Model):

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
    models.Model
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
    models.Model
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
    models.Model
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

class AffectationRoleOperationnel(models.Model):

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
    models.Model
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


class DelegationCompetence(models.Model):

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

class PointOperationnel(models.Model):

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

    actif = models.BooleanField(
        default=True
    )

    commentaire = models.TextField(
        blank=True,
        null=True
    )

    def __str__(self):
        return self.nom


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

class AuditLog(models.Model):

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


class ContactInstitution(models.Model):

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

class InstitutionDomaine(models.Model):

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

