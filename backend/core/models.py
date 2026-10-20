import hashlib
import uuid
import os
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.gis.db import models as gis_models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.postgres.indexes import GinIndex
from core.validators import validate_image_file
from .validators import validate_image_file, validate_identity_document_file
from .crypto_fields import EncryptedTextField, EncryptedEmailField, EncryptedJSONField, blind_index
from .file_crypto import get_encrypted_file_storage

# Nom de fichier stocké basé sur un UUID plutôt que le nom d'origine (même patron que
# secure_document_path/secure_recherche_photo_path plus bas dans ce fichier, ici dupliqué par
# champ pour rester une fonction top-level nommée — requis pour que Django sache sérialiser
# `upload_to` dans les migrations) : jamais de collision, jamais de fuite d'information via le
# nom déposé par l'utilisateur, et surtout plus jamais bloqué par FileField.max_length (100 par
# défaut, jamais changé sur ces champs) quand le nom d'origine — souvent une longue description
# exportée par un téléphone ou téléchargée depuis un site — dépasse cette limite. Repéré en
# direct : dépôt de crise bloqué par « Ensure this filename has at most 100 characters » sur une
# photo dont le nom en faisait 120.
def secure_user_photo_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"photos/{uuid.uuid4()}{extension}"


# Logo d'institution (marque blanche) : contrairement à documents/photos/recherches, ce préfixe
# n'est PAS bloqué par proxy/nginx.conf -- un logo doit être publiquement affichable (header du
# site), c'est le but même du champ. Ne jamais réutiliser ce préfixe pour un fichier sensible.
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


class UserManager(DjangoUserManager):
    """`email` étant chiffré (voir core/crypto_fields.py), la résolution par USERNAME_FIELD
    (utilisée par Django authenticate()/ModelBackend et donc par la connexion JWT) doit passer
    par `email_bidx`, pas par `email=` qui ne peut plus jamais matcher un ciphertext."""

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

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    # Chiffré (voir core/crypto_fields.py) : `unique=True` déplacé sur `email_bidx`, seul moyen
    # de garantir l'unicité une fois `email` chiffré de façon non déterministe (Fernet inclut un
    # nonce aléatoire -- deux lignes avec le même email en clair ont un ciphertext différent, la
    # contrainte unique ne peut donc plus porter sur la colonne chiffrée elle-même).
    email = EncryptedEmailField()
    # Chiffré (voir core/crypto_fields.py) : `unique=True` déplacé ici depuis `email`, seul
    # moyen de garantir l'unicité une fois `email` chiffré de façon non déterministe (Fernet
    # inclut un nonce aléatoire -- deux lignes avec le même email en clair ont un ciphertext
    # différent). Resserré en unique=True/NOT NULL par la migration 0183, après que la
    # migration de données 0182 ait rempli cette colonne pour les lignes existantes.
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

    # Case "Je souhaite rejoindre la réserve" à l'inscription publique (voir RegisterView,
    # Institution.reserve_active) -- `reserve_institution` identifie QUELLE réserve (résolue
    # depuis le Host au moment de l'inscription, voir core/branding.py), `reserve_verifiee`
    # bascule à True quand le responsable de cette institution a traité la candidature (voir
    # UserViewSet.verifier_reserve). `reserve_a_verifier` côté serializer (souhaite ET pas
    # encore vérifiée) pilote la bannière "à vérifier", même gabarit que
    # UserSerializer.get_needs_institution_setup.
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
            # GIN sur les JSONField de composition de zone -- cible le lookup
            # Q(zone_communes__contains=[code])/Q(zone_departements__contains=[code]) de
            # _crisis_zone_resolver (views.py), non indexé jusqu'ici. Coût d'écriture
            # négligeable (table peu volumineuse comparée à Offer/Request/Information).
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


class ContributionZoneCommune(EnvironmentScopedModel):
    """Qui a fait entrer CETTE commune dans `Crisis.zone_communes` — `zone_communes` reste un
    simple JSONField (utilisé tel quel par tout le scoping zone existant, ex.
    SatelliteViewSet.supervision), cette table ne fait qu'en tracer la provenance, en plus.
    `institution` null = ajout sans propriétaire précis (ex. un admin élargissant la zone de
    réponse sans que ce soit la commune elle-même qui se déclare) : librement retirable par
    quiconque peut éditer la crise. `institution` renseigné = ajouté par cette commune/EPCI
    elle-même déclarant une implication, ou par un de ses propres contacts via l'éditeur de
    zone — voir CrisisViewSet.perform_update, seul cette institution (ou un administrateur
    global, décision utilisateur du 2026-09-18) peut alors la retirer.

    Une commune n'a qu'UN SEUL propriétaire par crise (contrainte d'unicité) : le premier
    contributeur fait foi, un second ajout de la même commune ne change pas la provenance déjà
    enregistrée — cohérent avec le principe "jamais un choix automatique silencieux", on ne
    réattribue jamais la propriété d'une entrée déjà tracée."""

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
    description = EncryptedTextField(null=True, blank=True)
    photo = models.ImageField(upload_to=secure_demande_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
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
    first_name_request = EncryptedTextField()
    last_name_request = EncryptedTextField()
    email_request = EncryptedEmailField()
    # Voir User.email_bidx pour le raisonnement -- utilisé par resolve_or_invite_demandeur pour
    # rapprocher cette demande d'un compte User existant (recherche EXACTE, jamais via le champ
    # chiffré lui-même).
    email_request_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    phone_request = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deletion_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    # Distinct de deletion_token (portées différentes : celui-ci ne permet que de modifier la
    # demande, jamais de la désactiver) — même patron que Offer.reponse_token. Généré à la
    # création, même patron que deletion_token.
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
            # commune_code n'avait pas db_index=True contrairement à epci_code/departement_code/
            # region_code -- pourtant le niveau de zone le plus courant pour une mairie (sa
            # propre commune) passe par ce champ (voir zone_scoping.SECTEUR_CHAMP_PAR_NIVEAU).
            models.Index(fields=["commune_code"]),
        ]

    def save(self, *args, **kwargs):
        self.email_request_bidx = blind_index(self.email_request) if self.email_request else None
        super().save(*args, **kwargs)

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
    # Distinct de deletion_token (portées différentes : celui-ci ne permet que de modifier le
    # signalement, jamais de le désactiver) — même patron que Offer.reponse_token. Généré à la
    # création, même patron que deletion_token.
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
    description = EncryptedTextField(null=True, blank=True)
    photo = models.ImageField(upload_to=secure_offre_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    # Résolus une seule fois à la création (voir OfferViewSet.perform_create), à partir de
    # `location` — même rôle que Request.commune_code/Information.commune_code, ajouté ici
    # pour la "vue secteur" (mairie/EPCI/département) sans reverse-géocoder chaque offre à
    # chaque requête (l'ancien vue_mairie le faisait ligne par ligne, voir son commentaire).
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

    # Une offre d'hébergement (offer_type "Hébergement") ne vise plus forcément que les
    # sinistrés -- demande explicite de Sylvain le 24/09 : la même offre peut aussi bien
    # accueillir des sinistrés qu'accueillir des intervenants mobilisés (les deux cases sont
    # indépendantes, une même offre peut cocher les deux). Sans objet pour les autres
    # offer_type, laissées à leurs valeurs par défaut. accueil_sinistres démarre à True pour
    # ne rien changer au comportement des offres d'hébergement déjà en base (seul usage qui
    # existait jusqu'ici) ; accueil_intervenants démarre à False car c'est un nouvel usage,
    # opt-in, qui nécessite en plus une validation par un régulateur avant d'être exploitable
    # (voir accueil_intervenants_valide_par -- même patron que Crisis.validator/User.validator
    # : FK nullable, null = en attente).
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

    # Dépôt groupé (entreprise/association déposant plusieurs personnes/véhicules en une seule
    # visite du formulaire public, voir propose-help-form) : organisation_nom identifie qui
    # dépose (distinct de first_name_offer/last_name_offer, la personne physique), groupe_id
    # est partagé par toutes les lignes d'une même soumission — simple étiquette de
    # regroupement pour le tableau de bord régulateur (ReportingComponent), pas une FK vers un
    # modèle de lot : un dépôt groupé n'a pas de cycle de vie propre au-delà de la sélection.
    organisation_nom = EncryptedTextField(blank=True, null=True)
    groupe_id = models.UUIDField(null=True, blank=True)

    # Précisions spécifiques à certaines catégories (OfferType.type), une seule
    # s'applique en pratique selon le type choisi — voir propose-help-form. hebergement_duree
    # et les autres champs Hébergement viennent de HebergementDetailsMixin (base de la classe).
    numero_adeli_rpps = EncryptedTextField(null=True, blank=True)
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
    immatriculation = EncryptedTextField(null=True, blank=True)

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

    # Uniquement pertinent pour du matériel apporté ET exploité par l'offreur lui-même (type
    # Matériel, presence_physique=True) : combien de personnes viennent avec lui pour l'aider à
    # l'exploiter — utile pour dimensionner l'accueil/hébergement de l'équipe mobilisée, pas
    # juste du matériel seul. accompagne=None si la question ne s'est jamais posée (offre
    # antérieure à ce champ, ou type/presence_physique ne la justifiant pas).
    accompagne = models.BooleanField(null=True, blank=True)
    nombre_accompagnants = models.PositiveIntegerField(null=True, blank=True)

    # Déclarées par le bénévole à la soumission de l'offre (propose-help-form) — permet de
    # filtrer les candidats lors du recrutement sur un point opérationnel (PointOperationnel.
    # competences_requises est le pendant côté besoin, celui-ci est côté offre).
    competences = models.ManyToManyField("Competence", blank=True, related_name="offres")

    class Meta:
        indexes = [
            # Sert le tri par défaut (-created_at) et toute pagination -- la table la plus
            # volumineuse des quatre (7250+ lignes, cible 300-400k), cf. plan pagination
            # Signalements.
            models.Index(fields=["-created_at"]),
        ]

    def save(self, *args, **kwargs):
        self.email_offer_bidx = blind_index(self.email_offer) if self.email_offer else None
        super().save(*args, **kwargs)

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

    # True par défaut si posé par l'équipe (déjà "lu" par construction, c'est elle qui écrit) ;
    # False si posé par le propriétaire de l'offre -- alimente la file "Retours externes" de la
    # page Cellule de crise (voir OfferViewSet.messages, qui repasse ce champ à True à la
    # lecture institutionnelle).
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

    # Optionnel : regroupe des thèmes plus fins sous un thème générique — même patron que
    # Competence.parent (voir TeamsComponent), pour l'affichage en menu déroulant pliable côté
    # déclaration de crise (voir DeclareCrisisFormComponent, "Thèmes à l'écoute"). Jamais plus
    # d'un niveau (un sous-thème ne peut pas lui-même avoir des enfants), non contraint en base
    # pour rester simple, à respecter côté formulaire.
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sous_besoins",
    )

    # Optionnel (beaucoup de besoins existants n'ont pas encore été qualifiés) : indique si le
    # besoin se satisfait par une compétence humaine, du matériel, ou les deux — voir
    # BesoinNature. Détermine quel(s) type(s) de correspondance (BesoinCompetence/BesoinMateriel)
    # a du sens de proposer pour ce besoin dans la page admin "Correspondances".
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

    # Faux par défaut (fail-closed) : une association/entreprise n'est réputée mandatée sur une
    # crise qu'après validation explicite d'un régulateur AUT_LOCALE (voir
    # ImplicationInstitutionViewSet.perform_create et PointOperationnelViewSet.perform_create),
    # jamais par défaut. Vrai pour les collectivités/services publics (mairie, EPCI, préfecture,
    # SDIS...), qui n'ont pas besoin de mandat pour agir sur une crise.
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

    # Convention de sous-traitance RGPD (article 28) — voir core/convention_sous_traitance.py
    # et frontend/.../convention-sous-traitance. Exigée une seule fois PAR INSTITUTION (pas par
    # utilisateur : la convention lie la collectivité en tant que personne morale, un second
    # membre qui la rejoint ensuite n'a pas à re-signer) au moment où le PREMIER compte
    # "Autorité locale" (mairie/EPCI/SDIS) rejoint ou crée cette institution — voir
    # UserViewSet.confirmer_institution/creer_mon_institution. `convention_version` mémorise le
    # texte réellement accepté (voir CONVENTION_VERSION) pour ne jamais prétendre couvrir une
    # future révision sans nouvelle acceptation explicite.
    convention_sous_traitance_acceptee_le = models.DateTimeField(null=True, blank=True)
    convention_sous_traitance_acceptee_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="conventions_sous_traitance_acceptees",
    )
    convention_sous_traitance_version = models.CharField(max_length=10, blank=True)

    # Marque blanche (voir InstitutionWebDomaine ci-dessous pour la résolution par Host, et
    # core/branding.py pour l'usage) -- tous blank/vides par défaut, ce qui fait retomber
    # resolve_institution_branding/get_mail_branding sur les valeurs par défaut "Assista-Crise".
    # Volontairement en clair (pas de EncryptedTextField) : ce sont des informations publiques
    # d'identité visuelle, pas des données personnelles.
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

    # Active la case "rejoindre la réserve" à l'inscription publique (voir RegisterView,
    # register.component) quand le Host visité résout vers cette institution -- False pour
    # toutes les institutions ordinaires, qui n'ont pas de réserve à recruter.
    reserve_active = models.BooleanField(default=False)

    def __str__(self):
        return self.nom


