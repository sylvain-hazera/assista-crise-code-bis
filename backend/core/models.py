import uuid
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.gis.db import models as gis_models
from django.db import models


class RoleUtilisateur(models.TextChoices):
    ADMINISTRATEUR = "ADMIN", "Administrateur"
    AUTORITE_LOCALE = "AUT_LOCALE", "Autorité locale"
    SECOURS_ORGANISES = "SECOURS", "Secours organisés"
    UTILISATEUR_SIMPLE = "UTIL_SIMPLE", "Utilisateur"


class Statut(models.TextChoices):
    NON_TRAITEE = "NON_TRAITEE", "Non traitée"
    EN_COURS_DE_TRAITEMENT = "EN_COURS", "En cours de traitement"
    TRAITEE = "TRAITEE", "Traitée"
    DISPONIBLE = "DISPONIBLE", "Disponible"
    INDISPONIBLE = "INDISPONIBLE", "Indisponible"


class Utilisateur(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    telephone_utilisateur = models.CharField(max_length=20, null=True, blank=True)
    photo = models.ImageField(upload_to="photos/", null=True, blank=True)
    type = models.CharField(
        max_length=20,
        choices=RoleUtilisateur.choices,
        default=RoleUtilisateur.UTILISATEUR_SIMPLE,
    )
    

    crise_touchee = models.ForeignKey(
        "Crise",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="victimes"
    )
    consulte_demande = models.ManyToManyField(
        "Demande",
        blank=True,
        related_name="utilisateurs_consultant"
    )

    consulte_information = models.ManyToManyField(
        "Information",
        blank=True,
        related_name="utilisateurs_consultant"
    )

    consulte_offre = models.ManyToManyField(
        "Offre",
        blank=True,
        related_name="utilisateurs_consultant"
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.username


class Crise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=100)
    localisation = gis_models.PointField(srid=4326)
    radius = models.IntegerField(default=10)
    date_debut = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    description = models.CharField(max_length=150, null=True, blank=True)


    validateur = models.ForeignKey(
        'Utilisateur',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="crises_validees"
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.nom


class TypeDemande(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.type


class Demande(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    titre = models.CharField(max_length=150)
    photo = models.ImageField(upload_to="photos/demandes/", null=True, blank=True)
    localisation = gis_models.PointField(srid=4326)
    prenom_demande = models.CharField(max_length=60)
    nom_demande = models.CharField(max_length=80)
    email_demande = models.EmailField()
    telephone_demande = models.CharField(max_length=20)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_expiration = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.NON_TRAITEE,
    )


    type_demande = models.ForeignKey(
        TypeDemande, on_delete=models.PROTECT, related_name="demandes"
    )
    crise = models.ForeignKey(
        "Crise", on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes"
    )
    auteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demandes_saisies",
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.titre


class TypeInformation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.type


class Information(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    titre = models.CharField(max_length=150)
    photo = models.ImageField(upload_to="photos/informations/", null=True, blank=True)
    prenom_information = models.CharField(max_length=60)
    nom_information = models.CharField(max_length=80)
    email_information = models.EmailField()
    telephone_information = models.CharField(max_length=20)
    localisation = gis_models.PointField(srid=4326)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_expiration = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.DISPONIBLE,
    )


    type_information = models.ForeignKey(
        TypeInformation, on_delete=models.PROTECT, related_name="informations"
    )
    crise = models.ForeignKey(
        "Crise", on_delete=models.SET_NULL, null=True, blank=True, related_name="informations"
    )
    auteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="informations_saisies",
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.titre


class TypeOffre(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.type





class Offre(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    titre = models.CharField(max_length=150)
    photo = models.ImageField(upload_to="photos/offres/", null=True, blank=True)
    localisation = gis_models.PointField(srid=4326)
    prenom_offre = models.CharField(max_length=60)
    nom_offre = models.CharField(max_length=80)
    email_offre = models.EmailField()
    date_creation = models.DateTimeField(auto_now_add=True)
    date_expiration = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.DISPONIBLE,
    )


    type_offre = models.ForeignKey(
        TypeOffre, on_delete=models.PROTECT, related_name="offres"
    )
    crise = models.ForeignKey(
        "Crise", on_delete=models.SET_NULL, null=True, blank=True, related_name="offres"
    )

    auteur = models.ForeignKey(
        Utilisateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offres_saisies",
    )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.titre