class InstitutionWebDomaine(EnvironmentScopedModel):
    """Hostname HTTP (marque blanche) résolvant vers le branding/les emails de cette institution
    -- voir core/branding.py::resolve_institution_branding. Volontairement un modèle À PART
    d'InstitutionDomaine (qui est un domaine EMAIL, ex: "sdis33.fr", utilisé pour le
    rattachement automatique par adresse mail, voir institution_attachment.py) : mélanger les
    deux casserait ce mécanisme existant et n'a aucun sens fonctionnel (le Host d'une requête
    web n'a aucun rapport avec le domaine de l'email de quelqu'un).

    Une institution peut avoir plusieurs hostnames (ex: "cj.assista-crise.fr" ET
    "app.reserve-resilience.org" si le partenaire pointe un CNAME dessus -- le navigateur
    envoie le Host réellement visité, jamais la cible du CNAME, donc les deux doivent être
    déclarés ici pour résoudre au même branding)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="domaines_web")
    hostname = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.hostname


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


class OfferTypeBesoin(models.Model):
    """Pont OfferType -> Besoin, mirror de RequestTypeBesoin -- permet de filtrer les types
    d'offre sélectionnables sur le formulaire public "proposer de l'aide" aux seuls thèmes
    qu'au moins une institution a déclarés "à l'écoute" pour la crise/zone choisie (voir
    besoins_ecoute.py)."""

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

    # Le Besoin précis derrière `competence` (voir resolve_besoin_for_request/_information,
    # views.py) -- capturé directement à la création plutôt que redérivé depuis `competence`
    # (ambigu : une Competence peut être partagée par plusieurs Besoin via BesoinCompetence).
    # Sert à classer un dossier "ressource" (nature COMPETENCE/MIXTE) vs "moyen" (MATERIEL) sur
    # la page Cellule de crise, sans requête supplémentaire.
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

    # Posé par un participant du dossier (souvent un bénévole terrain) pour signaler une
    # urgence au régulateur sans attendre le prochain point — voir TeamViewSet ou
    # DossierViewSet.marquer_important, qui notifie les régulateurs concernés (même recherche
    # que populate_dossier_participants_and_notify, via _regulateurs_pour_dossier).
    important = models.BooleanField(default=False)
    date_signalement_important = models.DateTimeField(null=True, blank=True)

    # Ajouté pour la synchronisation local -> central (voir core/sync_outbox.py) : seul moyen
    # de détecter qu'un satellite a divergé du central pendant une coupure (le central a-t-il
    # été modifié par quelqu'un d'autre entre-temps ?) sans lui, aucune donnée de version
    # disponible pour arbitrer un conflit plutôt que d'écraser silencieusement.
    modifie_le = models.DateTimeField(auto_now=True)

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
    """Active la diffusion automatique d'alertes sismiques sur les canaux mesh actifs d'une
    institution -- voir core/management/commands/verifier_alertes_sismiques.py (exécuté par
    cron, pas de celery-beat dans ce projet). Source : API publique du catalogue BCSF-Rénass/
    EOST (api.franceseisme.fr, service FDSN event), confirmée fonctionnelle le 10/10 -- pas de
    projet open source équivalent trouvé pour la diffusion vers un réseau mesh (recherche du
    10/10), construit nativement, seul le PRINCIPE est inspiré de meshcore-bot (github.com/
    agessaman/meshcore-bot, qui fait la même chose avec l'API sismique américaine USGS).

    Centre géographique résolu depuis Institution.commune_code (référentiel Commune interne,
    centre_latitude/centre_longitude) -- pas de lat/lon à saisir à la main, et rien ne se passe
    pour une institution sans commune renseignée.

    magnitude_min par défaut à 3.5 (revenu en arrière le 10/10, était passé à 4.0 un instant) --
    en France métropolitaine (sismicité modérée, pas en bord de plaque), M3-3.5 est largement
    RESSENTI mais ne cause quasiment jamais de dégât ; le seuil où un risque réel (dégâts
    légers -- fissures, tuiles, cheminées) devient plausible se situe plutôt vers M4-4.5,
    SURTOUT si l'épicentre est peu profond (ex: Le Teil, 2019, M4.9 à ~1-2km de profondeur --
    dégâts significatifs inhabituels pour cette magnitude, justement à cause de la faible
    profondeur). Décision utilisateur du 10/10 : être alerté dès que "ressenti" (3.5) reste
    préférable, quitte à avoir plus de diffusions -- reste réglable par institution si besoin
    de monter à 4+ pour se limiter aux séismes à risque réel de dégât."""

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
    """Évènement sismique déjà diffusé sur le mesh -- anti-doublon entre deux cycles de
    vérification (un même séisme reste dans le catalogue BCSF-Rénass pendant des jours, voir
    verifier_alertes_sismiques). `institution=None` : diffusion communautaire (canal Fr_EMCOM,
    pas propre à une institution -- voir _diffuser_emcom, demande utilisateur du 10/10), suivie
    séparément des diffusions propres à chaque institution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="seismes_diffuses",
    )

    # Identifiant de l'évènement côté API (ex: "fr2026uuqykq") -- PAS une clé primaire
    # fonctionnelle ici, juste ce que le catalogue utilise, unique par institution (deux
    # institutions à portée du même séisme doivent chacune recevoir leur propre diffusion).
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
    """Catégories types d'un annuaire de crise PCS/PICS -- structure confirmée via plusieurs
    trames officielles (ministère de l'Intérieur, préfectures) : pas de liste nationale unique
    figée, mais cette structure revient systématiquement (préfecture/secours/santé/élus/
    réseaux/établissements sensibles/médias)."""
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
    """Canal d'alerte préféré d'un interlocuteur PCS. TELEPHONE reste volontairement manuel
    (pas d'envoi auto, juste la checklist) ; SMS/API_TIERCE sont des valeurs RÉSERVÉES -- aucun
    envoi automatique implémenté pour elles pour l'instant (pas de passerelle SMS gratuite
    disponible, demande utilisateur du 11/10) mais choisies dès maintenant pour qu'un
    interlocuteur puisse déjà être catégorisé ainsi, prêt pour une intégration future (SMS,
    Intramuros, Facebook...) sans migration de données -- voir core/alertes_pcs.py."""
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
    # Le destinataire a cliqué lui-même le lien d'accusé de réception du mail -- à distinguer
    # de CONFIRME_MANUEL (la mairie l'a coché à la main, typiquement après un appel
    # téléphonique) : aucune des deux n'implique l'autre, voir docstring de NotificationAlertePCS.
    CONFIRME_PAR_CONTACT = "CONFIRME_PAR_CONTACT", "Confirmé par le contact lui-même"
    CONFIRME_MANUEL = "CONFIRME_MANUEL", "Confirmé manuellement"


class ReponseContactPCS(models.TextChoices):
    """Réponse rapide proposée sur la page publique d'accusé de réception (voir
    AccuserReceptionAlertePCSPublicView) -- évite un appel téléphonique non nécessaire quand le
    contact n'a rien à ajouter."""
    PAS_DE_RAPPEL = "PAS_DE_RAPPEL", "Pas besoin de me rappeler"
    MERCI_RAPPELER = "MERCI_RAPPELER", "Merci de me rappeler pour échanger sur la situation"
    AUTRE = "AUTRE", "Autre (voir commentaire)"


class InterlocuteurAlertePCS(EnvironmentScopedModel):
    """Annuaire PARTAGÉ des interlocuteurs à prévenir lors d'une activation de PCS/PICS (voir
    NotificationAlertePCS) -- demande utilisateur du 11/10. Volontairement PAS une FK unique
    vers une institution (contrairement à ContactInstitution) : un même interlocuteur (ex: le
    SIDPC d'une préfecture, le même pour tout un département) doit pouvoir être rattaché par
    plusieurs communes/intercommunalités sans être ressaisi -- même esprit que le catalogue
    partagé Competence/MaterielCatalogue (voir TagLikeViewSetMixin), mais EnvironmentScopedModel
    ici (contrairement à ces deux-là) : ce modèle porte de vraies coordonnées externes utilisées
    pour de vrais envois d'alerte, DEMO et PROD ne doivent jamais se mélanger dessus.

    `nom`/`email`/`telephone`/`notes` chiffrés (voir core/crypto_fields.py, même convention que
    Request/Offer/Information) -- PII d'une personne physique. `organisme` reste en clair
    (information organisationnelle, ex: "Préfecture de la Gironde", comme Institution.nom)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institutions = models.ManyToManyField(
        "Institution", related_name="interlocuteurs_alerte_pcs", blank=True,
    )

    # Dénormalisé depuis l'institution qui crée le contact (même mécanisme que
    # Institution.departement_code) -- sert UNIQUEMENT à borner la recherche d'un contact
    # existant (?q=) au département de l'institution qui cherche, pour qu'une commune ne tombe
    # jamais par recherche sur un contact purement local d'une commune d'un autre département.
    # Pas une contrainte dure (une institution peut rattacher un contact hors de ce département).
    departement_code = models.CharField(max_length=3, null=True, blank=True)

    categorie = models.CharField(
        max_length=30, choices=CategorieInterlocuteurPCS.choices, default=CategorieInterlocuteurPCS.AUTRE,
    )

    nom = EncryptedTextField()
    organisme = models.CharField(max_length=255, blank=True)
    email = EncryptedEmailField(null=True, blank=True)
    telephone = EncryptedTextField(null=True, blank=True)
    notes = EncryptedTextField(null=True, blank=True)

    # Optionnel -- seulement pour un élu/agent communal ayant un compte applicatif, permet
    # l'envoi Matrix (voir core/matrix.envoyer_dm, qui prend un User, pas un identifiant Matrix
    # brut). SET_NULL : la suppression d'un compte ne doit jamais faire disparaître la fiche.
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
    """Une ligne par (crise, interlocuteur) -- créée (sans envoi) dès la déclaration de la
    crise (voir CrisisViewSet.perform_create/core.alertes_pcs.preparer_checklist_pcs), fait
    office de checklist manuelle ET de suivi d'un éventuel envoi automatique (email/Matrix).

    `interlocuteur` en SET_NULL + champs `*_snapshot` : cette ligne est un historique attaché à
    UNE déclaration de crise précise -- elle ne doit jamais changer de texte ni disparaître si
    l'annuaire partagé est modifié/l'interlocuteur retiré après coup (même logique qu'un journal
    d'audit). `institution_nom_snapshot` existe parce que `Crisis` n'a pas de FK institution
    (résolue seulement au moment de la déclaration, voir CrisisViewSet.perform_create) -- sert
    à afficher "la commune de X vous informe..." sur la page publique d'accusé de réception
    sans dépendre d'un lien qui n'existe pas sur `Crisis` elle-même.

    `token_confirmation` : même patron exact que AffectationPointBenevole/EngagementRessource
    (secrets.token_urlsafe(32), généré à la création, pas d'expiration -- la protection est la
    longueur du jeton, cohérent avec le reste de l'app). Permet au destinataire de cliquer un
    lien dans le mail reçu pour accuser réception SANS AVOIR DE COMPTE (voir
    AccuserReceptionAlertePCSPublicView) -- passe le statut à CONFIRME_PAR_CONTACT, évitant un
    appel téléphonique de relance potentiellement inutile."""

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
    # Texte réellement envoyé (choisi/modifié par l'utilisateur qui a déclenché l'envoi, "pour
    # cette fois uniquement" -- demande utilisateur du 11/10) -- conservé pour trace, jamais
    # réutilisé comme modèle par défaut ailleurs.
    message_envoye = models.TextField(null=True, blank=True)

    reponse_contact = models.CharField(max_length=20, choices=ReponseContactPCS.choices, null=True, blank=True)
    commentaire_contact = EncryptedTextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_envoi_auto = models.DateTimeField(null=True, blank=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)

    # Rempli seulement pour CONFIRME_MANUEL (un utilisateur de l'app a coché la case après un
    # appel) -- jamais pour CONFIRME_PAR_CONTACT, qui n'est l'action d'aucun utilisateur de
    # l'app (le contact n'a pas de compte).
    confirme_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications_pcs_confirmees",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["crise", "interlocuteur"], name="uq_notification_pcs_crise_interlocuteur"),
        ]

    def __str__(self):
        return f"{self.nom_snapshot} / {self.crise.name} ({self.statut})"


# Types d'institution correspondant à une collectivité territoriale au sens strict (par
# opposition aux services de l'État qui partagent pourtant le même niveau de secteur -- SDIS,
# gendarmerie, préfecture, voir SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION dans geo_reference.py) :
# seules celles-ci reçoivent une Zone "Mon territoire" automatique (voir
# _assurer_zone_mon_territoire, appelée depuis Institution.save()) et l'accès élargi aux
# fonctionnalités PCS/PICS (voir _institution_est_autorite_locale, core/views.py).
TYPES_COLLECTIVITE_TERRITORIALE = {"MAIRIE", "EPCI", "CG", "CR"}


def _assurer_zone_mon_territoire(institution) -> None:
    """Crée (ou met à jour) la Zone "Mon territoire" d'une collectivité, couvrant toute sa
    zone de compétence (une commune, ou toutes les communes de son EPCI/département/région,
    voir geo_lookup.communes_de_secteur) -- jamais bloquant : une panne réseau ou une Commune
    non résolue ne doit jamais empêcher la création/l'édition de l'Institution elle-même (même
    principe que audit_log, voir core/audit.py)."""
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
    """Référencement des dégâts par bâtiment (ex: Le Porge, 255 habitations sinistrées) —
    point sur la carte dont la couleur reflète `statut_evaluation`, complété par
    `statut_chantier` une fois des dégâts constatés. Alimenté soit par import CSV fourni par la
    collectivité (voir ImportHabitationsView), soit à terme par un lookup BAN automatique sur
    la commune/zone (voir doc de conception -- non encore implémenté)."""

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
    """Fil d'échange sur une habitation -- visible à la fois par les agents et par un
    participant dont le RattachementHabitation a été accepté (voir populate côté vue), pour
    permettre l'échange régulateur <-> propriétaire/locataire demandé explicitement."""

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
    """Demande d'un particulier ou d'une entreprise de se réclamer propriétaire ou locataire
    d'une habitation référencée -- déposée SANS compte obligatoire (comme un signalement
    public, voir InformationViewSet), le suivi étant ensuite accessible par magic-link (même
    mécanisme que dossier-suivi, voir build_magic_link) ou par un compte classique si le
    demandeur en a un. Les deux types de lien peuvent coexister pour une même habitation (un
    propriétaire ET un locataire), d'où l'absence de contrainte d'unicité stricte -- seule la
    vue empêche une nouvelle demande EN_ATTENTE identique (même email + même type de lien)."""

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
    # Voir User.email_bidx pour le raisonnement -- utilisé par le garde-fou anti-doublon
    # (recherche EXACTE, voir RattachementHabitationViewSet) et le rapprochement avec un compte
    # User existant à l'acceptation.
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

    # Justificatif (photo) fourni par le demandeur -- titre de propriété, bail, facture à son
    # adresse... Non requis à la création (déposable dès le formulaire public ou ajouté après
    # coup), voir RattachementHabitationViewSet. Champ direct plutôt que le modèle Document
    # générique : Document exige IsAuthenticated par défaut (voir DocumentViewSet), alors que ce
    # dépôt doit rester possible sans compte, comme le reste de la demande -- même convention
    # que Offer.photo pour le dépôt "proposer de l'aide".
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
    """Photo recto/verso du permis de conduire (ou autre pièce d'identité) fournie par un
    candidat à une réserve marque blanche (voir User.souhaite_rejoindre_reserve) -- exigence
    assurance du partenaire, pas une fonctionnalité générique. Modèle à part plutôt que des
    champs directs sur User : même raisonnement que RattachementHabitation.justificatif, et
    évite d'alourdir User (déjà très chargé) d'un besoin propre à un seul type de compte.

    Chiffré au repos (contrairement à tout le reste des ImageField du projet, voir
    core/file_crypto.py -- EncryptedFileSystemStorage, clé FILE_ENCRYPTION_KEY dédiée) : une
    pièce d'identité est plus sensible qu'une photo de profil ou un justificatif de domicile,
    jamais lisible même avec un accès direct au volume/disque. `upload_to=secure_document_path`
    réutilise délibérément le préfixe "documents/" (déjà bloqué par
    `location /media/documents/ { return 403; }` dans proxy/nginx.conf) -- pas de nouveau bloc
    nginx à ajouter, mais à ne JAMAIS changer sans ajouter le blocage correspondant."""

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
    """Activation du module "Estimation des dégâts" par une institution, pour une crise précise
    -- désactivé par défaut : sans ligne ici (ou actif=False), aucun accès public ni
    institutionnel au référencement des dégâts pour cette crise (voir
    habitations.institution_accede_commune). `zone` restreint où les bâtiments (Habitation)
    peuvent être chargés en réutilisant le catalogue Zone existant -- laissée vide, aucune
    restriction géographique au-delà de la commune/délégation déjà vérifiée par ailleurs (voir
    habitations.commune_dans_zone_module)."""

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


# --- Simulation d'inondation par commune (outil de planification préventive pour les mairies,
# distinct du référencement des dégâts ci-dessus) -----------------------------------------------
#
# Ces trois modèles sont un CACHE de résultat de calcul (relief, paliers, adresses testées),
# jamais des faits constatés -- ne JAMAIS écrire dans Habitation.statut_evaluation depuis ce
# calcul : une simulation reste une hypothèse, un statut d'évaluation est un constat de terrain.
# Voir core/inondation.py pour le calcul lui-même.


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
    """Grille d'accumulation de flux (ruissellement) d'une commune -- une seule ligne par
    commune, pas de dimension "niveau" contrairement à PalierInondationSimule (une crue éclair
    n'a pas de niveau d'eau absolu à faire varier, voir core/ruissellement.py). Calculée à
    partir de la MÊME grille d'altitude que GrilleAltimetrieCommune, jamais un nouvel appel
    externe."""

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
    """Polygone de zone inondée simulée pour UN niveau d'eau (mètres) sur une commune --
    précalculé par paliers (voir inondation.calculer_paliers_inondation) pour que le curseur
    còté frontend n'ait qu'à changer de couche déjà chargée, jamais recalculer en direct.
    `polygone` vide/null = rien d'inondé à ce niveau (relief entièrement hors d'eau)."""

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
    """Une adresse BAN d'une commune scannée pour la simulation, avec son altitude et le plus
    petit niveau d'eau simulé qui l'atteint (`seuil_inondation_metres`, null = jamais atteinte
    dans la plage testée) -- voir inondation.seuils_inondation_adresses. Séparé d'Habitation à
    dessein : ceci n'est jamais un constat, seulement une hypothèse de planification."""

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
    # Grille d'altitude + paliers (niveau d'eau simulé, futur ruissellement) -- toujours borné
    # (grille plafonnée, voir inondation.py:MAX_COTE), ne dépend jamais de la taille de la
    # commune en nombre d'adresses.
    PALIERS = "PALIERS", "Relief et paliers d'eau"
    # Scan BAN + seuil par adresse -- NON borné (une grande ville peut avoir des dizaines de
    # milliers d'adresses), volontairement séparé de PALIERS pour que la simulation du niveau
    # d'eau reste utilisable même sur une commune où le chargement des adresses échouerait ou
    # serait trop long (demande explicite du 2026-09-30, suite à l'échec du chargement complet
    # sur Bordeaux -- voir docstring de seuils_inondation_adresses).
    ADRESSES = "ADRESSES", "Adresses BAN"
    # Accumulation de flux (crue éclair/ruissellement, voir core/ruissellement.py) -- même
    # grille que PALIERS, toujours bornée, mais algorithme différent (pas de remplissage par
    # connexité : une crue éclair n'a pas de "niveau d'eau absolu"). Demande explicite du
    # 2026-09-30, au regard de l'épisode de vigilance rouge Gard/Hérault de ce jour-là.
    RUISSELLEMENT = "RUISSELLEMENT", "Ruissellement"


class TacheSimulationInondation(EnvironmentScopedModel):
    """État d'UNE tâche Celery (paliers OU adresses, voir `type_tache`) pour une commune -- UNE
    ligne par (commune, environment, type_tache), écrasée à chaque nouveau lancement (jamais un
    historique) : sert uniquement à savoir si un calcul est déjà en cours pour éviter d'en
    relancer un second en double (deux mairies, ou un même utilisateur qui revient sur la
    page), et à permettre à l'utilisateur de changer de page puis revenir -- l'état vit en
    base, pas dans le navigateur (voir SimulationInondationView)."""

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
    # Distinct du leader (chef d'équipe terrain) : le régulateur pilote l'équipe depuis le
    # centre de crise. Alimenté depuis les utilisateurs ayant le rôle REGULATEUR via
    # AffectationRoleOperationnel, pas une simple promotion du leader.
    regulateur = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="teams_regulees"
    )

    # Temps d'engagement continu sans repos, affiché sur la page Cellule de crise -- None = au
    # repos/pas encore engagée. Volontairement manuel dans les deux sens (TeamViewSet
    # .demarrer_engagement/.mettre_au_repos, décision utilisateur du 26/09) : aucune inférence
    # automatique depuis l'activité (risque de faux repos si l'équipe est juste en attente).
    engagement_debut = models.DateTimeField(null=True, blank=True)
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


class TypeDemandeMobilisation(models.TextChoices):
    MISE_A_DISPOSITION = "MISE_A_DISPOSITION", "Se mettre à disposition"
    SE_RENDRE_A = "SE_RENDRE_A", "Se rendre à un endroit précis"


class StatutDemandeMobilisation(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVOQUEE = "REVOQUEE", "Révoquée"


class DemandeMobilisation(EnvironmentScopedModel):
    """Acte formel par lequel une institution (« l'autorité X ») demande à une personne ou à une
    autre institution (« Y ») de se mettre à disposition ou de se rendre à un endroit précis,
    dans le cadre d'une crise — cadrage du 2026-09-19. Volontairement nommée "demande" et non
    "réquisition" : une réquisition légale au sens strict (article L. 2215-1 du CGCT, ou celles
    prévues par la loi du 13 août 2004) est un pouvoir limité à des autorités précises (préfet,
    maire dans des conditions définies) — cette plateforme n'émet ici qu'une DEMANDE formelle
    tracée, jamais un acte de réquisition au sens juridique, pour ne jamais laisser croire à une
    contrainte légale que ce document ne confère pas réellement (voir la formulation du futur
    PDF/attestation, à reprendre avec la même prudence).

    `jeton_verification` est posé en prévision d'une future attestation PDF + QR code de
    vérification (pas encore construite à ce stade) — même pattern que Offer.deletion_token/
    reponse_token (secrets.token_urlsafe(32), généré côté vue).

    Cible (Y) : exactement UNE des trois ci-dessous doit être renseignée (validé côté
    serializer) — un utilisateur déjà inscrit, une autre institution inscrite, ou une personne
    sans compte connue seulement via une offre d'aide qu'elle a déposée (identité/contact/
    immatriculation déjà saisis à ce moment-là par elle-même, voir Offer)."""

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

    # Pertinents seulement pour SE_RENDRE_A — lieu structuré si un point opérationnel existe
    # déjà (préféré, cohérent avec la carte), texte libre sinon (un lieu de rendez-vous n'a pas
    # toujours de PointOperationnel créé au moment de la demande).
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
    """Secteur de recherche (méthode SAR -- Search And Rescue) : découpe la zone de recherche
    d'une RecherchePersonne en polygones distincts, affectés chacun à une équipe, pour suivre
    ce qui a DÉJÀ été fouillé -- `NoeudMeshUtilisateurViewSet.positions_en_mission`/la carte
    montrent où une équipe EST, pas ce qu'elle a déjà couvert, ce qui ne suffit pas à coordonner
    une recherche au sol sans repasser deux fois au même endroit ni laisser de trou.

    Idée native, demande utilisateur du 10/10 : aucun outil SAR open source équivalent trouvé
    (recherche GitHub du 10/10 -- SARTopo, l'outil le plus proche, n'est pas open source),
    construite pour s'articuler avec RecherchePersonne/Team déjà existants plutôt que reprendre
    quoi que ce soit. Dessin du polygone côté frontend via le même composant que Zone
    (ZoneMapComponent/TerraDraw), pas un nouvel outil de dessin."""

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

    # Catégories du catalogue matériel (MaterielCatalogueCategorie) à masquer dans le
    # sélecteur de stock pour les centres de ce type — ex: un centre d'accueil des personnes
    # (HEBERGEMENT) n'a pas vocation à proposer des engins de déblaiement. Liste vide (défaut)
    # = aucune restriction, comportement inchangé pour tous les types non explicitement seedés.
    # Volontairement une liste d'EXCLUSION plutôt que d'autorisation : n'affecte que les
    # catégories explicitement écartées, sans exiger de choix pour toutes les autres.
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

    # Même idiome que HebergementDetailsMixin.animaux_acceptes (hébergement chez l'habitant) --
    # ici pour un centre d'accueil institutionnel : permet à une personne cherchant un centre de
    # savoir si elle peut y amener son animal (demande utilisateur du 12/10, confirmée par la
    # fiche "Assurer la protection du secteur évacué" d'un PCS réel : "trouver un centre
    # d'accueil acceptant ces animaux").
    accepte_animaux = models.BooleanField(default=False)

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
    catégorie (None) reste un matériel "Autre" générique, cherché/ajouté normalement.

    ENGIN reste dédié au formulaire public (offre d'un particulier). Les 9 catégories
    suivantes structurent le catalogue côté stock de centre (point-inventaire-modal) — voir
    PointType.categories_materiel_exclues pour le filtrage par type de centre."""
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
    """Vocabulaire partagé et extensible des besoins matériel/logistique (lit, nourriture,
    eau...) — même esprit que Competence/InformationType (voir TagLikeViewSetMixin) : n'importe
    quel centre peut ajouter une entrée, immédiatement réutilisable par tous les autres.
    Remplace l'ancien TypeMateriel (TextChoices figé), trop rigide pour ce besoin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=100, unique=True)

    # Voir MaterielCatalogueCategorie — permet de proposer certaines entrées dans une liste à
    # cocher dédiée plutôt que dans la recherche générique "Autre matériel". Distinct de
    # `parent` ci-dessous : cette énumération fixe sert au filtrage du STOCK des centres
    # (point-inventaire-modal, PointType.categories_materiel_exclues), pas à l'organisation du
    # catalogue public.
    categorie = models.CharField(max_length=30, choices=MaterielCatalogueCategorie.choices, null=True, blank=True)

    # Regroupement libre optionnel (sous-matériel), pour l'administration du catalogue et
    # l'affichage en menu déroulant pliable côté formulaire public "Proposer mon aide" — même
    # patron que Besoin.parent/Competence.parent (voir MaterielComponent, admin). Jamais plus
    # d'un niveau, non contraint en base pour rester simple, à respecter côté formulaire.
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sous_materiels",
    )

    # Permet de retirer une entrée obsolète/en doublon (ex: un nom qui duplique une des options
    # structurelles fixes d'Offer.materiel_type) de la sélection publique sans la supprimer —
    # les offres existantes qui la référencent (Offer.materiel_catalogue) restent intactes.
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
    # Distinct de BENEVOLE_AUTRE_EQUIPE (qui reste tel quel, déjà en base) : un intervenant
    # logé pour une mission longue, pas forcément rattaché à "une autre équipe" au sens où
    # cette valeur le sous-entendait -- voir "Logement intervenants" (24/09).
    INTERVENANT = "INTERVENANT", "Intervenant mobilisé (logement multi-jours)"
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
    """Réservation d'un logement (centre OU offre de particulier validée -- exactement l'un
    des deux, jamais les deux ni aucun) pour un intervenant sur une crise donnée -- vue
    "Ressources mobilisées" (24/09, réflexion avec Sylvain). Distinct de RegistrePresence (le
    "secrétariat" d'un point, qui constate une arrivée effective sur place) : ceci est la
    décision/planification prise depuis le bureau, avant même que la personne parte. Une
    nouvelle ligne à chaque réaffectation plutôt qu'un update -- garde l'historique, "le
    logement actuel" = la ligne la plus récente pour ce couple (intervenant, crise), voir
    TeamViewSet.ressources_mobilisees."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    intervenant = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="affectations_logement",
    )
    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, related_name="affectations_logement",
    )
    # CASCADE (pas SET_NULL) sur les deux : la contrainte XOR ci-dessous exige TOUJOURS
    # exactement une cible -- un SET_NULL déclenché par la suppression du point/de l'offre
    # violerait cette contrainte (constaté en testant : IntegrityError à la suppression d'un
    # point ayant des affectations). Supprimer un logement supprime donc ses réservations,
    # jamais une ligne orpheline sans cible.
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
    """Suivi d'état/maintenance d'une offre de matériel (24/09, "fiche matériel" -- demande
    explicite : état, commentaire libre, qui répare, où/quand/combien coûte la réparation,
    documents). Pas de champ "état courant" séparé -- même patron que
    AffectationLogementIntervenant : l'état actuel est celui du plus récent événement (voir
    Meta.ordering), une nouvelle ligne à chaque changement garde l'historique complet des
    pannes/réparations plutôt qu'un simple update en place.

    Les documents (photos de la panne, facture du réparateur...) passent par le modèle
    Document existant (déjà générique, FK `offre` déjà présente) -- pas de nouveau modèle
    fichier ici, juste un commentaire libre les référençant si besoin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offre = models.ForeignKey("Offer", on_delete=models.CASCADE, related_name="suivi_evenements")

    etat = models.CharField(max_length=20, choices=EtatMateriel.choices)

    commentaire = models.TextField(blank=True, null=True)

    # "qui assure la réparation si nécessaire, ou, quand, combien (si c'est un réparateur
    # pro)" -- texte libre plutôt qu'un annuaire de réparateurs structuré, ce matériel de
    # secours n'a pas vocation à entretenir un tel référentiel.
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

    nom_referent = EncryptedTextField(max_length=80)
    prenom_referent = EncryptedTextField(max_length=60)
    contact_referent = EncryptedTextField(
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
    ages_enfants = EncryptedJSONField(default=list, blank=True)

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
    """Catalogue partagé des types de risques majeurs -- même esprit que Competence/
    MaterielCatalogue (voir TagLikeViewSetMixin) : librement extensible, n'importe quelle
    commune peut déclarer un risque jamais vu ailleurs (ex: incendie de forêt) sans attendre
    une mise à jour de l'app -- confirmé nécessaire (pas juste un confort) en croisant 3 vrais
    PCS le 12/10 : aucune des 3 communes lues (Floirac, Saint-Sixt, Canet-de-Salars) n'a la même
    liste de risques (nucléaire, rupture de barrage, radon... chacun propre à une poignée de
    communes). `generalites` est le texte générique (indépendant de la commune, structure
    "DICRIM" : nature du risque, mécanismes) -- à distinguer de RisqueCommunal, qui porte ce qui
    est propre à CHAQUE commune (état des lieux, enjeux)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=100, unique=True)
    generalites = models.TextField(blank=True, help_text="Description générique du risque, indépendante de la commune.")
    actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom


class RisqueCommunal(EnvironmentScopedModel):
    """Ce qu'UNE institution déclare à propos d'un RisqueMajeurType : son état des lieux local
    (zones concernées, historique...) et ses enjeux (population/bâtiments exposés) -- voir
    structure "État des lieux"/"Enjeux communaux" d'un PCS. EnvironmentScopedModel (contrairement
    à RisqueMajeurType, catalogue global) : une déclaration DEMO ne doit jamais se mélanger avec
    une vraie déclaration PROD."""
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


class TypeVulnerabilite(models.Model):
    """Catalogue partagé des catégories de vulnérabilité pour le registre communal des personnes
    vulnérables (voir PersonneVulnerable) -- même esprit que RisqueMajeurType/Competence (voir
    TagLikeViewSetMixin) : librement extensible, un item non prévu peut être ajouté à la volée et
    réutilisé ensuite par tout le monde. IMPORTANT (exigence RGPD actée avec Sylvain) :
    description FONCTIONNELLE/OPÉRATIONNELLE uniquement (ce dont la personne a besoin en cas
    d'évacuation/alerte) -- JAMAIS un diagnostic médical ni une donnée de santé (catégorie
    spéciale RGPD art. 9, hors de portée de ce registre). C'est délibérément un catalogue
    coché/pas coché plutôt qu'un champ de notes libres à côté : un champ "notes" est justement la
    porte par laquelle une description médicale finirait par se glisser."""
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
    """Registre communal des personnes vulnérables (recensement PCS, voir art. L121-6-1 du
    CASF) -- fiche PERMANENTE (pas liée à une crise précise, contrairement à Habitation), radiée
    via `actif=False` mais jamais supprimée physiquement, même patron que RisqueCommunal.

    Donnée très sensible : accès contrôlé exclusivement via core/vulnerabilites.py (jamais une
    permission générique type IsInstitutionalActor seule) -- réservé à la RCSC/aux RESPONSABLE
    désignés de la mairie compétente sur la commune, ou à une institution tierce avec une
    DelegationCompetence active sur la compétence "Recensement personnes vulnérables" pour cette
    commune. Champs identifiants chiffrés au repos (EncryptedTextField, clé FIELD_ENCRYPTION_KEY
    déjà utilisée ailleurs dans ce fichier -- pas de nouvelle clé, ce n'est pas un fichier comme
    PieceIdentiteReserve)."""
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


class MeshCoreConnexionType(models.TextChoices):
    TCP = "TCP", "TCP (réseau)"
    SERIE = "SERIE", "Série (USB)"
    BLE = "BLE", "Bluetooth (BLE)"


class CompagnonMeshCore(EnvironmentScopedModel):
    """Nœud MeshCore en rôle Companion utilisé comme passerelle entre le mesh radio et
    assista-crise, piloté par le service-pont (`meshcore-bridge/`, hors de ce dépôt Django,
    service asyncio permanent utilisant `meshcore-py`) — PAS un nœud personnel de terrain, voir
    NoeudMeshUtilisateur pour ça. Une institution peut avoir plusieurs companions (redondance,
    ou un par poste de commandement) ; `principal` désigne celui utilisé par défaut pour les
    envois. Phase de test (voir doc de conception « Maillage Terrain ») : `institution` reste
    facultative pour permettre un premier companion de test non rattaché."""

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

    # Position du companion physique (poste de commandement, véhicule...) — saisie manuelle,
    # pour l'afficher sur la carte au même titre que les répéteurs (RelaisMeshCore) et servir
    # plus tard à choisir automatiquement le companion le plus proche d'un destinataire quand
    # plusieurs passerelles seront réparties sur le territoire (voir doc de conception).
    location = gis_models.PointField(srid=4326, null=True, blank=True)

    principal = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    # Convention COMMUNAUTAIRE de canal régional (ex: "fr-naq" pour Nouvelle-Aquitaine) — PAS
    # une notion imposée par le firmware/protocole MeshCore (vérifié : aucune ACL ni aucun
    # découpage régional protocolaire n'existe côté MeshCore, l'ACL du firmware est une table de
    # permissions par répéteur/room server, sans rapport avec la géographie). Simple étiquette
    # texte libre, saisie par un administrateur — sert à core.routage_mesh.
    # meilleur_compagnon_pour_contact pour repérer quel companion est réputé couvrir quelle
    # région quand aucun contact direct n'est encore connu pour un destinataire donné.
    region_tag = models.CharField(max_length=20, blank=True)

    derniere_connexion = models.DateTimeField(null=True, blank=True)
    dernier_etat = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Rapporté par le service-pont : CONNECTE / DECONNECTE / ERREUR.",
    )
    derniere_erreur = models.TextField(null=True, blank=True)

    # Batterie du companion LUI-MÊME (pas un nœud de terrain) -- commande locale get_bat(),
    # sans coût d'antenne mesh (voir boucle_batterie_compagnon côté pont) : interrogeable bien
    # plus souvent qu'une télémétrie de nœud distant. Valeur BRUTE de la réponse firmware
    # GET_BATT_AND_STORAGE (unité non confirmée sur le matériel réel de ce projet, probablement
    # des millivolts) -- un autre client (Home Assistant) la sonde déjà via le même proxy
    # toutes les 5s sans problème (voir meshcore-bridge/proxy.py), donc la fréquence n'est pas
    # la contrainte ici, seulement l'incertitude d'unité.
    derniere_batterie_niveau = models.PositiveIntegerField(null=True, blank=True)
    derniere_batterie_date = models.DateTimeField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} ({self.connexion_type})"


class NoeudMeshUtilisateur(EnvironmentScopedModel):
    """Correspondance entre la clé publique d'un nœud MeshCore de terrain (Companion personnel)
    et un compte utilisateur assista-crise — sans ça, le service-pont ne sait pas qui a envoyé
    un message reçu sur le mesh."""

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
    """Message mesh ENTRANT détecté comme une possible urgence -- mot-clé SOS/urgence (voir
    core.views._detecter_mot_cle_sos), ou arrivé sur un canal nommé par convention
    communautaire pour les communications d'urgence (ex: "Fr_EMCOM" chez Meshtastic/Gaulix,
    voir core.views._canal_est_dedie_urgence). Adapté de la détection de mots-clés de
    Mesh-Bridge (github.com/IceNet-01/Mesh-Bridge), demande utilisateur du 10/10.

    Ne crée PAS automatiquement de Request/DeclarationSecurite : un faux positif deviendrait
    sinon une fausse alerte officielle dans le système métier. Se contente de notifier les
    administrateurs (email + DM Matrix, voir core.views._signaler_sos_mesh) pour une
    vérification humaine rapide -- cette ligne EST la trace de cette notification."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    protocole = models.CharField(max_length=10, choices=ProtocoleMesh.choices)

    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="alertes_sos_mesh",
    )

    # Vide pour un message privé (DM) -- un canal seulement.
    canal_nom = models.CharField(max_length=100, null=True, blank=True)

    # Clé publique (MeshCore) ou node_num (Meshtastic, converti en texte) si connu -- sert de
    # clé d'anti-rafale (voir _signaler_sos_mesh), pas une FK (l'expéditeur réel n'est pas
    # toujours résolu en compte utilisateur, notamment sur un canal).
    expediteur_identifiant = models.CharField(max_length=64, null=True, blank=True)
    # Chiffrés (voir core/crypto_fields.py) comme les autres champs texte libre pouvant porter
    # du PII dans ce projet (ex: RecherchePersonne.description, DeclarationSecurite.commentaire)
    # -- un message mesh entrant peut contenir un nom, une localisation, une description de
    # blessure, et c'est précisément le contenu capturé ici.
    expediteur_nom = EncryptedTextField(max_length=100, blank=True)
    contenu = EncryptedTextField()
    mot_cle_detecte = models.CharField(max_length=50)

    notification_envoyee = models.BooleanField(default=False)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SOS mesh « {self.mot_cle_detecte} » ({self.protocole}, {self.date_creation:%d/%m %H:%M})"


class MessageMeshLog(EnvironmentScopedModel):
    """Journal des DM échangés via MeshCore — phase de test : un log plat, pas encore le
    cloisonnement strict de visibilité par équipe prévu dans la conception définitive (voir doc
    de conception « Maillage Terrain », principe « administrer un companion n'est pas lire les
    messages ») puisqu'il n'y a pour l'instant qu'un usage de test, pas de vraies équipes
    terrain sur le mesh."""

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

    # Équipe de l'expéditeur au moment de la réception — capturée à la création, pas
    # recalculée dynamiquement (un message déjà journalisé garde son contexte même si la
    # personne change d'équipe ensuite). C'est ce qui porte le cloisonnement de visibilité :
    # administrer un companion n'est pas lire les messages (voir doc de conception « Maillage
    # Terrain ») — seuls le leader et le régulateur de CETTE équipe voient ce message.
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
    """Commande ponctuelle à exécuter par le pont sur SON PROPRE companion (ex: annoncer sa
    présence sur le mesh) — même mécanisme de file d'attente que MessageMeshLog (le pont
    interroge périodiquement plutôt que d'exposer un port entrant sur son conteneur, voir
    meshcore-bridge/bridge.py:boucle_commandes), pour des actions qui ne sont pas des messages.
    Volontairement limité à l'appareil directement connecté : piloter un relais distant (ex:
    un répéteur) nécessite une authentification déportée (login administrateur du relais,
    protocole différent) hors du périmètre de cette file pour l'instant."""

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
    """Diagnostic réseau MeshCore : chemin radio (répéteurs traversés + SNR par saut) suivi par
    un paquet de trace en diffusion (send_trace, lib meshcore_py) -- adapté de la fonctionnalité
    traceroute de MeshMonitor (github.com/Yeraze/meshmonitor), demande utilisateur du 10/10.

    Toujours en mode FLOOD (pas de chemin forcé en paramètre, même si send_trace le permettrait)
    -- le plus simple et le plus fiable : mesure directement la couverture radio réelle du
    companion (quels répéteurs sont traversés, quel SNR par saut), sans cible obligatoire.
    Corrélation requête/réponse via `tag` (voir EventType.TRACE_DATA côté lib) -- un pur
    identifiant protocolaire, pas une clé primaire fonctionnelle, conservé pour diagnostic.

    Chaque ligne est un instantané : la topologie mesh est dynamique, le chemin peut changer
    d'une exécution à l'autre, aucune corrélation garantie entre deux lignes consécutives."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshCore, on_delete=models.CASCADE, related_name="traceroutes")

    # PositiveBigIntegerField : `tag` est un entier 32 bits NON SIGNÉ côté protocole
    # (random.randint(1, 0xFFFFFFFF) côté pont, voir boucle_traceroutes) -- jusqu'à
    # 4294967295, qui dépasse le plafond signé 32 bits d'un PositiveIntegerField ordinaire
    # (2147483647) et provoque une erreur PostgreSQL "integer out of range" à l'écriture
    # (constaté en test réel le 10/10, corrigé avant tout déploiement en prod).
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
    """Répéteur MeshCore (infrastructure pure — ne se pilote pas comme un Companion, ne se
    connecte à rien : c'est un point fixe posé sur le terrain). Sa position est le plus souvent
    importée automatiquement (voir CompagnonMeshCoreViewSet.synchroniser_contacts : un
    répéteur détecté dans le répertoire du companion, avec position GPS connue, crée/met à
    jour directement l'entrée ici, identifiée par pubkey_hex — plus besoin du bouton "Importer"
    manuel) ; peut aussi être saisie manuellement pour un répéteur pas encore détecté."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="relais_meshcore",
    )

    nom = models.CharField(max_length=100)

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    # unique (NULL excepté, comportement standard SQL) : un répéteur détecté deux fois via
    # synchroniser_contacts (compagnons différents, ou resynchronisation) ne doit jamais créer
    # de doublon — l'import automatique s'appuie dessus (get_or_create par pubkey_hex).
    pubkey_hex = models.CharField(max_length=64, null=True, blank=True, unique=True)

    actif = models.BooleanField(default=True)

    commentaire = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nom


class CanalMeshCore(EnvironmentScopedModel):
    """Canal MeshCore (clé partagée, diffusion à N destinataires) — visibilité large
    (institution/crise), à la différence des DM privés (MessageMeshLog, cloisonnés par
    équipe). Sert à la coordination générale, jamais à du contenu sensible : le chiffrement
    par clé partagée est plus faible que le chiffrement par paire des DM (voir doc de
    conception).

    `equipe` (optionnel) fait de ce canal LE canal privé d'une équipe — la réponse au problème
    de routage des DM (MessageMeshLog.equipe résolu via `expediteur.teams.first()`, arbitraire
    dès qu'un utilisateur appartient à plusieurs équipes) : un message de canal appartient sans
    ambiguïté à l'équipe du canal sur lequel il est arrivé. La clé elle-même reste distribuée
    en privé (DM, jamais un nom de canal préfixé `#` dont la clé serait dérivable par tout le
    monde) — voir TeamViewSet.provisionner_canal_meshcore. Un DM direct régulateur <-> personne
    reste possible en plus (MessageMeshLog), pour du contenu vraiment 1-à-1.

    `compagnon`/`canal_idx` : un canal MeshCore se configure localement sur CHAQUE appareil qui
    doit y participer (firmware, commande set_channel — pas une simple donnée serveur qui se
    propagerait sur le mesh) — impossible de le pousser à distance sur le nœud personnel d'un
    membre, qui doit configurer lui-même canal_idx/nom/clé reçus par DM. Le service-pont, lui,
    provisionne automatiquement CE champ sur le companion partagé auquel il est connecté (voir
    boucle_provisionnement_canaux côté pont) afin de pouvoir envoyer/recevoir sur ce canal en
    son nom — un seul companion actif dans cette phase de test, donc un seul (compagnon,
    canal_idx) par canal suffit."""

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

    # Clé partagée du canal — sensible mais nécessaire au service-pont pour déchiffrer/envoyer
    # sur ce canal. Jamais renvoyée en clair par l'API (voir serializer, write_only). 16 octets
    # (32 hex) imposés par le firmware (voir set_channel côté pont) pour un canal privé — pas
    # dérivée d'un nom public comme le fait le firmware pour un canal préfixé `#`.
    cle_partagee_hex = models.CharField(max_length=64, null=True, blank=True)

    compagnon = models.ForeignKey(
        "CompagnonMeshCore", on_delete=models.SET_NULL, null=True, blank=True, related_name="canaux_provisionnes",
    )
    canal_idx = models.PositiveSmallIntegerField(null=True, blank=True)

    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def derive_cle_publique(nom: str) -> str:
        """Dérivation de clé d'un canal public préfixé `#` (ex: "#meteo") -- même algorithme que
        le firmware (set_channel, voir meshcore_py commands/device.py:
        sha256(nom)[:16 octets]), calculable par n'importe qui connaissant juste le nom : c'est
        tout le principe d'un canal public, contrairement à un canal d'équipe dont la clé doit
        rester distribuée en privé (voir docstring de la classe). Voir CanalMeshCoreSerializer."""
        return hashlib.sha256(nom.encode("utf-8")).hexdigest()[:32]

    # Clé du canal "Public" PRÉCONFIGURÉ (slot 0, réservé -- voir docstring de
    # CanalMeshCoreObsolete et meshcore-bridge/bridge.py:CANAL_IDX_MAX) de la même façon sur
    # TOUT appareil MeshCore de sortie d'usine -- valeur documentée par le projet lui-même
    # (docs.meshcore.io/companion_protocol), jamais une clé d'équipe ni spécifique à cette
    # installation. Contrairement à un canal `#nom` choisi par quelqu'un (nom impossible à
    # deviner depuis le seul chan_hash observé sur l'air, fonction à sens unique), celui-ci est
    # universel et connu à l'avance : on peut donc le reconnaître et le rendre utilisable
    # automatiquement dès qu'un companion capte effectivement son trafic (voir
    # CompagnonMeshCoreViewSet.signaler_canaux_detectes), sans qu'un humain ait à le nommer ou
    # fournir sa clé. Confirmé en conditions réelles le 11/10 : le canal détecté le plus actif
    # (chan_hash "11", 47 paquets) correspondait exactement à cette clé.
    SECRET_PUBLIC_PAR_DEFAUT = "8b3387e9c5cdea6ac9e5edbaa115cd72"

    @staticmethod
    def chan_hash_pour_secret(secret_hex: str) -> str:
        """chan_hash (1 octet, 2 car. hex) annoncé en clair sur l'air pour un secret donné --
        sha256(secret)[0:1 octet], voir meshcore_py reader.py et docstring de
        CanalMeshCoreDetecte. Sert à reconnaître le canal Public par défaut (SECRET_PUBLIC_
        PAR_DEFAUT) parmi les chan_hash remontés par signaler_canaux_detectes, sans jamais
        avoir eu besoin de connaître un nom."""
        return hashlib.sha256(bytes.fromhex(secret_hex)).hexdigest()[:2]

    def __str__(self):
        return self.nom


class CanalMeshCoreDetecte(EnvironmentScopedModel):
    """Canal MeshCore dont un companion capte le trafic radio (paquet GRP_TXT -- hash de clé
    sur 1 octet, toujours présent sur l'air même sans connaître la clé, voir
    EventType.RX_LOG_DATA côté pont) sans le connaître localement -- typiquement une ancienne
    clé d'équipe encore utilisée par des nœuds qui n'ont pas reçu la rotation, ou un canal tiers
    au voisinage radio. Affiché en lecture seule sur la page canaux MeshCore (demande
    utilisateur du 10/10) : indéchiffrable sans la clé, donc pas de fil de discussion possible,
    juste un signalement de présence. Une ligne par (compagnon, chan_hash) -- mise à jour plutôt
    que recréée à chaque paquet, voir CompagnonMeshCoreViewSet.signaler_canaux_detectes."""

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
    """Ancien slot de canal MeshCore à libérer sur un companion après rotation de clé (voir
    TeamViewSet.provisionner_canal_meshcore, regenerer=true) -- snapshot pris juste avant que
    CanalMeshCore.canal_idx/compagnon ne soient réécrits sur la nouvelle clé, seul moment où
    cette information (quel index libérer, sur quel companion) est encore connue : la rotation
    écrase la seule ligne qui la portait, rien d'autre ne la mémorise.

    Délai de grâce de 48h avant suppression effective (demande utilisateur du 10/10) : la clé
    change immédiatement côté serveur, mais des messages déjà en vol sur l'ancien canal au
    moment de la rotation pourraient encore arriver juste après. Voir
    CompagnonMeshCoreViewSet.canaux_a_liberer / rapporter_canal_libere et
    boucle_nettoyage_canaux côté pont -- "libérer" un slot MeshCore n'a pas de commande
    firmware dédiée, c'est un set_channel avec un nom vide (même convention que
    _trouver_canal_existant_ou_libre côté pont pour reconnaître un slot libre)."""

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
    """Salon Matrix privé d'une équipe (SSO Element/Synapse, voir core/oidc.py) — équivalent
    fonctionnel de CanalMeshCore ("1 équipe = 1 canal privé"), mais indépendant : MeshCore reste
    en place pour son propre usage (portée radio hors réseau), Matrix sert aux échanges enrichis
    et au positionnement PERMANENT en mission (contrairement au suivi MeshCore volontairement
    limité aux missions EN_COURS pour préserver la batterie/le temps d'antenne, voir
    boucle_positions_missions côté pont MeshCore -- aucune contrainte de ce type ici).

    Provisionné explicitement (TeamViewSet.provisionner_salon_matrix), pas automatiquement à la
    création de l'équipe -- une institution choisit d'activer Matrix pour cette équipe, même
    logique opt-in que MeshCore. `room_id` reste vide tant que le pont ne l'a pas créé côté
    Synapse (voir matrix-bridge/bridge.py, boucle_provisionnement_salons) ; une fois posé, le
    pont resynchronise en continu les membres du salon sur `equipe.members`, sans autre action
    manuelle (pas de notion de "régénération" ici, une invitation Matrix ne fuite pas comme une
    clé partagée MeshCore)."""

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
    """PERMANENTS : le personnel de l'institution (rôles institutionnels, voir
    core/matrix.py:membres_permanents_institution). BENEVOLES : tous les membres des équipes
    ACTIVES de l'institution, quel que soit leur rôle -- se vide/remplit automatiquement au fil
    des mobilisations (voir core/matrix.py:membres_benevoles_institution), pas de notion de
    "crise" propre au salon lui-même, juste une photo continue des équipes actives."""
    PERMANENTS = "PERMANENTS", "Permanents"
    BENEVOLES = "BENEVOLES", "Bénévoles mobilisés"


class SalonMatrixInstitution(EnvironmentScopedModel):
    """Salon Matrix général d'une institution (demande explicite de Sylvain le 24/09, en plus
    des salons par équipe SalonMatrixEquipe) -- deux salons distincts par institution, un pour
    le personnel permanent, un pour les bénévoles actuellement mobilisés sur ses équipes
    actives. La composition de CHAQUE salon est recalculée en continu par le pont (voir
    matrix-bridge/bridge.py, boucle_provisionnement_salons_institution), jamais figée à la
    création : un bénévole démobilisé (équipe désactivée, ou retiré de ses équipes) perd
    l'accès au salon BENEVOLES automatiquement, sans action manuelle."""

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
    """Trace du déplacement d'un utilisateur pendant qu'il partage sa position en direct dans le
    salon Matrix de son équipe (balise de position live Element/MSC3489, voir
    matrix-bridge/bridge.py) — contrairement à DernierePositionUtilisateur (un seul
    enregistrement écrasé, capture opportuniste ponctuelle), chaque mise à jour de balise est
    conservée ici pour permettre à un régulateur de rejouer le trajet d'une équipe. Suivi
    PERMANENT tant que le partage de position Element reste actif (demande explicite de
    Sylvain, 23/09) — alimenté uniquement par le pont Matrix, jamais par le frontend Angular
    (qui continue d'utiliser DernierePositionUtilisateur/MaPositionView pour la capture
    opportuniste classique)."""

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
    """Contact tel que connu par UN companion donné (table de contacts déjà tenue par le
    firmware lui-même — voir EventType.CONTACTS dans la lib meshcore, dispatché en fin de
    CONTACT_END avec nom/type/position). Synchronisée périodiquement par le service-pont
    (meshcore-bridge/bridge.py), jamais saisie à la main : c'est le répertoire brut découvert
    sur le mesh, à distinguer de NoeudMeshUtilisateur (association explicite à un compte) et de
    RelaisMeshCore (déclaration manuelle) — sert justement à faciliter ces deux associations."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    compagnon = models.ForeignKey(CompagnonMeshCore, on_delete=models.CASCADE, related_name="contacts")

    pubkey_hex = models.CharField(max_length=64)

    nom = EncryptedTextField(max_length=100, blank=True)

    type_contact = models.CharField(max_length=12, choices=TypeContactMeshCore.choices, default=TypeContactMeshCore.INCONNU)

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    dernier_advert = models.DateTimeField(null=True, blank=True)

    # Nombre de sauts (répéteurs) du chemin connu par CE companion vers ce contact — reflète
    # `out_path_len` de la lib meshcore (voir EventType.CONTACTS/get_contacts,
    # meshcore-bridge/bridge.py:boucle_contacts) : None si aucun chemin connu (sentinel
    # firmware 255, "direct/flood" — pas la même chose que "0 saut", qui signifie un chemin
    # confirmé sans répéteur). Sert à core.routage_mesh.meilleur_compagnon_pour_contact pour
    # préférer, à recense égale, le companion le plus proche (le moins de sauts) d'un
    # destinataire.
    nombre_sauts = models.PositiveSmallIntegerField(null=True, blank=True)

    # Étiquette régionale (convention communautaire, ex: "fr-naq") assignée manuellement à ce
    # contact une fois sa zone connue — aucune inférence automatique (le firmware ne fournit
    # aucune donnée géographique fiable au-delà d'une position GPS optionnelle, souvent absente
    # pour un simple companion de terrain). Sert de repli dans
    # core.routage_mesh.meilleur_compagnon_pour_contact quand aucun chemin direct n'est connu.
    region_tag = models.CharField(max_length=20, blank=True)

    # Télémétrie (canaux LPP "voltage"/"percentage" de la réponse à une requête
    # BinaryReqType.TELEMETRY, voir meshcore-bridge/bridge.py:boucle_positions_missions) --
    # capturée seulement pendant une mission EN_COURS (même requête déjà faite pour la
    # position, voir sa docstring : aucune requête radio supplémentaire, on garde juste plus
    # de la réponse qu'avant). Jamais écrasée par une valeur absente (voir
    # CompagnonMeshCoreViewSet.synchroniser_contacts), donc reste la dernière mesure connue
    # même longtemps après la fin d'une mission.
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
    # Connexion locale directe à un VRAI appareil (API TCP native du firmware, port 4403 par
    # défaut) — via la lib officielle `meshtastic` (TCPInterface), pas le chiffrement fait
    # maison de crypto.py : c'est le firmware lui-même qui gère le PSK/PKI, comme le fait
    # l'appli officielle en WiFi local. Pensé pour l'usage offline (PC sans accès internet,
    # donc sans broker MQTT joignable) — voir meshtastic-bridge/bridge.py:_executer_compagnon_tcp.
    TCP = "TCP", "Connexion locale directe (réseau, sans internet)"
    # Même principe que TCP mais l'appareil est branché en USB directement sur l'hôte du pont
    # (cas d'un satellite Raspberry Pi, voir satellite/docker-compose.yml) — lib officielle
    # `meshtastic` (SerialInterface), voir meshtastic-bridge/bridge.py:_executer_compagnon_serie.
    SERIE = "SERIE", "Connexion série (USB, sans internet)"


class CompagnonMeshtastic(EnvironmentScopedModel):
    """Identité de nœud Meshtastic — soit PUREMENT LOGICIELLE relayée par un broker MQTT tiers
    (ex: Gaulix, `mqtt.gaulix.fr`), soit un VRAI appareil joint en direct par IP locale
    (`connexion_type=TCP`, voir MeshtasticConnexionType) — pilotée par
    meshtastic-bridge/bridge.py. En mode MQTT, il n'y a ni firmware ni radio : `node_num` est un
    identifiant 32 bits que NOUS choisissons nous-mêmes, et le chiffrement (AES-CTR par canal)
    est réimplémenté côté pont — voir meshtastic-bridge/crypto.py, dérivé du firmware officiel
    (CryptoEngine.cpp, Channels.cpp). En mode TCP, `node_num`/le chiffrement sont sans objet
    pour NOUS : le firmware du vrai appareil connecté s'en charge lui-même."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="compagnons_meshtastic",
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
    # Racine de topic MQTT Meshtastic (ex: "msh/EU_868") — dépend de la région radio du réseau
    # relayé, PAS de notre propre matériel puisqu'on n'en a pas : celle du réseau qu'on rejoint.
    # "Traitement/msh/EU_868" et pas "msh/EU_868" pour Gaulix — vérifié en sniffant leur broker
    # en direct (topics réels observés), contrairement à leur documentation publique qui
    # n'indique que la racine "msh/EU_868". Racine différente probable pour un autre réseau.
    topic_racine = models.CharField(max_length=100, default="Traitement/msh/EU_868")

    mqtt_username = models.CharField(max_length=100, blank=True)
    # write_only côté serializer (comme x25519_private_key_hex) — jamais renvoyé en clair par
    # l'API une fois enregistré. Vide = pas d'authentification (cas de certains brokers publics).
    mqtt_password = models.CharField(max_length=255, blank=True)
    mqtt_use_tls = models.BooleanField(default=False)

    # Faux par défaut (fail-closed) : validé en conditions réelles le 13/09 que Gaulix ne relaie
    # de façon fiable QUE le contenu en clair (`decoded`) — un DM/canal chiffré (PSK classique ou
    # PKI) n'a jamais été confirmé reçu par un vrai appareil, cause exacte non identifiée malgré
    # investigation poussée (voir meshtastic-bridge/README.md). Purement déclaratif par broker :
    # tant que ce n'est pas coché, le pont force le clair pour CE companion quoi qu'il arrive,
    # plutôt que de compter sur un admin qui s'en souvient — voir boucle_envoi_dm/boucle_envoi_canaux.
    chiffrement_supporte = models.BooleanField(
        default=False,
        help_text="Décoché par défaut (cas Gaulix) : le pont force alors l'envoi en clair pour "
                   "ce broker, quel que soit le canal/la clé configurés.",
    )

    principal = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    # Paire de clés X25519 (DM chiffrés par clé publique, firmware 2.5+ — voir crypto.py) —
    # générée automatiquement à la création (save()), jamais fournie par le client. La clé
    # privée n'est JAMAIS exposée par l'API (voir CompagnonMeshtasticSerializer, exclue des
    # fields) ; seule la publique est dérivée et montrée pour être communiquée au correspondant.
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
    """Canal Meshtastic (PSK partagée par canal, comme CanalMeshCore) sur lequel notre companion
    logiciel écoute/publie. `nom` DOIT correspondre exactement au nom du canal configuré sur les
    vrais appareils (c'est lui qui compose le topic MQTT : `<topic_racine>/2/e/<nom>/<node_id>`),
    pas une simple étiquette libre côté assista-crise.

    `psk_hex` : vide = pas de chiffrement (canal "public" en clair) ; sinon soit 32 caractères
    hex (PSK complète 16 octets = AES128) ou 64 (32 octets = AES256), soit un octet unique 01-0A
    représentant l'index de PSK "par défaut" du firmware (voir meshtastic-bridge/crypto.py —
    valeurs officielles du protocole, PAS une clé secrète propre à assista-crise). Jamais
    renvoyée en clair par l'API (write_only, comme CanalMeshCore.cle_partagee_hex)."""

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

    # Canal utilisé par défaut pour le nommage du topic MQTT d'un DM chiffré par clé publique
    # (PKI) : dans ce mode le canal ne sert à RIEN pour le chiffrement ni la conversation (voir
    # crypto.py), juste une contrainte technique du protocole (le topic MQTT a besoin d'un nom
    # de canal) — l'utilisateur ne doit pas avoir à en choisir un pour un DM PKI, le pont prend
    # celui-ci automatiquement. Un seul principal actif à la fois (pas de contrainte DB stricte,
    # comme CompagnonMeshtastic.principal).
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
    # Clé publique X25519 annoncée par CE nœud (paquet NodeInfo, champ User.public_key) —
    # nécessaire pour lui envoyer un DM réellement chiffré par clé publique (PKI, firmware
    # 2.5+) plutôt qu'un DM "classique" chiffré avec la PSK d'un canal partagé. Vide si le
    # nœud n'a jamais annoncé de clé (PKI non activé côté firmware) ou pas encore vu.
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
    """Journal des DM Meshtastic — miroir de MessageMeshLog. Un DM Meshtastic « classique »
    (avant PKC) est un MeshPacket adressé (`to`) à un node_num précis mais chiffré avec la PSK
    du canal utilisé (voir `canal`) : la confidentialité vient de l'adressage applicatif, pas
    d'une clé propre au destinataire — quiconque a la PSK du canal peut déchiffrer le contenu
    brut, seul le node visé l'affiche comme un message qui lui est destiné. Le PKC (clé publique
    par nœud, firmware 2.5+) n'est pas encore implémenté ici (voir meshtastic-bridge/crypto.py)."""

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

    # Cible UN companion précis plutôt que "le premier qui passe" -- nécessaire quand un même
    # canal "partagé" (compagnon=None sur CanalMeshtastic, voir sa docstring) est en réalité
    # servi par PLUSIEURS companions actifs en parallèle (ex: un companion TCP local ET le pont
    # MQTT Gaulix) : sans ce champ, les deux pontes interrogent la même file EN_ATTENTE et SE
    # DISPUTENT les mêmes lignes (le premier à répondre les marque ENVOYE, l'autre ne les voit
    # plus jamais) -- aucun des deux chemins n'est alors garanti de transmettre. Laissé à None
    # pour un message normal (comportement historique inchangé, "premier arrivé" reste la
    # règle) ; renseigné explicitement par core.management.commands.verifier_alertes_sismiques
    # pour garantir qu'une alerte Fr_EMCOM parte bien par CHAQUE companion, demande utilisateur
    # du 10/10.
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
    """Jeton court, à usage unique, permettant à un satellite (Raspberry Pi déployé sur site,
    voir Satellite) de prendre contact une première fois avec le central — généré par un
    administrateur/acteur institutionnel pour SON institution, communiqué hors-bande (affiché
    à l'écran, saisi manuellement lors de l'installation du Pi). Ne sert qu'à créer l'entrée
    Satellite (statut EN_ATTENTE, voir SatelliteViewSet.enroler) : les identifiants durables du
    satellite (compte de service dédié) ne sont générés qu'après validation explicite d'un
    administrateur, jamais à ce stade — double validation, même principe que le workflow
    d'acceptation ACTEUR non-AUT_LOCALE (ImplicationInstitutionViewSet)."""

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
    """Boîtier déployé sur site (Raspberry Pi) hébergeant, selon son profil, le pont/proxy
    MeshCore/Meshtastic local (GW) et/ou une instance assista-crise complète utilisable même
    sans internet (FULL) — voir le cadrage "Chantier B" (plan). Initie toujours lui-même la
    connexion sortante vers le central (jamais l'inverse, aucun port entrant à ouvrir sur le
    site distant).

    Pas de mécanisme de heartbeat séparé : `dernier_contact` est mis à jour par tout appel
    authentifié réussi du satellite (voir SatelliteViewSet.contact, futur point d'entrée
    commun des endpoints de synchronisation à venir) — c'est ce même champ, comparé aux seuils
    `SATELLITE_SEUIL_INACTIF_MINUTES`/`SATELLITE_SEUIL_PERDU_MINUTES` (settings), qui dérive
    l'état Actif/Inactif/Perdu exposé par le serializer (jamais stocké tel quel : recalculé à
    la lecture, pour ne jamais avoir un état figé qui ment si personne ne l'a recalculé)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="satellites")

    nom = models.CharField(max_length=100)

    profil = models.CharField(max_length=4, choices=ProfilSatellite.choices)

    statut_enrolement = models.CharField(
        max_length=12, choices=StatutEnrolementSatellite.choices,
        default=StatutEnrolementSatellite.EN_ATTENTE,
    )

    # Compte de service dédié à CE satellite (jamais partagé) — créé uniquement à
    # l'approbation (SatelliteViewSet.valider), authentifié en JWT par le satellite exactement
    # comme le pont MeshCore le fait déjà auprès de l'API (voir meshcore-bridge/bridge.py:
    # DjangoClient) : aucun nouveau mécanisme d'auth introduit ici.
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
    """Modèles couverts par la synchronisation local -> central (voir core/sync_outbox.py) —
    périmètre v1 (2026-09-18) : le travail des acteurs institutionnels sur place pendant une
    coupure (Dossier + son fil de commentaires/historique, DeclarationSecurite, Mission,
    MessageMeshLog). Explicitement PAS Request/Offer/Information : alimentés par les citoyens
    via internet, jamais via le LAN privé d'un satellite (voir le cadrage Chantier B) —
    ajoutables plus tard sans redesign, juste une nouvelle entrée ici + un sérialiseur dédié."""
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
    """Une écriture locale à propager vers le central — peuplé par des signaux Django
    (post_save), UNIQUEMENT quand `settings.INSTANCE_SATELLITE_LOCALE` est vrai (jamais côté
    central lui-même, sinon boucle). Consommé par la commande de gestion
    `synchroniser_sortant` (tournant dans le conteneur `sync-sortant` du profil Full, voir
    satellite/docker-compose.yml), qui pousse les événements EN_ATTENTE dans l'ordre
    chronologique vers `SatelliteViewSet.synchroniser`.

    Écriture toujours locale d'abord (le modèle métier est déjà sauvegardé quand cet
    enregistrement est créé) ; propagation asynchrone ensuite — jamais de connexion synchrone
    bloquante au moment de l'écriture, même principe que CommandeMeshCore/MessageMeshLog."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    modele = models.CharField(max_length=30, choices=ModeleSynchronisable.choices)
    objet_id = models.UUIDField()
    action = models.CharField(max_length=15, choices=ActionSynchronisation.choices)

    # Snapshot des champs pertinents au moment de l'écriture locale — un dict simple (pas un
    # sérialiseur DRF réutilisé : `author`/`id` sont read_only sur les sérialiseurs d'admin
    # existants, voir la note du cadrage Chantier B sur ce sujet), construit par
    # core/sync_outbox.py.
    payload = models.JSONField()

    # Valeur de `modifie_le` (côté modèles mutables uniquement, voir ModeleSynchronisable côté
    # DOSSIER/MISSION) connue AVANT la première écriture locale hors-ligne sur cet objet — sert
    # à détecter, côté central, si quelqu'un d'autre l'a modifié entre-temps (conflit) plutôt
    # que d'écraser silencieusement. Null pour les modèles "append-only" (DossierCommentaire,
    # DossierHistorique, DeclarationSecurite, MessageMeshLog) : jamais réédités après création,
    # donc jamais de conflit possible sur eux — un simple upsert par id suffit.
    version_de_base = models.DateTimeField(null=True, blank=True)

    # Snapshot du véritable auteur local (peut n'exister QUE côté local, pas encore de compte
    # web — voir la note du cadrage sur le compte auto-créé, non construit à ce jour). L'auteur
    # apparent côté central reste le compte de service du satellite (décision utilisateur du
    # 2026-09-18) ; ces deux champs permettent de retrouver qui a vraiment agi, affichés dans le
    # commentaire d'audit posé à l'application de l'événement.
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
    """Créé côté CENTRAL quand un événement de synchronisation mutable (Dossier/Mission) arrive
    avec une `version_de_base` qui ne correspond plus à l'état central actuel — quelqu'un
    (central ou un autre satellite) a modifié cet objet entre-temps. Jamais résolu
    automatiquement (principe déjà acté au cadrage Chantier B : "jamais un choix automatique
    silencieux") : un administrateur choisit explicitement quoi garder."""

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

