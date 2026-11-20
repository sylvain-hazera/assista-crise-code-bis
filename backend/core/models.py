import datetime
import hashlib
import secrets
import uuid
import os
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from core.validators import validate_image_file
from .validators import (
    validate_convention_file, validate_identity_document_file, validate_image_file,
)
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

    # Compte de service d'un pont radio (meshcore-bridge / meshtastic-bridge). Seuls ces
    # comptes, les comptes de service de satellite et les administrateurs réels peuvent lire
    # les endpoints qui exposent un SECRET en clair : mot de passe MQTT, clé privée X25519,
    # PSK de canal (voir core/permissions.py:EstComptePont). Avant le 07/11/2026, « authentifié »
    # suffisait : n'importe quel citoyen inscrit pouvait lire ces secrets.
    #
    # Se pose à la main, une fois, et jamais depuis l'API :
    #     manage.py marquer_compte_pont <email>
    compte_service_pont = models.BooleanField(
        default=False,
        help_text="Compte de service d'un pont radio : autorisé à lire les secrets mesh "
                   "(mot de passe MQTT, clés). À poser avec manage.py marquer_compte_pont.",
    )
    # Compte utilisé par un PROGRAMME et non par une personne (pont Matrix, script…), quand il
    # n'est ni un pont radio (`compte_service_pont`) ni le compte de service d'un satellite.
    # Une machine n'a pas de téléphone : elle n'est jamais tenue d'avoir un second facteur
    # (voir core/second_facteur.py). Sans ce marquage, un compte de service doté d'un rôle
    # serait pris pour un compte à pouvoir et cesserait de se connecter au bout de quinze jours.
    # N'ouvre AUCUN droit. Se pose à la main, jamais depuis l'API :
    #     manage.py marquer_compte_machine <email>
    compte_machine = models.BooleanField(
        default=False,
        help_text="Compte utilisé par un programme : dispensé de second facteur. "
                   "À poser avec manage.py marquer_compte_machine.",
    )
    postal_code = EncryptedTextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)

    # Date limite pour activer le second facteur (code à usage unique). Posée la première fois
    # que le compte est reconnu « à pouvoir » sans second facteur, à J+15 (décision de Sylvain du
    # 15/11/2026) : jusque-là le site rappelle, après il n'ouvre plus de session sans
    # activation. Voir `core/second_facteur.py`. Vide = jamais concerné jusqu'ici.
    second_facteur_exige_le = models.DateTimeField(null=True, blank=True, editable=False)

    # Renseignements institutionnels de l'inscription, appliqués seulement après confirmation de
    # l'email.
    pending_institution_name = EncryptedTextField(max_length=255, null=True, blank=True)
    pending_institution_type = models.CharField(max_length=100, null=True, blank=True)
    pending_commune_name = EncryptedTextField(max_length=255, null=True, blank=True)
    pending_commune_code = models.CharField(max_length=20, null=True, blank=True)

    # ── CE CHAMP N'EST PAS L'APPARTENANCE ────────────────────────────────────────────────
    #
    # « Dans quelle institution est cette personne » a deux réponses en base, et une seule fait
    # autorité : `ContactInstitution`, qui est une table de LIAISON — autant de lignes que
    # d'appartenances. Quelqu'un peut être à la fois agent d'une mairie et adhérent d'une
    # association, et c'est le cas courant, pas l'exception (8 comptes sur 54 en novembre 2026).
    #
    # Ce champ-ci est le **contexte actif** : l'institution pour laquelle la personne travaille
    # EN CE MOMENT. Il pilote la « Vue Ma Collectivité », le périmètre territorial
    # (`core/zone_scoping.py`) et le branding des emails. Il est posé au premier rattachement
    # (`ContactInstitution.save`, qui ne le détourne jamais s'il est déjà rempli) et se change
    # explicitement — voir `core/institution_courante.py` et
    # `POST /api/me/institution-active/`.
    #
    # **Ne jamais lire ce champ pour répondre « est-il membre de X ? »** : interroger
    # `ContactInstitution`. Un compte multi-appartenance n'aurait ici que l'une de ses
    # institutions, et laquelle dépendrait de l'ordre de ses inscriptions.
    institution = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="utilisateurs",
        help_text="Institution ACTIVE (contexte de travail), pas la liste des appartenances : "
                  "celle-ci vit dans ContactInstitution.",
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    # Chiffré ; l'unicité porte sur email_bidx.
    email = EncryptedEmailField()
    # Chiffrés aussi (18/11/2026, « tout doit être chiffré en base ») : l'identifiant reçoit le
    # plus souvent l'adresse elle-même, il annulait le chiffrement de `email`. Plus d'unicité
    # sur l'identifiant : la connexion et l'unicité passent par email_bidx. Les recherches par
    # nom se font en Python, après déchiffrement (décision du 06/10/2026).
    username = EncryptedTextField(max_length=150, blank=True, default="")
    first_name = EncryptedTextField(max_length=150, blank=True, default="")
    last_name = EncryptedTextField(max_length=150, blank=True, default="")
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

    # Engagement au secret professionnel sur le registre communal des personnes vulnérables
    # (art. R. 121-7 du CASF : les personnes qui traitent ces données y sont tenues). Porté par
    # le compte et non par l'habilitation, parce que l'engagement suit la PERSONNE : un agent
    # habilité sur deux communes, ou une association délégataire qui n'a pas d'habilitation
    # nominative, le signent une fois pour toutes. La version stockée permet de redemander la
    # signature si le texte change -- un engagement pris sur un autre texte n'engage à rien.
    engagement_secret_registre_le = models.DateTimeField(null=True, blank=True)
    engagement_secret_registre_version = models.CharField(max_length=20, blank=True, default="")

    def save(self, *args, **kwargs):
        self.email_bidx = blind_index(self.email)
        # Numéro enregistré en E.164 (« +262692123456 »), quelle que soit la façon dont il a
        # été saisi : c'est la seule écriture que tous les fournisseurs de SMS acceptent, et
        # la seule qui dise de quel PAYS il s'agit (voir core/telephone.py). Posé ici et non
        # dans les sérialiseurs, pour couvrir aussi les imports de fichiers et les scripts.
        # Un numéro illisible est conservé TEL QUEL : l'écraser ferait perdre le seul moyen
        # de joindre quelqu'un.
        if self.phone_number:
            from .telephone import normaliser

            self.phone_number = normaliser(self.phone_number) or self.phone_number
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
    description = EncryptedTextField(null=True, blank=True)
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
    # Quand les demandes, offres et signalements des habitants ont été purgés (cleanup_crises).
    # La crise elle-même reste : sa main courante, ses rapports, ses biens sinistrés et ses
    # dossiers de relogement vivent bien au-delà de trente jours.
    donnees_habitants_purgees_le = models.DateTimeField(null=True, blank=True)

    # Clôture en deux temps (core/cloture_crise.py) : proposée, puis effective sept jours plus
    # tard, le temps que chacun récupère son rapport. Vides tant que rien n'est proposé.
    fermeture_proposee_le = models.DateTimeField(null=True, blank=True)
    fermeture_proposee_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="fermetures_proposees")
    fermeture_prevue_le = models.DateTimeField(null=True, blank=True)

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
    acteur opérationnel. Les deux peuvent coexister.

    **C'est aussi la porte qui ouvre le territoire** à une institution qui n'en a pas (une
    AASC nationale, typiquement). Règle posée le 28/10/2026 : par défaut les droits valent
    **pour la crise et commune par commune** — `communes` dit lesquelles, et une liste vide
    signifie toutes celles de la crise. Chaque mairie accepte ainsi pour son seul territoire
    sur une crise multi-communes, sans voir ni bloquer les décisions des autres.

    Les droits de longue durée, eux, ne passent pas par ici : c'est l'objet d'une convention,
    portée par DelegationCompetence (qui a déjà ses `communes`, son `active` et sa `date_fin`).
    Les deux sources sont réunies par `zone_scoping.communes_accordees`.

    On ne duplique volontairement pas la notion de mandat : le périmètre fin se pose ICI, sur
    l'implication qui gouverne déjà les droits, plutôt que dans un second modèle qui finirait
    par diverger de celui-ci."""

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

    commentaire = EncryptedTextField(blank=True, null=True)

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

    communes = models.JSONField(
        default=list, blank=True,
        help_text="Codes INSEE des communes de la crise sur lesquelles cette institution est "
                  "acceptée. Liste vide = toutes les communes de la crise.",
    )

    # Chaque mairie décide chez elle (17/11/2026). `communes` dit où l'institution est
    # acceptée, `communes_refusees` où une mairie a dit non ; une commune de la crise absente
    # des deux attend encore la réponse de sa mairie. Voir core/accords_communes.py.
    communes_refusees = models.JSONField(
        default=list, blank=True,
        help_text="Codes INSEE des communes de la crise dont la collectivité a refusé "
                  "l'intervention de cette institution.",
    )

    # Une collectivité qui envoie sa réserve communale AILLEURS que chez elle. Sans ce
    # marqueur, une mairie qui se déclare acteur dit « ma commune est touchée » : la zone de
    # la crise s'étend à son territoire et elle est acceptée d'office partout. En renfort,
    # rien de cela : la zone ne bouge pas, et le maire de chaque commune d'accueil donne son
    # accord, comme pour une association.
    renfort = models.BooleanField(
        default=False,
        help_text="Intervient en renfort hors de son territoire : l'accord de chaque commune "
                  "d'accueil est requis, et la zone de la crise n'est pas étendue.",
    )

    # Ce que l'institution met à disposition (codes de core/aides_renfort.py) : centre
    # d'accueil, point de regroupement, personnel... Le détail va dans `commentaire`.
    aides_proposees = models.JSONField(default=list, blank=True)

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
    # La commune n'est concernée que sur les zones qu'elle a dessinées (ZoneAjouteeCrise) : son
    # code reste dans zone_communes, parce qu'il porte les droits et l'accord de son maire, mais
    # son contour entier n'entre pas dans la zone composée. Voir core/zones_crise.py.
    partielle = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["crise", "commune_code"], name="uq_contribution_zone_crise_commune"),
        ]

    def __str__(self):
        return f"{self.commune_code} sur {self.crise} ({self.institution or 'sans propriétaire'})"


class FormulaireTerrain(EnvironmentScopedModel):
    """Un questionnaire de terrain composé par une collectivité (voir
    core/formulaires_terrain.py) : évaluation de dégâts, recensement de besoins, visite de
    site... `questions` est la liste validée par `nettoyer_questions`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="formulaires_terrain")
    crise = models.ForeignKey(
        Crisis, on_delete=models.SET_NULL, null=True, blank=True, related_name="formulaires_terrain")
    titre = EncryptedTextField(max_length=150)
    description = EncryptedTextField(blank=True, default="")
    questions = models.JSONField(default=list)
    # Fermé : il reste lisible avec ses réponses, mais on n'y répond plus.
    actif = models.BooleanField(default=True)
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="formulaires_terrain_crees")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return self.titre


class ReponseFormulaireTerrain(EnvironmentScopedModel):
    """Une réponse à un questionnaire de terrain. Chiffrée ; seule la position reste lisible,
    parce que PostGIS doit la lire.

    `identifiant_client` est tiré sur l'appareil au moment de la saisie : une réponse renvoyée
    après une coupure de réseau n'est enregistrée qu'une fois."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    formulaire = models.ForeignKey(FormulaireTerrain, on_delete=models.CASCADE, related_name="reponses")
    auteur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reponses_formulaires_terrain")
    institution_auteur = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reponses_formulaires_terrain")
    identifiant_client = models.UUIDField()
    donnees = EncryptedTextField()
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    saisie_le = models.DateTimeField(null=True, blank=True)
    date_reception = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_reception"]
        constraints = [
            models.UniqueConstraint(
                fields=["formulaire", "identifiant_client"], name="uq_reponse_formulaire_identifiant_client"),
        ]


class ZoneAjouteeCrise(EnvironmentScopedModel):
    """Une zone dessinée EN PLUS de la zone initiale d'une crise (17/11/2026).

    Elle ne modifie pas `Crisis.zone`, peut ne pas la toucher, et reste attachée à
    l'institution qui l'a dessinée : elle seule, l'auteur de la crise ou un administrateur
    peuvent la retirer. Même règle de provenance que ContributionZoneCommune."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crise = models.ForeignKey(Crisis, on_delete=models.CASCADE, related_name="zones_ajoutees")
    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="zones_ajoutees_crises",
    )
    auteur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="zones_ajoutees_crises",
    )
    nom = models.CharField(max_length=100, blank=True, default="")
    geometrie = gis_models.PolygonField(srid=4326)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_creation"]

    def __str__(self):
        return f"{self.nom or 'Zone'} sur {self.crise}"


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
    title = EncryptedTextField(max_length=150)
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
    #: La collectivité ou la structure qui a enregistré cette fiche À LA DEMANDE de la personne
    #: (au téléphone, au guichet) — voir core/standard_crise.py. Vide : déposée par elle-même.
    enregistre_pour_autrui_par = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    email_request = EncryptedEmailField()
    # Index aveugle : rapprochement exact avec un compte existant (resolve_or_invite_demandeur).
    email_request_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    phone_request = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Chiffré ; retrouvé par son empreinte exacte (`deletion_token_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    deletion_token = EncryptedTextField(max_length=64, null=True, blank=True)
    deletion_token_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    # Lien de modification seule (deletion_token permet de désactiver).
    # Chiffré ; retrouvé par son empreinte exacte (`edition_token_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    edition_token = EncryptedTextField(max_length=64, null=True, blank=True)
    edition_token_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
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
    title = EncryptedTextField(max_length=150)
    photo = models.ImageField(upload_to=secure_information_photo_path, max_length=255, null=True, blank=True, validators=[validate_image_file])
    first_name_information = EncryptedTextField()
    last_name_information = EncryptedTextField()
    #: La collectivité ou la structure qui a enregistré cette fiche À LA DEMANDE de la personne
    #: (au téléphone, au guichet) — voir core/standard_crise.py. Vide : déposée par elle-même.
    enregistre_pour_autrui_par = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
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
    # Chiffré ; retrouvé par son empreinte exacte (`deletion_token_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    deletion_token = EncryptedTextField(max_length=64, null=True, blank=True)
    deletion_token_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    # Lien de modification seule (deletion_token permet de désactiver).
    # Chiffré ; retrouvé par son empreinte exacte (`edition_token_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    edition_token = EncryptedTextField(max_length=64, null=True, blank=True)
    edition_token_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
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


class VisibiliteOffre(models.TextChoices):
    """Qui a le droit de voir une offre d'aide.

    Ajouté le 11/11/2026. `Offer` était **entièrement public** : `OfferViewSet` est en
    `AllowAny`, la liste alimente la carte publique et la recherche, et le modèle ne portait ni
    institution ni notion de visibilité. C'était cohérent tant qu'une offre était le geste d'un
    citoyen qui propose son aide à tous.

    Ça ne l'est plus dès qu'un membre d'association devient une ressource : publier l'annuaire
    des bénévoles de la Réserve Résilience sur une carte publique serait exactement l'inverse
    de la consigne (« seule la réserve résilience a le droit de les voir comme ressource »).

    `PUBLIQUE` est le défaut, et toutes les offres existantes le restent : ce champ ne peut pas
    *réduire* par accident ce qui était déjà visible.
    """

    PUBLIQUE = "PUBLIQUE", "Publique"
    INTERNE = "INTERNE", "Réservée à son institution"


class Offer(HebergementDetailsMixin, EnvironmentScopedModel):
    """Offres d'aide"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = EncryptedTextField(max_length=150)
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
    #: La collectivité ou la structure qui a enregistré cette fiche À LA DEMANDE de la personne
    #: (au téléphone, au guichet) — voir core/standard_crise.py. Vide : déposée par elle-même.
    enregistre_pour_autrui_par = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    email_offer = EncryptedEmailField()
    # Voir User.email_bidx pour le raisonnement -- utilisé par resolve_or_invite_benevole pour
    # rapprocher cette offre d'un compte User existant (recherche EXACTE).
    email_offer_bidx = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    # Nullable côté modèle (pas de backfill à imposer aux offres déjà existantes) mais requis
    # côté formulaire public pour toute nouvelle soumission, même pattern que User.phone_number.
    phone_offer = EncryptedTextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Chiffré ; retrouvé par son empreinte exacte (`deletion_token_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    deletion_token = EncryptedTextField(max_length=64, null=True, blank=True)
    deletion_token_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    # Lien limité au fil de messages et à l'édition de l'offre (OfferReponsePublicView).
    # Chiffré ; retrouvé par son empreinte exacte (`reponse_token_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    reponse_token = EncryptedTextField(max_length=64, null=True, blank=True)
    reponse_token_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
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

    # Cloisonnement d'une offre (voir VisibiliteOffre). Une offre INTERNE n'est servie qu'aux
    # membres de son institution ; `institution` dit laquelle, et doit donc être renseignée
    # avec elle — un `INTERNE` sans institution ne serait visible de personne, ce que
    # `clean()` refuse plutôt que de le laisser disparaître en silence.
    visibilite = models.CharField(
        max_length=10, choices=VisibiliteOffre.choices, default=VisibiliteOffre.PUBLIQUE,
        db_index=True,
        help_text="PUBLIQUE = carte et recherche publiques, comme toute offre citoyenne. "
                   "INTERNE = réservée aux membres de `institution`.",
    )

    institution = models.ForeignKey(
        "Institution",
        on_delete=models.CASCADE,
        related_name="offres_internes",
        null=True,
        blank=True,
        help_text="Renseignée pour une offre INTERNE : l'institution dont les membres y ont "
                   "accès. Nulle pour une offre citoyenne publique.",
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
    transport_animaux_precision = EncryptedTextField(max_length=255, null=True, blank=True)
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

    def clean(self):
        """Une offre INTERNE sans institution ne serait visible de PERSONNE.

        Refusé explicitement plutôt que laissé passer : la ressource existerait en base, ne
        remonterait dans aucune liste, et on chercherait longtemps pourquoi un bénévole
        « n'apparaît pas ». Voir VisibiliteOffre."""
        super().clean()
        if self.visibilite == VisibiliteOffre.INTERNE and self.institution_id is None:
            raise DjangoValidationError({
                "institution": "Une offre interne doit nommer l'institution dont les membres "
                               "y ont accès.",
            })

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
    contenu = EncryptedTextField()
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

    description = EncryptedTextField(
        blank=True,
        null=True
    )

    telephone = EncryptedTextField(
        max_length=30,
        blank=True,
        null=True
    )

    email = EncryptedEmailField(
        blank=True,
        null=True
    )

    adresse = EncryptedTextField(
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

    # ── Rattachement à une institution mère ─────────────────────────────────────────────
    # Posé le 12/11/2026 : jusque-là, n'importe quel compte institutionnel créait des
    # institutions FLOTTANTES, au même rang que les mairies du référentiel national — d'où
    # les « Mairie debug test » qui traînent dans la liste.
    #
    # Les deux cas légitimes, nommés par Sylvain, sont tous deux des rattachements :
    #
    # - une collectivité crée ses satellites administratifs : CCAS/CIAS, médiathèque
    #   municipale, régie — des entités réelles, distinctes de la mairie, mais qui en
    #   dépendent ;
    # - une association crée ses échelons : un comité départemental sous l'association
    #   nationale.
    #
    # Dans les deux cas, la fille n'existe QUE sous sa mère. Le champ le dit, et
    # `InstitutionViewSet.perform_create` le pose d'office à partir du compte créateur — on
    # ne demande pas à l'utilisateur de déclarer un rattachement qu'il n'a pas le choix de
    # mettre ailleurs.
    #
    # PROTECT : supprimer une mère qui a des filles effacerait leur rattachement en silence,
    # et avec lui la seule trace de qui en répond.
    institution_parente = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="institutions_filles",
        help_text="Institution dont celle-ci dépend : CCAS ou médiathèque sous une mairie, "
                   "comité départemental sous une association nationale. Vide pour une "
                   "institution de plein exercice (mairie, préfecture, association tête de "
                   "réseau).",
    )

    #: Ce que l'institution a déjà et qui peut servir en cas de crise : clés du catalogue
    #: `core/atouts.py` (« SALLE_ACCUEIL », « CUISINE », « LOISIRS »…). Une proposition, jamais
    #: un engagement : cocher « cantine scolaire » dit qu'il existe une cuisine et à qui en
    #: parler, pas qu'un repas est promis.
    atouts = models.JSONField(default=list, blank=True)

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

            # Les trois codes sont DÉNORMALISÉS depuis la commune (voir
            # commune_secteur_codes) : la commune fait foi, et on ne rejoint pas `Commune` à
            # chaque lecture.
            #
            # Mais une résolution qui ÉCHOUE ne vaut pas une résolution vide. `_resolve_commune`
            # interroge geo.api.gouv.fr avec un budget d'appels et une temporisation : quand le
            # budget est épuisé ou le service indisponible, elle rend des codes vides. Les
            # recopier tels quels effaçait un rattachement qu'on connaissait — perte silencieuse
            # d'information, et cause de l'échec intermittent de
            # test_un_niveau_epci_borne_sur_l_intercommunalite (10/11/2026) : le test posait un
            # `epci_code`, `save()` le jetait, et le périmètre tombait à « aucune ».
            #
            # Donc : la valeur calculée gagne quand elle existe, sinon on garde ce qu'on a. Une
            # commune française appartient toujours à un EPCI depuis 2017, et un changement
            # d'EPCI donne un code non vide : le cas « résolu, et réellement sans EPCI » que
            # cette règle ne distingue pas n'existe pas en pratique.
            secteur = commune_secteur_codes(self.commune_code)
            for champ in ("epci_code", "departement_code", "region_code"):
                calcule = secteur.get(champ)
                if calcule or not getattr(self, champ, None):
                    setattr(self, champ, calcule)

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
    email_reply_to = EncryptedEmailField(blank=True, help_text="Reply-To des emails envoyés au nom de cette institution.")

    # Adresse de serveur Matrix à SAISIR dans Element X, pour les membres de cette institution.
    # Vide = MATRIX_SERVER_NAME, l'adresse partagée.
    #
    # Distinct du `server_name` de Synapse, et c'est TOUT l'intérêt : Synapse n'a qu'un seul
    # `server_name`, inscrit dans chaque identifiant d'utilisateur et de salon, et il ne sait pas
    # en héberger deux — les comptes restent donc `@…:matrix.assista-crise.fr`. Mais le POINT
    # D'ENTRÉE, lui, peut porter le domaine du partenaire : le proxy sert déjà
    # `matrix.reserve-resilience.org` vers le même Synapse, avec son propre certificat (voir
    # proxy/nginx.conf). Les deux usages de MATRIX_SERVER_NAME étaient confondus avant le
    # 11/11/2026 — l'identité et l'adresse à taper — ce qui faisait croire que rien n'était
    # personnalisable.
    matrix_hostname = models.CharField(
        max_length=255, blank=True,
        help_text="Adresse de serveur Matrix à saisir dans Element X (ex: "
                   "matrix.exemple.org). Vide = adresse partagée. Le domaine doit être servi "
                   "par le proxy et couvert par son certificat, sinon Element ne s'y connecte "
                   "pas.",
    )

    # Affiche la case « rejoindre la réserve » à l'inscription quand le Host résout vers cette
    # institution.
    reserve_active = models.BooleanField(default=False)

    def __str__(self):
        return self.nom


class ConfigurationEnvoiInstitution(EnvironmentScopedModel):
    """Identifiants d'envoi (email, SMS) propres à une institution en marque blanche.

    Lève la limite inscrite dans `core/branding.py` depuis l'origine : « compte SMTP unique
    Assista-Crise en v1, `reply_to` est le seul levier de personnalisation de l'adresse ». Une
    institution qui fournit sa clé Brevo envoie depuis SA propre adresse, et Assista-Crise
    n'apparaît plus dans le message.

    **Modèle séparé d'`Institution`, et c'est une décision.** Les champs de marque blanche
    (`nom_affichage`, couleurs, `logo`) vivent sur `Institution` dans un bloc qui porte en
    commentaire « en clair : informations publiques » — y mêler des secrets casserait cette
    invariante et l'hypothèse du prochain lecteur. Surtout, `InstitutionSerializer` est servi
    largement et lu par beaucoup de rôles : un modèle à part garantit que la clé ne voyage
    jamais par défaut. Le projet a déjà payé cette leçon — cinq endpoints livraient des secrets
    mesh en clair à tout compte connecté, d'où `EstComptePont`.

    Les clés sont **chiffrées au repos** (règle du projet : on ne stocke rien en clair) et
    **jamais relues par l'API** : le sérialiseur n'expose que « configurée / non configurée ».
    Une clé perdue se régénère chez le fournisseur, ce qui est plus sûr que de pouvoir la
    relire depuis l'application."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.OneToOneField(
        "Institution", on_delete=models.CASCADE, related_name="configuration_envoi",
    )

    # ── Email (Brevo) ────────────────────────────────────────────────────────
    brevo_actif = models.BooleanField(
        default=False,
        help_text="Faux = les emails de cette institution partent du SMTP Assista-Crise, "
                   "avec le texte de l'institution (signature, Reply-To).",
    )
    brevo_cle_api = EncryptedTextField(
        blank=True,
        help_text="Clé API Brevo (commence par « xkeysib- »). Jamais relue par l'API.",
    )
    brevo_expediteur_email = EncryptedEmailField(
        blank=True,
        help_text="Adresse expéditrice. Doit être un « sender » VÉRIFIÉ dans le compte Brevo, "
                   "sinon l'API refuse l'envoi.",
    )
    brevo_expediteur_nom = models.CharField(
        max_length=70, blank=True,
        help_text="Nom affiché de l'expéditeur. Vide = nom_affichage de l'institution. "
                   "70 caractères maximum (limite Brevo).",
    )

    # Relecture avant envoi : quand un membre de l'institution déclenche un message vers un
    # TIERS, le message est capturé en brouillon au lieu de partir, et l'interface ouvre une
    # fenêtre de relecture (voir core/brouillons_envoi.py). N'affecte jamais les messages qu'une
    # personne s'envoie à elle-même en s'inscrivant, ni ceux sans humain derrière.
    relecture_avant_envoi = models.BooleanField(
        default=False,
        help_text="Ouvre une fenêtre de relecture quand un membre écrit à un tiers au nom de "
                   "l'institution. L'action, elle, a déjà eu lieu : un brouillon jamais relu "
                   "part automatiquement au bout de 24 h.",
    )

    # ── SMS ──────────────────────────────────────────────────────────────────
    # `fournisseur_sms` est une chaîne et non un choix figé : le registre des fournisseurs
    # vit dans core/envoi_sms.py, et ajouter un opérateur ne doit pas demander une migration.
    fournisseur_sms = models.CharField(
        max_length=30, blank=True,
        help_text="Identifiant du fournisseur SMS (voir core/envoi_sms.py). Vide = aucun "
                   "envoi de SMS pour cette institution.",
    )
    sms_cle_api = EncryptedTextField(blank=True, help_text="Jamais relue par l'API.")
    # IntraMuros : chaque collectivité a SA clé (elle a son propre espace chez IntraMuros).
    # La clé se range ici, chiffrée ; l'envoi lui-même attend la documentation de leur API
    # (voir core/alerte_population.py, canal INTRAMUROS).
    intramuros_cle_api = EncryptedTextField(blank=True, default="", help_text="Jamais relue par l'API.")
    sms_expediteur = models.CharField(
        max_length=30, blank=True,
        help_text="Nom ou numéro d'expéditeur présenté au destinataire, selon ce que le "
                   "fournisseur autorise.",
    )

    # ── Crédits Brevo ────────────────────────────────────────────────────────────────────
    # Relevés depuis `GET /v3/account` (voir core/credits_brevo.py). L'API rend le RESTANT,
    # pas le quota : `*_reference` garde le plus haut niveau vu sur la période, ce qui permet
    # d'afficher une jauge sans demander à l'utilisateur de recopier son contrat.
    brevo_credits_email = models.IntegerField(null=True, blank=True)
    brevo_credits_email_reference = models.IntegerField(null=True, blank=True)
    brevo_credits_sms = models.IntegerField(null=True, blank=True)
    brevo_periode_fin = models.DateField(null=True, blank=True)
    brevo_credits_releves_le = models.DateTimeField(null=True, blank=True)
    #: En dessous de ce nombre de crédits restants, on prévient. Un nombre et non un
    #: pourcentage : « il reste 500 emails » se comprend sans calcul, et c'est ce qui dit si
    #: l'on peut encore écrire à tous ses bénévoles.
    brevo_seuil_alerte_email = models.PositiveIntegerField(default=1000)
    brevo_seuil_alerte_sms = models.PositiveIntegerField(default=50)
    # ── Tarifs déclarés, pour chiffrer une campagne avant de l'envoyer ───────────────────
    # En CENTIMES, pour ne pas traîner des flottants sur de l'argent. Déclarés par
    # l'institution : ils dépendent de son contrat, que nous ne connaissons pas. Zéro = non
    # renseigné, et l'écran dit alors « coût inconnu » plutôt que « gratuit » — annoncer la
    # gratuité à tort ferait partir un SMS à quatre cents personnes sans y penser.
    cout_unitaire_email = models.PositiveIntegerField(
        default=0, help_text="Coût d'un email, en centimes. 0 = non renseigné.")
    cout_unitaire_sms = models.PositiveIntegerField(
        default=0, help_text="Coût d'un SMS Brevo, en centimes. 0 = non renseigné.")
    cout_unitaire_sms_mobimel = models.PositiveIntegerField(
        default=0, help_text="Coût d'un SMS Mobimel, en centimes. 0 = non renseigné.")

    #: Qui gère le compte Brevo et doit être prévenu — souvent pas celui qui envoie. Adresse
    #: de fonction ; écrite par le bureau, jamais devinée.
    brevo_admin_email = EncryptedEmailField(blank=True)
    #: Dernière alerte envoyée, et à quel niveau : sans cette mémoire, chaque envoi sous le
    #: seuil renverrait un message, et l'alerte deviendrait le bruit qu'on apprend à ignorer.
    brevo_alerte_envoyee_le = models.DateTimeField(null=True, blank=True)
    brevo_alerte_niveau = models.CharField(max_length=10, blank=True, default="")

    # Dernier résultat observé, posé par les fonctions d'envoi. Sert à l'écran de configuration :
    # une clé acceptée à la saisie peut être révoquée ensuite, et sans cette trace personne ne
    # le verrait avant qu'un destinataire ne signale l'absence de message.
    dernier_envoi_email_le = models.DateTimeField(null=True, blank=True)
    derniere_erreur_email = EncryptedTextField(blank=True)
    dernier_envoi_sms_le = models.DateTimeField(null=True, blank=True)
    derniere_erreur_sms = EncryptedTextField(blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    @property
    def email_configure(self):
        """Prêt à envoyer : actif, une clé ET une adresse. Les trois, parce qu'un des trois
        manquant produit un refus de Brevo et non un envoi dégradé."""
        return bool(self.brevo_actif and self.brevo_cle_api and self.brevo_expediteur_email)

    @property
    def sms_configure(self):
        return bool(self.fournisseur_sms and self.cle_sms_effective)

    @property
    def cle_sms_effective(self):
        """La clé à présenter au fournisseur SMS.

        Brevo sert emails et SMS avec UNE clé : la redemander dans un second champ ferait
        saisir deux fois le même secret, et le jour où elle est régénérée on n'en mettrait à
        jour qu'un. Avec Brevo, le champ SMS vide veut donc dire « la même »."""
        if self.sms_cle_api:
            return self.sms_cle_api
        if self.fournisseur_sms == "BREVO":
            return self.brevo_cle_api
        return ""

    def __str__(self):
        return f"Configuration d'envoi de {self.institution.nom}"


class ModeleMessage(EnvironmentScopedModel):
    """Texte d'un message réécrit par une institution (voir core/modeles_messages.py).

    Une ligne par (institution, clé de modèle) : absente = le texte par défaut du catalogue
    s'applique. C'est ce qui fait que RIEN ne change pour une institution qui ne personnalise
    pas — et qu'ajouter un modèle au catalogue n'oblige personne à le réécrire.

    `cle` est une chaîne et non un choix figé : le catalogue vit dans le code, et y ajouter un
    message ne doit pas demander une migration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="modeles_messages",
    )

    cle = models.CharField(max_length=60)

    # Vide = garder le défaut du catalogue pour ce champ seulement. Une institution qui veut
    # changer le corps sans toucher au sujet ne doit pas avoir à recopier le sujet.
    sujet = EncryptedTextField(blank=True)
    corps = EncryptedTextField(blank=True)

    actif = models.BooleanField(
        default=True,
        help_text="Faux = revenir au texte par défaut sans perdre la version réécrite.",
    )

    modifie_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="modeles_messages_modifies",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['institution', 'cle'],
                                    name='unique_modele_message_institution_cle'),
        ]

    def __str__(self):
        return f"Modèle « {self.cle} » de {self.institution.nom}"


class BrouillonEnvoi(EnvironmentScopedModel):
    """Message capturé en attente de relecture (voir core/brouillons_envoi.py).

    **Les liens magiques y sont masqués.** `corps` contient `[LIEN_1]`, `[LIEN_2]`… et
    `liens_masques` porte la correspondance vers les vraies URL, **chiffrée** : ce sont des
    porteurs d'identité, et le client ne doit jamais les voir. Le relecteur n'est pas forcément
    le titulaire du compte concerné — cas réel, un administrateur qui déclenche une
    réinitialisation de mot de passe pour quelqu'un d'autre.

    L'action qui a produit ce message a DÉJÀ eu lieu : seul le message attend. D'où le délai
    au-delà duquel il part quand même."""

    class Canal(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"

    class Statut(models.TextChoices):
        A_RELIRE = "A_RELIRE", "À relire"
        ENVOYE = "ENVOYE", "Envoyé"
        ABANDONNE = "ABANDONNE", "Abandonné"
        # Parti au-delà du délai sans avoir été relu : distinct d'ENVOYE pour qu'on puisse
        # mesurer si la relecture sert vraiment ou si elle est systématiquement oubliée.
        EXPEDIE_SANS_RELECTURE = "EXPEDIE_AUTO", "Expédié sans relecture (délai dépassé)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="brouillons_envoi",
    )
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="brouillons_envoi_crees",
    )

    canal = models.CharField(max_length=6, choices=Canal.choices, default=Canal.EMAIL)
    statut = models.CharField(max_length=14, choices=Statut.choices, default=Statut.A_RELIRE)

    # Chiffrés : un message peut contenir un nom, une adresse, un motif de refus.
    sujet = EncryptedTextField(blank=True)
    corps = EncryptedTextField()
    # Liste d'adresses. Chiffrée pour la même raison que les autres adresses du projet.
    destinataires = EncryptedJSONField(default=list)
    reply_to = EncryptedTextField(blank=True)

    # JSON {placeholder: url}. JAMAIS servi par l'API — voir le sérialiseur.
    liens_masques = EncryptedTextField(blank=True)

    # LOT : messages produits par la MÊME action et identiques à leurs valeurs près.
    #
    # Un import de 200 bénévoles produit 200 messages qui ne diffèrent que par un nom et un
    # lien. Faire relire 200 fois le même texte n'est pas une relecture, c'est une corvée que
    # personne ne fera — et une relecture que personne ne fait est pire qu'une absence de
    # relecture, parce qu'elle donne l'illusion d'un contrôle. On n'en montre donc qu'un, sous
    # sa forme générique, et le valider envoie tout le lot (demande du 11/11/2026).
    lot = models.UUIDField(
        null=True, blank=True, db_index=True,
        help_text="Partagé par les messages d'une même action ayant le même texte générique. "
                   "Nul = message unique, relu seul.",
    )

    # {PRENOM: …, NOM: …, EMAIL: …} pour CE destinataire. `corps` est stocké sous sa forme
    # GÉNÉRIQUE ; ces valeurs y sont réinjectées au seul moment de l'envoi, comme les liens.
    # Chiffré : ce sont des données personnelles.
    valeurs = EncryptedJSONField(default=dict, blank=True)

    # Ce que le relecteur a changé, si quelque chose : utile pour savoir si les modèles par
    # défaut sont bons, ou systématiquement réécrits au même endroit.
    modifie_par_relecteur = models.BooleanField(default=False)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_traitement = models.DateTimeField(null=True, blank=True)
    traite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="brouillons_envoi_traites",
    )
    erreur = EncryptedTextField(blank=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [models.Index(fields=["statut", "date_creation"])]

    def __str__(self):
        return f"[{self.statut}] {self.canal} — {self.sujet[:40]}"


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
    # Chiffré depuis le 16/11/2026 : le journal de bord cite des personnes, et il se nourrit
    # désormais des messages des équipes (cellule de crise, « Porter au journal »).
    contenu = EncryptedTextField()
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

    commentaire = EncryptedTextField(
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

    commentaire = EncryptedTextField(
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

    # Dossier GÉNÉRIQUE : ouvert pour une mission d'intérêt général, à la demande d'une
    # institution et non d'une personne qui appelle à l'aide. Il n'a donc ni demande, ni
    # signalement, ni habitation d'origine -- mais il porte le chat, les photos et la
    # traçabilité de l'intervention, ce pour quoi il existe.
    generique = models.BooleanField(default=False)
    institution_demandeuse = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dossiers_demandes",
        help_text="Institution à la demande de laquelle ce dossier générique a été ouvert.",
    )

    titre = EncryptedTextField(
        max_length=255
    )

    description = EncryptedTextField()

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

    titre = EncryptedTextField(
        max_length=255
    )

    description = EncryptedTextField(
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

    # Institution qui COMMANDE la mission (la mairie qui demande une garde du feu). Sert aussi
    # au périmètre : c'est par elle qu'une mission sans équipe ni crise reste rattachée à
    # quelqu'un. Vide sur les missions créées avant le 16/11/2026 sans équipe.
    institution = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="missions_commandees",
    )

    # Mission d'intérêt général (garde du feu, surveillance d'un site, ronde) : elle ne répond
    # pas à l'appel à l'aide de quelqu'un, elle est demandée par l'institution elle-même. Elle
    # peut donc donner lieu à des dossiers GÉNÉRIQUES, sans demandeur (voir Dossier.generique),
    # ouverts à la demande -- un par jour de garde, par exemple.
    #
    # `titre` est un intitulé GÉNÉRIQUE dans tous les cas : il nomme un type de mission
    # (« Garde du feu »), jamais une personne ni une adresse. Ce qui est propre à une
    # intervention va dans le dossier.
    interet_general = models.BooleanField(default=False)

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

    commentaire = EncryptedTextField()

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

    commentaire = EncryptedTextField(
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

    commentaire = EncryptedTextField(
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

    metadata_privees = EncryptedJSONField(
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

    bien = models.ForeignKey(
        "BienSinistre", on_delete=models.CASCADE, null=True, blank=True, related_name="documents",
        help_text="Bien sinistré autre qu'une habitation (véhicule, bateau, hangar…).",
    )

    pret = models.ForeignKey(
        "PretMateriel", on_delete=models.CASCADE, null=True, blank=True, related_name="documents",
        help_text="Prêt de matériel dont cette photo documente l'état.",
    )
    #: « DEPART » ou « RETOUR » : à quelle fiche d'état du prêt la photo appartient.
    moment_pret = models.CharField(max_length=6, blank=True, default="")

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


class ReleveSourceOuverte(models.Model):
    """État du dernier relevé de chaque source ouverte copiée en base (vigilance, routes,
    carburants) -- voir core/sources_ouvertes.py. Sert à deux choses : savoir si un relevé est
    dû, et dire à la supervision qu'une source ne se rafraîchit plus. Une copie périmée
    affichée comme fraîche serait pire que pas de copie."""

    source = models.CharField(max_length=30, primary_key=True)
    dernier_essai = models.DateTimeField(null=True, blank=True)
    dernier_succes = models.DateTimeField(null=True, blank=True)
    # Nombre de lignes écrites au dernier relevé réussi.
    lignes = models.PositiveIntegerField(default=0)
    # Motif du dernier échec, vide après un succès. Jamais de secret ici : le texte d'une
    # exception réseau ne porte que l'adresse appelée.
    erreur = models.TextField(blank=True, default="")

    def __str__(self):
        return f"{self.source} : {self.dernier_succes or 'jamais relevé'}"


class EvenementRoutier(models.Model):
    """Événement en cours sur le réseau routier national (Bison Futé, flux DATEX II des
    directions interdépartementales des routes) -- voir core/trafic_routier.py.

    Donnée publique partagée PROD/DEMO. Une ligne par SITUATION : une situation regroupe ce que
    l'exploitant publie d'un même chantier ou d'un même accident (travaux + voie neutralisée +
    limitation + déviation), et c'est elle qu'un agent lit, pas ses quatre fragments. La table
    est un instantané : ce qui disparaît du flux est supprimé au relevé suivant."""

    class Categorie(models.TextChoices):
        FERMETURE = "FERMETURE", "Route fermée"
        ACCIDENT = "ACCIDENT", "Accident"
        OBSTACLE = "OBSTACLE", "Obstacle ou dégât"
        CONDITIONS = "CONDITIONS", "Conditions de circulation"
        DEVIATION = "DEVIATION", "Déviation"
        TRAVAUX = "TRAVAUX", "Travaux"
        RESTRICTION = "RESTRICTION", "Restriction"
        AUTRE = "AUTRE", "Autre"

    reference = models.CharField(max_length=80, primary_key=True)
    categorie = models.CharField(max_length=12, choices=Categorie.choices, db_index=True)
    # Ce que la situation comporte, en clair : ["Travaux", "Voie neutralisée", "Vitesse limitée"].
    natures = models.JSONField(default=list, blank=True)
    # low / medium / high / highest, tel que publié.
    gravite = models.CharField(max_length=10, blank=True, default="")
    route = models.CharField(max_length=20, blank=True, default="")
    commune_nom = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    localisation = models.TextField(blank=True, default="")
    gestionnaire = models.CharField(max_length=160, blank=True, default="")
    # Lu dans le point de repère routier (« 42PR12D ») : absent pour une ligne sur douze.
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    location = gis_models.PointField(srid=4326)
    # Autre extrémité quand l'événement porte sur un tronçon.
    location_fin = gis_models.PointField(srid=4326, null=True, blank=True)
    debut = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    mis_a_jour_le = models.DateTimeField(null=True, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"{self.get_categorie_display()} {self.route} {self.commune_nom}".strip()


class StationCarburant(models.Model):
    """Station-service et ce qu'elle peut encore délivrer (flux instantané des prix des
    carburants, ministère de l'Économie) -- voir core/carburants.py.

    Donnée publique partagée PROD/DEMO. Ce qui sert en crise n'est pas le prix mais la RUPTURE :
    savoir où un véhicule d'intervention peut encore faire le plein, et voir une pénurie se
    dessiner sur un territoire."""

    reference = models.CharField(max_length=20, primary_key=True)
    adresse = models.CharField(max_length=255, blank=True, default="")
    ville = models.CharField(max_length=120, blank=True, default="")
    code_postal = models.CharField(max_length=10, blank=True, default="")
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    location = gis_models.PointField(srid=4326)
    carburants_disponibles = models.JSONField(default=list, blank=True)
    # Rupture temporaire : la station vend ce carburant d'ordinaire et n'en a plus.
    ruptures_temporaires = models.JSONField(default=list, blank=True)
    # Rupture définitive : la station ne le vend plus, ce n'est pas un signal de pénurie.
    ruptures_definitives = models.JSONField(default=list, blank=True)
    # {"Gazole": {"prix": 1.699, "maj": "2026-11-15T06:00:00+00:00"}}
    prix = models.JSONField(default=dict, blank=True)
    automate_24_24 = models.BooleanField(default=False)
    # Dernière mise à jour d'un prix par la station : une station muette depuis des mois a
    # probablement fermé, l'écran le dit.
    mis_a_jour_le = models.DateTimeField(null=True, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Station {self.reference} {self.ville}"


class ObservationMeteo(models.Model):
    """Dernière mesure connue d'une station Météo-France (environ 2 000, métropole et
    outre-mer) -- voir core/observations_meteo.py.

    Donnée publique partagée PROD/DEMO. Une ligne par station, réécrite à chaque relevé : un
    état courant, pas une série. Seule exception, `cumuls` garde les pluies horaires des
    dernières 24 heures, parce que le cumul sur la journée -- l'indicateur qui compte pour une
    inondation -- n'est pas publié et doit être additionné ici."""

    station = models.CharField(max_length=8, primary_key=True)
    nom = models.CharField(max_length=80, blank=True, default="")
    altitude_m = models.IntegerField(null=True, blank=True)
    departement_code = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    location = gis_models.PointField(srid=4326)
    # Mesures du paquet 6 minutes. Toutes les stations ne mesurent pas tout : le vent n'est
    # relevé que par quatre stations sur dix.
    mesure_le = models.DateTimeField(null=True, blank=True)
    temperature_c = models.FloatField(null=True, blank=True)
    humidite_pct = models.FloatField(null=True, blank=True)
    vent_kmh = models.FloatField(null=True, blank=True)
    vent_direction = models.FloatField(null=True, blank=True)
    rafale_kmh = models.FloatField(null=True, blank=True)
    pluie_6min_mm = models.FloatField(null=True, blank=True)
    neige_cm = models.FloatField(null=True, blank=True)
    # Mesures du paquet horaire.
    heure_le = models.DateTimeField(null=True, blank=True)
    pluie_1h_mm = models.FloatField(null=True, blank=True)
    rafale_1h_kmh = models.FloatField(null=True, blank=True)
    # [{"h": instant, "rr": mm}] sur 24 heures glissantes, et ce qu'on en tire. `heures_cumulees`
    # dit sur combien d'heures porte le cumul : il est partiel tant que 24 relevés horaires ne
    # se sont pas succédé.
    cumuls = models.JSONField(default=list, blank=True)
    pluie_24h_mm = models.FloatField(null=True, blank=True)
    heures_cumulees = models.PositiveSmallIntegerField(default=0)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Station {self.station} {self.nom}".strip()


class FoyerActif(models.Model):
    """Pixel chaud détecté par satellite ces deux derniers jours (NASA FIRMS) -- voir
    core/foyers_actifs.py. Un pixel chaud n'est pas forcément un feu : `source_fixe` marque ceux
    qui reviennent au même endroit quatre jours sur sept (usines, torchères)."""

    reference = models.CharField(max_length=60, primary_key=True)
    date = models.DateTimeField(db_index=True)
    location = gis_models.PointField(srid=4326)
    satellite = models.CharField(max_length=8, blank=True, default="")
    confiance = models.CharField(max_length=10, default="nominale")
    # Puissance radiative du foyer, en mégawatts.
    puissance_mw = models.FloatField(null=True, blank=True)
    de_jour = models.BooleanField(default=True)
    source_fixe = models.BooleanField(default=False, db_index=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Foyer {self.reference}"


class ConfigurationAlerteFeu(EnvironmentScopedModel):
    """Annonce des foyers détectés par satellite près de la commune de l'institution, sur ses
    canaux radio et par message à ses rattachés (commande relever_sources_ouvertes). Inactive
    tant que l'institution ne l'a pas demandée : le signal a des faux positifs (écobuages,
    brûlages) et doit être voulu."""

    institution = models.OneToOneField(
        "Institution", on_delete=models.CASCADE, related_name="configuration_alerte_feu",
    )
    actif = models.BooleanField(default=False)
    rayon_km = models.PositiveIntegerField(
        default=15, validators=[MinValueValidator(2), MaxValueValidator(60)])
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Alerte feu {self.institution.nom} ({'active' if self.actif else 'inactive'})"


class FoyerSignale(EnvironmentScopedModel):
    """Maille de 5 km déjà annoncée à une institution (anti-doublon). Effacée au bout de trois
    jours : un feu qui dure n'est annoncé qu'une fois, un nouveau feu au même endroit l'est."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="foyers_signales",
    )
    maille = models.CharField(max_length=24)
    date_signalement = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institution", "maille"], name="uq_foyer_signale_institution_maille"),
        ]

    def __str__(self):
        return f"Foyer {self.maille} -> {self.institution.nom}"


class MesureRadioactivite(models.Model):
    """Dernière mesure d'une balise du réseau Téléray (ASNR) : débit de dose gamma ambiant et
    bruit de fond habituel de la balise, en nanosieverts par heure -- voir
    core/radioactivite.py. Donnée publique partagée PROD/DEMO. Un affichage, jamais une alerte."""

    station = models.PositiveIntegerField(primary_key=True)
    nom = models.CharField(max_length=120, blank=True, default="")
    location = gis_models.PointField(srid=4326)
    # Balise posée autour d'une installation nucléaire (les deux tiers du réseau).
    proche_installation = models.BooleanField(default=False)
    debit_nsv_h = models.FloatField()
    bruit_de_fond_nsv_h = models.FloatField(null=True, blank=True)
    # Validation de la mesure par l'ASNR ; une mesure « non valide » est gardée et signalée.
    valide = models.BooleanField(default=True)
    mesure_le = models.DateTimeField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Balise {self.nom} : {self.debit_nsv_h} nSv/h"


class Seisme(models.Model):
    """Événement sismique des trente derniers jours en France, hexagone et outre-mer (catalogue
    du BCSF-Rénass) -- voir core/seismes.py. `nature` distingue les séismes des tirs de
    carrière, explosions et glissements de terrain que le réseau enregistre aussi."""

    reference = models.CharField(max_length=40, primary_key=True)
    date = models.DateTimeField(db_index=True)
    location = gis_models.PointField(srid=4326)
    magnitude = models.FloatField()
    profondeur_km = models.FloatField(null=True, blank=True)
    lieu = models.CharField(max_length=160, blank=True, default="")
    zone = models.CharField(max_length=60, blank=True, default="")
    nature = models.CharField(max_length=40, default="earthquake")
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"M{self.magnitude} {self.lieu}"


class Defibrillateur(models.Model):
    """Défibrillateur déclaré en service dans la base nationale Géo'DAE -- voir
    core/defibrillateurs.py. La carte de tous les appareils du pays, tels que leurs exploitants
    les déclarent ; à ne pas confondre avec les fiches de Sites sensibles, qu'une collectivité
    a vérifiées une à une."""

    reference = models.CharField(max_length=20, primary_key=True)
    nom = models.CharField(max_length=255, blank=True, default="")
    adresse = models.CharField(max_length=255, blank=True, default="")
    commune_code = models.CharField(max_length=10, blank=True, default="", db_index=True)
    # « Intérieur » ou « Extérieur », et si l'accès est libre.
    acces = models.CharField(max_length=40, blank=True, default="")
    acces_libre = models.BooleanField(default=False)
    emplacement = models.CharField(max_length=255, blank=True, default="")
    disponibilite = models.CharField(max_length=120, blank=True, default="")
    location = gis_models.PointField(srid=4326)
    releve_le = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"Défibrillateur {self.reference} {self.adresse}"


class IndicateurSante(models.Model):
    """Part des passages aux urgences attribués à une pathologie dans un département, pour la
    dernière semaine publiée par Santé publique France -- voir core/sante_urgences.py. Un taux
    pour 100 000 passages aux urgences : une tendance, pas un nombre de malades."""

    pathologie = models.CharField(max_length=16)
    departement_code = models.CharField(max_length=3, db_index=True)
    semaine = models.CharField(max_length=10, blank=True, default="")
    debut_semaine = models.DateField()
    taux_urgences = models.FloatField(null=True, blank=True)
    taux_urgences_precedent = models.FloatField(null=True, blank=True)
    taux_sos = models.FloatField(null=True, blank=True)
    releve_le = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["pathologie", "departement_code"],
                                    name="uq_indicateur_sante_pathologie_departement"),
        ]

    def __str__(self):
        return f"{self.pathologie} {self.departement_code} {self.semaine}"


class ArreteCirculation(models.Model):
    """Arrêté de circulation d'une collectivité publié dans DiaLog, quand il change un
    itinéraire : circulation interdite, interdite aux poids lourds, ou alternée -- voir
    core/arretes_circulation.py. Donnée publique partagée PROD/DEMO ; instantané quotidien."""

    class Categorie(models.TextChoices):
        FERMETURE = "FERMETURE", "Circulation interdite"
        POIDS_LOURDS = "POIDS_LOURDS", "Interdite aux poids lourds"
        ALTERNAT = "ALTERNAT", "Circulation alternée"

    reference = models.CharField(max_length=80, primary_key=True)
    categorie = models.CharField(max_length=12, choices=Categorie.choices, db_index=True)
    description = models.CharField(max_length=500, blank=True, default="")
    autorite = models.CharField(max_length=200, blank=True, default="")
    voies = models.CharField(max_length=300, blank=True, default="")
    # Tonnage à partir duquel l'interdiction s'applique (poids lourds).
    tonnage_max = models.FloatField(null=True, blank=True)
    debut = models.DateTimeField(null=True, blank=True)
    # Vide = arrêté permanent.
    fin = models.DateTimeField(null=True, blank=True)
    url = models.CharField(max_length=300, blank=True, default="")
    geometrie = gis_models.GeometryCollectionField(srid=4326)
    location = gis_models.PointField(srid=4326)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"{self.get_categorie_display()} {self.voies}".strip()


class StationCirculation(models.Model):
    """Station de comptage du réseau routier national (un tronçon, un sens de circulation) et
    sa dernière mesure : vitesse, débit, état du trafic -- voir core/circulation.py.

    `vitesse_habituelle_kmh` n'est pas une donnée de la source : c'est ce serveur qui l'apprend,
    mesure après mesure, pour reconnaître un ralentissement là où l'exploitant ne publie pas
    d'état. Donnée publique partagée PROD/DEMO."""

    code = models.CharField(max_length=40, primary_key=True)
    gestionnaire = models.CharField(max_length=20, blank=True, default="")
    axe = models.CharField(max_length=20, blank=True, default="", db_index=True)
    sens = models.CharField(max_length=20, blank=True, default="")
    longueur_m = models.PositiveIntegerField(default=0)
    # Code de l'agglomération dont l'exploitant publie un état du trafic (« ST42 »), ou vide.
    agglomeration = models.CharField(max_length=20, blank=True, default="")
    # Trait droit du début à la fin du tronçon ; vide quand le référentiel n'a pas de coordonnées.
    trace = gis_models.LineStringField(srid=4326, null=True, blank=True)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    # +1 : chaussée à droite du trait, -1 : à gauche, 0 : inconnu (voir cote_de_la_chaussee).
    cote = models.SmallIntegerField(default=0)
    referentiel_le = models.DateTimeField()

    vitesse_kmh = models.FloatField(null=True, blank=True)
    debit_veh_h = models.PositiveIntegerField(null=True, blank=True)
    mesure_le = models.DateTimeField(null=True, blank=True)
    # État publié par l'exploitant (FLUIDE, DENSE, SATURE, BLOQUE), vide s'il n'en publie pas.
    etat = models.CharField(max_length=10, blank=True, default="")
    etat_le = models.DateTimeField(null=True, blank=True)
    vitesse_habituelle_kmh = models.FloatField(null=True, blank=True)
    mesures_comptees = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.axe} {self.sens} ({self.code})".strip()


class PointQualiteAir(models.Model):
    """Qualité de l'air ESTIMÉE par modèle (OpenWeather) en l'un des points fixes de la liste de
    core/qualite_air.py : l'indice courant (1 bon à 5 très mauvais -- ce n'est pas l'indice ATMO),
    les polluants, et la prévision des deux jours à venir. État courant seulement, réécrit à
    chaque relevé : rien n'est archivé. Donnée sous licence CC BY-SA 4.0, mention obligatoire."""

    code = models.CharField(max_length=10, primary_key=True)        # code INSEE de la commune
    nom = models.CharField(max_length=120)
    departement = models.CharField(max_length=3, db_index=True)
    location = gis_models.PointField(srid=4326)
    indice = models.PositiveSmallIntegerField()
    # Concentrations en microgrammes par mètre cube : {"pm2_5": 4.1, "pm10": 6.0, "no2": …}.
    composants = models.JSONField(default=dict, blank=True)
    mesure_le = models.DateTimeField()
    # [[instant ISO, indice]…], heure par heure.
    prevision = models.JSONField(default=list, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Air à {self.nom} : {self.indice}"


class AntenneIndisponible(models.Model):
    """Antenne de téléphonie mobile déclarée en panne ou en maintenance par son opérateur
    (fichier quotidien de l'Arcep) -- voir core/antennes_mobiles.py.

    `premiere_vue_le` n'est pas une donnée de la source : c'est le jour où ce serveur a vu le
    site en panne pour la première fois, qui sert d'âge à la panne quand l'opérateur ne déclare
    pas de date de début. Donnée publique partagée PROD/DEMO."""

    # « opérateur|numéro de station ANFR » : deux opérateurs peuvent partager un pylône.
    cle = models.CharField(max_length=80, primary_key=True)
    operateur = models.CharField(max_length=40, db_index=True)
    station = models.CharField(max_length=20, blank=True, default="")
    commune = models.CharField(max_length=120, blank=True, default="")
    code_insee = models.CharField(max_length=5, blank=True, default="")
    location = gis_models.PointField(srid=4326)
    # Vrai : hors service. Faux : en service. Vide : l'opérateur ne le dit pas.
    voix_hs = models.BooleanField(null=True, blank=True)
    donnees_hs = models.BooleanField(null=True, blank=True)
    # {"voix2g": "OK", "data4g": "HS", …} : le détail par technologie, quand il est donné.
    technologies = models.JSONField(default=dict, blank=True)
    motif = models.CharField(max_length=12, blank=True, default="")
    debut = models.DateTimeField(null=True, blank=True)
    premiere_vue_le = models.DateTimeField()
    jour_du_fichier = models.DateField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"{self.operateur} {self.commune}".strip()


class Maregraphe(models.Model):
    """Marégraphe du réseau REFMAR (Shom et partenaires) : dernier niveau mesuré, et ce que ce
    serveur en déduit -- marée attendue, surcote estimée, prochaine pleine mer. Voir
    core/niveaux_mer.py.

    `ajustement` n'est pas une donnée de la source : ce sont les amplitudes des ondes de marée
    que ce serveur a ajustées sur six mois de mesures de la station, avec l'incertitude mesurée
    de cet ajustement. Vide tant que l'historique ne suffit pas. Donnée publique partagée
    PROD/DEMO."""

    code = models.CharField(max_length=20, primary_key=True)
    nom = models.CharField(max_length=120, blank=True, default="")
    reseau = models.CharField(max_length=20, blank=True, default="")
    location = gis_models.PointField(srid=4326)
    referentiel_le = models.DateTimeField()

    niveau_m = models.FloatField(null=True, blank=True)
    niveau_le = models.DateTimeField(null=True, blank=True)
    maree_attendue_m = models.FloatField(null=True, blank=True)
    surcote_cm = models.IntegerField(null=True, blank=True)
    pleine_mer_le = models.DateTimeField(null=True, blank=True)
    pleine_mer_niveau_m = models.FloatField(null=True, blank=True)

    ajustement = models.JSONField(default=dict, blank=True)
    ajuste_le = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.nom or self.code


class StationHydrometrique(models.Model):
    """Station de mesure en rivière (Hub'Eau) et ses dernières mesures : hauteur à l'échelle,
    débit, variation sur une et trois heures -- voir core/hauteurs_eau.py.

    `historique` garde six heures de hauteurs ([[instant ISO, millimètres]…]) : c'est lui qui
    donne la tendance, sans rien redemander à la source. Donnée publique partagée PROD/DEMO."""

    code = models.CharField(max_length=20, primary_key=True)
    nom = models.CharField(max_length=200, blank=True, default="")
    cours_eau = models.CharField(max_length=120, blank=True, default="")
    departement = models.CharField(max_length=3, blank=True, default="", db_index=True)
    location = gis_models.PointField(srid=4326)
    referentiel_le = models.DateTimeField()

    hauteur_m = models.FloatField(null=True, blank=True)
    hauteur_le = models.DateTimeField(null=True, blank=True)
    debit_m3s = models.FloatField(null=True, blank=True)
    debit_le = models.DateTimeField(null=True, blank=True)
    variation_1h_cm = models.FloatField(null=True, blank=True)
    variation_3h_cm = models.FloatField(null=True, blank=True)
    historique = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.nom or self.code


class RisqueAvalanche(models.Model):
    """Indice de risque d'avalanche d'un massif (bulletin de Météo-France), aujourd'hui et
    demain, sur l'échelle européenne de 1 (faible) à 5 (très fort) -- voir core/avalanche.py.
    Le contour du massif est gardé même sans bulletin (hors saison) : `risque` est alors vide."""

    massif_code = models.PositiveSmallIntegerField(primary_key=True)
    nom = models.CharField(max_length=120, blank=True, default="")
    chaine = models.CharField(max_length=60, blank=True, default="")
    departement_nom = models.CharField(max_length=160, blank=True, default="")
    geometrie = gis_models.MultiPolygonField(srid=4326)
    risque = models.PositiveSmallIntegerField(null=True, blank=True)
    risque_demain = models.PositiveSmallIntegerField(null=True, blank=True)
    commentaire = models.CharField(max_length=300, blank=True, default="")
    resume = models.TextField(blank=True, default="")
    publie_le = models.DateTimeField(null=True, blank=True)
    valide_jusqu_a = models.DateTimeField(null=True, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Avalanche {self.nom} : {self.risque}"


class TronconVigilanceCrues(models.Model):
    """Tronçon de cours d'eau surveillé par Vigicrues et son niveau de vigilance (1 vert,
    2 jaune, 3 orange, 4 rouge) -- voir core/vigilance_crues.py. Donnée publique partagée
    PROD/DEMO ; instantané réécrit à chaque relevé."""

    code = models.CharField(max_length=20, primary_key=True)
    nom = models.CharField(max_length=160, blank=True, default="")
    niveau = models.PositiveSmallIntegerField(default=1, db_index=True)
    geometrie = gis_models.MultiLineStringField(srid=4326)
    publie_le = models.DateTimeField(null=True, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"{self.nom} (vigilance {self.niveau})"


class RestrictionEau(models.Model):
    """Niveau de restriction d'usage de l'eau le plus élevé en vigueur dans un département,
    d'après VigiEau -- voir core/restrictions_eau.py. Vide = aucune restriction ; sinon
    « vigilance », « alerte », « alerte_renforcee » ou « crise ». Le niveau le plus élevé du
    département ne s'applique pas forcément à chaque commune : l'écran le dit."""

    departement_code = models.CharField(max_length=3, primary_key=True)
    niveau = models.CharField(max_length=20, blank=True, default="")
    niveau_superficielle = models.CharField(max_length=20, blank=True, default="")
    niveau_souterraine = models.CharField(max_length=20, blank=True, default="")
    niveau_potable = models.CharField(max_length=20, blank=True, default="")
    # Jour auquel VigiEau rapporte ces niveaux (le jour même, ou la veille le matin).
    date_donnees = models.DateField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Restrictions d'eau {self.departement_code} : {self.niveau or 'aucune'}"


class ZoneBrulee(models.Model):
    """Surface brûlée des trente derniers jours, repérée par satellite (EFFIS, Copernicus) --
    voir core/feux_satellite.py. Une mémoire de ce qui a brûlé, pas une alerte : seuls les feux
    d'une trentaine d'hectares ou plus y figurent, avec un jour de retard."""

    reference = models.CharField(max_length=40, primary_key=True)
    date_feu = models.DateTimeField(null=True, blank=True)
    commune_nom = models.CharField(max_length=160, blank=True, default="")
    departement_nom = models.CharField(max_length=120, blank=True, default="")
    surface_ha = models.FloatField(null=True, blank=True)
    geometrie = gis_models.MultiPolygonField(srid=4326)
    # Centre de la zone : pour la borner à une emprise sans manipuler le contour.
    location = gis_models.PointField(srid=4326)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Feu {self.commune_nom} ({self.surface_ha} ha)"


class DangerFeuForet(models.Model):
    """Danger de feu de forêt d'un département pour demain et après-demain (« météo des
    forêts » de Météo-France, publiée de juin à septembre) -- voir core/meteo_forets.py.
    1 faible, 2 modéré, 3 élevé, 4 très élevé. Table vide hors saison."""

    departement_code = models.CharField(max_length=3, primary_key=True)
    niveau_demain = models.PositiveSmallIntegerField(null=True, blank=True)
    niveau_apres_demain = models.PositiveSmallIntegerField(null=True, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Danger feu {self.departement_code} : {self.niveau_demain}"


class ReleveMeteoForets(models.Model):
    """Ligne unique : l'état du dernier relevé de la météo des forêts, et la réponse BRUTE de
    Météo-France. Le connecteur a été écrit hors saison, sans avoir vu une vraie réponse :
    garder la première permet d'ajuster l'analyse sans attendre la publication suivante (voir
    l'avertissement en tête de core/meteo_forets.py)."""

    en_saison = models.BooleanField(default=False)
    # Faux quand une carte a été publiée mais que l'analyse n'y a rien reconnu.
    compris = models.BooleanField(default=True)
    type_contenu = models.CharField(max_length=120, blank=True, default="")
    brut = models.BinaryField(null=True, blank=True)
    releve_le = models.DateTimeField()

    def __str__(self):
        return "Météo des forêts : " + ("en saison" if self.en_saison else "hors saison")


class ImagePluie(models.Model):
    """Image nationale de la pluie prévue pour un quart d'heure donné (prévision immédiate de
    Météo-France), déjà mise en projection Mercator pour être posée sur la carte -- voir
    core/pluie.py. Une douzaine de lignes au plus : les échéances passées sont retirées.

    Donnée publique partagée PROD/DEMO. En base et non dans un cache, pour la même raison que
    `VignetteVigilanceMeteo` : la tâche planifiée et le serveur web lisent la même copie."""

    echeance = models.DateTimeField(primary_key=True)
    # Heure de référence du calcul qui a produit cette image.
    calcul = models.DateTimeField()
    image = models.BinaryField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Pluie prévue pour {self.echeance:%d/%m %H:%M}"


class ImageRafales(models.Model):
    """Image nationale des rafales de vent prévues pour un quart d'heure donné (prévision
    immédiate de Météo-France), peinte par ce serveur en paliers de km/h et déjà en projection
    Mercator -- voir core/rafales.py. Même forme et même durée de vie que `ImagePluie`.

    Donnée publique partagée PROD/DEMO."""

    echeance = models.DateTimeField(primary_key=True)
    # Heure de référence du calcul qui a produit cette image.
    calcul = models.DateTimeField()
    image = models.BinaryField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Rafales prévues pour {self.echeance:%d/%m %H:%M}"


class CelluleOrage(models.Model):
    """Une cellule de pluie intense de la dernière image radar analysée (core/orages.py) :
    SELON LES RELEVÉS pour son contour et son intensité, SELON NOS ESTIMATIONS (qui ne sont pas
    des prévisions) pour son déplacement et les communes qu'elle atteindrait. Remplacées à
    chaque image. Donnée publique partagée PROD/DEMO."""

    identifiant = models.CharField(max_length=12, help_text="Stable d'une image à l'autre tant que la cellule est suivie.")
    heure_image = models.DateTimeField()
    centre = gis_models.PointField(srid=4326)
    contour = gis_models.PolygonField(srid=4326)
    # Zone balayée en une heure si la cellule gardait sa vitesse et sa direction.
    couloir = gis_models.PolygonField(srid=4326, null=True, blank=True)
    # Position et déplacement dans la grille radar (1 km), pour suivre la cellule à l'image suivante.
    ligne = models.FloatField()
    colonne = models.FloatField()
    vitesse_lignes = models.FloatField(null=True, blank=True)
    vitesse_colonnes = models.FloatField(null=True, blank=True)
    max_mmh = models.FloatField()
    moyenne_mmh = models.FloatField()
    surface_km2 = models.FloatField()
    tendance_mmh = models.FloatField(null=True, blank=True, help_text="Écart d'intensité maximale avec l'image précédente.")
    cap_deg = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Direction vers laquelle elle va, 0 = nord.")
    vitesse_kmh = models.PositiveSmallIntegerField(null=True, blank=True)
    longueur_km = models.PositiveIntegerField(default=0)
    ligne_de_grain = models.BooleanField(default=False)
    communes_touchees = models.JSONField(default=list, blank=True)
    communes_estimees = models.JSONField(default=list, blank=True)
    grele_prevue = models.BooleanField(default=False, help_text="Grêle prévue par Météo-France (AROME-PI) sous la cellule.")
    rafale_prevue_kmh = models.PositiveSmallIntegerField(null=True, blank=True)
    rafale_mesuree = models.JSONField(null=True, blank=True)
    trace = models.JSONField(default=list, blank=True)
    # Diagnostic de grêle d'AROME-PI le plus fort sous la cellule (kg/m², voir orages.SEUIL_GRELE_KGM2).
    grele_diagnostic_kgm2 = models.FloatField(null=True, blank=True)
    # Éclairs vus par le satellite MTG sous la cellule dans les 20 minutes autour de l'image.
    eclairs = models.PositiveIntegerField(null=True, blank=True)
    # Signatures Doppler (core/doppler.py), SELON LES RELEVÉS des radars les plus proches :
    # rotation {vrot_ms, elevations, lon, lat, radar}, grêle {z_max_dbz, sommet_45_m,
    # isotherme0_m, probable, radar}, divergence {ms, radar}.
    doppler_rotation = models.JSONField(null=True, blank=True)
    doppler_grele = models.JSONField(null=True, blank=True)
    doppler_divergence = models.JSONField(null=True, blank=True)
    # Double polarisation : {grele, portes_grele, debris, radar}.
    doppler_polarimetrie = models.JSONField(null=True, blank=True)
    doppler_radars = models.JSONField(default=list, blank=True)
    doppler_heure = models.DateTimeField(null=True, blank=True)
    # Suivi par tobac sur l'heure écoulée (core/suivi_tobac.resumer) : {suivie_depuis_min, noyaux,
    # noyaux_intenses, surface_10min_km2, max_10min_mmh, evolution, fusion, division}.
    suivi = models.JSONField(null=True, blank=True)
    releve_le = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["-max_mmh"])]


class ImageRadarOrage(models.Model):
    """Les dernières images radar, ramenées à 1 km et compactées : il en faut deux pour estimer
    un déplacement (core/orages.py). Trois lignes au plus."""

    heure = models.DateTimeField(primary_key=True)
    largeur = models.PositiveIntegerField()
    hauteur = models.PositiveIntegerField()
    projdef = models.CharField(max_length=300)
    x0 = models.FloatField()
    y0 = models.FloatField()
    grille = models.BinaryField()
    radars = models.JSONField(default=list, blank=True)
    radars_absents = models.JSONField(default=list, blank=True)
    # Nombre d'images que contient chaque fenêtre de cumul de pluie ({"1h": 12, …}).
    images_par_fenetre = models.JSONField(default=dict, blank=True)
    releve_le = models.DateTimeField()


class ImpactFoudre(models.Model):
    """Un éclair vu par l'imageur de foudre du satellite MTG (core/foudre.py), sur la métropole.
    48 heures gardées. Donnée publique partagée PROD/DEMO."""

    instant = models.DateTimeField(db_index=True)
    location = gis_models.PointField(srid=4326)
    duree_ms = models.PositiveIntegerField(default=0)
    radiance = models.FloatField(default=0)
    confiance = models.FloatField(null=True, blank=True)


class RadarMeteo(models.Model):
    """Radar de Météo-France : identifiant de l'API, balayages publiés, position lue dans
    l'en-tête de ses propres fichiers (core/doppler.py)."""

    station = models.PositiveSmallIntegerField(primary_key=True)
    nom = models.CharField(max_length=80)
    tours = models.JSONField(default=list, blank=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    altitude = models.FloatField(default=0)
    maj = models.DateTimeField()


class ImpactBlitzortung(models.Model):
    """Impact de foudre du réseau communautaire Blitzortung (commande ecouter_blitzortung), à
    titre INDICATIF : affiché, jamais analysé ni annoncé (conditions de Blitzortung.org).
    24 heures gardées."""

    instant = models.DateTimeField(db_index=True)
    location = gis_models.PointField(srid=4326)


class ProduitFoudre(models.Model):
    """Produit EUMETSAT déjà lu (une tranche de dix minutes, parfois en plusieurs fichiers)."""

    identifiant = models.CharField(max_length=200, primary_key=True)
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    eclairs = models.PositiveIntegerField(default=0)
    releve_le = models.DateTimeField()


class PluieCommunesImage(models.Model):
    """Pluie tombée en cinq minutes au centre de chaque commune où il a plu, selon une image
    radar (core/orages.cumuler_pluie). 25 heures gardées, de quoi recalculer les cumuls."""

    heure = models.DateTimeField(primary_key=True)
    valeurs = models.JSONField(default=dict, blank=True, help_text="code INSEE -> mm en cinq minutes")


class PrevisionPluieCommune(models.Model):
    """Estimation de la pluie de l'heure qui vient par commune, par extrapolation des images radar
    (core/prevision_immediate.py, pysteps) : NOS ESTIMATIONS, pas une prévision officielle.
    Remplacées à chaque image ; une ligne seulement là où il pleuvrait."""

    commune_code = models.CharField(max_length=10, primary_key=True)
    heure_image = models.DateTimeField()
    dans_min_intense = models.PositiveSmallIntegerField(null=True, blank=True,
                                                        help_text="Minutes avant 30 mm/h ou plus, si dans l'heure.")
    max_mmh = models.FloatField(default=0)
    cumul_mm = models.FloatField(default=0)
    releve_le = models.DateTimeField()


class ImageRadarEstimee(models.Model):
    """Pluie de l'heure qui vient, extrapolée des images radar par pysteps
    (core/prevision_immediate.enregistrer_images) : NOS ESTIMATIONS, pas une prévision. Une image
    par pas de cinq minutes, de +5 à +60, remplacées à chaque image observée. Grille compacte
    comme ImageRadarOrage (mm/h plafonné à 254)."""

    minutes = models.PositiveSmallIntegerField(primary_key=True)
    heure_base = models.DateTimeField(help_text="Heure de l'image observée dont elle est extrapolée.")
    largeur = models.PositiveIntegerField()
    hauteur = models.PositiveIntegerField()
    projdef = models.CharField(max_length=300)
    x0 = models.FloatField()
    y0 = models.FloatField()
    grille = models.BinaryField()
    releve_le = models.DateTimeField()


class AdresseBAN(models.Model):
    """Une adresse de la Base Adresse Nationale, copiée en local pour les communes qui nous
    concernent (core/referentiel_adresses.py) : territoire des institutions communales et
    intercommunales, communes des crises ouvertes. Donnée publique partagée PROD/DEMO, non
    chiffrée : c'est le LIEN entre une personne et une adresse qui est chiffré, ailleurs.

    Une adresse disparue du fichier national est marquée `retiree_le`, jamais effacée : les
    fiches et les habitations qui y renvoient par `ban_id` restent valables."""

    ban_id = models.CharField(max_length=64, primary_key=True, help_text="Clé d'interopérabilité de la BAN.")
    commune_code = models.CharField(max_length=10, db_index=True)
    commune_nom = models.CharField(max_length=100, blank=True, default="")
    code_postal = models.CharField(max_length=5, blank=True, default="")
    numero = models.CharField(max_length=10, blank=True, default="")
    suffixe = models.CharField(max_length=10, blank=True, default="")
    voie = models.CharField(max_length=200, blank=True, default="")
    lieu_dit = models.CharField(max_length=200, blank=True, default="")
    location = gis_models.PointField(srid=4326)
    type_position = models.CharField(max_length=30, blank=True, default="",
                                     help_text="entrée, bâtiment, segment, parcelle… (BAN).")
    parcelles = models.CharField(max_length=300, blank=True, default="", help_text="Parcelles cadastrales, séparées par |.")
    retiree_le = models.DateTimeField(null=True, blank=True, db_index=True)
    modifie_le = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=["commune_code", "retiree_le"])]

    @property
    def libelle(self):
        """« 12 bis Rue des Pins, Lieu-dit, 33680 Le Porge »."""
        debut = " ".join(p for p in (self.numero, self.suffixe, self.voie) if p)
        lieu = self.lieu_dit if self.lieu_dit and self.lieu_dit != self.voie else ""
        fin = " ".join(p for p in (self.code_postal, self.commune_nom) if p)
        return ", ".join(p for p in (debut, lieu, fin) if p)

    def __str__(self):
        return self.libelle


class PotentielOrageFeu(models.Model):
    """Potentiel d'orage de feu (pyrocumulonimbus) pour une heure de l'après-midi, calculé sur le
    profil vertical d'ARPEGE (core/orages_de_feu.py) : NOS ESTIMATIONS, pas une prévision.
    `grilles` : PFT, C-Haines et palier, compressés ; `image` : le palier peint pour la carte.
    Donnée publique partagée PROD/DEMO."""

    echeance = models.DateTimeField(primary_key=True)
    calcul = models.DateTimeField(help_text="Heure de référence du calcul ARPEGE.")
    largeur = models.PositiveIntegerField()
    hauteur = models.PositiveIntegerField()
    ouest = models.FloatField(help_text="Longitude du premier point de grille.")
    nord = models.FloatField(help_text="Latitude du premier point de grille.")
    grilles = models.BinaryField()
    image = models.BinaryField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Potentiel d'orage de feu pour {self.echeance:%d/%m %H:%M}"


class ProduitFeuMTG(models.Model):
    """Liste de pixels en feu du satellite MTG déjà lue (LSA SAF, une toutes les dix minutes) --
    core/feux_mtg.py. Gardée une semaine."""

    creneau = models.DateTimeField(primary_key=True)
    detections = models.PositiveIntegerField(default=0, help_text="Pixels retenus dans l'emprise.")
    releve_le = models.DateTimeField()


class DetectionFeuMTG(models.Model):
    """Un pixel en feu vu par MTG dans l'emprise de la France (core/feux_mtg.py). Gardé une
    semaine, pour reconnaître les sources fixes. Donnée publique partagée PROD/DEMO."""

    creneau = models.DateTimeField(db_index=True)
    instant = models.DateTimeField()
    location = gis_models.PointField(srid=4326)
    puissance_mw = models.FloatField(help_text="Puissance rayonnée du pixel (FRP), en MW.")
    incertitude_mw = models.FloatField(default=0)
    confiance = models.FloatField(default=0)


class FeuSuivi(models.Model):
    """Un feu en cours suivi par le satellite MTG : pixels voisins regroupés, puissance toutes
    les dix minutes, contexte (orage, foudre, potentiel d'orage de feu) -- core/feux_mtg.py.
    Recalculés à chaque relevé. Détection satellite, à confirmer ; jamais annoncée."""

    identifiant = models.CharField(max_length=40, primary_key=True)
    premier_vu = models.DateTimeField()
    dernier_vu = models.DateTimeField()
    centre = gis_models.PointField(srid=4326)
    statut = models.CharField(max_length=10, default="actif", help_text="« actif » ou « plus vu ».")
    puissance_mw = models.FloatField(help_text="Puissance rayonnée totale à la dernière image où il est vu.")
    puissance_max_mw = models.FloatField()
    instant_max = models.DateTimeField()
    pixels = models.PositiveIntegerField(default=0)
    confirme = models.BooleanField(default=False, help_text="Vu sur au moins deux images.")
    source_fixe = models.BooleanField(default=False, db_index=True)
    courbe = models.JSONField(default=list, blank=True, help_text="[[créneau, MW, pixels]] des dernières 24 h.")
    contexte = models.JSONField(default=dict, blank=True)
    calcule_le = models.DateTimeField()

    def __str__(self):
        return f"Feu suivi {self.identifiant}"


class CumulPluieCommune(models.Model):
    """Cumuls glissants de pluie par commune, selon le radar (1 h, 3 h, 24 h), recalculés à
    chaque image. Seules les communes où il a plu dans les 24 h ont une ligne."""

    commune_code = models.CharField(max_length=10, primary_key=True)
    mm_1h = models.FloatField(default=0)
    mm_3h = models.FloatField(default=0)
    mm_24h = models.FloatField(default=0)
    heure = models.DateTimeField()


class AnalyseOrages(models.Model):
    """Résumé de chaque analyse radar, gardé trente jours : de quoi comparer après coup les
    cellules détectées aux orages réellement signalés, et régler les seuils avant toute annonce."""

    heure = models.DateTimeField(primary_key=True)
    radars_absents = models.JSONField(default=list, blank=True)
    cellules = models.JSONField(default=list, blank=True)
    releve_le = models.DateTimeField()


class ChampVent(models.Model):
    """Champ de vent à dix mètres pour une heure donnée (modèle ARPEGE de Météo-France), gardé
    sous forme compacte pour l'animation de la carte -- voir core/vent.py. `donnees` : un octet
    par point pour la composante vers l'est, puis autant pour la composante vers le nord.

    Donnée publique partagée PROD/DEMO. Une dizaine de lignes au plus."""

    echeance = models.DateTimeField(primary_key=True)
    calcul = models.DateTimeField()
    largeur = models.PositiveIntegerField()
    hauteur = models.PositiveIntegerField()
    # Position du premier point (coin nord-ouest) ; le pas est celui de vent.PAS_DEGRES.
    ouest = models.FloatField()
    nord = models.FloatField()
    donnees = models.BinaryField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Vent prévu pour {self.echeance:%d/%m %H:%M}"


class ImagePrecipitationHiver(models.Model):
    """Image nationale du type de précipitation prévu pour un quart d'heure donné -- neige,
    verglas, grésil, grêle -- peinte par ce serveur, en projection Mercator. Voir
    core/precipitations_hiver.py. Même forme et même durée de vie que `ImagePluie`.

    Donnée publique partagée PROD/DEMO."""

    echeance = models.DateTimeField(primary_key=True)
    calcul = models.DateTimeField()
    image = models.BinaryField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Neige et verglas prévus pour {self.echeance:%d/%m %H:%M}"


class VigilanceMeteo(models.Model):
    """Dernière vigilance Météo-France connue pour un département (ou « FRA » pour la France
    entière), copiée par `verifier_vigilance_meteo` -- voir core/meteo_france.py.

    Donnée publique, partagée PROD/DEMO comme `Commune` : rien de personnel, donc rien de
    chiffré. Une ligne par département, réécrite à chaque relevé : c'est un état courant, pas un
    historique. Les pages et la diffusion d'alerte lisent CETTE copie ; aucun navigateur
    n'interroge Météo-France, et aucune requête d'utilisateur ne déclenche d'appel sortant."""

    departement_code = models.CharField(max_length=3, primary_key=True)
    # 1 vert, 2 jaune, 3 orange, 4 rouge -- le maximum tous phénomènes confondus.
    couleur_j = models.PositiveSmallIntegerField(default=1)
    couleur_j1 = models.PositiveSmallIntegerField(default=1)
    # {"J": {"debut", "fin", "phenomenes": [{"id", "couleur", "periodes": [...]}]}, "J1": {...}}
    # -- seuls les phénomènes en jaune ou plus y figurent.
    detail = models.JSONField(default=dict, blank=True)
    # Bulletin de suivi : [{"titre", "lignes": [...]}]. Vide tant que le département est vert ou
    # jaune (Météo-France ne rédige un bulletin départemental qu'à partir de l'orange).
    bulletin = models.JSONField(default=list, blank=True)
    # Heure de publication par Météo-France, et heure de notre dernier relevé réussi.
    publie_le = models.DateTimeField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Vigilance {self.departement_code} : J={self.couleur_j} J+1={self.couleur_j1}"


class VignetteVigilanceMeteo(models.Model):
    """Carte nationale de vigilance (image officielle de Météo-France) pour aujourd'hui (« J »)
    et demain (« J1 »), copiée au même moment que `VigilanceMeteo`. Stockée en base et non dans
    un cache : la commande planifiée et le serveur web doivent lire la même copie."""

    echeance = models.CharField(max_length=2, primary_key=True)
    image = models.BinaryField()
    releve_le = models.DateTimeField()

    def __str__(self):
        return f"Vignette de vigilance {self.echeance}"


class ConfigurationAlerteVigilance(EnvironmentScopedModel):
    """Diffusion automatique de la vigilance Météo-France du département de l'institution, sur
    ses canaux radio et par message aux personnes qui lui sont rattachées (commande
    verifier_vigilance_meteo). Inactive tant que l'institution ne l'a pas demandée. Seuil orange
    par défaut : le jaune revient plusieurs fois par semaine et userait l'attention."""

    COULEURS_SEUIL = [(2, "Jaune"), (3, "Orange"), (4, "Rouge")]

    institution = models.OneToOneField(
        "Institution", on_delete=models.CASCADE, related_name="configuration_alerte_vigilance",
    )
    actif = models.BooleanField(default=False)
    couleur_min = models.PositiveSmallIntegerField(default=3, choices=COULEURS_SEUIL)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Alerte vigilance {self.institution.nom} ({'active' if self.actif else 'inactive'})"


class VigilanceDiffusee(EnvironmentScopedModel):
    """Niveau de vigilance déjà annoncé à une institution pour un phénomène (anti-doublon entre
    deux relevés). Une ligne par institution et par phénomène tant que l'épisode dure ; elle est
    supprimée quand le phénomène repasse sous le seuil, pour que l'épisode suivant soit annoncé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="vigilances_diffusees",
    )
    departement_code = models.CharField(max_length=3)
    phenomene = models.PositiveSmallIntegerField()
    couleur = models.PositiveSmallIntegerField()
    date_diffusion = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institution", "phenomene"], name="uq_vigilance_diffusee_institution_phenomene"),
        ]

    def __str__(self):
        return f"Vigilance {self.couleur} phénomène {self.phenomene} -> {self.institution.nom}"


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

    #: À quels moments cet interlocuteur est à prévenir (18/11/2026). Rien ne part tout seul :
    #: la liste est PRÉPARÉE avec ces personnes déjà cochées, et quelqu'un confirme d'un clic —
    #: pour qu'une crise d'essai ne réveille pas la préfecture.
    prevenir_ouverture_crise = models.BooleanField(default=True)
    prevenir_ouverture_centre = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)
    ordre = models.PositiveIntegerField(default=0)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "categorie"]

    def __str__(self):
        return f"{self.nom} ({self.organisme or self.get_categorie_display()})"


    def save(self, *args, **kwargs):
        """Numéro en E.164 : c'est à ce téléphone que part l'alerte PCS par SMS, et un
        préfixe mal deviné l'envoie à quelqu'un d'autre (voir core/telephone.py)."""
        if self.telephone:
            from .telephone import normaliser

            self.telephone = normaliser(self.telephone) or self.telephone
        super().save(*args, **kwargs)

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

    #: Pourquoi cette ligne a été préparée : l'ouverture de la crise, ou celle d'un centre d'accueil.
    motif = models.CharField(max_length=10, default="CRISE", choices=[("CRISE", "Ouverture de la crise"), ("CENTRE", "Ouverture d'un centre d'accueil")])
    point = models.ForeignKey("PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications_alerte_pcs")
    point_nom_snapshot = models.CharField(max_length=255, blank=True, default="")
    #: Cochée d'avance dans la liste à confirmer : l'annuaire dit de prévenir cette personne à ce moment-là.
    preselectionne = models.BooleanField(default=True)
    canal_tente = models.CharField(max_length=20, choices=ModeAlertePCS.choices)

    statut = models.CharField(max_length=20, choices=StatutNotificationPCS.choices, default=StatutNotificationPCS.EN_ATTENTE)
    detail_erreur = EncryptedTextField(null=True, blank=True)

    # Chiffré ; retrouvé par son empreinte exacte (`token_confirmation_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    token_confirmation = EncryptedTextField(max_length=64)
    token_confirmation_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    # Texte réellement envoyé, conservé pour trace.
    message_envoye = EncryptedTextField(null=True, blank=True)

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
            # Une ligne par interlocuteur pour l'ouverture de la crise ; et une par centre d'accueil
            # ouvert, pour ceux à prévenir à ce moment-là (18/11/2026).
            models.UniqueConstraint(fields=["crise", "interlocuteur"], condition=models.Q(motif="CRISE"),
                                    name="uq_notification_pcs_crise_interlocuteur"),
            models.UniqueConstraint(fields=["crise", "interlocuteur", "point"], condition=models.Q(motif="CENTRE"),
                                    name="uq_notification_pcs_centre"),
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

    description = EncryptedTextField(blank=True, null=True)

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
    #: Maison brûlée, effondrée, emportée : il n'y a plus rien à habiter. Distinct de « dégâts
    #: forts », qui se répare (incendies de l'été 2026 : les deux se côtoyaient dans la même rue).
    DETRUITE = "DETRUITE", "Détruite"

    @classmethod
    def avec_degats(cls):
        """Les états qui constatent un dommage (ouvrent un dossier, comptent dans les exports)."""
        return (cls.DEGATS_FAIBLES, cls.DEGATS_FORTS, cls.DETRUITE)


class NatureDegatsHabitation(models.TextChoices):
    """Ce qui a causé le dommage constaté sur un bâtiment. Le suivi des dégâts sert pour tout
    sinistre, pas seulement l'eau : feu de forêt, tempête ou tornade, grêle, séisme… Posée
    maison par maison, parce qu'une même crise en mêle souvent plusieurs (orage : eau ici, vent
    là), et reprise dans les rapports pour l'assureur."""
    EAU = "EAU", "Eau (inondation, coulée de boue, submersion)"
    FEU = "FEU", "Feu (incendie, feu de forêt)"
    VENT = "VENT", "Vent (tempête, tornade)"
    GRELE = "GRELE", "Grêle"
    NEIGE = "NEIGE", "Neige, glace"
    TERRAIN = "TERRAIN", "Mouvement de terrain, séisme"
    EXPLOSION = "EXPLOSION", "Explosion, accident"
    AUTRE = "AUTRE", "Autre"

    @classmethod
    def pour_la_crise(cls, crise) -> str:
        """La nature proposée d'office d'après le type de la crise ; vide quand il ne dit rien."""
        return {"INCENDIE": cls.FEU, "INONDATION": cls.EAU, "ACCIDENT": cls.EXPLOSION}.get(getattr(crise, "type", ""), "")


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

    parcelle_cadastrale = EncryptedTextField(
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

    nature_degats = models.CharField(
        max_length=20, choices=NatureDegatsHabitation.choices, blank=True, default="",
        help_text="Cause du dommage constaté (eau, feu, vent…). Vide tant que rien n'est constaté.",
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

    # ── Évaluation à pied (20/11/2026, DOSSIER-ADRESSES-ET-DEGATS.md) ──
    #: Ce qu'est le bien : un logement par défaut (vide), sinon un type du catalogue extensible
    #: (véhicule, ouvrage, réseau…). La fiche reste la même : carte, décomptes, dossiers.
    type_bien = models.ForeignKey("TypeBien", on_delete=models.SET_NULL, null=True, blank=True, related_name="biens")
    #: Dangers relevés sur place : STRUCTURE, ELECTRICITE, GAZ, EAU, AUTRE.
    dangers = models.JSONField(default=list, blank=True)
    personne_sur_place = models.BooleanField(null=True, blank=True)
    a_reloger = models.BooleanField(null=True, blank=True)
    #: Vrai quand l'évaluateur a replacé le point : l'adresse nationale ne change pas.
    position_corrigee = models.BooleanField(default=False)
    #: Rapproché d'un autre bien (le même, vu deux fois) : jamais effacé, il est rattaché à
    #: celui-ci, et la séparation le détache sans rien perdre (RapprochementBien).
    fusionne_dans = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="rapproches")

    date_creation = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.adresse


class TypeBien(models.Model):
    """Catalogue partagé et extensible des types de bien évalués (logement, véhicule, route…),
    comme MaterielCatalogue : un texte libre saisi sur le terrain ajoute une entrée, proposée
    ensuite à tous dans la liste."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=80, unique=True)
    #: Pour reconnaître « véhicule » et « Véhicule » : minuscules, sans accents ni espaces doubles.
    cle = models.CharField(max_length=80, unique=True)
    #: Un bien de ce type peut-il avoir une adresse ? (Non pour un véhicule, un arbre.)
    a_une_adresse = models.BooleanField(default=True)
    ordre = models.PositiveSmallIntegerField(default=100)
    actif = models.BooleanField(default=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordre", "nom"]

    @staticmethod
    def cle_de(nom):
        import unicodedata
        texte = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().lower()
        return " ".join(texte.split())[:80]

    @staticmethod
    def id_de(cle):
        """Identifiant déduit du nom : le même type a le même identifiant sur le central et sur
        chaque satellite, qu'il vienne de la migration ou d'un texte libre saisi sur le terrain --
        sans cela, un bien remonté d'un satellite pointerait vers un type introuvable."""
        return uuid.uuid5(uuid.NAMESPACE_URL, f"assista-crise:type-bien:{cle}")

    def save(self, *args, **kwargs):
        self.nom = " ".join((self.nom or "").split())[:80]
        self.cle = TypeBien.cle_de(self.nom)
        if self._state.adding:
            self.id = TypeBien.id_de(self.cle)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class ConstatTerrain(EnvironmentScopedModel):
    """Un constat fait sur le terrain depuis l'application (évaluation à pied). Son identifiant
    est tiré SUR LE TÉLÉPHONE : renvoyé deux fois (réseau revenu, file rejouée), il ne crée
    jamais deux constats. Un fait daté, jamais modifié."""

    id = models.UUIDField(primary_key=True, editable=False)
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="constats_terrain")
    habitation = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="constats")
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="constats_terrain")
    #: Heure du constat sur le téléphone (il peut arriver des heures plus tard).
    constate_le = models.DateTimeField()
    recu_le = models.DateTimeField(auto_now_add=True)
    statut_evaluation = models.CharField(max_length=20, choices=StatutEvaluationHabitation.choices)
    nature_degats = models.CharField(max_length=20, blank=True, default="")
    nouveau_bien = models.BooleanField(default=False, help_text="Point ajouté sur place, sans adresse du référentiel.")

    class Meta:
        ordering = ["-constate_le"]


class PieceEnvoyee(models.Model):
    """Sur un satellite : une photo (Document d'un bien ou d'un dossier) déjà envoyée au central,
    avec son empreinte vérifiée par lui. Les fichiers ne passent pas par la file d'événements
    (core/sync_pieces.py)."""

    document_id = models.UUIDField(primary_key=True)
    envoyee_le = models.DateTimeField(auto_now_add=True)


class StatutRapprochementBien(models.TextChoices):
    PROPOSE = "PROPOSE", "Proposé"
    CONFIRME = "CONFIRME", "Même bien"
    REFUSE = "REFUSE", "Biens différents"
    SEPARE = "SEPARE", "Séparés après rapprochement"


class RapprochementBien(EnvironmentScopedModel):
    """Deux fiches qui désignent peut-être le même bien (même type, à moins de 50 m sur la même
    crise, ou rapprochées à la main). JAMAIS fusionnées d'office (décision du 20/11/2026) :
    confirmer rattache `autre` à `bien` (Habitation.fusionne_dans), séparer l'en détache."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="rapprochements_biens")
    bien = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="rapprochements_garde")
    autre = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="rapprochements_rattache")
    distance_m = models.FloatField(null=True, blank=True)
    statut = models.CharField(max_length=10, choices=StatutRapprochementBien.choices, default=StatutRapprochementBien.PROPOSE)
    manuel = models.BooleanField(default=False)
    propose_le = models.DateTimeField(auto_now_add=True)
    decide_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decide_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-propose_le"]
        indexes = [models.Index(fields=["crise", "statut"])]


class HabitationCommentaire(EnvironmentScopedModel):
    """Échanges sur une habitation entre agents et rattachés acceptés (propriétaire, locataire)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    habitation = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="commentaires")

    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    commentaire = EncryptedTextField()

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.habitation.adresse}"


class HabitationHistorique(EnvironmentScopedModel):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    habitation = models.ForeignKey(Habitation, on_delete=models.CASCADE, related_name="historique")

    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    evenement = models.CharField(max_length=255)

    commentaire = EncryptedTextField(blank=True, null=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.evenement


class StatutPointageTerrain(models.TextChoices):
    A_VALIDER = "A_VALIDER", "À valider"
    VALIDE = "VALIDE", "Validé"
    REFUSE = "REFUSE", "Refusé"


class PointageTerrain(EnvironmentScopedModel):
    """Ce qu'un intervenant (membre d'une équipe engagée sur la crise) a pointé sur le terrain,
    en attente de validation par la commune.

    Décision de Sylvain du 17/11/2026 : « ouvre le pointage aux intervenants mais le pointage
    doit être validé par du personnel municipal ou élu ». Tant qu'il n'est pas validé, un
    pointage n'est PAS une habitation : il n'apparaît ni sur la carte publique, ni dans les
    décomptes, ni dans les rapports, et n'ouvre aucun dossier. À la validation il devient (ou
    complète) une `Habitation`, et le constat proposé devient son évaluation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="pointages_terrain")
    location = gis_models.PointField(srid=4326)
    adresse = EncryptedTextField()
    ban_id = models.CharField(max_length=64, blank=True, null=True)
    commune_code = models.CharField(max_length=10, blank=True, null=True)
    commune_nom = models.CharField(max_length=255, blank=True, null=True)
    #: Le constat proposé par l'intervenant ; la commune peut le corriger en validant.
    statut_evaluation = models.CharField(
        max_length=20, choices=StatutEvaluationHabitation.choices, default=StatutEvaluationHabitation.NON_EVALUEE)
    nature_degats = models.CharField(max_length=20, choices=NatureDegatsHabitation.choices, blank=True, default="")
    commentaire = EncryptedTextField(blank=True, default="")
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="pointages_terrain")
    date_creation = models.DateTimeField(auto_now_add=True)

    statut = models.CharField(max_length=12, choices=StatutPointageTerrain.choices, default=StatutPointageTerrain.A_VALIDER)
    #: La maison déjà référencée à cet endroit, puis celle que la validation a créée ou complétée.
    habitation = models.ForeignKey(Habitation, on_delete=models.SET_NULL, null=True, blank=True, related_name="pointages")
    traite_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    traite_le = models.DateTimeField(null=True, blank=True)
    motif_refus = EncryptedTextField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-date_creation"]
        indexes = [models.Index(fields=["crise", "statut"])]


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

    # Prénom séparé depuis le 11/11/2026. Avant, `nom_demandeur` portait l'identité entière et
    # le compte créé à l'acceptation était fabriqué en coupant cette chaîne au PREMIER espace
    # (voir RattachementHabitationViewSet.traiter) : « Jean Pierre Dupont » donnait le prénom
    # « Jean » et le patronyme « Pierre Dupont », sans que rien ne le signale.
    #
    # `blank=True` pour les lignes antérieures, qui n'ont jamais eu ce champ ; l'API l'exige à
    # la création (voir RattachementHabitationSerializer).
    prenom_demandeur = EncryptedTextField(max_length=255, blank=True)
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
        return f"{self.identite_demandeur} ({self.type_lien}) -> {self.habitation.adresse}"

    @property
    def identite_demandeur(self):
        """« Prénom Nom », ou le seul nom pour une demande antérieure au 11/11/2026.

        Existe pour que les quatre endroits qui affichent cette identité (journal, notification,
        deux emails) ne la recomposent pas chacun à leur façon — c'est ainsi qu'on finit avec un
        écran qui dit « Dupont » et un autre « Jean Dupont » pour la même demande."""
        return " ".join(part for part in ((self.prenom_demandeur or '').strip(),
                                          (self.nom_demandeur or '').strip()) if part)

    @property
    def noms_pour_compte(self):
        """(prénom, patronyme) pour le compte créé à l'acceptation.

        Le repli sur la découpe au premier espace ne sert QUE les demandes déposées avant le
        11/11/2026, qui n'ont pas de prénom séparé. Extrait ici pour être testable : il vivait
        en ligne dans la vue, où personne ne pouvait constater qu'il attribuait
        « Pierre Dupont » comme patronyme à un « Jean Pierre Dupont »."""
        prenom = (self.prenom_demandeur or '').strip()
        patronyme = (self.nom_demandeur or '').strip()
        if prenom:
            return prenom, patronyme
        parts = patronyme.split(' ', 1)
        if len(parts) > 1:
            return parts[0], parts[1]
        return '', patronyme

    @property
    def salutation_demandeur(self):
        """De quoi écrire « Bonjour … » : le prénom seul quand on l'a.

        Saluer quelqu'un par son patronyme est ce que faisaient ces emails faute de prénom
        séparé ; on garde ce repli pour les demandes qui n'en ont pas."""
        return (self.prenom_demandeur or '').strip() or (self.nom_demandeur or '').strip()


class StatutQualification(models.TextChoices):
    """État d'instruction d'une qualification.

    DECLAREE est le défaut, et le mot compte : tant que l'encadrement ne s'est pas prononcé,
    la qualification est une affirmation de son titulaire. La confondre avec VERIFIEE ferait
    envoyer en intervention quelqu'un sur la foi d'une case qu'il a cochée lui-même."""

    DECLAREE = "DECLAREE", "Déclarée par le membre"
    VERIFIEE = "VERIFIEE", "Vérifiée par l'encadrement"
    REFUSEE = "REFUSEE", "Refusée"


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

    # ── VÉRIFIER PUIS DÉTRUIRE (13/11/2026) ────────────────────────────────────────────
    #
    # Ce modèle gardait le permis indéfiniment : rien ne le validait, rien ne le supprimait,
    # et la seule date portée était celle du dépôt. C'était l'inverse exact de la politique de
    # conservation du projet (core/conservation_pieces.py, régime VERIFIER_DETRUIRE) sur la
    # pièce qui en est l'exemple même.
    #
    # Désormais : on consigne QUI a vérifié, QUAND, et jusqu'à quand la pièce était valable —
    # puis on détruit les images. C'est cette trace, et non la photo du permis, qui prouve que
    # le contrôle a eu lieu. Le numéro du permis n'est jamais saisi : il est aussi identifiant
    # que la copie.
    statut = models.CharField(
        max_length=12, choices=StatutQualification.choices,
        default=StatutQualification.DECLAREE,
    )
    verifie_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pieces_identite_verifiees",
    )
    verifie_le = models.DateTimeField(null=True, blank=True)
    valable_jusqu_au = models.DateField(
        null=True, blank=True,
        help_text="Date de fin de validité relevée sur la pièce au moment du contrôle. "
                  "Permet de redemander une pièce à jour sans en avoir gardé la copie.",
    )
    motif_refus = EncryptedTextField(
        blank=True,
        help_text="Obligatoire au refus : la personne doit savoir quoi corriger.",
    )
    piece_detruite_le = models.DateTimeField(null=True, blank=True)

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


class LieuDeDepart(models.TextChoices):
    """D'où part et où rentre la personne. Quelqu'un « en déplacement sur site » — logé sur
    place pour plusieurs jours — part de son hébergement et y rentre, pas de chez lui : c'est
    ce trajet-là que compte sa journée."""
    DOMICILE = "DOMICILE", "Domicile"
    HEBERGEMENT = "HEBERGEMENT", "Point d'hébergement (en déplacement sur site)"


class EngagementPersonnel(EnvironmentScopedModel):
    """« Je pars », « je rentre » pour le personnel municipal et les membres d'association
    (17/11/2026) : le temps qu'une personne a réellement passé sur une crise, d'après ce
    qu'elle déclare elle-même. Le pendant, pour les membres d'équipe, de ce que
    `EngagementRessource` fait pour une ressource proposée par une offre.

    Une personne n'a qu'un engagement ouvert à la fois : on ne part pas deux fois sans être
    rentré. `institution` dit au nom de qui elle est partie — celle de son équipe, sinon la
    sienne — et c'est elle qui relit le relevé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="engagements_personnels")
    crise = models.ForeignKey(Crisis, on_delete=models.CASCADE, related_name="engagements_personnels")
    equipe = models.ForeignKey(
        "Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="engagements_personnels")
    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="engagements_personnels")
    parti_le = models.DateTimeField()
    rentre_le = models.DateTimeField(null=True, blank=True)
    depart_de = models.CharField(max_length=12, choices=LieuDeDepart.choices, default=LieuDeDepart.DOMICILE)
    retour_a = models.CharField(max_length=12, choices=LieuDeDepart.choices, blank=True, default="")
    #: Nom du logement quand la personne est hébergée sur site (centre ou offre de logement).
    hebergement = EncryptedTextField(max_length=200, blank=True, default="")
    # Vrai dès qu'une heure a été saisie ou corrigée à la main par la personne, après coup :
    # le relevé distingue ce qui a été déclaré sur le moment de ce qui a été complété.
    saisie_manuelle = models.BooleanField(default=False)
    modifie_le = models.DateTimeField(null=True, blank=True)
    # Le chef d'équipe relit et valide ; il ne corrige pas à la place de la personne. Une
    # ligne validée ne se modifie plus. `remarque_chef` : ce qu'il demande de revoir.
    valide_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="engagements_personnels_valides")
    valide_le = models.DateTimeField(null=True, blank=True)
    remarque_chef = EncryptedTextField(blank=True, default="")

    class Meta:
        ordering = ["-parti_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "environment"], condition=models.Q(rentre_le__isnull=True),
                name="uq_engagement_personnel_un_seul_ouvert"),
        ]

    @property
    def duree(self):
        if self.rentre_le is None or self.rentre_le < self.parti_le:
            return None
        return self.rentre_le - self.parti_le


class NatureAppelStandard(models.TextChoices):
    DEMANDE_AIDE = "DEMANDE_AIDE", "Demande d'aide"
    OFFRE_AIDE = "OFFRE_AIDE", "Offre d'aide"
    SIGNALEMENT = "SIGNALEMENT", "Signalement"
    PERSONNE_DISPARUE = "PERSONNE_DISPARUE", "Personne disparue"
    RENSEIGNEMENT = "RENSEIGNEMENT", "Demande de renseignement"
    AUTRE = "AUTRE", "Autre"


class SuiteAppelStandard(models.TextChoices):
    A_TRAITER = "A_TRAITER", "À traiter"
    TRANSMIS = "TRANSMIS", "Transmis"
    TRAITE = "TRAITE", "Traité"
    SANS_SUITE = "SANS_SUITE", "Sans suite"


class AppelStandard(EnvironmentScopedModel):
    """Une fiche d'appel du standard de crise d'une collectivité (17/11/2026) : qui a appelé,
    pour quoi, et quelle suite a été donnée — voir core/standard_crise.py.

    Tout ce qui parle de la personne est chiffré. Un appel qui demande une intervention ouvre
    un dossier (`dossier`), qui ne reprend aucune de ces données : il renvoie à la fiche.

    18/11/2026, correction de Sylvain : une demande d'aide, une offre, un signalement ou une
    personne disparue reçus par téléphone ne sont PAS notés ici à part — ce serait un doublon.
    L'agent remplit le formulaire public à la place de l'appelant, et la vraie fiche est créée ;
    celle-ci n'en garde que la trace de l'appel (qui a décroché, quand) et y renvoie
    (`demandes`, `offres`, `informations`, `recherches`). Seuls « renseignement » et « autre »
    se saisissent directement ici."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="appels_standard")
    crise = models.ForeignKey(Crisis, on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_standard")
    #: Numéro lisible, par institution : c'est lui qu'on cite au téléphone et dans le dossier.
    numero = models.PositiveIntegerField()
    nature = models.CharField(max_length=20, choices=NatureAppelStandard.choices)
    appelant_nom = EncryptedTextField(blank=True, default="")
    appelant_telephone = EncryptedTextField(blank=True, default="")
    lieu = EncryptedTextField(blank=True, default="")
    objet = EncryptedTextField()
    suite = models.CharField(max_length=15, choices=SuiteAppelStandard.choices, default=SuiteAppelStandard.A_TRAITER)
    suite_donnee = EncryptedTextField(blank=True, default="")
    dossier = models.ForeignKey(
        "Dossier", on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_standard")
    recu_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_standard_recus")
    date_appel = models.DateTimeField(auto_now_add=True)
    traite_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_standard_traites")
    traite_le = models.DateTimeField(null=True, blank=True)
    #: Tiré par le navigateur à l'ouverture du formulaire : un formulaire qui crée plusieurs
    #: fiches (deux besoins dans une même demande) ne laisse qu'UNE fiche d'appel.
    identifiant_saisie = models.UUIDField(null=True, blank=True)
    demandes = models.ManyToManyField("Request", blank=True, related_name="appels_standard")
    offres = models.ManyToManyField("Offer", blank=True, related_name="appels_standard")
    informations = models.ManyToManyField("Information", blank=True, related_name="appels_standard")
    recherches = models.ManyToManyField("RecherchePersonne", blank=True, related_name="appels_standard")

    class Meta:
        ordering = ["-date_appel"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "numero", "environment"], name="uq_appel_standard_institution_numero"),
            models.UniqueConstraint(
                fields=["institution", "identifiant_saisie", "environment"],
                condition=models.Q(identifiant_saisie__isnull=False), name="uq_appel_standard_saisie"),
        ]


class PhotoReponseTerrain(EnvironmentScopedModel):
    """Une photo jointe à une réponse de formulaire de terrain, pour une question de type
    PHOTO : la fissure, la toiture, la laisse de crue. Chiffrée sur le disque.

    Elle arrive APRÈS sa réponse, par un envoi à part (un fichier ne voyage pas dans un JSON),
    et porte elle aussi un identifiant tiré sur l'appareil : renvoyée après une coupure de
    réseau, elle n'est rangée qu'une fois."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reponse = models.ForeignKey(
        "ReponseFormulaireTerrain", on_delete=models.CASCADE, related_name="photos")
    question_cle = models.CharField(max_length=40)
    identifiant_client = models.UUIDField()
    fichier = models.FileField(
        storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255,
        validators=[validate_image_file],
    )
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_ajout"]
        constraints = [
            models.UniqueConstraint(
                fields=["reponse", "identifiant_client"], name="uq_photo_reponse_terrain_identifiant_client"),
        ]


class ProcedurePPR(EnvironmentScopedModel):
    """Un plan de prévention des risques qui couvre une commune (Géorisques, base Gaspar),
    gardé en base — voir core/plans_prevention.py. `zones` porte les types de zones de son
    règlement (nom et règle), pas leur tracé, que Géorisques ne sert pas."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commune_code = models.CharField(max_length=10)
    #: pprn (naturels), pprt (technologiques) ou pprm (miniers).
    famille = models.CharField(max_length=10)
    id_gaspar = models.CharField(max_length=40)
    libelle = models.CharField(max_length=255, blank=True, default="")
    modele = models.CharField(max_length=40, blank=True, default="")
    bassin = models.CharField(max_length=255, blank=True, default="")
    en_revision = models.BooleanField(default=False)
    zonage_existe = models.BooleanField(default=False)
    zones = models.JSONField(default=list, blank=True)
    modifie_le = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "id_gaspar", "environment"],
                name="uq_procedure_ppr_commune_gaspar_environment",
            )
        ]


class ServitudePPR(EnvironmentScopedModel):
    """Le périmètre d'un plan de prévention des risques qui touche une commune, et l'adresse de
    son acte, tels que le Géoportail de l'urbanisme les publie (core/geoportail_urbanisme.py).
    Donnée publique. L'acte lui-même n'est pas recopié : il peut peser plus de 100 Mo."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commune_code = models.CharField(max_length=10, db_index=True)
    categorie = models.CharField(max_length=5)
    identifiant = models.CharField(max_length=120, blank=True, default="")
    nom = models.CharField(max_length=255)
    type_assiette = models.CharField(max_length=120, blank=True, default="")
    fichier = models.CharField(max_length=255, blank=True, default="")
    url_acte = models.CharField(max_length=500, blank=True, default="")
    polygone = gis_models.MultiPolygonField(srid=4326)
    releve_le = models.DateTimeField(auto_now=True)


class ReleveGeorisques(EnvironmentScopedModel):
    """Ce que Géorisques publie pour une commune, rubrique par rubrique, copié en base : risques
    recensés, arrêtés de catastrophe naturelle, atlas des zones inondables, mouvements de
    terrain, radon, sismicité (voir core/releve_georisques.py). Données publiques : rien de
    personnel. Les pages lisent cette copie, jamais le service."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commune_code = models.CharField(max_length=10)
    rubrique = models.CharField(max_length=20)
    donnees = models.JSONField(default=list)
    releve_le = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["commune_code", "rubrique", "environment"], name="uq_releve_georisques"),
        ]


class RelevePPR(EnvironmentScopedModel):
    """Trace qu'une famille de plans a été relevée pour une commune, même s'il n'y en a aucun :
    « relevé, et rien ici » n'est pas « jamais relevé »."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commune_code = models.CharField(max_length=10)
    famille = models.CharField(max_length=10)
    releve_le = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "famille", "environment"],
                name="uq_releve_ppr_commune_famille_environment",
            )
        ]


class ZonageOfficiel(EnvironmentScopedModel):
    """Une zone inondable officielle de l'État pour une commune (Géorisques), gardée en base.

    Relevée une fois, à la demande d'un agent, puis relue d'ici : la carte, le croisement avec
    les enjeux du plan, l'export et le document du plan n'interrogent jamais Géorisques
    eux-mêmes (voir core/zonages_officiels.py, qui espace les requêtes). Une ligne par scénario,
    même quand la commune n'a aucune zone pour lui : `polygone` vide veut alors dire « relevé,
    et rien ici » -- ce qui n'est pas la même chose que « jamais relevé »."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commune_code = models.CharField(max_length=10)
    #: Nom de la couche chez Géorisques (voir habitations.COUCHES_GEORISQUES).
    couche = models.CharField(max_length=40)
    polygone = gis_models.MultiPolygonField(srid=4326, null=True, blank=True)
    releve_le = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commune_code", "couche", "environment"],
                name="uq_zonage_officiel_commune_couche_environment",
            )
        ]

    def __str__(self):
        return f"{self.commune_code} — {self.couche}"


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


class EchelonEquipe(models.TextChoices):
    """Échelon territorial d'une équipe de coordination.

    Conçu et validé le 28/10/2026, écrit le 11/11/2026 pour l'arborescence des Casques Jaunes :
    `Team` avait déjà `equipe_parente` (arbre de profondeur libre) mais **aucun territoire**, et
    rien ne permettait donc de trier les équipes département → région → zone → national.

    Vide pour les équipes opérationnelles ordinaires, qui sont la grande majorité : un échelon ne
    se devine pas et le poser par défaut rangerait de force des équipes qui n'appartiennent à
    aucune hiérarchie.

    ZONE_DEFENSE correspond aux zones de défense et de sécurité (7 en métropole, décret du
    10/12/2015, plus les zones outre-mer) — voir core/zones_defense.py."""

    NATIONAL = "NATIONAL", "Coordination nationale"
    ZONE_DEFENSE = "ZONE_DEFENSE", "Coordination de zone de défense"
    REGIONAL = "REGIONAL", "Coordination régionale"
    DEPARTEMENTAL = "DEPARTEMENTAL", "Coordination départementale"
    COMMUNAL = "COMMUNAL", "Échelon communal"


# Du plus large au plus fin : sert à TRIER les équipes d'une arborescence. L'ordre est une
# donnée, pas l'ordre de déclaration de l'énumération -- s'en remettre à celui-ci casserait au
# premier échelon inséré au milieu.
ORDRE_ECHELONS = [
    EchelonEquipe.NATIONAL,
    EchelonEquipe.ZONE_DEFENSE,
    EchelonEquipe.REGIONAL,
    EchelonEquipe.DEPARTEMENTAL,
    EchelonEquipe.COMMUNAL,
]


class Team(EnvironmentScopedModel):
    """Équipes de gestion de crise"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = EncryptedTextField(null=True, blank=True)
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

    # ÉCHELON ET TERRITOIRE : ce qui manquait pour qu'un arbre d'équipes signifie quelque
    # chose. `equipe_parente` dit QUI est rattaché à qui ; ces deux champs disent CE QUE
    # représente l'équipe, donc comment la trier et où la chercher.
    echelon = models.CharField(
        max_length=15, choices=EchelonEquipe.choices, blank=True, default="",
        help_text="Vide pour une équipe opérationnelle ordinaire, qui n'appartient à aucune "
                   "hiérarchie territoriale.",
    )
    # Code INSEE pour une région ou un département ; identifiant de zone (ex. « ZD-SUD ») pour
    # une zone de défense, qui n'a pas de code INSEE. Jamais interprété géographiquement : le
    # matching d'intervention reste celui de `departements` / `communes` / `zone_precise`
    # ci-dessous, et une équipe départementale les renseigne AUSSI.
    # 20 et non 10 : un code INSEE tient en 3 caractères, mais un identifiant de zone de
    # défense est un libellé (« ZD-OCEAN-INDIEN », 15). Mesuré, pas estimé.
    territoire_code = models.CharField(max_length=20, blank=True, default="")
    territoire_libelle = models.CharField(max_length=100, blank=True, default="")

    # ENCADREMENT, par équipe et non par personne : la même personne peut encadrer son
    # département et n'être qu'intervenante ailleurs. Ni `leader` ni `regulateur` ne pouvaient
    # servir (une seule personne chacun), et AffectationRoleOperationnel est par INSTITUTION.
    # Pilote la composition du salon Matrix « Encadrement » (voir SalonMatrixEquipe).
    membres_encadrement = models.ManyToManyField(
        User, blank=True, related_name="teams_encadrees",
        help_text="Membres de cette équipe qui en forment l'encadrement. Un encadrant doit "
                   "aussi être membre : l'encadrement est une qualité au sein de l'équipe, "
                   "pas une appartenance de plus.",
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

    @property
    def rang_echelon(self):
        """Position dans ORDRE_ECHELONS, ou la fin pour une équipe sans échelon.

        Sert au tri : une équipe sans échelon ne doit pas s'intercaler entre deux échelons, elle
        vient après."""
        if not self.echelon:
            return len(ORDRE_ECHELONS)
        try:
            return ORDRE_ECHELONS.index(self.echelon)
        except ValueError:
            return len(ORDRE_ECHELONS)


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
    commentaire = EncryptedTextField(blank=True, null=True)

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
    # « Je rentre » (17/11/2026) : la fin de l'engagement, déclarée par la personne elle-même.
    # Avec « je pars » (EN_TRANSIT), c'est ce qui donne le temps réellement passé.
    RENTRE = "RENTRE", "Rentré — engagement terminé"


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
    # Chiffré ; retrouvé par son empreinte exacte (`token_confirmation_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    token_confirmation = EncryptedTextField(max_length=64)
    token_confirmation_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    date_transit = models.DateTimeField(null=True, blank=True)
    date_arrivee = models.DateTimeField(null=True, blank=True)
    date_retour = models.DateTimeField(null=True, blank=True)

    @property
    def duree_engagee(self):
        """Du départ déclaré (« je pars ») au retour déclaré (« je rentre »), ou None tant que
        l'un des deux manque. À défaut de départ déclaré, l'arrivée fait foi : on ne compte pas
        un trajet que personne n'a déclaré."""
        debut = self.date_transit or self.date_arrivee
        if debut is None or self.date_retour is None or self.date_retour < debut:
            return None
        return self.date_retour - debut

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

    titre = EncryptedTextField(
        max_length=255
    )

    message = EncryptedTextField()

    # ── La fiche derrière le résumé ─────────────────────────────────────────────────────
    # Ajouté le 12/11/2026 : « le régulateur en voit un résumé, clique dessus, et ouvre la
    # fiche de la notification avec qui, quand, quoi, comment ».
    #
    # Une notification tenait jusqu'ici en un titre et un paragraphe, et le clic emmenait au
    # mieux sur une crise — à charge pour le lecteur de retrouver de quoi on lui parlait.
    # `details` porte les faits sous forme de couples libellé/valeur, affichés tels quels :
    # c'est la forme qui convient à toutes les notifications sans en figer aucune.
    #
    # ⚠ `details` N'EST PAS CHIFFRÉ. On n'y met donc que ce qui peut être lu en clair dans la
    # base : des noms d'institutions, des dates, des libellés de besoin. Jamais le nom, le
    # téléphone ou l'adresse d'une personne — ces informations vivent dans leur modèle, et la
    # fiche renvoie vers lui par `lien`.
    details = EncryptedJSONField(
        default=list, blank=True,
        help_text="Liste de {\"libelle\": ..., \"valeur\": ...} affichée dans la fiche. "
                   "Aucune donnée personnelle : ce champ n'est pas chiffré.",
    )

    #: Route de l'application à ouvrir depuis la fiche (ex: « /admin/crises?id=… »). Relative,
    #: jamais une URL absolue : une notification ne doit pas pouvoir emmener hors du site.
    lien = models.CharField(max_length=500, blank=True, default="")

    #: Intitulé du bouton qui suit `lien` — « Ouvrir la crise », « Voir la demande ». Sans
    #: lui, le bouton dirait « Ouvrir » sans dire quoi.
    lien_libelle = models.CharField(max_length=80, blank=True, default="")

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
    lieu_texte = EncryptedTextField(max_length=255, blank=True)

    motif = EncryptedTextField(blank=True)

    statut = models.CharField(
        max_length=15, choices=StatutDemandeMobilisation.choices, default=StatutDemandeMobilisation.ACTIVE,
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_revocation = models.DateTimeField(null=True, blank=True)

    # Chiffré ; retrouvé par son empreinte exacte (`jeton_verification_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    jeton_verification = EncryptedTextField(max_length=64, null=True, blank=True)
    jeton_verification_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

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

    ville = EncryptedTextField(
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

    #: La collectivité ou la structure qui a enregistré cette fiche À LA DEMANDE de la personne
    #: (au téléphone, au guichet) — voir core/standard_crise.py. Vide : déposée par elle-même.
    enregistre_pour_autrui_par = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
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

    commentaire = EncryptedTextField()

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

    commentaire = EncryptedTextField(
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

    commentaire = EncryptedTextField(
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

    nom = EncryptedTextField(max_length=100)

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

    commentaire = EncryptedTextField(
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
    responsabilite = EncryptedTextField(
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

    # Début de la PÉRIODE déclarée, et non l'instant de la déclaration : deux choses
    # différentes, et les confondre rendait le modèle incapable d'exprimer « je suis disponible
    # le 5 novembre ». `auto_now_add` écrasait systématiquement la valeur par l'heure de
    # création, si bien qu'on ne pouvait dire que « disponible à partir de maintenant jusqu'à
    # telle date » — donc aucune grille prospective, alors que c'est exactement ce qu'une
    # association regarde pour armer une garde (voir DisponibiliteOperationnelleViewSet.grille).
    #
    # Corrigé le 28/10/2026 sans risque : la table était vide et aucun écran ne l'alimentait.
    # Quatre autres modèles partagent cette forme (InstitutionCompetence,
    # AffectationCompetence, AffectationRoleOperationnel, DelegationCompetence) et ne sont PAS
    # touchés : pour eux « depuis quand cela vaut » est bien l'instant de création, et ils
    # portent des données réelles.
    date_debut = models.DateTimeField(
        default=timezone.now,
        help_text="Début de la période de disponibilité déclarée.",
    )

    date_fin = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fin de la période. Vide = permanence ouverte, sans terme.",
    )

    # Quand la déclaration a été faite. Null sur les lignes antérieures à ce champ : leur
    # `date_debut` ÉTAIT leur date de création, prétendre la connaître autrement serait
    # inventer.
    date_creation = models.DateTimeField(auto_now_add=True, null=True)

    commentaire = EncryptedTextField(
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

    commentaire = EncryptedTextField(
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

# Denrées et lieux de stock (core/stocks.py) : conservation, préparation, moyens du lieu.
class ConservationStock(models.TextChoices):
    AMBIANT = "AMBIANT", "Température ambiante"
    FRAIS = "FRAIS", "Au frais (0 à 4 °C)"
    SURGELE = "SURGELE", "Surgelé (−18 °C)"


class PreparationStock(models.TextChoices):
    """Ce qu'il faut pour qu'une denrée soit consommable. Vide : ce n'est pas une denrée."""
    PRET = "PRET", "Prêt à consommer"
    A_RECHAUFFER = "A_RECHAUFFER", "À réchauffer"
    A_CUISINER = "A_CUISINER", "À cuisiner"


class CuissonLieu(models.TextChoices):
    AUCUNE = "AUCUNE", "Rien pour chauffer"
    RECHAUFFAGE = "RECHAUFFAGE", "De quoi réchauffer"
    CUISINE = "CUISINE", "Une cuisine"


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

    #: Le lieu de la commune où ce point est installé, quand ce lieu tient déjà un stock : le
    #: gymnase, l'atelier municipal. Demande de Sylvain du 18/11/2026 — « je fais mon stock au
    #: dépôt "gymnase" et quand je fais mon "centre d'accueil gymnase" je récupère son stock ».
    #: Un même lieu a plusieurs usages : dépôt en temps normal, centre d'accueil ET point de
    #: regroupement pendant une crise, tous sur le même stock (voir core/stocks_points.py).
    lieu_de_stock = models.ForeignKey(
        "DepotStock", on_delete=models.SET_NULL, null=True, blank=True, related_name="points_installes")

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

    adresse = EncryptedTextField(
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

    commentaire = EncryptedTextField(
        blank=True,
        null=True
    )

    description = EncryptedTextField(
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

    # Ce que le point a pour garder et préparer des denrées (core/stocks_points.py) : sans froid,
    # on n'y envoie pas de frais ; sans de quoi chauffer, pas de plats à réchauffer.
    froid_positif = models.BooleanField(default=False, help_text="Réfrigérateur ou chambre froide (0 à 4 °C).")
    froid_negatif = models.BooleanField(default=False, help_text="Congélateur (−18 °C).")
    cuisson = models.CharField(max_length=12, choices=CuissonLieu.choices, default=CuissonLieu.AUCUNE)

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

    description = EncryptedTextField(blank=True, null=True)

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

    description = EncryptedTextField(blank=True, null=True)

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


class DossierPCS(EnvironmentScopedModel):
    """Ce que le plan communal de sauvegarde d'une institution a d'ADMINISTRATIF, et que rien
    d'autre ne porte : l'arrêté qui l'approuve, le lieu du poste de commandement communal, et
    le texte des modalités d'activation.

    Tout le reste du plan -- risques, enjeux, dispositifs, missions, annuaire, moyens -- existe
    déjà ailleurs et n'est PAS recopié ici : le document se construit à la demande depuis ces
    données vivantes (core/document_pcs.py). Recopier ferait deux vérités, dont une périmée.

    Une ligne par institution et par zone (PROD/DEMO), créée à la première ouverture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="dossiers_pcs")

    arrete_numero = models.CharField(max_length=60, blank=True)
    arrete_date = models.DateField(null=True, blank=True)
    lieu_pcc = EncryptedTextField(
        max_length=255, blank=True,
        help_text="Où se réunit le poste de commandement communal (salle, adresse).",
    )
    lieu_pcc_repli = EncryptedTextField(
        max_length=255, blank=True,
        help_text="Lieu de repli si le premier est inaccessible (inondé, sans courant).",
    )
    modalites_activation = EncryptedTextField(
        blank=True,
        help_text="Qui déclenche le plan, sur quels signaux, et comment l'équipe est prévenue.",
    )
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["institution", "environment"], name="dossier_pcs_unique"),
        ]

    def __str__(self) -> str:
        return f"Dossier PCS — {self.institution.nom}"


class RevisionPCS(EnvironmentScopedModel):
    """Une ligne du « tableau des mises à jour » du plan : ce qui a été revu, quand, par qui.
    Immuable, comme la main courante : on n'efface pas l'historique d'un plan."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dossier = models.ForeignKey(DossierPCS, on_delete=models.CASCADE, related_name="revisions")
    date = models.DateField()
    objet = EncryptedTextField(max_length=500)
    auteur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="revisions_pcs",
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-date_creation"]

    def __str__(self) -> str:
        return f"{self.date:%d/%m/%Y} — {self.objet[:60]}"


class FonctionPCS(EnvironmentScopedModel):
    """Une case de l'organigramme du poste de commandement communal, et sa fiche réflexe.

    Deux façons de dire qui tient la fonction, et la première évite les doublons : désigner
    l'ÉQUIPE qui la tient (`equipe`), dont le responsable et l'encadrement sont alors repris ; ou,
    à défaut, saisir des NOMS -- dans une petite commune, l'adjoint chargé de la logistique n'a
    pas forcément de compte, et le jour de la crise c'est un nom et un téléphone qu'on cherche.
    Un nom saisi l'emporte sur celui de l'équipe. Chiffrés, comme toute coordonnée.

    `consignes` vide = la fiche type de la trame de l'État (core/pcs_fiches.py), reprise telle
    quelle dans le document. La commune ne réécrit que ce qu'elle veut changer."""

    class Fonction(models.TextChoices):
        DOS = "DOS", "Maire — directeur des opérations de secours"
        COORDINATION = "COORDINATION", "Coordinateur des moyens et des actions"
        ALERTE = "ALERTE", "Responsable de l'alerte de la population"
        SOUTIEN = "SOUTIEN", "Responsable du soutien des populations"
        LOGISTIQUE = "LOGISTIQUE", "Responsable logistique"
        SECRETARIAT = "SECRETARIAT", "Secrétariat"
        AUTRE = "AUTRE", "Autre fonction"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dossier = models.ForeignKey(DossierPCS, on_delete=models.CASCADE, related_name="fonctions")
    fonction = models.CharField(max_length=20, choices=Fonction.choices)
    libelle = models.CharField(max_length=120, blank=True, help_text="Nom de la fonction, quand elle est « autre ».")
    # L'équipe qui tient la fonction. C'est le lien qui évite de nommer les mêmes personnes deux
    # fois : quand il est posé, le responsable de l'équipe est le titulaire et son encadrement
    # fournit le suppléant (voir document_pcs.personnes_de_la_fonction). Et c'est de CETTE
    # équipe que l'équipe créée pour une crise reprend ses membres, pour le point correspondant
    # (cellule de crise, centre d'accueil, regroupement des moyens). L'équipe de la crise reste
    # une équipe à part : un salon par crise (document_pcs.composer_depuis_le_plan).
    equipe = models.ForeignKey(
        "Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="fonctions_pcs",
    )
    titulaire = EncryptedTextField(blank=True, default="")
    titulaire_telephone = EncryptedTextField(blank=True, default="")
    suppleant = EncryptedTextField(blank=True, default="")
    suppleant_telephone = EncryptedTextField(blank=True, default="")
    consignes = EncryptedTextField(blank=True, help_text="Fiche réflexe propre à la commune ; vide = la fiche type.")
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date_maj"]

    def __str__(self) -> str:
        return self.libelle or self.get_fonction_display()


class MoyenAlertePCS(EnvironmentScopedModel):
    """Un moyen d'alerter la population : sirène, véhicule avec haut-parleur, automate d'appel,
    personne relais d'un quartier… FR-Alert n'en fait pas partie : il relève du préfet."""

    class Type(models.TextChoices):
        SIRENE = "SIRENE", "Sirène"
        VEHICULE = "VEHICULE", "Véhicule avec haut-parleur"
        AUTOMATE = "AUTOMATE", "Automate d'appel ou de SMS"
        RELAIS = "RELAIS", "Personne relais de quartier"
        PORTE_A_PORTE = "PORTE_A_PORTE", "Porte-à-porte"
        AFFICHAGE = "AFFICHAGE", "Panneaux, site et réseaux de la commune"
        AUTRE = "AUTRE", "Autre moyen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dossier = models.ForeignKey(DossierPCS, on_delete=models.CASCADE, related_name="moyens_alerte")
    type = models.CharField(max_length=20, choices=Type.choices)
    description = EncryptedTextField(max_length=500, blank=True, help_text="Lieu, circuit, liste de diffusion…")
    zone = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name="moyens_alerte")
    personne = EncryptedTextField(blank=True, default="")
    personne_telephone = EncryptedTextField(blank=True, default="")
    #: Fiche de déclenchement propre à la commune ; vide = la fiche type du moyen (core/pcs_fiches.py).
    consignes = EncryptedTextField(blank=True, default="")
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type", "date_maj"]

    def __str__(self) -> str:
        return f"{self.get_type_display()} — {self.description[:60]}"


class PieceJointePCS(EnvironmentScopedModel):
    """Un fichier déposé par la commune sur son plan : la procédure de déclenchement de la
    sirène, le plan du gymnase, la fiche réflexe maison en PDF (18/11/2026).

    Rattaché au plan tout entier, ou à UNE fiche réflexe (`fonction`), ou à UN moyen d'alerte
    (`moyen_alerte`) — c'est ce dernier que la page « Alerter les habitants » ressort quand on
    coche la sirène.

    Même sécurité que le reste : chiffré sur le disque (`get_encrypted_file_storage`), rangé
    sous `documents/` que le serveur web refuse de servir, et lu seulement par la vue du plan,
    qui vérifie que l'appelant tient le plan de CETTE collectivité et inscrit chaque
    téléchargement à la main courante."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dossier = models.ForeignKey(DossierPCS, on_delete=models.CASCADE, related_name="pieces")
    fonction = models.ForeignKey(FonctionPCS, on_delete=models.CASCADE, null=True, blank=True, related_name="pieces")
    moyen_alerte = models.ForeignKey(MoyenAlertePCS, on_delete=models.CASCADE, null=True, blank=True, related_name="pieces")
    titre = EncryptedTextField(max_length=200)
    fichier = models.FileField(
        storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255,
        validators=[validate_identity_document_file],
    )
    #: Nom d'origine, pour le rendre au téléchargement ; le nom sur le disque est un identifiant.
    nom_fichier = EncryptedTextField(max_length=200, blank=True, default="")
    type_mime = models.CharField(max_length=60, blank=True, default="")
    taille = models.PositiveIntegerField(default=0)
    depose_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_depot = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_depot"]   # le titre est chiffré : trié en Python à l'affichage
        verbose_name = "pièce jointe du plan"

class ExercicePCS(EnvironmentScopedModel):
    """Un exercice du plan et ce qu'on en a tiré. `crise` relie, quand il y en a une, la crise
    d'exercice qui a servi à le jouer dans l'application."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dossier = models.ForeignKey(DossierPCS, on_delete=models.CASCADE, related_name="exercices")
    date = models.DateField()
    theme = EncryptedTextField(max_length=255)
    deroulement = EncryptedTextField(blank=True)
    enseignements = EncryptedTextField(blank=True)
    actions = EncryptedTextField(blank=True, help_text="Ce qui doit changer dans le plan à la suite de l'exercice.")
    crise = models.ForeignKey("Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="exercices_pcs")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date:%d/%m/%Y} — {self.theme[:60]}"


class AbonnementAlerte(EnvironmentScopedModel):
    """Un habitant qui a demandé à recevoir les alertes d'une collectivité.

    C'est un consentement, pas une déduction : on n'écrit pas aux gens parce qu'ils habitent
    quelque part, on écrit à ceux qui l'ont demandé. `actif=False` = il s'est désabonné ; la
    ligne reste, pour savoir qu'il l'a fait."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="abonnements_alerte")
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="abonnes_alerte")
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "institution", "environment"], name="abonnement_alerte_unique"),
        ]

    def __str__(self) -> str:
        return f"Abonnement de {self.utilisateur_id} aux alertes de {self.institution.nom}"


class AlertePopulation(EnvironmentScopedModel):
    """Une alerte envoyée aux habitants par une collectivité, et ce qu'elle est devenue.

    Ce n'est PAS l'alerte officielle (FR-Alert relève du préfet) : c'est le message de la
    commune à ceux qui ont demandé à le recevoir, et aux personnes déjà touchées par la crise.

    `bilan` garde, canal par canal, combien de personnes étaient joignables, combien de messages
    sont partis et pourquoi les autres ne le sont pas -- une alerte « envoyée » qui n'a touché
    personne est la pire des fausses assurances. Immuable : une alerte partie ne se corrige pas,
    on en envoie une autre."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.PROTECT, related_name="alertes_population")
    crise = models.ForeignKey("Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="alertes_population")
    titre = EncryptedTextField(max_length=150)
    message = EncryptedTextField()
    urgent = models.BooleanField(default=True)
    canaux = models.JSONField(default=list)
    bilan = EncryptedJSONField(default=dict)
    #: Ce que l'alerte a demandé SUR LE TERRAIN : sirène, véhicule, relais, porte-à-porte — les
    #: moyens décrits dans « Alerte de la population » (18/11/2026). Une ligne par moyen coché.
    terrain = EncryptedJSONField(default=list, blank=True)
    destinataires = models.PositiveIntegerField(default=0)
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="alertes_population")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"{self.date_creation:%d/%m/%Y %H:%M} — {self.titre}"


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

    commentaire = EncryptedTextField(blank=True, null=True)

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

    commentaire = EncryptedTextField(blank=True, null=True)

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

    commentaire = EncryptedTextField(blank=True, null=True)

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


# ══ Suivi du relogement des familles ═══════════════════════════════════════════════════════
#
# Demande de Sylvain du 12/11/2026 : « comme on a fait une page suivi hébergement des équipes,
# il me faudra une page, suivi hébergement des familles nécessitant un relogement [...] tout ce
# qui est nécessaire pour assurer le suivi de personnes ayant bénéficié d'un relogement suite à
# une crise. À terme, on devra pouvoir éditer des rapports [...] tant de familles relogées,
# tant de manières pérennes. »
#
# **Pourquoi DEUX tables et non une.** Un foyer sinistré passe presque toujours par plusieurs
# solutions successives : gymnase la première nuit, hôtel la semaine suivante, logement
# communal pour six mois, puis un bail. Écrire tout cela dans une seule ligne mise à jour en
# place détruit l'historique — or c'est précisément l'historique que le rapport demande : « tant
# de familles relogées DE MANIÈRE PÉRENNE » suppose de savoir distinguer le provisoire de ce qui
# a tenu. Le dossier porte donc le foyer et son parcours ; chaque hébergement est une ligne.
#
# **Rien en clair.** Le nom du référent, ses coordonnées, la composition du foyer et les notes
# d'accompagnement sont les données les plus sensibles de tout le produit : des personnes
# sinistrées, nommées, avec l'adresse où elles dorment. Tout ce qui est nominatif est en
# `EncryptedTextField`, comme le reste du domaine (voir DOCUMENTATION.md § 10.1).


class TypeSolutionRelogement(models.TextChoices):
    """Ce que vaut la solution dans le temps — la colonne qui fait le rapport.

    Trois valeurs, pas deux : l'intermédiaire existe pour de vrai (un logement communal prêté
    six mois pendant que l'assurance instruit), et le compter comme définitif ferait annoncer
    des familles relogées qui seront à la rue au printemps."""

    URGENCE = "URGENCE", "Hébergement d'urgence (quelques nuits)"
    TEMPORAIRE = "TEMPORAIRE", "Solution temporaire (quelques semaines)"
    INTERMEDIAIRE = "INTERMEDIAIRE", "Solution intermédiaire (plusieurs mois)"
    DEFINITIVE = "DEFINITIVE", "Solution définitive (retour ou relogement pérenne)"


class TitreOccupation(models.TextChoices):
    """À quel titre la famille occupe le logement : ce qui dit si elle peut en être sortie."""

    CENTRE = "CENTRE", "Centre d'hébergement collectif"
    HOTEL = "HOTEL", "Hôtel ou meublé payé par la collectivité"
    PROCHES = "PROCHES", "Hébergée par des proches"
    PRET = "PRET", "Prêt à titre gratuit"
    CONVENTION = "CONVENTION", "Convention d'occupation précaire"
    BAIL = "BAIL", "Bail (meublé, HLM, parc privé)"
    RETOUR = "RETOUR", "Retour au domicile d'origine"


class StatutDossierRelogement(models.TextChoices):
    EN_RECHERCHE = "EN_RECHERCHE", "Sans solution — en recherche"
    HEBERGE = "HEBERGE", "Hébergée"
    RELOGEE = "RELOGEE", "Relogée durablement"
    RETOUR_DOMICILE = "RETOUR_DOMICILE", "Retournée au domicile"
    CLOS_SANS_SUITE = "CLOS_SANS_SUITE", "Clos sans suite (perdue de vue, refus, départ)"


class DossierRelogement(EnvironmentScopedModel):
    """Un foyer à reloger à la suite d'une crise, et son parcours.

    L'unité est le FOYER et non la personne : on reloge une famille, on ne la découpe pas. La
    composition (`nombre_adultes`, `nombre_enfants`) sert aux rapports — « 31 personnes » n'est
    pas « 12 familles », et les deux chiffres sont attendus."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, related_name="dossiers_relogement",
    )
    #: Qui assure le suivi. La mairie le plus souvent, parfois l'association mandatée.
    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dossiers_relogement",
    )

    # ── Le foyer ────────────────────────────────────────────────────────────────────────
    # Chiffrés : des personnes sinistrées, nommées, avec l'endroit où elles dorment.
    nom_referent = EncryptedTextField(
        max_length=255,
        help_text="Nom de la personne référente du foyer, telle qu'on s'adresse à elle.",
    )
    telephone_referent = EncryptedTextField(max_length=50, blank=True, null=True)
    email_referent = EncryptedTextField(max_length=255, blank=True, null=True)

    nombre_adultes = models.PositiveSmallIntegerField(default=1)
    nombre_enfants = models.PositiveSmallIntegerField(default=0)
    #: Ce qui fait passer un dossier devant les autres, et qui conditionne le type de logement.
    personnes_vulnerables = models.BooleanField(
        default=False,
        help_text="Personne âgée, en situation de handicap, malade, femme enceinte, "
                   "nourrisson : à loger en priorité et pas n'importe où.",
    )
    animaux = models.BooleanField(
        default=False,
        help_text="Un foyer avec animaux est refusé par la plupart des hébergements : c'est "
                   "un critère de recherche, pas un détail.",
    )
    besoin_pmr = models.BooleanField(default=False)

    commune_origine_code = models.CharField(max_length=10, blank=True, default="")
    commune_origine_nom = models.CharField(max_length=255, blank=True, default="")

    # ── Rattachements, tous facultatifs ─────────────────────────────────────────────────
    # Un dossier de relogement naît souvent d'une demande d'aide ou d'un constat de dégâts ;
    # il peut aussi être ouvert à la main depuis un accueil physique, sans rien derrière.
    demande = models.ForeignKey(
        "Request", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dossiers_relogement",
        help_text="Demande d'hébergement à l'origine du dossier, si elle existe.",
    )
    dossier = models.ForeignKey(
        "Dossier", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dossiers_relogement",
    )
    habitation = models.ForeignKey(
        "Habitation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dossiers_relogement",
        help_text="Logement sinistré d'origine (module d'estimation des dégâts).",
    )

    statut = models.CharField(
        max_length=20, choices=StatutDossierRelogement.choices,
        default=StatutDossierRelogement.EN_RECHERCHE,
    )

    #: Notes d'accompagnement social. Chiffrées : c'est ce qu'il y a de plus intime dans un
    #: dossier de crise.
    accompagnement = EncryptedTextField(blank=True, null=True)

    date_ouverture = models.DateField(default=datetime.date.today)
    date_cloture = models.DateField(null=True, blank=True)

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"Relogement {self.crise.name} — {self.nombre_personnes} personne(s)"

    @property
    def nombre_personnes(self) -> int:
        return (self.nombre_adultes or 0) + (self.nombre_enfants or 0)

    @property
    def solution_courante(self):
        """L'hébergement en cours, c'est-à-dire la dernière ligne non terminée.

        Pas « la plus récente » tout court : une solution close le mois dernier ne loge
        personne, et l'afficher comme courante ferait croire la famille à l'abri."""
        return self.solutions.filter(date_fin_effective__isnull=True).order_by(
            "-date_debut", "-date_creation").first()


class SolutionRelogement(EnvironmentScopedModel):
    """Un hébergement successif d'un foyer : où, à quel titre, de quand à quand.

    Une ligne par solution, jamais une mise à jour en place : le parcours d'un foyer EST
    l'information que le rapport de fin de crise demande."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    dossier_relogement = models.ForeignKey(
        DossierRelogement, on_delete=models.CASCADE, related_name="solutions",
    )

    type_solution = models.CharField(max_length=20, choices=TypeSolutionRelogement.choices)
    titre_occupation = models.CharField(max_length=20, choices=TitreOccupation.choices)

    # ── Où ──────────────────────────────────────────────────────────────────────────────
    # Trois origines possibles, toutes facultatives : un centre du dispositif, une offre
    # d'hébergement reçue, ou rien de tout cela (un hôtel réservé au téléphone).
    point = models.ForeignKey(
        "PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="solutions_relogement",
        help_text="Centre d'hébergement du dispositif.",
    )
    offre = models.ForeignKey(
        "Offer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="solutions_relogement",
        help_text="Offre d'hébergement retenue pour ce foyer.",
    )
    #: Chiffrée : c'est l'adresse où dort une famille sinistrée.
    adresse = EncryptedTextField(blank=True, null=True)
    commune_code = models.CharField(max_length=10, blank=True, default="")
    commune_nom = models.CharField(max_length=255, blank=True, default="")
    #: Qui héberge, quand ce n'est ni un centre ni une offre enregistrée (un hôtel, un bailleur
    #: social, un particulier venu au guichet).
    hebergeur = EncryptedTextField(max_length=255, blank=True, null=True)
    hebergeur_contact = EncryptedTextField(max_length=255, blank=True, null=True)

    # ── Quand ───────────────────────────────────────────────────────────────────────────
    date_debut = models.DateField()
    #: Terme prévu du prêt, de la convention ou du bail. C'est LA date qui fait le suivi :
    #: sans elle, « arrive à son terme » ne peut pas se calculer, et on découvre la sortie le
    #: jour où la famille appelle.
    date_fin_prevue = models.DateField(null=True, blank=True)
    date_fin_effective = models.DateField(null=True, blank=True)
    motif_fin = EncryptedTextField(max_length=255, blank=True, default="")

    # ── Combien ─────────────────────────────────────────────────────────────────────────
    loyer_mensuel = models.PositiveIntegerField(
        null=True, blank=True, help_text="Euros par mois, entier (même convention que "
                                          "HebergementDetailsMixin.loyer_montant_*).")
    reste_a_charge = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Ce que paie réellement la famille, une fois les aides déduites.")
    prise_en_charge_par = EncryptedTextField(
        max_length=255, blank=True, default="",
        help_text="Qui paie le reste : commune, CCAS, assurance, association…")

    commentaire = EncryptedTextField(blank=True, null=True)

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_debut", "-date_creation"]

    def __str__(self) -> str:
        return f"{self.get_type_solution_display()} du {self.date_debut}"

    @property
    def en_cours(self) -> bool:
        return self.date_fin_effective is None

    @property
    def jours_restants(self):
        """Jours avant le terme PRÉVU, ou None si aucun terme n'est posé.

        Négatif quand le terme est dépassé sans que la sortie ait été enregistrée : c'est un
        cas réel et c'est le plus urgent de tous — personne ne sait où en est cette famille."""
        if self.date_fin_effective is not None or self.date_fin_prevue is None:
            return None
        return (self.date_fin_prevue - datetime.date.today()).days


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

    commentaire = EncryptedTextField(blank=True, null=True)

    # Texte libre (pas d'annuaire de réparateurs).
    reparateur_nom = EncryptedTextField(max_length=255, blank=True, null=True)
    reparateur_contact = EncryptedTextField(max_length=255, blank=True, null=True)
    lieu_reparation = EncryptedTextField(max_length=255, blank=True, null=True)
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
    etat_des_lieux = EncryptedTextField(blank=True)
    enjeux = EncryptedTextField(blank=True)
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
    GEODAE = "GEODAE", "Géo'DAE (base nationale des défibrillateurs)"
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
    # Un défibrillateur n'est pas un lieu à protéger mais un moyen à connaître : toujours une
    # ressource, jamais un enjeu.
    DEFIBRILLATEUR = "DEFIBRILLATEUR", "Défibrillateur"
    AUTRE = "AUTRE", "Autre"


class EchelonCompetence(models.TextChoices):
    """Qui a la charge du site — et donc qui le valide dans SON plan.

    Une collectivité ne valide pas un territoire, elle valide sa compétence : sur les 852
    établissements scolaires du Finistère, 75 collèges publics relèvent du département, 374
    écoles publiques des communes, 40 lycées publics de la région. Mélanger les trois donne une
    liste de 852 lignes « à relire » qu'aucun agent départemental ne relira.

    Le reste doit rester RETROUVABLE sans être à valider : d'où un échelon par ligne et un
    filtre par défaut, plutôt qu'un import qui trierait à la place de l'agent."""
    COMMUNE = "COMMUNE", "Commune"
    EPCI = "EPCI", "Intercommunalité"
    DEPARTEMENT = "DEPARTEMENT", "Département"
    REGION = "REGION", "Région"
    ETAT = "ETAT", "État"
    PRIVE = "PRIVE", "Privé ou associatif"
    INDETERMINE = "INDETERMINE", "À déterminer"


# Le niveau de secteur d'une institution (Institution.secteur_niveau_effectif, voir
# SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION) vers l'échelon de compétence correspondant : c'est ce qui
# permet à la page de n'afficher par défaut que ce qui relève de la collectivité connectée.
ECHELON_PAR_NIVEAU_SECTEUR = {
    "commune": EchelonCompetence.COMMUNE,
    "epci": EchelonCompetence.EPCI,
    "departement": EchelonCompetence.DEPARTEMENT,
    "region": EchelonCompetence.REGION,
    "national": EchelonCompetence.ETAT,
}


class StatutSiteSensible(models.TextChoices):
    """Décision de la mairie sur une proposition. PROPOSE est l'état de sortie de tout import :
    rien n'entre jamais directement au plan sans qu'un agent l'ait regardé."""
    PROPOSE = "PROPOSE", "Proposé — à vérifier"
    RETENU = "RETENU", "Retenu au plan de sauvegarde"
    ECARTE = "ECARTE", "Écarté"


class SiteSensible(EnvironmentScopedModel):
    """La FICHE d'un enjeu du territoire : école, EHPAD, site industriel, élevage, gymnase…

    **Une fiche par établissement, partagée par toutes les collectivités concernées.** Le
    collège de Châteauneuf n'existe qu'une fois : si la mairie l'importe la première, le
    département en profite ; si le département l'importe le premier, la mairie en profite. Les
    corrections aussi sont partagées — une adresse redressée par un agent communal sert au
    conseil départemental, et réciproquement. C'est ce qui évite deux inventaires divergents du
    même territoire, chacun se dégradant de son côté.

    Ce que chaque collectivité fait de la fiche lui appartient en revanche : sa décision
    (retenu/écarté), son commentaire, sa convention, son point opérationnel. C'est
    `SuiviSiteSensible`, une ligne par (fiche, institution).

    Pré-alimenté depuis des bases publiques nationales (voir core/opendata/) et jamais retenu
    d'office : une base ouverte se trompe et vieillit (FINESS garde des pharmacies fermées
    depuis 2009, le recensement des équipements sportifs classe les écluses du canal de Nantes à
    Brest en « installation sportive »). L'open data épargne la saisie, jamais la vérification.

    `attributs` conserve le brut utile de la source (statut Seveso, régime ICPE, public/privé,
    restauration, internat…) sans imposer une colonne par source : seules les notions communes à
    toutes les sources sont des champs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Qui l'a fait entrer dans la base — trace, et rien de plus : la fiche n'appartient à
    # personne. SET_NULL pour qu'une institution supprimée ne fasse pas disparaître l'enjeu du
    # territoire, qui existe toujours.
    institution_origine = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sites_sensibles_importes",
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

    telephone = EncryptedTextField(max_length=30, blank=True, null=True)

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

    # Qui en a la charge. Déduit par le connecteur quand la source le dit (l'annuaire de
    # l'éducation donne le type d'établissement et le statut public/privé, donc la compétence),
    # corrigeable par l'agent, et INDETERMINE quand la source ne permet pas de conclure.
    echelon_competence = models.CharField(
        max_length=15, choices=EchelonCompetence.choices,
        default=EchelonCompetence.INDETERMINE,
    )

    # Date de la donnée source telle qu'annoncée par le producteur, pas la date d'import : c'est
    # elle qui dit à l'agent à quel point l'information peut être périmée.
    date_source = models.DateField(null=True, blank=True)

    date_import = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    # Qui a corrigé la fiche à la main, et quand. Indispensable depuis qu'elle est partagée : un
    # ré-import ne doit pas réécraser le nom qu'un agent a redressé, et comme la décision vit
    # désormais ailleurs (SuiviSiteSensible), elle ne peut plus servir d'indice.
    corrige_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sites_sensibles_corriges",
    )
    corrige_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["categorie", "nom"]
        constraints = [
            # Une seule fiche par établissement et par environnement, toutes collectivités
            # confondues : c'est la contrainte qui tient la promesse « pas de doublon ».
            models.UniqueConstraint(
                fields=["source", "source_id", "environment"],
                condition=~models.Q(source_id=""),
                name="uq_site_sensible_source_id",
            )
        ]

    def __str__(self):
        return f"{self.nom} ({self.get_categorie_display()})"


class SuiviSiteSensible(EnvironmentScopedModel):
    """Ce qu'UNE collectivité fait d'une fiche partagée : sa décision, et ce qui en découle.

    La fiche est commune (SiteSensible), le suivi est propre : un collège est retenu au plan du
    département et peut être écarté de celui de la commune, qui n'en a pas la charge. De même,
    une convention lie une collectivité précise à une entreprise précise — elle n'est pas
    transposable à la voisine.

    Absence de ligne = aucune décision prise : c'est l'état « à vérifier », et c'est pourquoi il
    n'y a pas de ligne créée à l'import."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    site = models.ForeignKey(SiteSensible, on_delete=models.CASCADE, related_name="suivis")
    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="suivis_sites_sensibles",
    )

    statut = models.CharField(
        max_length=10, choices=StatutSiteSensible.choices, default=StatutSiteSensible.PROPOSE,
    )

    commentaire = EncryptedTextField(blank=True, null=True)

    valide_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sites_sensibles_valides",
    )

    # Une ressource recensée n'est pas une ressource acquise : seule une convention engage. La
    # case cochée est l'information opérationnelle (« a-t-on un accord ? »), les champs suivants
    # servent à la retrouver le jour où il faut l'invoquer à 3 h du matin.
    convention_existe = models.BooleanField(default=False)
    convention_numero = models.CharField(max_length=100, blank=True, null=True)
    convention_date_signature = models.DateField(null=True, blank=True)
    # Pas demandée, ajoutée quand même : une convention expirée est plus dangereuse qu'une
    # absence de convention, parce qu'on compte dessus.
    convention_echeance = models.DateField(null=True, blank=True)
    # Chiffré au repos comme une pièce d'identité (core/file_crypto.py) : une convention porte
    # des noms, des signatures, parfois l'adresse personnelle d'un exploitant en nom propre.
    # Préfixe documents/ bloqué par proxy/nginx.conf, jamais servi comme URL /media/ directe —
    # le téléchargement passe par l'action dédiée, qui trace.
    convention_document = models.FileField(
        storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255,
        null=True, blank=True, validators=[validate_convention_file],
    )

    # Rempli quand la collectivité transforme le site en point opérationnel (un gymnase retenu
    # devient le centre d'accueil qu'on ouvrira le jour J, nom, adresse et coordonnées déjà
    # renseignés). SET_NULL et pas CASCADE : supprimer un point ne doit pas effacer la décision.
    point_operationnel = models.ForeignKey(
        "PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="suivis_sites_sensibles",
    )

    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "institution", "environment"],
                name="uq_suivi_site_sensible_institution",
            )
        ]

    def __str__(self):
        return f"{self.site_id} — {self.institution_id} ({self.get_statut_display()})"


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
    # sites_sensibles.importer_source, plus deux choses pendant que l'import tourne :
    # l'avancement ({"tranches_faites": 5, "tranches_total": 12, "tranche_en_cours":
    # "département 24"}), et `incomplet`, la liste en français de ce qui manque et pourquoi.
    # Cette dernière est la plus importante : les sources plafonnent le nombre de résultats
    # qu'elles servent, parfois sans le dire, et un recensement tronqué qui se croit complet est
    # plus dangereux qu'une absence de recensement (voir opendata/base.py:Collecte).
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
    #: Identifiant de cette adresse dans la Base Adresse Nationale, quand la fiche a été
    #: rattachée à une adresse de la commune (core/rattachement_adresses.py). Chiffré comme
    #: l'adresse : il la désigne aussi sûrement qu'elle. Vide = adresse libre, non rattachée.
    adresse_ban_id = EncryptedTextField(null=True, blank=True)
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
    demandeur_consentement = EncryptedTextField(
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


class QualiteDesignataire(models.TextChoices):
    """Qualité de celui qui désigne, telle qu'il la déclare sur l'honneur. La plateforme ne peut
    pas vérifier qu'un compte est bien celui du maire : c'est précisément l'office de
    l'attestation sur l'honneur, qui fait porter la responsabilité de la déclaration sur son
    auteur et la rend opposable."""
    MAIRE = "MAIRE", "Maire"
    ADJOINT = "ADJOINT", "Adjoint au maire"
    AGENT = "AGENT", "Personnel de mairie habilité par le maire à désigner"


#: Version du texte d'engagement au secret professionnel. À incrémenter dès que le texte change :
#: les engagements pris sur une version antérieure seront redemandés (voir
#: User.engagement_secret_registre_version).
VERSION_ENGAGEMENT_SECRET_REGISTRE = "2026-10"


class HabilitationRegistreVulnerables(EnvironmentScopedModel):
    """Habilitation nominative à tenir le registre communal des personnes vulnérables.

    Exigée par l'**art. R. 121-7 du CASF** : seuls le maire et les agents des services
    municipaux, du CCAS et le cas échéant du CIAS **nommément désignés et habilités** peuvent
    traiter ces données, et ils sont tenus au secret professionnel. Une appartenance d'équipe ne
    vaut pas désignation nominative -- c'est pourquoi cette table remplace, et ne complète pas,
    l'ancien critère « membre de la RCSC ou RESPONSABLE » pour la branche mairie (voir
    core/vulnerabilites.py).

    Deux actes distincts, délibérément séparés :

    1. **La désignation**, portée ici : un maire, un adjoint ou un agent habilité à le faire
       désigne quelqu'un, en attestant sur l'honneur de sa propre qualité. C'est l'acte de la
       collectivité, responsable de traitement.
    2. **L'engagement au secret**, porté par le compte désigné
       (User.engagement_secret_registre_le) : l'acte personnel du désigné. Une habilitation
       dont l'engagement n'est pas signé n'ouvre AUCUNE donnée -- elle ouvre seulement l'écran
       qui fait signer.

    Rien n'est jamais supprimé : une habilitation retirée passe à actif=False avec son motif,
    de sorte qu'on puisse toujours répondre à « qui avait accès au registre le 14 août ? »."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE,
        related_name="habilitations_registre_vulnerables",
        help_text="La collectivité détentrice du registre -- c'est elle le responsable de "
                  "traitement, la plateforme n'étant que sous-traitante (RGPD art. 28).",
    )

    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="habilitations_registre_vulnerables",
        help_text="Le désigné. Son compte doit être rattaché à l'institution : R. 121-7 ne "
                  "permet de désigner que des agents de la commune, du CCAS ou du CIAS.",
    )

    fonction = EncryptedTextField(
        max_length=150, blank=True,
        help_text="Fonction au titre de laquelle la personne est désignée (ex: « agent "
                  "d'accueil du CCAS ») -- trace le besoin d'en connaître de R. 121-8.",
    )

    accordee_par = models.ForeignKey(
        User, on_delete=models.PROTECT,
        related_name="habilitations_registre_accordees",
        help_text="PROTECT et non SET_NULL : une désignation sans désignant n'est plus une "
                  "désignation, et l'effacer viderait la preuve de l'habilitation.",
    )
    qualite_accordant = models.CharField(
        max_length=10, choices=QualiteDesignataire.choices,
    )
    attestation_accordant = models.BooleanField(
        default=False,
        help_text="Attestation sur l'honneur du désignant : il certifie sa qualité et son droit "
                  "de désigner. Une habilitation sans attestation est refusée à la création.",
    )

    date_octroi = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(
        null=True, blank=True,
        help_text="Échéance facultative -- utile pour un remplacement saisonnier (plan "
                  "canicule) qui doit se refermer sans qu'on y pense.",
    )

    actif = models.BooleanField(default=True)
    retiree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="habilitations_registre_retirees",
    )
    date_retrait = models.DateTimeField(null=True, blank=True)
    motif_retrait = EncryptedTextField(blank=True)

    class Meta:
        ordering = ["-date_octroi"]
        constraints = [
            # Une seule habilitation vivante par (personne, collectivité) : deux lignes actives
            # rendraient indécidable laquelle fait foi, et le retrait de l'une laisserait
            # l'accès ouvert par l'autre.
            models.UniqueConstraint(
                fields=["institution", "utilisateur"],
                condition=models.Q(actif=True),
                name="habilitation_registre_unique_active",
            ),
        ]
        indexes = [models.Index(fields=["utilisateur", "actif"])]

    def __str__(self):
        return f"Habilitation registre {self.utilisateur} ({self.institution})"

    @property
    def valide(self):
        """Désignation en cours de validité -- indépendamment de l'engagement au secret, qui
        est l'acte de l'autre partie."""
        from django.utils import timezone

        if not self.actif:
            return False
        return self.date_fin is None or self.date_fin > timezone.now()


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

    # Chiffré ; retrouvé par son empreinte exacte (`token_confirmation_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    token_confirmation = EncryptedTextField(max_length=64)
    token_confirmation_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

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

    user_agent = EncryptedTextField(
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

    ancien_etat = EncryptedJSONField(
        null=True,
        blank=True
    )

    nouvel_etat = EncryptedJSONField(
        null=True,
        blank=True
    )

    commentaire = EncryptedTextField(
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
    recherche = EncryptedJSONField(null=True, blank=True)

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

    fonction = EncryptedTextField(
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

    # Gouvernance de l'institution, et non rôle opérationnel de crise : un membre du bureau
    # d'une association administre ses membres, prend en charge les candidatures et valide les
    # étapes d'un recrutement (voir § 5.13 de DOCUMENTATION.md).
    #
    # Porté par le RATTACHEMENT et non par le compte, délibérément : on est au bureau d'UNE
    # association précise. La même personne peut être au bureau des Casques Jaunes et simple
    # membre d'une autre AASC, et les cinq rôles de compte (UserRole) sont globaux — en ajouter
    # un sixième obligerait à rejuger toutes les gardes du projet pour une notion qui n'est pas
    # globale. Ce n'est pas non plus un RoleOperationnel : ceux-là servent l'opérationnel de
    # crise (Responsable, Régulateur, Correspondant sécurité), pas la gouvernance associative.
    membre_bureau = models.BooleanField(
        default=False,
        help_text="Membre du bureau de cette institution : administre les membres et prend en "
                  "charge les candidatures.",
    )

    # ── Suivi associatif (voir § 5.12 bis de DOCUMENTATION.md) ─────────────────────────────
    # `actif` reste la question technique « ce rattachement ouvre-t-il des droits ? ».
    # `statut` est la question humaine « où en est cette personne dans l'association ? ».
    # Les deux sont nécessaires et ne se confondent pas : quelqu'un en congé garde ses accès et
    # son ancienneté mais ne doit pas apparaître dans les disponibilités d'une mobilisation.
    class StatutMembre(models.TextChoices):
        ACTIF = "ACTIF", "Actif"
        CONGE = "CONGE", "En congé"
        SORTI = "SORTI", "Sorti de l'association"

    statut = models.CharField(
        max_length=6, choices=StatutMembre.choices, default=StatutMembre.ACTIF,
    )

    date_adhesion = models.DateField(
        null=True, blank=True,
        help_text="Première adhésion à l'association.",
    )

    # Renouvellement annuel SANS cotisation (décision du 28/10/2026 : l'association n'en
    # perçoit pas) : la date dit jusqu'à quand l'adhésion court, pas qu'un paiement a été reçu.
    # Aucun montant n'est stocké, et il ne faut pas en ajouter sans revoir la question : une
    # gestion financière est un autre métier que la préparation de crise.
    adhesion_valide_jusquau = models.DateField(
        null=True, blank=True,
        help_text="Fin de validité de l'adhésion (renouvellement annuel, sans cotisation).",
    )

    # DATE SEULE, et c'est une décision explicite du responsable de traitement (28/10/2026).
    # Ni « apte / inapte », ni restriction, ni le certificat lui-même : ces trois-là révèlent un
    # état de santé (RGPD art. 9), que le projet s'interdit de stocker — voir § 5.11. Une date
    # de fin de validité est un fait administratif sur un document : elle permet d'alerter
    # avant l'échéance sans rien dire de la personne. Ne pas ajouter de champ ici sans reposer
    # la question au porteur du projet.
    aptitude_valide_jusquau = models.DateField(
        null=True, blank=True,
        help_text="Fin de validité du certificat médical. Date seule : aucune information "
                  "d'aptitude ni aucun document n'est conservé.",
    )

    class Meta:

        constraints = [

            models.UniqueConstraint(
                fields=["institution"],
                condition=models.Q(
                    contact_principal=True
                ),
                name="uq_contact_principal_institution"
            ),

            # UN SEUL RATTACHEMENT PAR (personne, institution) — 13/11/2026.
            #
            # N'interdit PAS la multi-appartenance, et c'est tout l'objet de la nuance : une
            # personne à la fois à la mairie de X et dans l'association Y a deux lignes, avec
            # deux institutions différentes. Seule la répétition de la MÊME paire est
            # interdite.
            #
            # Il y en avait 4 en production. Un doublon fausse tout comptage d'effectif, fait
            # apparaître la personne deux fois dans un annuaire, et oblige chaque lecture à se
            # protéger (`_get_or_create_contact_institution` existe pour cette seule raison,
            # après un MultipleObjectsReturned constaté le 02/10/2026). À l'échelle de
            # milliers d'institutions, ces doublons se multiplient en silence.
            models.UniqueConstraint(
                fields=["institution", "utilisateur", "environment"],
                name="uq_rattachement_par_personne_et_institution",
            ),

        ]

    def save(self, *args, **kwargs):
        """Garantit l'invariant : un rattachement actif implique un `User.institution`.

        « Dans quelle institution est cet utilisateur » a deux réponses en base. CETTE relation
        fait autorité, mais une quarantaine d'endroits lisent le raccourci `User.institution` —
        les vues territoriales (`zone_scoping`), l'accès au registre des personnes vulnérables,
        l'estimation des habitations, le branding des emails. Un rattachement créé sans poser le
        raccourci rend donc la personne aveugle à sa propre commune sur une partie de
        l'application, avec pour seule explication « Aucune commune associée à votre institution :
        contactez un administrateur » — alors que l'administrateur vient de la rattacher.

        C'est arrivé : `ContactInstitutionViewSet` créait la ligne sans passer par
        `grant_institution_and_demo_access`. Corriger ce chemin-là ne suffit pas, parce que le
        prochain chemin de rattachement pourra l'oublier à son tour, et le symptôme est
        silencieux. On tient donc l'invariant ICI, au seul endroit par lequel toute création
        passe forcément.

        Volontairement MINIMAL : seul le raccourci est posé. L'accueil complet (équipe de
        l'institution, accès à la zone de démonstration, email de messagerie) reste dans
        `grant_institution_and_demo_access`, qui a besoin d'une requête HTTP — ce filet n'en a
        pas et ne doit ni envoyer d'email ni dépendre du réseau.

        Jamais de détournement : le raccourci n'est posé que s'il est VIDE, donc un profil
        membre de plusieurs collectivités garde le contexte « Vue Ma Collectivité » qu'il a
        choisi."""
        # Sorti de l'association ⇒ le rattachement ne doit plus ouvrir de droits. Laisser les
        # deux divergents produirait un ancien membre qui garde ses accès, ce qu'aucun écran ne
        # montrerait : `statut` est lisible par le bureau, `actif` par le contrôle d'accès.
        if self.statut == self.StatutMembre.SORTI:
            self.actif = False
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = list(set(kwargs["update_fields"]) | {"actif"})

        super().save(*args, **kwargs)
        if not self.actif or not self.utilisateur_id or not self.institution_id:
            return
        # Relu en base plutôt que depuis `self.utilisateur` : l'instance en mémoire peut être
        # périmée (rattachement posé entre-temps par un autre chemin), et on ne veut surtout
        # pas écraser un contexte déjà choisi.
        User.objects.filter(pk=self.utilisateur_id, institution__isnull=True).update(
            institution_id=self.institution_id)

class Qualification(models.Model):
    """Catalogue partagé des qualifications d'un intervenant : PSC1, PSE1/2, radio, permis,
    CACES…

    Distinct de `Competence`, et ce n'est pas un doublon : une compétence dit ce que
    l'association sait faire et se rattache à une équipe sur une crise
    (`AffectationCompetence`) ; une qualification est un TITRE détenu par une personne, avec
    une date d'obtention et surtout une date de péremption. Pour une association agréée de
    sécurité civile, cette péremption est le cœur du suivi : un PSE1 expiré vaut un PSE1
    absent, et c'est le genre de chose qu'on découvre le jour de la mobilisation si personne ne
    l'a suivi.

    Catalogue partagé et extensible comme `Competence` / `RisqueMajeurType` : toute institution
    ajoute une entrée réutilisable par les autres, et les entrées retirées sont masquées
    (`actif=False`), jamais supprimées — un titre déjà attribué doit rester lisible."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=120, unique=True)

    description = models.TextField(blank=True, null=True)

    # CE QUI DÉCIDE DE LA DESTRUCTION DU FICHIER (13/11/2026). Clé d'une ligne de
    # core/conservation_pieces.py : régime, durée, base légale et « pourquoi », affichés sur la
    # page de dépôt comme sur la page de validation. Une pièce du régime « vérifier puis
    # détruire » (permis, pièce d'identité) voit son justificatif supprimé dès qu'une décision
    # est prise — voir core/pieces_conformite.py.
    #
    # Pas de `choices=` : la table vit en Python et évolue sans migration, et une clé inconnue
    # retombe sur la catégorie par défaut plutôt que de bloquer une entrée de catalogue créée
    # par une institution.
    categorie_piece = models.CharField(
        max_length=32, blank=True, default="SECOURISME",
        help_text="Catégorie de conservation (voir core/conservation_pieces.py) : elle "
                  "décide si le justificatif est détruit après validation.",
    )

    # Durée de validité habituelle, pour préremplir l'échéance à la saisie. Null = sans
    # péremption (un permis de conduire, un diplôme). Jamais appliquée de force : c'est la date
    # portée par le titre réel qui fait foi, pas notre calcul.
    validite_mois = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Durée de validité en mois, pour préremplir l'échéance. Vide = sans "
                  "péremption.",
    )

    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class SituationProfessionnelle(models.TextChoices):
    """Situation déclarée par un bénévole. Reprend les valeurs du formulaire d'adhésion des
    Casques Jaunes, qui sont celles que les gens ont déjà remplies."""

    SALARIE = "SALARIE", "Salarié(e)"
    RETRAITE = "RETRAITE", "Retraité(e)"
    INDEPENDANT = "INDEPENDANT", "Chef(fe) d'entreprise, artisan, profession libérale"
    FONCTIONNAIRE = "FONCTIONNAIRE", "Fonctionnaire"
    ETUDIANT = "ETUDIANT", "Étudiant(e)"
    RECHERCHE_EMPLOI = "RECHERCHE_EMPLOI", "En recherche d'emploi"
    AUTRE = "AUTRE", "Autre"


class FrequenceEngagement(models.TextChoices):
    """Volume d'engagement annoncé à l'adhésion. **Ce n'est PAS une disponibilité.**

    Renommé le 11/11/2026 : s'appeler « disponibilité » en faisait un second moteur apparent à
    côté de `DisponibiliteOperationnelle`, qui est le seul interrogé pour constituer une équipe.
    Deux notions se ressemblaient donc sans jamais se parler — exactement la confusion qui fait
    mobiliser sur la mauvaise source.

    La différence est de nature, pas de précision : « environ 10 jours par an » ne dit RIEN du
    5 novembre. On ne peut donc pas la convertir en déclarations datées sans inventer des
    dates, et elle ne peut pas servir à armer une garde. Elle sert à autre chose, qui compte
    aussi : dimensionner l'effectif mobilisable sur l'année, et savoir à qui l'on peut demander
    souvent.

    Les libellés sont ceux du formulaire d'adhésion : les reformuler rendrait incomparables les
    réponses déjà collectées."""

    OCCASIONNELLE = "OCCASIONNELLE", "Occasionnelle (moins de 5 jours par an)"
    REGULIERE = "REGULIERE", "Régulière (environ 10 jours par an)"
    FREQUENTE = "FREQUENTE", "Fréquente (plus de 10 jours par an)"


class FicheBenevole(EnvironmentScopedModel):
    """Fiche d'un bénévole d'association : ce qui permet de le joindre et de le mobiliser.

    **Alignée sur le modèle des RESSOURCES** (`Offer`, `Habitation`) et non inventée : une
    adresse texte, un point géocodé, et le secteur dénormalisé (commune, EPCI, département,
    région). C'est ce qui fait qu'un bénévole se cherche et se filtre comme une offre d'aide ou
    une habitation — « une ressource particulière, qui se trouve être membre de l'association »
    (décision du 11/11/2026).

    Conséquence directe et voulue : **le département d'affectation vient du GÉOCODAGE**, pas
    d'un préfixe de code postal. Un code postal n'est pas un code commune — la Corse partage
    `20xxx` entre 2A et 2B, l'outre-mer demande trois chiffres — alors que `commune_code` donne
    le département de façon exacte par `commune_secteur_codes`. La dérivation par code postal
    (`core/departements.py`) ne sert plus que de repli quand le géocodage échoue.

    **Rattachée à l'UTILISATEUR et non au rattachement associatif**, exactement pour la raison
    déjà écrite sur `QualificationMembre` : une adresse et une date de naissance appartiennent à
    la personne, pas à l'association. Quelqu'un membre de deux AASC a une seule adresse, et la
    saisir deux fois ferait diverger les deux copies.

    Qui la voit : la hiérarchie du bénévole, par le même filtre que les comptes (voir
    core/visibilite_membres.py). Les champs personnels sont chiffrés au repos — règle du
    projet, on ne stocke rien en clair.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    utilisateur = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="fiche_benevole",
    )

    # ── Adresse, alignée sur Habitation/Offer ────────────────────────────────────────────
    adresse = EncryptedTextField(blank=True)
    code_postal = EncryptedTextField(blank=True)
    ville = EncryptedTextField(max_length=255, blank=True)

    location = gis_models.PointField(srid=4326, null=True, blank=True)
    ban_id = models.CharField(
        max_length=50, blank=True,
        help_text="Identifiant BAN de l'adresse, pour rafraîchissement et déduplication "
                   "ultérieurs (même usage que Habitation.ban_id).",
    )

    # Secteur dénormalisé, posé une fois depuis commune_code (voir commune_secteur_codes) —
    # même motif qu'Offer : éviter une jointure sur Commune à chaque lecture.
    commune_code = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    epci_code = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    departement_code = models.CharField(max_length=3, blank=True, null=True, db_index=True)
    region_code = models.CharField(max_length=3, blank=True, null=True, db_index=True)

    # ── Ce que la personne a déclaré en adhérant ─────────────────────────────────────────
    date_naissance = models.DateField(
        null=True, blank=True,
        help_text="Déclarée à l'adhésion. Sert à vérifier la majorité et à instruire une "
                   "candidature ; jamais affichée dans les listes.",
    )
    metier = EncryptedTextField(
        blank=True,
        help_text="Métier ou formation déclarés. C'est ce qui permet de chercher un "
                   "électricien ou une infirmière parmi les membres.",
    )
    situation = models.CharField(
        max_length=20, choices=SituationProfessionnelle.choices, blank=True,
    )
    # JAMAIS lu par la constitution d'équipe : la seule source de disponibilité est
    # `DisponibiliteOperationnelle` (voir FrequenceEngagement et MesDisponibilitesView).
    frequence_engagement = models.CharField(
        max_length=20, choices=FrequenceEngagement.choices, blank=True,
        help_text="Volume d'engagement annoncé à l'adhésion. N'est pas une disponibilité : "
                   "les disponibilités datées vivent dans DisponibiliteOperationnelle.",
    )
    # Ce que la personne a écrit en s'inscrivant : une motivation, une contrainte, un souhait
    # de territoire. Chiffré — c'est un texte libre où les gens parlent d'eux.
    message = EncryptedTextField(blank=True)

    # Déclaratif, jamais une preuve : une qualification vérifiée vit dans QualificationMembre,
    # avec ses dates et sa pièce justificative. Les confondre ferait passer une case cochée à
    # l'inscription pour un diplôme contrôlé par le bureau.
    diplome_premier_secours = models.BooleanField(
        default=False,
        help_text="Déclaré par la personne à l'adhésion. Une qualification VÉRIFIÉE se saisit "
                   "dans QualificationMembre, avec ses dates et son justificatif.",
    )

    date_adhesion = models.DateField(
        null=True, blank=True,
        help_text="Date d'adhésion déclarée par le fichier d'origine, quand elle est connue.",
    )

    # Posée par la page de complétion : tant qu'elle est nulle, la personne n'a pas relu sa
    # fiche, et l'écran le lui redemande à la connexion.
    completee_le = models.DateTimeField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    @property
    def est_complete(self):
        """Ce qu'on considère comme une fiche exploitable : de quoi joindre la personne et
        savoir où elle est. Le reste est utile mais n'empêche pas de la mobiliser.

        **La fréquence d'engagement n'en fait plus partie** (11/11/2026, avec le passage au
        moteur unique) : elle dit un volume annuel, pas une capacité à être mobilisé. Une
        fiche sans elle reste parfaitement exploitable — on sait qui joindre et où. Ce qui
        dit « est-il disponible le 5 novembre » est ailleurs, dans
        `DisponibiliteOperationnelle`.

        Au passage, cette propriété lisait encore `self.disponibilite` après le renommage :
        l'`AttributeError` était avalée par DRF, qui retirait silencieusement `est_complete`
        de la réponse. L'écran ne voyait donc plus jamais « fiche à compléter ». Trouvé par un
        test, pas à l'œil."""
        return bool(self.adresse and self.commune_code)

    def __str__(self):
        return f"Fiche de {self.utilisateur.email}"


class QualificationMembre(EnvironmentScopedModel):
    """Qualification détenue par une personne, avec ses dates.

    Rattachée à l'UTILISATEUR et non à son rattachement associatif : un PSC1 appartient à la
    personne, pas à l'association. Quelqu'un membre de deux AASC détient un seul PSC1, et le
    bureau de chacune le voit — sans quoi la même attestation serait saisie deux fois et les
    deux copies divergeraient."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="qualifications",
    )

    qualification = models.ForeignKey(
        Qualification, on_delete=models.PROTECT, related_name="detenteurs",
    )

    date_obtention = models.DateField(null=True, blank=True)

    # Le champ qui justifie tout ce modèle. Null = sans péremption (voir
    # Qualification.validite_mois).
    date_expiration = models.DateField(null=True, blank=True)

    organisme = EncryptedTextField(
        max_length=160, blank=True, null=True,
        help_text="Organisme ayant délivré le titre.",
    )

    commentaire = EncryptedTextField(blank=True, null=True)

    # Qui l'a saisie : une qualification affirmée par le bureau n'a pas le même poids qu'une
    # ligne déclarée par l'intéressé, et il faut pouvoir le distinguer sans interroger les logs.
    # ── JUSTIFICATIF ET VÉRIFICATION (11/11/2026) ───────────────────────────────────────
    #
    # Le membre dépose lui-même sa pièce ; l'encadrement la consulte et la valide. Avant, une
    # qualification se saisissait à la main par le bureau, sur la foi d'une attestation vue
    # ailleurs : rien ne restait dans l'application, et une qualification « vérifiée » ne
    # l'était que dans le souvenir de celui qui l'avait saisie.
    #
    # MÊME PROTECTION QUE LES PIÈCES D'IDENTITÉ (voir PieceIdentiteReserve) : chiffré au repos
    # par `get_encrypted_file_storage` (core/file_crypto.py), rangé sous le préfixe
    # `documents/` que proxy/nginx.conf bloque — ne pas changer ce préfixe sans ajouter le
    # blocage correspondant — et jamais servi comme URL /media/ directe : seule une action
    # dédiée le rend, après contrôle des droits.
    justificatif = models.FileField(
        storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255,
        null=True, blank=True, validators=[validate_identity_document_file],
        help_text="Attestation, diplôme ou permis. Chiffré au repos, jamais accessible par "
                   "URL directe.",
    )
    justificatif_nom = EncryptedTextField(
        max_length=255, blank=True,
        help_text="Nom du fichier tel que déposé. Le nom réel est un UUID : sans cela, "
                   "l'écran afficherait « a3f2…pdf » au lieu de « PSC1-2024.pdf ».",
    )
    justificatif_depose_le = models.DateTimeField(null=True, blank=True)

    # LA TRACE QUI SURVIT AU FICHIER (13/11/2026). Renseignée quand le justificatif a été
    # détruit — après décision pour une pièce qui se vérifie sans se conserver, ou faute de
    # décision sous 30 jours. Sans ce champ, une pièce détruite serait indiscernable d'une
    # pièce jamais déposée, et l'écran dirait « aucune pièce » là où il faut dire « vérifiée,
    # puis détruite comme prévu ».
    piece_detruite_le = models.DateTimeField(null=True, blank=True)

    statut = models.CharField(
        max_length=12, choices=StatutQualification.choices,
        default=StatutQualification.DECLAREE,
        help_text="DÉCLARÉE tant que l'encadrement ne s'est pas prononcé. Une qualification "
                   "déclarée n'est PAS une qualification vérifiée.",
    )
    verifie_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="qualifications_verifiees",
    )
    verifie_le = models.DateTimeField(null=True, blank=True)
    motif_refus = EncryptedTextField(
        blank=True,
        help_text="Obligatoire au refus : le membre doit savoir quoi corriger pour redéposer.",
    )

    saisie_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="qualifications_saisies",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["qualification__nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "qualification", "environment"],
                name="uq_qualification_par_personne",
            ),
        ]

    def __str__(self):
        return f"{self.qualification} — {self.utilisateur}"

    @property
    def expiree(self):
        """Vrai quand le titre est périmé. Un titre sans date d'expiration ne périme jamais."""
        from django.utils import timezone

        if self.date_expiration is None:
            return False
        return self.date_expiration < timezone.localdate()

    def jours_avant_expiration(self):
        """Jours restants, négatif si déjà périmé, None si sans péremption. Sert l'alerte avant
        échéance : prévenir après coup ne sert à rien, le titre est déjà invalide."""
        from django.utils import timezone

        if self.date_expiration is None:
            return None
        return (self.date_expiration - timezone.localdate()).days


def _jeton_invitation():
    """Jeton d'invitation : 32 octets d'aléa cryptographique, URL-safe.

    `secrets` et non `random` : ce jeton vaut droit d'entrée dans le circuit de recrutement
    d'une association, un générateur prévisible permettrait de le devenir sans invitation."""
    return secrets.token_urlsafe(32)


class InvitationAssociation(EnvironmentScopedModel):
    """Lien d'invitation d'une association : qui s'inscrit par là demande à la rejoindre.

    Raison d'être : une AASC recrute avec des adresses personnelles (gmail, hotmail), donc le
    mécanisme de rattachement par domaine email des mairies (InstitutionDomaine) ne marchera
    jamais pour elle. Et faire SAISIR le nom de l'association est ce qui fabriquait des
    associations fantômes (voir attach_secours_user_to_institution). Un lien fait CHOISIR sans
    rien taper, et laisse une trace de qui a recruté qui.

    Le lien n'accorde rien par lui-même : il pose une candidature, que le bureau instruit
    (voir CandidatureAssociation). Quelqu'un qui devine un jeton n'obtient donc pas un accès,
    seulement une demande de plus à examiner."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="invitations",
    )

    # Chiffré ; retrouvé par son empreinte exacte (`jeton_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    jeton = EncryptedTextField(max_length=64, default=_jeton_invitation, editable=False)
    jeton_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

    libelle = EncryptedTextField(
        max_length=160, blank=True, null=True,
        help_text="À quoi sert ce lien (ex: « Forum des associations 2026 ») — permet de "
                  "savoir d'où viennent les candidatures.",
    )

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitations_creees",
    )

    # Un lien qui traîne indéfiniment sur un site public finit par être partagé n'importe où :
    # une échéance est la seule chose qui le referme sans intervention.
    date_expiration = models.DateField(null=True, blank=True)

    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return f"Invitation {self.institution} ({self.libelle or self.jeton[:8]})"

    @property
    def utilisable(self):
        from django.utils import timezone

        if not self.actif:
            return False
        if self.date_expiration and self.date_expiration < timezone.localdate():
            return False
        return self.institution.actif


class CandidatureAssociation(EnvironmentScopedModel):
    """Candidature d'une personne à une association, et son instruction par le bureau.

    Le circuit tel que l'association le pratique : demande reçue, prise en charge par quelqu'un
    du bureau, pièces et qualifications vérifiées, puis acceptée — ou refusée, car un
    recrutement peut aussi se conclure par un non et l'omettre obligerait à laisser des
    dossiers ouverts indéfiniment.

    Distinct de l'approbation de compte (`approve_account`), qui est la porte de la
    PLATEFORME : ici c'est l'association qui décide de ses membres. Accepter une candidature
    fait les deux d'un geste — le compte est activé et le rattachement posé — parce que
    demander au bureau de valider deux fois la même personne dans deux écrans différents
    produirait des comptes acceptés mais non rattachés, ce qu'on a déjà observé."""

    class Etape(models.TextChoices):
        DEMANDE = "DEMANDE", "Demande reçue"
        PRISE_EN_CHARGE = "PRISE_EN_CHARGE", "Prise en charge"
        VERIFICATION = "VERIFICATION", "Pièces et qualifications vérifiées"
        ACCEPTE = "ACCEPTE", "Accepté"
        REFUSE = "REFUSE", "Refusé"

    # Ordre du circuit. REFUSE n'y figure pas : il se prononce depuis n'importe quelle étape
    # non terminale, ce n'est pas une progression.
    ORDRE_ETAPES = [Etape.DEMANDE, Etape.PRISE_EN_CHARGE, Etape.VERIFICATION, Etape.ACCEPTE]
    ETAPES_TERMINALES = {Etape.ACCEPTE, Etape.REFUSE}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="candidatures",
    )

    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="candidatures",
    )

    etape = models.CharField(max_length=16, choices=Etape.choices, default=Etape.DEMANDE)

    # D'où vient la candidature : un lien d'invitation nommé dit quelle action de recrutement a
    # porté. Null = demande spontanée.
    invitation = models.ForeignKey(
        InvitationAssociation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="candidatures",
    )

    # Qui instruit le dossier. Nommément, et pas seulement « le bureau » : une candidature dont
    # personne ne se sent responsable est une candidature qui dort.
    pris_en_charge_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="candidatures_instruites",
    )

    message_candidat = EncryptedTextField(
        blank=True, null=True,
        help_text="Ce que la personne a écrit en demandant à rejoindre l'association.",
    )

    commentaire_bureau = EncryptedTextField(blank=True, null=True)

    # Dire pourquoi : un refus sans motif se represente à l'identique six mois plus tard.
    motif_refus = EncryptedTextField(blank=True, null=True)

    date_demande = models.DateTimeField(auto_now_add=True)
    date_prise_en_charge = models.DateTimeField(null=True, blank=True)
    date_decision = models.DateTimeField(null=True, blank=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_demande"]
        constraints = [
            # Une seule candidature EN COURS par personne et par association : deux dossiers
            # ouverts pour la même personne feraient instruire deux fois, et accepter deux
            # fois. Une candidature refusée n'empêche pas d'en redéposer une plus tard.
            models.UniqueConstraint(
                fields=["institution", "utilisateur", "environment"],
                condition=models.Q(etape__in=["DEMANDE", "PRISE_EN_CHARGE", "VERIFICATION"]),
                name="uq_candidature_en_cours",
            ),
        ]

    def __str__(self):
        return f"{self.utilisateur} → {self.institution} ({self.get_etape_display()})"

    @property
    def terminee(self):
        return self.etape in self.ETAPES_TERMINALES

    def transition_possible(self, vers):
        """Le circuit avance, il ne recule pas, et il ne repart pas d'une décision prise.

        Avancer de plusieurs crans d'un coup est permis : un bureau qui connaît la personne ne
        doit pas être forcé de cliquer trois fois pour dire oui. Reculer ne l'est pas — une
        étape franchie l'a été par quelqu'un, et la défranchir sans trace réécrirait
        l'instruction du dossier.

        Sortir d'une étape terminale ne l'est pas non plus : accepter a posé un rattachement et
        ouvert des accès, les retirer est un autre acte (voir ContactInstitution.statut, qui a
        « Sorti »), pas un retour en arrière du recrutement."""
        if self.terminee:
            return False
        if vers == self.Etape.REFUSE:
            return True
        if vers not in self.ORDRE_ETAPES:
            return False
        return self.ORDRE_ETAPES.index(vers) > self.ORDRE_ETAPES.index(self.etape)


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
    # Radio tenue par un NAVIGATEUR (relais navigateur, core/relais_navigateur.py), branchée sur
    # le poste de quelqu'un. Aucun pont ne doit essayer de l'ouvrir : elle n'est pas sur sa
    # machine. Le transport réel (USB, Bluetooth) est porté par la session, pas ici — la même
    # radio peut être relayée en USB aujourd'hui et en Bluetooth demain.
    NAVIGATEUR = "NAVIGATEUR", "Relayée par un navigateur"


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
    expediteur_identifiant = EncryptedTextField(max_length=64, null=True, blank=True)
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

    contenu = EncryptedTextField()

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

    commentaire = EncryptedTextField(null=True, blank=True)

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
    cle_partagee_hex = EncryptedTextField(max_length=64, null=True, blank=True)

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


class RoleCompteMqtt(models.TextChoices):
    """Les droits viennent du rôle, jamais d'une saisie libre : un champ « topic » libre dans
    l'interface permettrait de s'accorder `#` en lecture, donc de lire tout le trafic."""
    RADIO = "RADIO", "Passerelle ou pont radio (lecture/écriture sur sa racine)"
    SUPERVISION = "SUPERVISION", "Supervision (statistiques du broker seulement)"


class CompteMqtt(models.Model):
    """Compte du broker MQTT, administrable depuis l'interface web.

    Volontairement PAS `EnvironmentScopedModel` (comme ProvisionCanalMeshCore) : il n'y a qu'un
    broker par machine, un compte n'a pas de version de démonstration.

    Django est la source de vérité ; il réécrit `password_file` et `acl_file` à chaque
    changement, et le broker les relit (voir core/mqtt_comptes.py pour le pourquoi et le format).
    Les comptes d'infrastructure amorcés par le conteneur depuis ses secrets (exporter, pont)
    sont repris ici au premier rendu, sinon la réécriture les supprimerait.

    `mot_de_passe` est conservé chiffré au repos : il faut pouvoir le réafficher pour configurer
    un nœud radio sur place, des mois après sa création -- une passerelle est un boîtier sur un
    toit, pas un compte qu'on recrée d'un clic."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Jamais renvoyé par l'API en écriture seule : voir CompteMqttSerializer.
    nom = models.CharField(max_length=63, unique=True)
    role = models.CharField(max_length=12, choices=RoleCompteMqtt.choices, default=RoleCompteMqtt.RADIO)
    # Doit correspondre à `CompagnonMeshtastic.topic_racine` du companion concerné : une racine
    # qui ne correspond pas coupe le flux sans aucun message d'erreur.
    racine_topic = models.CharField(max_length=100, default="msh/EU_868")
    mot_de_passe = EncryptedTextField(max_length=128)
    description = models.CharField(max_length=200, blank=True)
    # Un compte d'infrastructure (exporter, pont) ne doit pas pouvoir être supprimé depuis le
    # web : l'exporteur de supervision et le pont en dépendent.
    infrastructure = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-infrastructure', 'nom']

    def __str__(self):
        return f"{self.nom} ({self.get_role_display()})"


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


class TypeSalonEquipe(models.TextChoices):
    """Les deux salons que porte toute équipe.

    INTERVENANTS est le salon de l'équipe entière, encadrement compris : un encadrant absent du
    salon de terrain ne voit pas ce qui s'y dit.

    ENCADREMENT réunit l'encadrement de l'équipe **et celui de ses équipes filles directes**,
    un seul niveau — « n-1 » (arbitrage du 11/11/2026). Chaque échelon parle à celui
    immédiatement en dessous. La remontée récursive avait d'abord été écrite puis écartée : elle
    faisait du salon national la réunion de tous les encadrants du pays, ce qui n'est plus un
    salon de commandement mais une liste de diffusion.

    Voir SalonMatrixEquipeSerializer.get_membres, qui calcule les deux."""

    INTERVENANTS = "INTERVENANTS", "Intervenants"
    ENCADREMENT = "ENCADREMENT", "Encadrement"


class SalonMatrixEquipe(EnvironmentScopedModel):
    """Salon Matrix privé d'une équipe, activé à la demande
    (TeamViewSet.provisionner_salon_matrix). room_id vide tant que matrix-bridge ne l'a pas
    créé ; les membres sont ensuite resynchronisés en continu.

    **Plusieurs salons par équipe depuis le 11/11/2026** : c'était un OneToOneField, une équipe
    n'avait qu'un salon. Les lignes existantes sont devenues INTERVENANTS par la migration, et
    c'est le seul choix qui ne détruit rien — l'unique salon d'une équipe était déjà celui de
    l'équipe entière, il garde donc son room_id, son historique et ses membres.

    Même motif que SalonMatrixInstitution (type + contrainte d'unicité), qui portait déjà deux
    salons par institution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    equipe = models.ForeignKey(
        "Team", on_delete=models.CASCADE, related_name="salons_matrix",
    )

    type = models.CharField(
        max_length=12, choices=TypeSalonEquipe.choices,
        default=TypeSalonEquipe.INTERVENANTS,
    )

    # Vide = le salon de tous les jours. Renseigné = le salon de l'équipe POUR CETTE CRISE.
    # Règle posée par Sylvain le 16/11/2026 : « un salon par crise, et les messages hors crise
    # ne suivent pas » -- alors même qu'une équipe permanente se réutilise d'une crise à
    # l'autre. C'est donc le salon, et non l'équipe, qui est propre à la crise. Seul le salon
    # INTERVENANTS a une variante par crise (voir core/salons_de_crise.py).
    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, null=True, blank=True, related_name="salons_equipe",
    )

    room_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Identifiant Matrix du salon (ex: !abc123:matrix.assista-crise.local), posé par le pont à la création.",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    derniere_synchronisation = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # Un seul salon de tous les jours par équipe et par type…
            models.UniqueConstraint(fields=['equipe', 'type'], condition=models.Q(crise__isnull=True),
                                    name='unique_salon_matrix_equipe_type'),
            # … et un seul par crise.
            models.UniqueConstraint(fields=['equipe', 'type', 'crise'], condition=models.Q(crise__isnull=False),
                                    name='unique_salon_matrix_equipe_type_crise'),
        ]

    def __str__(self):
        suffixe = f" — {self.crise.name}" if self.crise_id else ""
        return f"Salon Matrix {self.get_type_display()} de {self.equipe.name}{suffixe}"


class SalonMatrixMission(EnvironmentScopedModel):
    """Salon Matrix d'une mission : « 1 mission = 1 canal » (règle posée par Sylvain le
    16/11/2026). Il réunit les membres de toutes les équipes affectées à la mission, encadrement
    compris -- une mission peut mobiliser plusieurs équipes, et c'est le seul endroit où elles se
    parlent sans passer par leurs salons respectifs.

    Créé automatiquement avec la mission (voir core/salons_matrix.py). Tant que la mission n'est
    pas terminée, le pont en tient la composition à jour ; ensuite le salon reste, avec son
    historique, mais n'est plus synchronisé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mission = models.OneToOneField("Mission", on_delete=models.CASCADE, related_name="salon_matrix")
    room_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="Identifiant Matrix du salon, posé par le pont à la création.",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    derniere_synchronisation = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Salon Matrix de la mission {self.mission.titre}"


class TypeSalonInstitution(models.TextChoices):
    """PERMANENTS : personnel de l'institution ; BENEVOLES : membres de ses équipes actives ;
    ANNONCES : tout le monde, mais seul le bureau y écrit.

    ANNONCES, demandé le 13/11/2026, n'est pas un troisième salon de discussion : c'est une
    **diffusion**. Tout membre de l'association le reçoit, et seuls les membres du bureau
    (`ContactInstitution.membre_bureau`) peuvent y publier — techniquement, un niveau de
    pouvoir Matrix de 50 pour eux et 0 pour les autres (voir matrix-bridge).

    Pourquoi un salon à part plutôt qu'une consigne dans le salon « Bénévoles mobilisés » :
    une annonce qui compte (convocation, consigne de sécurité, information d'assemblée
    générale) doit être lisible sans remonter trente messages de coordination. Et une consigne
    de politesse ne tient pas en situation : c'est au salon de garantir le silence, pas aux
    gens.

    L'inverse — un salon où l'on peut répondre — reste BENEVOLES : la diffusion ne remplace
    pas la conversation, elle la décharge."""
    PERMANENTS = "PERMANENTS", "Permanents"
    BENEVOLES = "BENEVOLES", "Bénévoles mobilisés"
    ANNONCES = "ANNONCES", "Annonces de l'association"


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


class TransportRelais(models.TextChoices):
    USB = "USB", "USB (Web Serial)"
    BLE = "BLE", "Bluetooth (Web Bluetooth)"
    # Meshtastic seulement : l'API HTTP du nœud. MeshCore en Wi-Fi parle du TCP brut, qu'aucun
    # navigateur ne sait ouvrir.
    WIFI = "WIFI", "Réseau local (HTTP du nœud)"


class DiffusionCanalMeshtastic(EnvironmentScopedModel):
    """« CETTE passerelle a émis CE message de canal » (core/canaux_locaux.py).

    Le statut d'un message de canal est global : la première passerelle qui l'émettait le
    marquait envoyé, et les autres ne le recevaient plus. Pour un canal de crise partagé entre
    deux communes, une seule des deux passerelles locales l'aurait émis — l'autre commune ne
    l'entendait pas. Une ligne par couple (message, passerelle) rend chaque diffusion locale
    indépendante.

    Notée quand la passerelle PREND le message, pas quand elle confirme l'avoir émis : le pont
    Python d'un satellite marque l'envoi sans dire quelle passerelle l'a fait, et attendre sa
    confirmation ferait renvoyer le même message à chaque relève."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey("MessageCanalMeshtastic", on_delete=models.CASCADE,
                                related_name="diffusions")
    compagnon = models.ForeignKey("CompagnonMeshtastic", on_delete=models.CASCADE,
                                  related_name="diffusions_canal")
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "compagnon"],
                                    name="diffusion_canal_unique_par_passerelle"),
        ]


class SessionRelaisNavigateur(EnvironmentScopedModel):
    """Un poste qui relaie une radio depuis son navigateur (voir core/relais_navigateur.py).

    Existe pour trois raisons, toutes opérationnelles :

    1. **savoir qui relaie quoi** — sinon une radio apparaît active sans qu'on sache d'où ;
    2. **empêcher deux relais sur la même radio**, qui enverraient chaque message en double ;
    3. **nettoyer les sessions mortes** : une page web n'annonce pas sa fermeture de façon
       fiable — onglet tué, portable en veille, Wi-Fi coupé. Sans battement ni ménage, une
       radio resterait marquée relayée indéfiniment.

    Ce n'est pas un jeton d'authentification : l'appelant est authentifié normalement, et la
    session dit seulement qu'il a déclaré relayer CE companion. Le droit de le faire est
    recalculé à chaque appel (`peut_relayer`), jamais porté par la session — un membre sorti de
    l'institution perd la main immédiatement, sans attendre l'expiration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Exactement l'un des deux (contrainte ci-dessous). Deux clés étrangères plutôt qu'une clé
    # générique : on garde l'intégrité référentielle et la suppression en cascade, et deux
    # protocoles ne justifient pas `contenttypes`.
    compagnon = models.ForeignKey(
        "CompagnonMeshCore", on_delete=models.CASCADE, related_name="sessions_relais",
        null=True, blank=True,
    )
    compagnon_meshtastic = models.ForeignKey(
        "CompagnonMeshtastic", on_delete=models.CASCADE, related_name="sessions_relais",
        null=True, blank=True,
    )

    # Par où le navigateur parle à la radio. Porté par la session et non par le companion :
    # la même radio peut passer de l'USB au Bluetooth d'une intervention à l'autre.
    transport = models.CharField(max_length=4, choices=TransportRelais.choices,
                                 default=TransportRelais.USB)

    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sessions_relais",
    )

    ouverte_le = models.DateTimeField(auto_now_add=True)

    # Battu à chaque cycle de relais. C'est LUI qui fait foi pour « cette session est vivante »,
    # pas `fermee_le` : une fermeture propre est l'exception, pas la règle.
    dernier_contact = models.DateTimeField(auto_now_add=True, db_index=True)

    fermee_le = models.DateTimeField(null=True, blank=True)
    motif_fermeture = EncryptedTextField(max_length=120, blank=True)

    # Pour diagnostiquer un relais qui ne marche pas : « Chrome 141 sur Windows » explique
    # beaucoup de choses qu'un identifiant de session n'explique pas.
    user_agent = EncryptedTextField(max_length=255, blank=True)

    # Compteurs de trafic, pour voir d'un coup d'oeil si le relais fait quelque chose.
    trames_recues = models.PositiveIntegerField(default=0)
    trames_envoyees = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-dernier_contact"]
        constraints = [
            models.CheckConstraint(
                name="session_relais_un_seul_compagnon",
                condition=(
                    models.Q(compagnon__isnull=False, compagnon_meshtastic__isnull=True)
                    | models.Q(compagnon__isnull=True, compagnon_meshtastic__isnull=False)
                ),
            ),
        ]

    @property
    def radio(self):
        return self.compagnon or self.compagnon_meshtastic

    def __str__(self):
        return f"Relais {self.radio} par {self.utilisateur}"


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

    contenu = EncryptedTextField()

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
    # Appareil joint en Bluetooth par l'hôte du pont — la passerelle Windows (15/11/2026).
    BLE = "BLE", "Bluetooth (depuis la machine du pont)"
    # Radio tenue par un NAVIGATEUR (core/relais_navigateur.py). À exclure IMPÉRATIVEMENT de
    # `actifs-avec-identifiants` : le pont Meshtastic traite tout type inconnu comme du MQTT, il
    # ouvrirait donc une connexion au broker avec l'identité de cette radio.
    NAVIGATEUR = "NAVIGATEUR", "Relayée par un navigateur"


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
    ble_adresse = models.CharField(max_length=64, null=True, blank=True, help_text="Adresse Bluetooth de l'appareil (mode BLE uniquement).")

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
    # Racine sur laquelle le pont PUBLIE en plus de `topic_racine`, quand le broker sépare ce
    # qu'on écoute de ce qu'on émet. Constaté sur Gaulix le 17/11/2026 : les appareils y sont
    # abonnés sur `msh/EU_868`, et `Traitement/msh/EU_868` n'est que la sortie du traitement du
    # broker — un appareil a demandé son identité au pont, le pont a répondu sur
    # `Traitement/…`, et la réponse ne lui est jamais parvenue. Vide = une seule racine.
    topic_racine_emission = models.CharField(max_length=100, blank=True, default="")

    mqtt_username = models.CharField(max_length=100, blank=True)
    # write_only côté serializer (comme x25519_private_key_hex) — jamais renvoyé en clair par
    # l'API une fois enregistré. Vide = pas d'authentification (cas de certains brokers publics).
    mqtt_password = EncryptedTextField(max_length=255, blank=True)
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

    # Règle du 14/11/2026 (core/canaux_locaux.py) : une passerelle LOCALE (série ou navigateur)
    # est isolée par défaut — elle ne réémet que ce qui concerne sa crise et sa commune, et ce
    # qu'elle entend n'est réémis par aucune autre passerelle. Cocher lui rend le comportement de
    # réseau. Sans effet sur une passerelle MQTT ou TCP, qui est par nature une passerelle de
    # réseau. Les companions SÉRIE existants avant la règle ont été laissés à True : leur
    # comportement ne change pas sans qu'on le décide.
    relais_reseau = models.BooleanField(
        default=False,
        help_text="Passerelle locale seulement : réémettre aussi ce qui ne concerne ni sa crise ni "
                  "sa commune. Décoché par défaut (passerelle isolée).",
    )

    # Paire X25519 générée à la création ; la clé privée n'est jamais exposée par l'API.
    x25519_private_key_hex = EncryptedTextField(max_length=64, blank=True, editable=False)

    # Clé publique de l'APPAREIL physique (modes TCP/SERIE), rapportée par le pont à la
    # connexion -- différente de x25519_public_key_hex, qui est l'identité LOGICIELLE utilisée
    # en mode MQTT. C'est celle-ci qu'il faut poser dans `security.admin_key` des nœuds à
    # administrer : le firmware vérifie la clé de l'émetteur RADIO, c'est-à-dire l'appareil
    # passerelle, pas notre identité Django. Publique par nature : aucun chiffrement.
    cle_publique_appareil_hex = models.CharField(
        max_length=64, blank=True, editable=False,
        help_text="Clé publique de l'appareil passerelle, à autoriser dans security.admin_key des nœuds à administrer.",
    )

    derniere_connexion = models.DateTimeField(null=True, blank=True)
    dernier_etat = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Rapporté par le service-pont : CONNECTE / DECONNECTE / ERREUR.",
    )
    derniere_erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    # Correspondances « nom du canal sur la radio » (en minuscules) -> identifiant d'un canal
    # d'Assista-Crise (19/11/2026). Le relais rattache d'abord un canal par son NOM ; ici, la
    # personne qui tient la radio dit qu'un canal déjà présent (« Alerte ») EST tel canal
    # (celui de la commune), sans rien réécrire sur la radio. Chiffré comme tout ce qui est
    # saisi ; jamais interrogé en SQL.
    correspondances_canaux = EncryptedJSONField(default=dict, blank=True)

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
    psk_hex = EncryptedTextField(max_length=64, null=True, blank=True)

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
    # 19/11/2026 : sauts parcourus par le dernier paquet entendu (hop_start - hop_limit) et
    # moment de cette dernière écoute, quel que soit le type de paquet.
    sauts = models.PositiveSmallIntegerField(null=True, blank=True)
    dernier_entendu = models.DateTimeField(null=True, blank=True)

    date_synchronisation = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["compagnon", "node_num"], name="uq_contact_meshtastic_compagnon_node_num"),
        ]

    def __str__(self):
        return f"{self.long_name or self.short_name or format(self.node_num, '08x')}"


class SourceLiaisonMeshtastic(models.TextChoices):
    """D'où vient l'observation d'une liaison. La distinction est essentielle à l'analyse : seuls
    RF et VOISINAGE prouvent qu'un nœud RAPPORTE ce qu'il entend. Un saut de traceroute ne le
    prouve pas — un relais qui ne rapporte rien ferait passer pour « à sens unique » tout ce
    qu'il entend sans le dire (voir core/analyse_liaisons.py)."""
    RF = "RF", "Reçu par une passerelle MQTT (SNR mesuré)"
    VOISINAGE = "VOISINAGE", "Déclaré par un rapport de voisinage (NeighborInfo)"
    TRACEROUTE = "TRACEROUTE", "Saut d'un traceroute"
    # MeshCore (19/11/2026) : deux relais consécutifs du chemin d'un paquet en inondation se
    # sont entendus. Pas de SNR : seule la dernière réception est mesurée.
    CHEMIN = "CHEMIN", "Relais consécutifs d'un chemin MeshCore"


class MesureTelemetrieMeshtastic(EnvironmentScopedModel):
    """Une mesure de télémétrie d'un nœud Meshtastic, telle qu'une passerelle l'a reçue
    (19/11/2026, tableau radio). DeviceMetrics : batterie, tension, occupation du canal, temps
    d'antenne. LocalStats (passerelles) : paquets émis/reçus, nœuds en ligne, bruit de fond.

    Données techniques, sans rien de personnel : en clair, parce qu'on les agrège par intervalle
    de temps. Gardées 30 jours (purge au fil des rapports)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    compagnon = models.ForeignKey(CompagnonMeshtastic, on_delete=models.CASCADE, related_name="mesures")
    node_num = models.PositiveBigIntegerField()
    horodatage = models.DateTimeField()
    batterie = models.PositiveSmallIntegerField(null=True, blank=True, help_text="%, 101 = secteur")
    tension = models.FloatField(null=True, blank=True)
    occupation_canal = models.FloatField(null=True, blank=True, help_text="% du temps où le canal est occupé")
    temps_antenne_tx = models.FloatField(null=True, blank=True, help_text="% du temps passé à émettre")
    uptime_s = models.PositiveIntegerField(null=True, blank=True)
    paquets_tx = models.PositiveIntegerField(null=True, blank=True)
    paquets_rx = models.PositiveIntegerField(null=True, blank=True)
    noeuds_en_ligne = models.PositiveSmallIntegerField(null=True, blank=True)
    bruit_dbm = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["node_num", "horodatage"], name="mesure_mt_noeud_heure"),
                   models.Index(fields=["compagnon", "horodatage"], name="mesure_mt_gw_heure")]


class CompteurPaquetsMeshtastic(EnvironmentScopedModel):
    """Paquets reçus par une passerelle, par heure et par type (portnum) : la répartition du
    trafic, et ce qui occupe le canal (19/11/2026)."""
    compagnon = models.ForeignKey(CompagnonMeshtastic, on_delete=models.CASCADE, related_name="compteurs_paquets")
    heure = models.DateTimeField()
    type_paquet = models.CharField(max_length=40)
    nombre = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["compagnon", "heure", "type_paquet"],
                                               name="uq_compteur_paquets_mt")]


class LiaisonMeshtastic(EnvironmentScopedModel):
    """Liaison radio ORIENTÉE et mesurée : `recepteur` a entendu `emetteur` directement.

    Agrégée, pas un journal de réceptions : une ligne par (émetteur, récepteur, source), dont on
    retient le MEILLEUR SNR observé et le nombre d'observations. À l'échelle d'un réseau
    départemental, conserver chaque réception ferait des millions de lignes pour une information
    qui ne sert qu'agrégée.

    Le sens compte : une liaison n'est pas symétrique. « B entend A » n'implique pas « A entend
    B » — c'est précisément ce que l'analyse cherche (relais sourd, liaison déséquilibrée).

    Modèle repris de `carte-live-meshtastic` (table `liens`, GPL-3.0, sauveteur71, avec son
    autorisation), simplifié : pas de table de réceptions séparée."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Numéros de nœud Meshtastic (32 bits), pas des FK : on observe des nœuds qu'on ne connaît pas
    # forcément encore, et une FK obligerait à créer un ContactMeshtastic pour chaque inconnu.
    emetteur = models.PositiveBigIntegerField()
    recepteur = models.PositiveBigIntegerField()
    source = models.CharField(max_length=10, choices=SourceLiaisonMeshtastic.choices)

    # Meilleur SNR observé dans ce sens, en dB. Null pour une source qui n'en fournit pas
    # (voisinage sans SNR, saut de traceroute sans mesure).
    snr = models.FloatField(null=True, blank=True)
    rssi = models.IntegerField(null=True, blank=True)
    nombre = models.PositiveIntegerField(default=1)

    premier_vu = models.DateTimeField(auto_now_add=True)
    dernier_vu = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["emetteur", "recepteur", "source", "environment"],
                name="uq_liaison_meshtastic_sens_source",
            ),
        ]
        indexes = [
            # L'analyse lit toujours une fenêtre temporelle, jamais la table entière.
            models.Index(fields=["-dernier_vu"]),
            models.Index(fields=["recepteur"]),
        ]

    def __str__(self):
        return f"{self.emetteur:08x} -> {self.recepteur:08x} ({self.source}, {self.snr} dB)"


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

    contenu = EncryptedTextField()

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

    contenu = EncryptedTextField()

    statut = models.CharField(max_length=12, choices=StatutMessageMesh.choices, default=StatutMessageMesh.EN_ATTENTE)

    erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.canal.nom}] {self.contenu[:40]}"


class TypeTacheAdminMeshtastic(models.TextChoices):
    """Opérations d'administration à distance. Volontairement réduit : chaque entrée est une
    commande qu'on sait justifier et dont on connaît le coût en cas d'erreur.

    Absents EXPRÈS : `factory_reset`, `nodedb_reset`, `set_channel` et `shutdown`. Un répéteur est
    souvent sur un point haut : une extinction ou une réinitialisation à distance se paie d'un
    déplacement, parfois en montagne et en hiver. `set_channel` demanderait en plus de
    transporter une PSK de canal jusqu'à l'appareil, ce que ce chemin ne fait pas."""

    LIRE_METADATA = "LIRE_METADATA", "Lire la version de firmware et le modèle"
    LIRE_CONFIG_LORA = "LIRE_CONFIG_LORA", "Lire la configuration LoRa (puissance, région, preset)"
    LIRE_CONFIG_APPAREIL = "LIRE_CONFIG_APPAREIL", "Lire la configuration de l'appareil (rôle, rediffusion)"
    LIRE_PROPRIETAIRE = "LIRE_PROPRIETAIRE", "Lire le nom du nœud"
    LIRE_CONFIG_MQTT = "LIRE_CONFIG_MQTT", "Lire la configuration MQTT (broker, JSON)"
    LIRE_REGLAGES = "LIRE_REGLAGES", "Lire une section de réglages (radio, appareil, modules)"
    DEFINIR_REGLAGES = "DEFINIR_REGLAGES", "Modifier des réglages (rôle, preset, sauts, voisinage…)"
    DEFINIR_NOM = "DEFINIR_NOM", "Renommer le nœud"
    DEFINIR_PUISSANCE = "DEFINIR_PUISSANCE", "Définir la puissance d'émission"
    DEFINIR_MQTT_JSON = "DEFINIR_MQTT_JSON", "Activer ou couper la publication JSON du MQTT"
    REDEMARRER = "REDEMARRER", "Redémarrer le nœud"
    # ── 19/11/2026 : le reste de ce que l'administration Meshtastic permet sans risque ──
    LIRE_CANAUX = "LIRE_CANAUX", "Lire les canaux (noms et rôles, jamais les clés)"
    LIRE_ETAT_CONNEXION = "LIRE_ETAT_CONNEXION", "Lire l'état des connexions (Wi-Fi, Ethernet, Bluetooth, série)"
    LIRE_MESSAGES_PREDEF = "LIRE_MESSAGES_PREDEF", "Lire les messages prédéfinis"
    DEFINIR_MESSAGES_PREDEF = "DEFINIR_MESSAGES_PREDEF", "Définir les messages prédéfinis"
    POSITION_FIXE = "POSITION_FIXE", "Fixer la position du nœud"
    RETIRER_POSITION_FIXE = "RETIRER_POSITION_FIXE", "Retirer la position fixe"
    REGLER_HEURE = "REGLER_HEURE", "Mettre le nœud à l'heure"
    FAVORI = "FAVORI", "Marquer un nœud comme favori"
    RETIRER_FAVORI = "RETIRER_FAVORI", "Retirer un nœud des favoris"
    IGNORER = "IGNORER", "Ignorer un nœud"
    NE_PLUS_IGNORER = "NE_PLUS_IGNORER", "Ne plus ignorer un nœud"
    OUBLIER_NOEUD = "OUBLIER_NOEUD", "Retirer un nœud de la base"
    VIDER_BASE_NOEUDS = "VIDER_BASE_NOEUDS", "Vider la base des nœuds"
    TRACEROUTE = "TRACEROUTE", "Traceroute vers un nœud (chemin et SNR aller-retour)"


# Opérations d'ÉCRITURE : le firmware exige pour elles une clé de session valide (AdminModule.cpp,
# `checkPassKey`), les lectures en sont dispensées (`messageIsRequest`). Le pont doit donc
# obtenir la clé par une lecture juste avant d'écrire -- voir meshtastic-bridge/admin_meshtastic.py.
TACHES_ADMIN_ECRITURE = frozenset({
    TypeTacheAdminMeshtastic.DEFINIR_PUISSANCE,
    TypeTacheAdminMeshtastic.DEFINIR_MQTT_JSON,
    TypeTacheAdminMeshtastic.DEFINIR_REGLAGES,
    TypeTacheAdminMeshtastic.DEFINIR_NOM,
    TypeTacheAdminMeshtastic.REDEMARRER,
    TypeTacheAdminMeshtastic.DEFINIR_MESSAGES_PREDEF,
    TypeTacheAdminMeshtastic.POSITION_FIXE,
    TypeTacheAdminMeshtastic.RETIRER_POSITION_FIXE,
    TypeTacheAdminMeshtastic.REGLER_HEURE,
    TypeTacheAdminMeshtastic.FAVORI,
    TypeTacheAdminMeshtastic.RETIRER_FAVORI,
    TypeTacheAdminMeshtastic.IGNORER,
    TypeTacheAdminMeshtastic.NE_PLUS_IGNORER,
    TypeTacheAdminMeshtastic.OUBLIER_NOEUD,
    TypeTacheAdminMeshtastic.VIDER_BASE_NOEUDS,
})
# Opérations qui visent un AUTRE nœud que leur cible, désigné par `parametres.node_num`.
TACHES_ADMIN_SUR_UN_NOEUD = frozenset({
    TypeTacheAdminMeshtastic.FAVORI, TypeTacheAdminMeshtastic.RETIRER_FAVORI,
    TypeTacheAdminMeshtastic.IGNORER, TypeTacheAdminMeshtastic.NE_PLUS_IGNORER,
    TypeTacheAdminMeshtastic.OUBLIER_NOEUD,
})

# Longueurs imposées par le firmware pour l'identité d'un nœud, en OCTETS et non en caractères :
# un seul emoji ou deux lettres accentuées suffisent à dépasser le nom court, et le firmware
# tronquerait en silence.
NOM_LONG_MAX_OCTETS = 39
NOM_COURT_MAX_OCTETS = 4

# Puissance d'émission, en dBm. 27 dBm (500 mW) est le plafond de la bande 869,4-869,65 MHz
# utilisée par la région EU_868, sous réserve d'un rapport cyclique de 10 % (décision ERC 70-03,
# reprise par l'ARCEP). Le firmware ne vérifie PAS cette valeur dans AdminModule (vérifié dans le
# code le 06/11/2026) : c'est donc ici qu'on la borne, pas ailleurs.
#
# Deux plafonds, une seule règle (révision du 09/11/2026) : jusqu'à PUISSANCE_MAX_DBM la demande
# passe seule ; au-delà, jusqu'à PUISSANCE_MAX_ABSOLUE_DBM, elle exige la confirmation
# réglementaire explicite, comme les autres réglages qui décident de ce qui part dans l'air (voir
# core/mesh_reglages.py). 36 dBm est le plafond de la région la plus permissive de la table du
# firmware (NZ_865) : c'est une borne de cohérence, pas une autorisation.
PUISSANCE_MAX_DBM = 27
PUISSANCE_MAX_ABSOLUE_DBM = 36
PUISSANCE_MIN_DBM = 1

# Nombre de passages du pont avant d'abandonner une tâche. Une opération d'administration
# traverse le mesh et peut échouer parce qu'un relais dormait, pas parce qu'elle est mauvaise.
TENTATIVES_MAX_TACHE_ADMIN = 3

# Au-delà, une tâche laissée EN_COURS est rendue à la file : le pont a redémarré en plein vol.
# Large à dessein -- une lecture de configuration à travers plusieurs sauts prend des minutes.
DELAI_RECLAMATION_TACHE_ADMIN_S = 300


class StatutTacheAdminMeshtastic(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    EN_COURS = "EN_COURS", "En cours"
    TERMINEE = "TERMINEE", "Terminée"
    ECHEC = "ECHEC", "Échec"


class TacheAdminMeshtastic(EnvironmentScopedModel):
    """Une opération d'administration à distance sur un nœud Meshtastic, mise en file ici et
    exécutée par le pont (meshtastic-bridge/admin_meshtastic.py).

    Pourquoi une file et pas un appel synchrone : l'opération traverse la radio. Elle met de
    quelques secondes à plusieurs minutes, peut ne jamais aboutir si le nœud dort, et c'est le
    pont -- pas Django -- qui tient la connexion à l'appareil passerelle.

    **Ce qui conditionne tout, côté firmware** (lu dans `AdminModule::handleReceivedProtobuf` le
    06/11/2026, pas dans la documentation qui ne le dit pas) : un message d'administration venant
    d'un AUTRE nœud n'est accepté que dans deux cas.

    1. Il est chiffré par clé publique (`pki_encrypted`) et la clé publique de l'émetteur est
       l'une des TROIS que le nœud cible porte dans `config.security.admin_key` (comparaison
       octet par octet sur 32 octets). Sinon : `ADMIN_PUBLIC_KEY_UNAUTHORIZED`.
    2. Il arrive sur un canal nommé « admin » avec `admin_channel_enabled` -- mécanisme
       historique, sans aucune vérification de clé, que ce projet n'utilise pas : il donne
       l'administration à quiconque possède la PSK de ce canal.

    Conséquence pratique : **administrer un nœud suppose d'avoir posé au préalable la clé
    publique de l'appareil passerelle dans `security.admin_key` de ce nœud**, avec l'application
    Meshtastic officielle, une fois, en le tenant en main. Ce n'est pas un défaut de ce code :
    c'est la seule chose qui empêche n'importe qui de reconfigurer vos relais par radio. La clé
    à poser est affichée sur la page d'administration (CompagnonMeshtastic.cle_publique_appareil_hex).

    `reponse` est chiffrée au repos : une configuration lue peut contenir la PSK WiFi de
    l'appareil (`config.network`) ou des clés de canal (`get_channel_response`), et le projet ne
    stocke rien de tel en clair."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Passerelle qui exécutera la tâche : c'est SON pont qui relève la file, et c'est SA clé
    # publique d'appareil que le nœud cible doit autoriser.
    compagnon = models.ForeignKey(
        CompagnonMeshtastic, on_delete=models.CASCADE, related_name="taches_admin",
    )

    # Nœud visé. Vide = la passerelle elle-même : le firmware traite alors le message comme
    # local (`mp.from == 0`) et n'exige NI clé d'administration NI clé de session. C'est le seul
    # cas qui marche sans aucun provisionnement préalable.
    node_num_cible = models.PositiveBigIntegerField(
        null=True, blank=True,
        help_text="Vide = l'appareil passerelle lui-même (aucune autorisation préalable requise).",
    )

    type_tache = models.CharField(max_length=30, choices=TypeTacheAdminMeshtastic.choices)

    # Paramètres de l'opération, ex. {"puissance_dbm": 20}. Jamais de secret ici (voir les
    # opérations volontairement absentes de TypeTacheAdminMeshtastic) : pas de chiffrement.
    parametres = models.JSONField(null=True, blank=True)

    statut = models.CharField(
        max_length=12, choices=StatutTacheAdminMeshtastic.choices,
        default=StatutTacheAdminMeshtastic.EN_ATTENTE,
    )

    tentatives = models.PositiveSmallIntegerField(default=0)

    # Réponse brute, rendue lisible par le pont puis sérialisée en JSON. Chiffrée : voir docstring.
    reponse = EncryptedTextField(null=True, blank=True)

    erreur = models.TextField(null=True, blank=True)

    demande_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="taches_admin_meshtastic",
        help_text="Qui a demandé l'opération — une écriture sur un relais doit être imputable.",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_prise = models.DateTimeField(null=True, blank=True, help_text="Quand le pont l'a prise en charge.")
    date_reponse = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["statut", "compagnon"]),
            models.Index(fields=["-date_creation"]),
        ]

    @property
    def est_ecriture(self):
        return self.type_tache in TACHES_ADMIN_ECRITURE

    def __str__(self):
        cible = f"{self.node_num_cible:08x}" if self.node_num_cible else "passerelle"
        return f"{self.get_type_tache_display()} -> {cible} ({self.statut})"


class ConfigurationNoeudMeshtastic(EnvironmentScopedModel):
    """Dernière configuration relevée sur un nœud par une tâche d'administration.

    Une ligne par nœud, remplacée à chaque relevé : on veut l'état courant du réseau, pas son
    historique. (Un historique se reconstruirait au besoin depuis les tâches, qui gardent leur
    réponse.)

    Rien n'est chiffré ici, à la différence de `TacheAdminMeshtastic.reponse` : ce sont des
    caractéristiques radio, aucune donnée personnelle. Et `puissance_emission_dbm` doit rester
    un nombre lisible par l'ORM -- `core/analyse_liaisons.py` s'en sert pour corriger l'écart de
    SNR, et un champ chiffré par Fernet n'est ni comparable ni agrégeable en SQL."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    node_num = models.PositiveBigIntegerField()

    # Le relevé qui compte pour l'analyse d'asymétrie : sans lui, la correction de puissance est
    # nulle et la détection de relais sourd confond « sourd » et « voisin qui émet plus fort ».
    # ATTENTION : 0 n'est pas « 0 dBm ». Le firmware interprète tx_power = 0 comme « applique le
    # maximum autorisé pour la région » (RadioInterface::getTxPower), c'est donc une puissance
    # INCONNUE de nous. core/analyse_liaisons.py traite 0 comme absent, et l'interface l'affiche
    # « maximum de la région » et non « 0 dBm ».
    puissance_emission_dbm = models.SmallIntegerField(
        null=True, blank=True,
        help_text="dBm. 0 = le firmware applique le maximum de la région : puissance inconnue.",
    )

    region = models.CharField(max_length=20, blank=True)
    modem_preset = models.CharField(max_length=30, blank=True)
    hop_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    role = models.CharField(max_length=30, blank=True)
    firmware_version = models.CharField(max_length=40, blank=True)
    hardware_model = models.CharField(max_length=40, blank=True)

    releve_par = models.ForeignKey(
        CompagnonMeshtastic, on_delete=models.SET_NULL, null=True, blank=True, related_name="configurations_relevees",
    )

    date_releve = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["node_num", "environment"], name="uq_configuration_noeud_meshtastic",
            ),
        ]

    def __str__(self):
        return f"Config {self.node_num:08x} ({self.puissance_emission_dbm} dBm)"


class PointAltitude(models.Model):
    """Altitude d'un point, mise en cache (IGN RGE ALTI).

    **Pas cloisonné PROD/DEMO**, volontairement : le relief est le même dans les deux zones, et
    `core/inondation.py` partage déjà ses grilles d'altitude entre elles pour la même raison (et
    pour qu'elles ne divergent pas). Aucune donnée personnelle : une altitude de terrain.

    La clé est arrondie à 1e-4 degré (~11 m) : assez fin pour un profil radio au pas de 100 m,
    assez grossier pour que deux calculs sur le même site retombent sur les mêmes points — c'est
    ce qui rend un recalcul de couverture quasi gratuit, alors que l'API IGN est limitée à
    2,5 requêtes par seconde.

    Clé TEXTUELLE unique « lat,lon » et non deux colonnes séparées : on relit quelques milliers
    de points d'un coup, et un `filter(cle_lat__in=[...], cle_lon__in=[...])` est un produit
    cartésien, pas une liste de couples — il ramènerait des dizaines de milliers de lignes sans
    rapport. Un seul `cle__in` indexé fait le travail exactement.

    Le relief ne change pas : une ligne n'est jamais à rafraîchir."""

    # « 45.4321,4.3900 » — produite par core/relief_radio.py:_cle, jamais à la main.
    cle = models.CharField(max_length=24, unique=True)
    altitude_m = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=["cle"])]

    def __str__(self):
        return f"{self.cle} : {self.altitude_m} m"


class CalibrationRadio(EnvironmentScopedModel):
    """Écart mesuré entre le modèle de propagation et les liaisons réellement observées.

    C'est ce qui sépare une prévision d'une illustration. Un bilan de liaison théorique se trompe
    de 10 à 20 dB en milieu réel (végétation, bâti, désadaptation d'antenne) ; on compare donc le
    modèle aux `LiaisonMeshtastic` mesurées et on en retient la MÉDIANE de l'écart — pas la
    moyenne, qu'une seule liaison aberrante suffirait à fausser.

    `perte_environnement_db` est nul tant qu'il y a moins de cinq liaisons exploitables : on
    préfère afficher « non calibré » qu'une correction tirée de deux observations.

    Chaque calcul est conservé (une ligne par passage) : voir dériver la calibration dans le
    temps est en soi un signal -- un réseau dont l'écart se dégrade a un problème matériel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    preset = models.CharField(max_length=20)
    liaisons_retenues = models.PositiveIntegerField(default=0)
    ecart_median_db = models.FloatField(null=True, blank=True)
    perte_environnement_db = models.SmallIntegerField(
        null=True, blank=True,
        help_text="Déduit de l'écart médian, borné à [4, 30] dB. Vide = pas assez de liaisons.",
    )
    # Les quarante liaisons les plus pénalisantes, pour pouvoir vérifier une calibration plutôt
    # que de la croire. Numéros de nœud et SNR seulement : aucune donnée personnelle.
    exemples = models.JSONField(null=True, blank=True)

    date_calcul = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["-date_calcul"])]

    def __str__(self):
        return f"Calibration radio {self.date_calcul:%d/%m/%Y} ({self.liaisons_retenues} liaisons)"


class StatutCouvertureRadio(models.TextChoices):
    EN_COURS = "EN_COURS", "Calcul en cours"
    TERMINEE = "TERMINEE", "Terminée"
    ECHEC = "ECHEC", "Échec"


class CouvertureRadioSite(EnvironmentScopedModel):
    """Couverture calculée d'un site d'émission, sur le relief.

    Conservée parce qu'elle coûte : quelques milliers d'interrogations d'altitude, limitées à
    2,5 requêtes par seconde. Le cache de points (`PointAltitude`) rend le RECALCUL rapide, mais
    la première passe sur un site neuf prend de l'ordre d'une minute.

    Un site n'est pas forcément un nœud existant : on calcule aussi des points candidats (un
    château d'eau, un pylône) pour savoir s'ils vaudraient la peine. D'où une position libre
    plutôt qu'une clé étrangère obligatoire.

    `calibre` à faux signale une couverture **non calibrée** : c'est alors une indication de
    relief, pas une prévision, et l'interface doit le dire."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=120)
    location = gis_models.PointField(srid=4326)
    # Nœud correspondant, quand le site en est un : permet de recalculer la couverture d'un
    # relais existant après un changement de puissance ou d'antenne.
    node_num = models.PositiveBigIntegerField(null=True, blank=True)

    hauteur_antenne_m = models.FloatField(default=6.0)
    hauteur_cible_m = models.FloatField(default=2.0)
    preset = models.CharField(max_length=20, default="LONG_FAST")
    puissance_dbm = models.FloatField(default=27.0)
    rayon_max_km = models.FloatField(default=40.0)
    nb_rayons = models.PositiveIntegerField(default=72)
    pas_m = models.PositiveIntegerField(default=500)

    perte_environnement_db = models.FloatField()
    calibre = models.BooleanField(default=False)

    # [[lat, lon, marge_db, distance_m], ...] : les points ATTEINTS seulement. Les autres ne
    # servent à rien et tripleraient la taille.
    points = models.JSONField(default=list)
    surface_estimee_km2 = models.FloatField(null=True, blank=True)
    points_sans_altitude = models.PositiveIntegerField(
        default=0,
        help_text="Points pour lesquels l'IGN n'a rien renvoyé : au-delà de quelques pourcents, "
                   "la couverture est sous-estimée.",
    )

    # Le statut vit ici et pas dans un second modèle : une couverture EST son propre état de
    # tâche (même rôle que TacheSimulationInondation, mais il n'y a qu'un calcul par site, donc
    # rien à coordonner entre types de tâche). Survit à un changement de page.
    statut = models.CharField(
        max_length=12, choices=StatutCouvertureRadio.choices,
        default=StatutCouvertureRadio.EN_COURS,
    )
    erreur = models.TextField(null=True, blank=True)

    date_lancement = models.DateTimeField(auto_now_add=True)
    date_calcul = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["-date_lancement"]), models.Index(fields=["node_num"])]

    def __str__(self):
        return f"Couverture {self.nom} ({self.surface_estimee_km2} km²)"


class NiveauAccesRadio(models.TextChoices):
    """Trois niveaux, et pas un de plus : ce qui les sépare est QUI subit l'erreur.

    - `AUCUN` : le menu Radio reste visible, mais toute page y renvoie vers /admin/radio, qui
      explique ce qu'il faut (un nœud, ou une passerelle) et permet de demander le droit. Ne
      pas afficher le menu du tout avait été écarté : une commune qui n'a pas encore de radio
      doit pouvoir découvrir qu'elle existe et la demander, sinon le dispositif n'a aucune
      porte d'entrée -- même raisonnement que « Habilitations registre ».
    - `OPERATEUR` : le droit intermédiaire. Lecture de tout le réseau, simulations de
      couverture, et administration **du matériel dont on répond** : ses propres nœuds, et ceux
      de son institution — **passerelle de l'institution comprise** (voir
      `peut_administrer_noeud`). Un particulier qui porte un nœud n'a aucune raison d'être
      institutionnel pour le régler ; une collectivité qui a déployé une passerelle n'a aucune
      raison de demander à quiconque l'autorisation de la régler, c'est elle qui ira la
      rechercher si un réglage la rend muette.
    - `ADMINISTRATEUR` : en plus, n'importe quel nœud et n'importe quelle passerelle, y compris
      celle d'une institution qui aurait perdu la main sur son propre matériel, ou une
      passerelle sans institution renseignée. C'est le recours, pas le régime normal."""

    AUCUN = "AUCUN", "Aucun accès radio"
    OPERATEUR = "OPERATEUR", "Opérateur radio (ses propres nœuds)"
    ADMINISTRATEUR = "ADMINISTRATEUR", "Administration radio complète"


class TypeTacheAdminMeshCore(models.TextChoices):
    """Opérations d'administration à distance sur un répéteur MeshCore.

    Volontairement réduit, comme son équivalent Meshtastic. Ce qui en est **absent exprès** :

    - `poweroff`, `shutdown`, `start ota` : un répéteur est souvent sur un point haut, et ces
      trois-là se paient d'un déplacement ;
    - `set prv.key`, `set public.key` : elles changent l'IDENTITÉ du nœud ;
    - `password`, `set guest.password` : elles transportent un secret — et le firmware
      **réaffiche le nouveau mot de passe dans sa réponse** (`CommonCLI.cpp` l. 272 :
      « echo back just to let admin know for sure!! »).

    Trois autres sont absentes parce que **le firmware les refuse déjà à distance** (garde
    `sender_timestamp == 0`) : `erase`, `set freq` et `log`/`stats-*`. C'est ce qui rend
    MeshCore plus sûr à administrer que Meshtastic : on ne peut pas, par radio, rendre un
    répéteur définitivement sourd.

    `VERIFIER_ACCES` n'est pas une opération d'exploitation : c'est la **preuve** qu'on contrôle
    le nœud, exigée avant toute écriture (voir RattachementNoeudRadio)."""

    VERIFIER_ACCES = "VERIFIER_ACCES", "Vérifier qu'on peut administrer ce nœud"
    LIRE_STATUT = "LIRE_STATUT", "Lire le statut du répéteur"
    LIRE_VOISINS = "LIRE_VOISINS", "Lire la liste des voisins entendus"
    LIRE_REGIONS = "LIRE_REGIONS", "Lire les portées déclarées"
    LIRE_TELEMETRIE = "LIRE_TELEMETRIE", "Lire la télémétrie"
    RADIO_TEMPORAIRE = "RADIO_TEMPORAIRE", "Essayer des paramètres radio, avec retour automatique"
    DEFINIR_REGLAGE = "DEFINIR_REGLAGE", "Modifier un réglage (set)"
    ANNONCER = "ANNONCER", "Déclencher une annonce (advert)"
    REDEMARRER = "REDEMARRER", "Redémarrer le répéteur"
    # ── 19/11/2026 : le reste de ce que MeshCore permet, sur un répéteur joint par le nœud ──
    LIRE_REGLAGE = "LIRE_REGLAGE", "Relire un réglage (get)"
    LIRE_VERSION = "LIRE_VERSION", "Lire la version du firmware"
    LIRE_HORLOGE = "LIRE_HORLOGE", "Lire l'horloge du répéteur"
    LIRE_ACL = "LIRE_ACL", "Lire la liste des accès (ACL)"
    LIRE_PROPRIETAIRE = "LIRE_PROPRIETAIRE", "Lire les informations du propriétaire"
    SYNCHRO_HORLOGE = "SYNCHRO_HORLOGE", "Remettre l'horloge à l'heure (clock sync)"
    CONNEXION_ROOM = "CONNEXION_ROOM", "Se connecter à un room server"
    DECONNECTER = "DECONNECTER", "Fermer la session"
    # ── … et sur le nœud local lui-même (la passerelle qui exécute) ──
    LOCAL_STATISTIQUES = "LOCAL_STATISTIQUES", "Nœud local : statistiques (radio, paquets, système)"
    LOCAL_REGLAGES = "LOCAL_REGLAGES", "Nœud local : réglages et identité"
    LOCAL_CHEMIN_ANNONCE = "LOCAL_CHEMIN_ANNONCE", "Nœud local : chemin d'annonce d'un contact"
    LOCAL_DECOUVRIR_CHEMIN = "LOCAL_DECOUVRIR_CHEMIN", "Nœud local : découvrir le chemin vers un contact"
    LOCAL_NOM = "LOCAL_NOM", "Nœud local : changer le nom"
    LOCAL_POSITION = "LOCAL_POSITION", "Nœud local : changer la position"
    LOCAL_PUISSANCE = "LOCAL_PUISSANCE", "Nœud local : puissance d'émission"
    LOCAL_RADIO = "LOCAL_RADIO", "Nœud local : paramètres radio"
    LOCAL_SUPPRIMER_CONTACT = "LOCAL_SUPPRIMER_CONTACT", "Nœud local : supprimer un contact"
    LOCAL_REINIT_CHEMIN = "LOCAL_REINIT_CHEMIN", "Nœud local : réinitialiser le chemin d'un contact"


# Opérations qui ÉCRIVENT sur le nœud : elles exigent le droit sur ce nœud précis, la zone
# PROD, et pour un nœud MeshCore une preuve de contrôle faite (voir acces_radio.py).
TACHES_ADMIN_MESHCORE_ECRITURE = frozenset({
    TypeTacheAdminMeshCore.RADIO_TEMPORAIRE,
    TypeTacheAdminMeshCore.DEFINIR_REGLAGE,
    TypeTacheAdminMeshCore.ANNONCER,
    TypeTacheAdminMeshCore.REDEMARRER,
    TypeTacheAdminMeshCore.SYNCHRO_HORLOGE,
})
# Opérations qui ouvrent une session avec le mot de passe d'administration du répéteur (ou
# lisent sa liste d'accès) sans rien y écrire : même condition qu'une écriture — le mot de
# passe ne sert que si la preuve de contrôle est faite.
TACHES_ADMIN_MESHCORE_SESSION = frozenset({
    TypeTacheAdminMeshCore.LIRE_REGLAGE,
    TypeTacheAdminMeshCore.LIRE_VERSION,
    TypeTacheAdminMeshCore.LIRE_HORLOGE,
    TypeTacheAdminMeshCore.LIRE_ACL,
    TypeTacheAdminMeshCore.CONNEXION_ROOM,
    TypeTacheAdminMeshCore.DECONNECTER,
})
# Opérations sur le nœud LOCAL (la passerelle qui exécute) : la cible est sa propre clé.
TACHES_ADMIN_MESHCORE_LOCALES_LECTURE = frozenset({
    TypeTacheAdminMeshCore.LOCAL_STATISTIQUES,
    TypeTacheAdminMeshCore.LOCAL_REGLAGES,
    TypeTacheAdminMeshCore.LOCAL_CHEMIN_ANNONCE,
    TypeTacheAdminMeshCore.LOCAL_DECOUVRIR_CHEMIN,
})
TACHES_ADMIN_MESHCORE_LOCALES_ECRITURE = frozenset({
    TypeTacheAdminMeshCore.LOCAL_NOM,
    TypeTacheAdminMeshCore.LOCAL_POSITION,
    TypeTacheAdminMeshCore.LOCAL_PUISSANCE,
    TypeTacheAdminMeshCore.LOCAL_RADIO,
    TypeTacheAdminMeshCore.LOCAL_SUPPRIMER_CONTACT,
    TypeTacheAdminMeshCore.LOCAL_REINIT_CHEMIN,
})
TACHES_ADMIN_MESHCORE_LOCALES = TACHES_ADMIN_MESHCORE_LOCALES_LECTURE | TACHES_ADMIN_MESHCORE_LOCALES_ECRITURE


class TacheAdminMeshCore(EnvironmentScopedModel):
    """Une opération d'administration à distance sur un répéteur MeshCore, mise en file ici et
    exécutée par le pont (`meshcore-bridge/`).

    Même forme que `TacheAdminMeshtastic`, et pour les mêmes raisons : l'opération traverse la
    radio, elle met de quelques secondes à plusieurs minutes, et c'est le pont — pas Django —
    qui tient la connexion au companion.

    **Ce qui diffère de Meshtastic, et c'est l'essentiel :**

    1. **L'autorisation est un mot de passe ou une ACL, pas une clé posée sur l'appareil.** Les
       deux se testent (`send_login`, `req_status`), donc le droit d'écrire est subordonné à
       une preuve faite — voir `RattachementNoeudRadio.statut_preuve`. Sur Meshtastic, le
       firmware refusait de lui-même ; ici **il n'y a aucun filet** : qui a le mot de passe
       écrit.
    2. **Le firmware interdit déjà à distance** ce qui pourrait rendre le nœud injoignable
       (`erase`, `set freq`, `set prv.key`). Le risque résiduel d'une écriture est donc plus
       faible, et `RADIO_TEMPORAIRE` (`tempradio`) le réduit encore : les paramètres reviennent
       seuls au bout du délai.

    `reponse` est chiffrée au repos : un relevé de statut peut contenir la configuration du
    répéteur, et certaines réponses du firmware réaffichent des secrets."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Companion qui exécutera : c'est lui qui ouvre la session, et c'est SA clé publique que
    # l'ACL du répéteur doit contenir.
    compagnon = models.ForeignKey(
        CompagnonMeshCore, on_delete=models.CASCADE, related_name="taches_admin",
    )

    pubkey_cible = models.CharField(
        max_length=64,
        help_text="Clé publique du répéteur visé. Jamais vide, contrairement à Meshtastic : "
                  "le companion local se pilote par CommandeMeshCore, pas par cette file.",
    )

    type_tache = models.CharField(max_length=30, choices=TypeTacheAdminMeshCore.choices)

    # Paramètres, ex. {"cle": "advert.interval", "valeur": "240"} ou les cinq champs de
    # tempradio. Jamais de secret ici : les commandes qui en transportent sont absentes de
    # TypeTacheAdminMeshCore.
    parametres = models.JSONField(null=True, blank=True)

    statut = models.CharField(
        max_length=12, choices=StatutTacheAdminMeshtastic.choices,
        default=StatutTacheAdminMeshtastic.EN_ATTENTE,
        help_text="Mêmes états que la file Meshtastic : en avoir deux jeux pour une mécanique "
                  "identique ne ferait que créer des divergences.",
    )

    tentatives = models.PositiveSmallIntegerField(default=0)

    reponse = EncryptedTextField(null=True, blank=True)
    erreur = models.TextField(null=True, blank=True)

    demande_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="taches_admin_meshcore",
        help_text="Qui a demandé l'opération — une écriture sur un relais doit être imputable.",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_prise = models.DateTimeField(null=True, blank=True)
    date_reponse = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["statut", "compagnon"]),
            models.Index(fields=["-date_creation"]),
            models.Index(fields=["pubkey_cible"]),
        ]

    @property
    def est_ecriture(self):
        return (self.type_tache in TACHES_ADMIN_MESHCORE_ECRITURE
                or self.type_tache in TACHES_ADMIN_MESHCORE_LOCALES_ECRITURE)

    def __str__(self):
        return f"{self.get_type_tache_display()} -> {self.pubkey_cible[:12]} ({self.statut})"


class LiaisonMeshCore(EnvironmentScopedModel):
    """Liaison radio ORIENTÉE et observée côté MeshCore : `recepteur` a entendu `emetteur`.

    Jumelle de `LiaisonMeshtastic`, et le raisonnement est le même (voir sa docstring et
    `core/analyse_liaisons.py`) : une ligne par sens, agrégée, parce qu'à l'échelle d'un réseau
    départemental conserver chaque réception ferait des millions de lignes pour une information
    qui ne sert qu'agrégée.

    **Ce qui diffère, et qui est la difficulté propre à MeshCore** : l'émetteur n'est connu que
    par un **préfixe** de sa clé publique. `req_neighbours` rend `pubkey_prefix_length` octets
    par voisin, 4 par défaut — pas les 32 de la clé. On stocke donc le préfixe tel qu'il est
    venu, avec sa longueur, et la résolution vers un nœud connu est une opération séparée qui
    peut être ambiguë. Inventer une clé complète à partir d'un préfixe serait fabriquer une
    liaison qui n'existe pas.

    Le récepteur, lui, est connu entièrement : c'est le répéteur qu'on a interrogé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    emetteur_prefixe_hex = models.CharField(
        max_length=64,
        help_text="Préfixe de la clé publique du voisin entendu, tel que le répéteur l'a rendu.",
    )
    prefixe_octets = models.PositiveSmallIntegerField(
        default=4,
        help_text="Longueur du préfixe, en octets. 4 par défaut (pubkey_prefix_length). Deux "
                  "préfixes de longueurs différentes ne se comparent pas.",
    )

    recepteur_pubkey_hex = models.CharField(
        max_length=64,
        help_text="Clé publique COMPLÈTE du répéteur interrogé : c'est nous qui l'avons choisi.",
    )

    source = models.CharField(
        max_length=10, choices=SourceLiaisonMeshtastic.choices,
        default=SourceLiaisonMeshtastic.VOISINAGE,
        help_text="Mêmes sources que côté Meshtastic : un rapport de voisinage ne prouve pas "
                  "la même chose qu'une réception directe.",
    )

    snr = models.FloatField(null=True, blank=True)
    nombre = models.PositiveIntegerField(default=1)

    premier_vu = models.DateTimeField(auto_now_add=True)
    dernier_vu = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["emetteur_prefixe_hex", "recepteur_pubkey_hex", "source", "environment"],
                name="uq_liaison_meshcore_sens_source",
            ),
        ]
        indexes = [
            models.Index(fields=["-dernier_vu"]),
            models.Index(fields=["recepteur_pubkey_hex"]),
        ]

    def __str__(self):
        return f"{self.emetteur_prefixe_hex} -> {self.recepteur_pubkey_hex[:12]} ({self.source})"


class ReleveVoisinageMeshCore(EnvironmentScopedModel):
    """Dernier relevé de voisinage d'un répéteur : combien il en déclare, combien on en a reçu.

    Une ligne par répéteur, remplacée à chaque relevé — même choix que
    `ConfigurationNoeudMeshtastic` : on veut l'état courant du réseau, pas son historique.

    **Pourquoi cette table existe du tout.** L'analyse d'asymétrie a besoin de savoir si
    l'absence d'un voisin dans la liste est une PREUVE d'absence. Côté Meshtastic elle ne l'est
    jamais : le rapport de voisinage y est plafonné à 10 sans que rien ne le dise. Côté
    MeshCore, la réponse porte `neighbours_count` (le total chez le répéteur) et
    `results_count` (ce que contient cette page) : on peut donc SAVOIR, et c'est une
    information qu'il serait dommage de jeter."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    pubkey_hex = models.CharField(max_length=64)

    total_annonce = models.PositiveIntegerField(
        help_text="`neighbours_count` : ce que le répéteur dit avoir de voisins.",
    )
    recus = models.PositiveIntegerField(
        help_text="`results_count` cumulé des pages reçues.",
    )
    prefixe_octets = models.PositiveSmallIntegerField(default=4)

    date_releve = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pubkey_hex", "environment"], name="uq_releve_voisinage_meshcore_noeud",
            ),
        ]

    @property
    def complet(self):
        """Vrai quand on a reçu tout ce que le répéteur annonce.

        À faux, une absence ne prouve rien — exactement la précaution n° 3 de
        `analyse_liaisons.py`, mais ici fondée sur un décompte et non sur une supposition."""
        return self.recus >= self.total_annonce

    def __str__(self):
        return f"{self.pubkey_hex[:12]} : {self.recus}/{self.total_annonce} voisins"


class CompteurPaquetsMeshCore(EnvironmentScopedModel):
    """Trames MeshCore entendues par un récepteur (notre companion ou un observateur MQTT), par
    heure et par type de charge : la nature du trafic, comme côté Meshtastic (19/11/2026)."""
    recepteur_pubkey_hex = models.CharField(max_length=64)
    heure = models.DateTimeField()
    type_paquet = models.CharField(max_length=20)
    nombre = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["recepteur_pubkey_hex", "heure", "type_paquet", "environment"],
                                               name="uq_compteur_paquets_mc")]


class SourceObservateurMeshCore(EnvironmentScopedModel):
    """Un broker MQTT où des **observateurs** MeshCore republient ce qu'ils entendent.

    Un observateur est un répéteur ou un room server dont le firmware a reçu un client MQTT
    (`heltec_v4_repeater_observer_mqtt` et consorts). Ce n'est pas MeshCore : le firmware
    officiel ne contient aucun `mqtt`. Ils publient sur
    `meshcore/<iata>/<cle_observateur>/{packets,raw,status,neighbors}`, et le champ `raw` d'un
    message `packets` porte la trame hexadécimale — l'entrée de `core/decodeur_meshcore.py`.

    **Pourquoi une table plutôt qu'une variable d'environnement** : il y a plusieurs brokers
    (deux « analyzer » publics intégrés au firmware, plus les brokers privés), un exploitant
    peut n'ouvrir la lecture que sur un préfixe, et chacun a ses identifiants. Les déclarer en
    base permet d'en ajouter un sans redéployer le pont — même raisonnement que
    `CompagnonMeshtastic` pour les brokers Meshtastic.

    Le mot de passe est chiffré au repos, et servi au seul pont (`EstComptePont`) : c'est un
    identifiant d'accès à un service tiers, et le projet ne stocke rien de tel en clair."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nom = models.CharField(max_length=100)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True,
        related_name="sources_observateurs_meshcore",
    )

    broker_host = models.CharField(max_length=255)
    broker_port = models.PositiveIntegerField(default=1883)
    mqtt_username = models.CharField(max_length=100, blank=True)
    mqtt_password = EncryptedTextField(max_length=255, blank=True)
    mqtt_use_tls = models.BooleanField(default=False)

    # Filtre d'abonnement. Par défaut tout l'écosystème ; un exploitant qui ne nous ouvre qu'une
    # région donnera plutôt `meshcore/BOD/#`. Normalisé à l'enregistrement (voir le serializer)
    # parce qu'un filtre faux donne une connexion parfaite et zéro paquet -- la leçon du
    # 10/11/2026 côté Meshtastic.
    filtre_topic = models.CharField(
        max_length=200, default="meshcore/#",
        help_text="Filtre d'abonnement MQTT, ex. « meshcore/# » ou « meshcore/BOD/# ».",
    )
    # 19/11/2026 : deux sortes de sources. Un broker MQTT où les observateurs publient, ou le
    # flux temps réel d'une instance CoreScope (WebSocket à la racine du site, une observation
    # par message) — `broker_host` est alors l'adresse de l'instance.
    type_source = models.CharField(max_length=12, default="MQTT",
                                   choices=[("MQTT", "Broker MQTT"), ("CORESCOPE", "Flux temps réel CoreScope")])
    # 19/11/2026 : certains brokers de l'écosystème ne s'atteignent qu'en WebSocket sur 443
    # (mqtt.meshmapper.net, par exemple), à travers les pare-feu qui ne laissent passer que le web.
    mqtt_transport = models.CharField(
        max_length=12, default="tcp", choices=[("tcp", "TCP"), ("websockets", "WebSocket")],
    )
    mqtt_ws_chemin = models.CharField(max_length=100, default="/mqtt", blank=True,
                                      help_text="Chemin WebSocket, « /mqtt » le plus souvent.")

    actif = models.BooleanField(default=True)

    derniere_connexion = models.DateTimeField(null=True, blank=True)
    dernier_etat = models.CharField(max_length=20, null=True, blank=True)
    derniere_erreur = models.TextField(null=True, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker_host", "broker_port", "filtre_topic", "environment"],
                name="uq_source_observateur_meshcore",
            ),
        ]

    def __str__(self):
        return f"{self.nom} ({self.broker_host}:{self.broker_port})"


class NoeudPublicMeshCore(EnvironmentScopedModel):
    """Nœud du réseau MeshCore public, importé depuis une instance CoreScope.

    **Ce n'est pas une observation à nous.** `ContactMeshCore` dit « notre companion a entendu
    ce nœud » ; cette table dit « telle instance tierce le connaît ». Les confondre ferait
    entrer des nœuds qu'on n'a jamais entendus dans notre diagnostic de liaisons, et nos
    conclusions porteraient sur un réseau qu'on n'observe pas.

    **Répéteurs et rooms seulement.** Un `companion` est l'appareil personnel de quelqu'un et sa
    position est très souvent son domicile : importer les 707 companions que l'instance connaît
    reviendrait à importer 707 adresses de personnes qui n'ont rien demandé à Assista-Crise. Un
    répéteur, lui, est de l'infrastructure — un point haut, un pylône. C'est le même filtrage
    que la carte applique déjà à `ContactMeshCore`, et que la fédération applique à ses relais
    (`core/federation_carte_live.py`), pour la même raison.

    **La convention `🚫` est honorée** : un opérateur qui ne veut pas être affiché renomme son
    nœud avec ce préfixe, et les instances CoreScope le retirent de leurs réponses. Si l'une
    nous le servait quand même, on ne l'enregistre pas — republier ce que quelqu'un a demandé à
    cacher serait pire que de ne pas l'avoir.

    **Les données appartiennent à l'exploitant de l'instance**, pas à la licence du code
    (CoreScope est en GPL-3.0, ce qui ne dit rien de ce que son instance sert). Un import
    suppose son accord ; `instance` garde donc l'origine de chaque ligne, pour qu'on sache
    toujours à qui demander et quoi retirer.

    Les scores sont repris tels quels et non recalculés : ils viennent de ce que l'instance a
    réellement observé, sur un volume qu'on n'a pas. `coverage_score` est de la couverture
    **constatée**, pas un calcul de relief — c'est mieux, et c'est gratuit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    instance = models.CharField(
        max_length=255,
        help_text="Instance d'origine, ex. « https://meshstats.serveurperso.in ».",
    )
    pubkey_hex = models.CharField(max_length=64)

    nom = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, help_text="repeater ou room ; jamais companion.")

    location = gis_models.PointField(srid=4326, null=True, blank=True)

    premier_vu = models.DateTimeField(null=True, blank=True)
    dernier_vu = models.DateTimeField(null=True, blank=True)
    relais_actif = models.BooleanField(default=False)
    relais_24h = models.PositiveIntegerField(default=0)

    # Scores de l'instance, repris tels quels (0 à 1 pour les quatre premiers).
    score_couverture = models.FloatField(null=True, blank=True)
    score_redondance = models.FloatField(null=True, blank=True)
    score_pont = models.FloatField(null=True, blank=True)
    score_utilite = models.FloatField(null=True, blank=True)
    note_utilite = models.CharField(max_length=4, blank=True)

    # Taille du préfixe de hash que ce nœud utilise dans les chemins. À 1 octet, ses sauts sont
    # inexploitables comme preuve de topologie (256 valeurs) : voir core/resolution_prefixes.py.
    taille_hash = models.PositiveSmallIntegerField(null=True, blank=True)

    date_import = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "pubkey_hex", "environment"],
                name="uq_noeud_public_meshcore",
            ),
        ]
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["-dernier_vu"]),
        ]

    def __str__(self):
        return f"{self.nom or self.pubkey_hex[:12]} ({self.role})"


class MoyenAdminRadio(models.TextChoices):
    """Par quoi on est autorisé à administrer un nœud — c'est-à-dire ce qu'on remplit en le
    réclamant (demande du 10/11/2026 : « soit login / mot de passe, soit le répéteur contient la
    clé de xxx »).

    Les deux moyens viennent du firmware MeshCore, pas de nous
    (`examples/simple_repeater/MyMesh.cpp:92-104`) : un mot de passe vide fait vérifier que
    l'émetteur figure dans l'**ACL** du répéteur, sinon le mot de passe est comparé à celui de
    l'administrateur, puis à celui de l'invité.

    `AUCUN` est le cas d'un rattachement Meshtastic : l'autorisation n'y est pas un mot de passe
    mais la clé publique de la passerelle posée dans `security.admin_key` du nœud, qu'on ne peut
    ni lire ni vérifier à distance (voir TacheAdminMeshtastic)."""

    AUCUN = "AUCUN", "Aucun (Meshtastic : clé d'administration posée sur l'appareil)"
    MOT_DE_PASSE = "MOT_DE_PASSE", "Mot de passe d'administration du répéteur"
    ACL = "ACL", "Clé publique de notre companion inscrite dans l'ACL du répéteur"


class StatutPreuveRadio(models.TextChoices):
    """Où en est la démonstration qu'on contrôle vraiment ce nœud.

    Ce qui rend MeshCore différent : la preuve est **faisable**. Un mot de passe se teste avec
    `send_login`, une entrée d'ACL avec `req_status` — tous deux exposés par la bibliothèque
    `meshcore`. On n'accorde donc pas le droit d'écrire sur déclaration ; on le vérifie.

    `NON_VERIFIE` n'est pas un échec : c'est l'état d'un rattachement Meshtastic, où il n'y a
    rien à vérifier à distance, et celui d'un rattachement MeshCore qui vient d'être créé."""

    NON_VERIFIE = "NON_VERIFIE", "Pas encore vérifiée"
    EN_ATTENTE = "EN_ATTENTE", "Vérification en file"
    VERIFIEE = "VERIFIEE", "Contrôle démontré"
    ECHEC = "ECHEC", "Vérification refusée par le nœud"


class RattachementNoeudRadio(EnvironmentScopedModel):
    """« Ce nœud est à nous » — pour le matériel que personne ne porte.

    Comble le trou laissé par la règle du 10/11/2026 (le droit d'écrire suit la propriété) : un
    répéteur sur un château d'eau n'est le nœud personnel de personne, donc il n'était réglable
    que par un administrateur de la plateforme. Il fallait pouvoir le rattacher à une
    institution ou à un compte.

    **Pourquoi un modèle de plus, et pas un champ sur `NoeudUtilisateurMeshtastic` :** celui-là
    répond à une autre question. Il dit « ce nœud EST cette personne », et c'est de lui que le
    pont tire l'expéditeur d'un message reçu. Y rendre `utilisateur` facultatif pour y loger un
    répéteur aurait fait porter deux sens au même champ, et cassé la résolution d'expéditeur.
    Ici on ne dit pas qui est le nœud, on dit **qui en répond**.

    Les deux cibles sont facultatives mais il en faut au moins une (contrainte en base) : un
    rattachement qui ne rattache à rien ne protège ni n'autorise personne, il ne ferait que
    bloquer le `node_num` pour les autres.

    **Ce qu'un rattachement ne donne PAS.** Il ouvre le droit dans *notre* API ; le firmware,
    lui, continue d'exiger que la clé publique de la passerelle figure dans `security.admin_key`
    du nœud visé — ce qui suppose de l'avoir eu en main. Un rattachement abusif ne permet donc
    pas de reconfigurer le matériel d'autrui ; il permet d'essayer, et l'appareil refuse. C'est
    ce qui autorise à laisser un exploitant rattacher lui-même son matériel au lieu de réserver
    le geste à un administrateur, qui ne saurait pas de toute façon à qui appartient quoi.

    **MeshCore change la nature de la preuve** (10/11/2026). Sur Meshtastic, le rattachement est
    une déclaration que seul le firmware démentira. Sur MeshCore, les deux moyens d'administrer
    un répéteur sont *vérifiables à distance* : un mot de passe d'administration se teste avec
    `send_login`, une entrée d'ACL se teste avec `req_status`. Le droit ne s'accorde donc pas sur
    déclaration : on réclame le répéteur, on prouve qu'on le contrôle, et `statut_preuve` porte
    le résultat. Un rattachement MeshCore non vérifié n'ouvre aucune écriture."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Une identité, et une seule, selon le protocole. Meshtastic identifie par un entier 32
    # bits, MeshCore par une clé publique Ed25519 : aucun champ commun n'existe, et en
    # fabriquer un (« identifiant » texte) rendrait impossible la jointure avec
    # NoeudUtilisateurMeshtastic d'un côté et ContactMeshCore de l'autre.
    node_num = models.PositiveBigIntegerField(
        null=True, blank=True,
        help_text="Nœud Meshtastic visé. Unique : deux responsables pour un même appareil ne "
                  "veut rien dire, et c'est ce qui rend les conflits visibles plutôt que "
                  "silencieux.",
    )

    pubkey_hex = models.CharField(
        max_length=64, blank=True,
        help_text="Clé publique du nœud MeshCore visé (Ed25519, 64 caractères hexadécimaux).",
    )

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, null=True, blank=True,
        related_name="noeuds_radio_rattaches",
    )
    utilisateur = models.ForeignKey(
        "User", on_delete=models.CASCADE, null=True, blank=True,
        related_name="noeuds_radio_rattaches",
        help_text="Pour un répéteur qui appartient à une personne (un radioamateur qui en a "
                  "posé un chez lui) et non à une collectivité.",
    )

    libelle = EncryptedTextField(
        max_length=100, blank=True,
        help_text="Comment on l'appelle sur le terrain, ex. « répéteur du château d'eau » — "
                  "le nom annoncé par le firmware ne dit pas toujours où il est.",
    )
    note = EncryptedTextField(blank=True)

    # ── Comment on administre ce nœud, et la preuve qu'on le peut ──────────────
    moyen_admin = models.CharField(
        max_length=14, choices=MoyenAdminRadio.choices, default=MoyenAdminRadio.AUCUN,
    )

    # Mot de passe d'administration du répéteur MeshCore. Chiffré au repos : c'est la clé de
    # l'appareil, et le projet ne stocke rien de tel en clair. Jamais renvoyé par l'API
    # (write_only), et servi au seul pont (EstComptePont) comme les autres secrets radio.
    #
    # Pourquoi le stocker du tout : une tâche d'administration est mise en file et exécutée par
    # le pont des minutes plus tard, parfois après un réessai. Demander le mot de passe à chaque
    # opération supposerait qu'un humain soit là au moment de l'exécution, ce qui n'est pas le
    # cas. L'alternative -- le porter dans la ligne de tâche -- l'étalerait dans la file.
    mot_de_passe = EncryptedTextField(max_length=64, blank=True)

    # Par quel companion on parle à ce nœud. Nécessaire dans les deux cas : c'est ce companion
    # qui ouvre la session (mot de passe), et c'est SA clé publique qui doit figurer dans l'ACL
    # du répéteur (voie ACL).
    compagnon_meshcore = models.ForeignKey(
        CompagnonMeshCore, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="noeuds_administres",
    )

    statut_preuve = models.CharField(
        max_length=12, choices=StatutPreuveRadio.choices, default=StatutPreuveRadio.NON_VERIFIE,
    )
    date_verification = models.DateTimeField(null=True, blank=True)
    erreur_verification = models.TextField(blank=True)

    rattache_par = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rattachements_noeuds_radio_poses",
        help_text="Qui l'a rattaché — un rattachement ouvre un droit d'écriture, il doit être "
                  "imputable.",
    )
    date_rattachement = models.DateTimeField(auto_now_add=True)

    @property
    def preuve_faite(self):
        """Vrai quand le contrôle du nœud a été démontré.

        Un rattachement Meshtastic n'a rien à prouver : le firmware refusera de lui-même si la
        clé d'administration n'est pas posée (voir la docstring de la classe). Un rattachement
        MeshCore, lui, n'ouvre l'écriture qu'une fois la session ou l'ACL vérifiée."""
        if self.pubkey_hex:
            return self.statut_preuve == StatutPreuveRadio.VERIFIEE
        return True

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(institution__isnull=False) | models.Q(utilisateur__isnull=False),
                name="ck_rattachement_noeud_radio_une_cible",
            ),
            # Une identité et une seule : un node_num Meshtastic OU une clé publique MeshCore.
            # Les deux à la fois ne désignent pas un appareil, et aucune des deux n'en désigne
            # aucun -- dans les deux cas la ligne ne ferait que bloquer un identifiant.
            models.CheckConstraint(
                condition=(
                    models.Q(node_num__isnull=False) & models.Q(pubkey_hex="")
                    | models.Q(node_num__isnull=True) & ~models.Q(pubkey_hex="")
                ),
                name="ck_rattachement_noeud_radio_une_identite",
            ),
            # L'unicité du node_num était portée par le champ ; elle devient conditionnelle,
            # puisqu'une ligne MeshCore le laisse vide et que NULL n'entre pas dans un index
            # unique de la même façon selon les bases.
            models.UniqueConstraint(
                fields=["node_num"], condition=models.Q(node_num__isnull=False),
                name="uq_rattachement_noeud_radio_node_num",
            ),
            models.UniqueConstraint(
                fields=["pubkey_hex"], condition=~models.Q(pubkey_hex=""),
                name="uq_rattachement_noeud_radio_pubkey",
            ),
        ]
        indexes = [
            models.Index(fields=["institution"]),
            models.Index(fields=["utilisateur"]),
            models.Index(fields=["pubkey_hex"]),
        ]

    def __str__(self):
        cible = self.institution.nom if self.institution_id else (
            self.utilisateur.email if self.utilisateur_id else "?"
        )
        identite = (format(self.node_num, '08x') if self.node_num is not None
                    else self.pubkey_hex[:12])
        return f"{self.libelle or identite} — {cible}"


class StatutDemandeAccesRadio(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente d'instruction"
    ACCORDEE = "ACCORDEE", "Accordée"
    REFUSEE = "REFUSEE", "Refusée"
    RETIREE = "RETIREE", "Retirée"


class DemandeAccesRadio(models.Model):
    """Demande d'accès au domaine radio, et le droit lui-même quand elle est accordée.

    Une seule table pour les deux parce que le droit EST la demande instruite : séparer
    « demande » et « habilitation » obligerait à les garder cohérentes, et la question à
    laquelle il faut pouvoir répondre est « qui a obtenu ce droit, quand, accordé par qui, et
    au vu de quoi ? » -- c'est exactement une demande avec sa décision.

    Rien n'est jamais supprimé : un droit retiré passe en `RETIREE` avec son motif. Un retrait
    par effacement de ligne ferait disparaître la trace de ce qu'on avait accordé.

    **Pas un `EnvironmentScopedModel`, contrairement au reste du domaine radio.** Un droit radio
    porte sur du matériel réel, qui n'existe pas dans la zone de démonstration : le scoper
    aurait créé un droit DEMO sans objet, et obligé chaque lecture du niveau d'accès à connaître
    la zone de la requête. Le niveau se calcule donc sur les seules données PROD (voir
    core/acces_radio.py).

    Le niveau n'est **pas** le seul chemin vers le droit : posséder un nœud personnel actif
    l'ouvre aussi, sans demande. Cette table sert aux cas que le matériel ne prouve pas --
    typiquement l'agent d'une commune qui exploite la passerelle de la collectivité, ou
    l'opérateur à qui on confie la configuration de l'infrastructure."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="demandes_acces_radio",
        help_text="Le demandeur. Pas forcément un compte institutionnel : un bénévole qui "
                  "porte un nœud a besoin de le régler.",
    )

    niveau_demande = models.CharField(
        max_length=14, choices=NiveauAccesRadio.choices, default=NiveauAccesRadio.OPERATEUR,
    )

    # Ce que le demandeur déclare : matériel détenu, rattachement, usage prévu. C'est la seule
    # information dont dispose l'instructeur, elle est donc obligatoire à la création.
    motif = EncryptedTextField(
        help_text="Ce que le demandeur détient ou exploite comme matériel radio, et pour quoi "
                  "faire -- la seule pièce du dossier.",
    )

    statut = models.CharField(
        max_length=12, choices=StatutDemandeAccesRadio.choices,
        default=StatutDemandeAccesRadio.EN_ATTENTE,
    )

    niveau_accorde = models.CharField(
        max_length=14, choices=NiveauAccesRadio.choices, null=True, blank=True,
        help_text="Renseigné à l'octroi. Peut être inférieur au niveau demandé : accorder "
                  "OPERATEUR à qui demandait l'administration complète est une réponse "
                  "légitime, pas un refus.",
    )

    instruite_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="demandes_acces_radio_instruites",
        help_text="SET_NULL et non PROTECT : le droit reste valide si le compte instructeur "
                  "est supprimé, contrairement à une désignation nominative.",
    )
    commentaire_decision = EncryptedTextField(blank=True)

    date_demande = models.DateTimeField(auto_now_add=True)
    date_decision = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["utilisateur", "statut"]),
            models.Index(fields=["-date_demande"]),
        ]

    def __str__(self):
        return f"{self.utilisateur.email} — {self.statut} ({self.niveau_accorde or self.niveau_demande})"


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

    # Chiffré ; retrouvé par son empreinte exacte (`jeton_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    jeton = EncryptedTextField(max_length=64)
    jeton_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

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

    # Dernière fois que l'AGENT de mise à jour de ce satellite a interrogé le central. Vide =
    # le satellite n'a pas d'agent (installé avant le 14/11/2026 et jamais mis à jour depuis,
    # ou passerelle Windows) : lui adresser un ordre serait parler à personne, et l'écran ne
    # le propose donc pas.
    agent_mise_a_jour_vu = models.DateTimeField(null=True, blank=True)
    #: Les ordres que l'agent de ce satellite dit connaitre, tels qu'il les annonce a chaque
    #: passage. Vide = agent d'avant le 17/11/2026, qui ne sait que se mettre a jour.
    actions_agent = models.JSONField(default=list, blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} ({self.institution.nom}) — {self.statut_enrolement}"


class VersionSatellite(models.Model):
    """Une version que les satellites acceptent d'installer : un commit, et sa signature.

    **Le central ne fait que transmettre.** La signature est produite hors du serveur, avec une
    clé privée qui n'y est pas (voir `core/signature_satellites.py`) ; elle est vérifiée ici à
    la publication, puis une seconde fois par chaque satellite avec sa propre copie de la clé
    publique. Une ligne de cette table insérée à la main n'installerait donc rien.

    Ni le commit ni la signature ne sont des secrets : ils sont faits pour être montrés. Rien à
    chiffrer ici."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    commit = models.CharField(
        max_length=40, unique=True,
        help_text="Numéro de commit complet (40 caractères).",
    )
    libelle = models.CharField(
        max_length=120, blank=True,
        help_text="Ce que cette version apporte, en quelques mots. Affiché dans la liste.",
    )
    signature = models.TextField()

    publiee_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    date_publication = models.DateTimeField(auto_now_add=True)

    #: Retirée : plus proposée à l'installation. On ne supprime pas la ligne — les mises à jour
    #: déjà faites vers cette version doivent rester lisibles dans l'historique.
    retiree = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date_publication"]

    def __str__(self):
        return f"{self.commit[:10]} {self.libelle}".strip()


class StatutMiseAJour(models.TextChoices):
    DEMANDEE = "DEMANDEE", "Demandée"
    EN_COURS = "EN_COURS", "En cours"
    REUSSIE = "REUSSIE", "Réussie"
    ECHOUEE = "ECHOUEE", "Échouée"
    ANNULEE = "ANNULEE", "Annulée"
    EXPIREE = "EXPIREE", "Expirée"


class ActionSatellite(models.TextChoices):
    """Ce que le central peut demander à l'agent d'un satellite. Une liste fermée, sans
    paramètre : l'agent refuse tout mot qu'il ne connaît pas (satellite/agent_mise_a_jour.py)."""
    MISE_A_JOUR = "MISE_A_JOUR", "Mise à jour"
    # Regarder : rien de cela ne change la machine.
    BILAN = "BILAN", "Bilan complet"
    DIAGNOSTIC = "DIAGNOSTIC", "Diagnostic"
    JOURNAUX = "JOURNAUX", "Journaux de tous les services"
    MIGRATIONS = "MIGRATIONS", "État des migrations"
    SYSTEME = "SYSTEME", "État de la machine"
    RESEAU = "RESEAU", "État du réseau"
    DEPOT = "DEPOT", "État du code installé"
    # Agir : ce que ferait quelqu'un sur place, et rien d'autre.
    REDEMARRAGE = "REDEMARRAGE", "Redémarrage des services"
    MIGRER = "MIGRER", "Application des migrations"
    RECONSTRUCTION = "RECONSTRUCTION", "Reconstruction et redémarrage"
    NETTOYAGE = "NETTOYAGE", "Libération de place"
    SAUVEGARDE = "SAUVEGARDE", "Sauvegarde de la base"
    RESTAURATION = "RESTAURATION", "Retour à la version précédente"


class MiseAJourSatellite(models.Model):
    """Un ordre de mise à jour adressé à un satellite, et ce qu'il en est advenu.

    C'est le satellite qui vient le chercher (il initie toujours la connexion) : l'ordre attend
    donc son prochain passage, et expire s'il ne vient pas. Un seul ordre ouvert par satellite
    (contrainte ci-dessous) — deux mises à jour concurrentes sur une même machine se
    marcheraient dessus."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    satellite = models.ForeignKey(
        Satellite, on_delete=models.CASCADE, related_name="mises_a_jour",
    )
    #: Vide pour un diagnostic ou un redémarrage : ils ne font entrer aucune version.
    version = models.ForeignKey(
        VersionSatellite, on_delete=models.PROTECT, related_name="mises_a_jour",
        null=True, blank=True,
    )
    action = models.CharField(
        max_length=20, choices=ActionSatellite.choices, default=ActionSatellite.MISE_A_JOUR,
    )
    demandee_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    statut = models.CharField(
        max_length=10, choices=StatutMiseAJour.choices, default=StatutMiseAJour.DEMANDEE,
    )
    date_demande = models.DateTimeField(auto_now_add=True)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    #: Où en est le satellite, en clair : « Sauvegarde de la base », « Construction »…
    etape = models.CharField(max_length=200, blank=True)
    # Sorties des commandes lancées sur le satellite. Chiffré : un journal de construction ou
    # de démarrage peut citer des chemins, des noms de machine, des adresses du réseau local.
    journal = EncryptedTextField(blank=True)

    #: La version installée avant, telle que le satellite l'a rapportée : c'est vers elle qu'il
    #: faudrait revenir, et la retrouver après coup dans des journaux n'est pas un plan.
    version_avant = models.CharField(max_length=50, blank=True)

    #: L'ordre a été donné alors qu'une crise était en cours, en connaissance de cause.
    malgre_crise = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date_demande"]
        constraints = [
            models.UniqueConstraint(
                fields=["satellite"],
                condition=models.Q(statut__in=["DEMANDEE", "EN_COURS"]),
                name="uq_une_mise_a_jour_ouverte_par_satellite",
            ),
        ]

    def __str__(self):
        cible = self.version.commit[:10] if self.version_id else self.get_action_display().lower()
        return f"{self.satellite.nom} → {cible} ({self.statut})"


class ModeleSynchronisable(models.TextChoices):
    """Modèles synchronisés satellite -> central : Dossier (et son fil), DeclarationSecurite,
    Mission, et tout le domaine mesh observé sur place. Jamais Request/Offer/Information."""
    DOSSIER = "Dossier", "Dossier"
    DOSSIER_COMMENTAIRE = "DossierCommentaire", "Commentaire de dossier"
    DOSSIER_HISTORIQUE = "DossierHistorique", "Historique de dossier"
    DECLARATION_SECURITE = "DeclarationSecurite", "Déclaration de sécurité"
    MISSION = "Mission", "Mission"
    MESSAGE_MESH_LOG = "MessageMeshLog", "Message direct MeshCore"
    # Domaine mesh élargi le 06/11/2026 : un satellite observe du trafic radio que le central ne
    # voit pas (il est à l'autre bout du pays, voire à La Réunion), et seuls les DM MeshCore
    # remontaient. Les canaux figurent dans la liste parce qu'un satellite en crée localement --
    # le canal « Public » est auto-provisionné dès qu'un companion voit son trafic (voir
    # CompagnonMeshCoreViewSet.signaler_canaux_detectes) : sans eux, les messages de ce canal
    # arriveraient au central avec une FK introuvable. La file étant traitée dans l'ordre de
    # création (`order_by("cree_le")`), le canal précède toujours ses messages.
    CANAL_MESHCORE = "CanalMeshCore", "Canal MeshCore"
    CANAL_MESHTASTIC = "CanalMeshtastic", "Canal Meshtastic"
    MESSAGE_CANAL_MESHCORE = "MessageCanalMeshCore", "Message de canal MeshCore"
    MESSAGE_MESHTASTIC_LOG = "MessageMeshtasticLog", "Message direct Meshtastic"
    MESSAGE_CANAL_MESHTASTIC = "MessageCanalMeshtastic", "Message de canal Meshtastic"
    ALERTE_MESH_SOS = "AlerteMeshSOS", "Alerte SOS mesh"
    # Le stock tenu hors connexion (17/11/2026, core/sync_stock.py).
    DEPOT_STOCK = "DepotStock", "Dépôt de stock"
    ARTICLE_STOCK = "ArticleStock", "Article de stock"
    MOUVEMENT_STOCK = "MouvementStock", "Mouvement de stock"
    # L'évaluation des dégâts hors ligne (20/11/2026, core/evaluation_terrain.py).
    HABITATION = "Habitation", "Bien évalué"
    HABITATION_HISTORIQUE = "HabitationHistorique", "Historique d'un bien"
    HABITATION_COMMENTAIRE = "HabitationCommentaire", "Commentaire d'un bien"
    CONSTAT_TERRAIN = "ConstatTerrain", "Constat de terrain"
    TYPE_BIEN = "TypeBien", "Type de bien"


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
    payload = EncryptedJSONField()

    # modifie_le connu avant la première écriture hors ligne : détection de conflit côté central.
    # Null pour les modèles en ajout seul.
    version_de_base = models.DateTimeField(null=True, blank=True)

    # Auteur local réel (l'auteur apparent côté central est le compte du satellite).
    auteur_local_email = EncryptedEmailField(max_length=255, blank=True)
    auteur_local_nom = EncryptedTextField(max_length=255, blank=True)

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

    payload_local = EncryptedJSONField(help_text="Ce que le satellite tentait d'appliquer.")
    etat_central_au_conflit = EncryptedJSONField(
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



# ══════════════════════════════════════════════════════════════════════════════════════════════
# CAMPAGNES DE DISPONIBILITÉ
#
# Demande de Sylvain du 11/11/2026 : une association doit pouvoir solliciter en masse ses
# bénévoles pour une période à venir, sur critères, et que la PÉRIODE ENTRE EN BASE — « et pas
# seulement un texte libre dans le mail » — pour constituer les équipes en avance.
# ══════════════════════════════════════════════════════════════════════════════════════════════


class MotifCampagne(models.TextChoices):
    """Pourquoi on solliciter ses bénévoles. **Typé et non libre**, et c'est le cœur du sujet.

    Un texte libre ne permet ni de trier les campagnes passées, ni d'adapter le ton du message,
    ni de savoir plus tard si l'association a été sollicitée pour une crise qui n'est jamais
    arrivée. Les trois valeurs sont celles que Sylvain a nommées, et elles ne décrivent pas la
    même urgence : on ne demande pas la même chose avant, pendant et après."""

    CRISE_A_VENIR = "CRISE_A_VENIR", "Crise à venir (prévisions, vigilance)"
    CRISE_EN_COURS = "CRISE_EN_COURS", "Crise en cours"
    RETABLISSEMENT = "RETABLISSEMENT", "Rétablissement à long terme"
    EXERCICE = "EXERCICE", "Exercice ou formation"


class StatutCampagne(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    ENVOYEE = "ENVOYEE", "Envoyée"
    CLOTUREE = "CLOTUREE", "Clôturée"


class EchelonCiblage(models.TextChoices):
    """Étendue géographique de la sollicitation.

    `RAYON_CRISE` exige une crise rattachée : c'est le seul critère qui ne se déduit pas des
    codes de secteur du bénévole mais d'une distance réelle."""

    NATIONAL = "NATIONAL", "National"
    ZONE_DEFENSE = "ZONE_DEFENSE", "Zone de défense"
    REGION = "REGION", "Région"
    DEPARTEMENT = "DEPARTEMENT", "Département"
    COMMUNE = "COMMUNE", "Commune"
    RAYON_CRISE = "RAYON_CRISE", "Rayon autour de la crise"


class CampagneDisponibilite(EnvironmentScopedModel):
    """Sollicitation de masse : « êtes-vous disponible du X au Y ? ».

    **La période est une donnée, pas une phrase.** C'est la demande explicite de Sylvain : un
    mail qui dit « du 12 au 26 janvier » dans son corps ne permet pas de constituer les équipes
    en avance, parce que rien en base ne sait de quoi il parle. Ici, `periode_debut` et
    `periode_fin` bornent la grille que le bénévole voit, les créneaux qu'il déclare, et les
    rotations qu'on en tire.

    Les réponses, elles, ne créent **aucun** nouveau stockage de disponibilité : elles vont dans
    `DisponibiliteOffre`, le moteur unique que lit la constitution d'équipe. Une campagne est un
    moyen de faire remplir ce moteur, pas une source parallèle.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.CASCADE, related_name="campagnes_disponibilite",
    )
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campagnes_disponibilite_creees",
    )

    intitule = EncryptedTextField(
        max_length=200,
        help_text="Ce que l'association verra dans sa liste de campagnes. Jamais envoyé tel "
                   "quel au bénévole : le message a son propre texte.",
    )
    motif = models.CharField(max_length=20, choices=MotifCampagne.choices)

    # Texte d'explication, écrit par l'association et inséré dans le message. Chiffré : il
    # décrit une situation opérationnelle, parfois avant qu'elle soit publique (une vigilance
    # météo attendue, un dispositif préfectoral en préparation).
    texte = EncryptedTextField(
        blank=True,
        help_text="Le « pourquoi », écrit par l'association. Inséré dans le message à la place "
                   "du placeholder [TEXTE].",
    )

    crise = models.ForeignKey(
        "Crisis", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campagnes_disponibilite",
        help_text="Obligatoire pour un ciblage par rayon : c'est son point qui sert de centre.",
    )

    periode_debut = models.DateField()
    periode_fin = models.DateField()

    #: Créneaux sur lesquels on interroge. Vide = les quatre. Une permanence de nuit ne se
    #: demande pas en cochant « disponible » tout court, et interroger sur les quatre quand
    #: trois ne servent pas fait répondre à côté.
    creneaux = ArrayField(
        models.CharField(max_length=10, choices=Creneau.choices),
        blank=True, default=list,
    )

    # ── Critères de ciblage, figés à la création ────────────────────────────────────────────
    # Figés et non recalculés : la liste des destinataires doit rester celle à qui on a
    # réellement écrit. Un bénévole qui obtient son PSE1 la semaine suivante n'a pas reçu le
    # message, et prétendre le contraire dans le suivi serait un mensonge.
    echelon = models.CharField(
        max_length=15, choices=EchelonCiblage.choices, default=EchelonCiblage.NATIONAL,
    )
    #: Code du territoire visé selon l'échelon (code INSEE de commune/département/région, ou
    #: identifiant de zone de défense « ZD-SUD »). Vide pour NATIONAL et RAYON_CRISE.
    territoire_code = models.CharField(max_length=20, blank=True)
    rayon_km = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="RAYON_CRISE uniquement : distance au point de la crise.",
    )

    competences = models.ManyToManyField(
        "Competence", blank=True, related_name="campagnes_disponibilite",
        help_text="Le bénévole doit déclarer AU MOINS UNE de ces compétences. Vide = toutes.",
    )
    qualifications = models.ManyToManyField(
        "Qualification", blank=True, related_name="campagnes_disponibilite",
        help_text="Titres exigés : permis, diplômes. Le bénévole doit les avoir TOUS.",
    )
    #: Exige que les titres exigés soient vérifiés par l'encadrement et non périmés, et que
    #: l'aptitude du membre soit valide. C'est le « à jour » demandé : un PSE1 déclaré mais
    #: jamais contrôlé, ou expiré, ne vaut pas un PSE1.
    titres_a_jour = models.BooleanField(default=True)
    #: « Taper large » (demande de Sylvain du 14/11/2026) : inclure les membres dont le dossier
    #: informatique ne permet pas de vérifier les critères — pas de fiche, pas d'adresse, pas
    #: de compétence saisie, titres non enregistrés. Leur dossier peut être en règle sur le
    #: papier ; l'outil, lui, ne le sait pas encore. Voir `ciblage_benevoles.cibler_large`.
    ciblage_large = models.BooleanField(
        default=False,
        help_text="Inclut aussi les membres dont le dossier n'est pas à jour dans l'outil : "
                  "les critères n'écartent alors que ceux dont on sait qu'ils n'y répondent "
                  "pas.",
    )

    equipe = models.ForeignKey(
        "Team", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campagnes_disponibilite",
        help_text="Limite la sollicitation à cette équipe et à toutes celles en dessous.",
    )

    # ── Rotations ───────────────────────────────────────────────────────────────────────────
    #: Les tours de garde sont une OPTION, explicitement activée (demande de Sylvain du
    #: 12/11/2026). La première version s'en remettait à `effectif_cible = 0`, ce qui faisait
    #: dépendre une décision d'organisation d'un nombre laissé à zéro — personne ne lit un
    #: formulaire comme ça. Beaucoup de campagnes ne veulent d'ailleurs que recueillir des
    #: disponibilités : « qui peut venir la semaine prochaine ? » n'appelle aucun tour de garde.
    tours_de_garde = models.BooleanField(
        default=False,
        help_text="Active le découpage de la période en tours de garde et la proposition "
                   "d'affectations. Sans elle, la campagne recueille seulement des "
                   "disponibilités.",
    )

    duree_rotation_jours = models.PositiveSmallIntegerField(
        default=3,
        help_text="Longueur d'un tour de garde. Les rotations découpent la période par "
                   "tranches de cette durée.",
    )
    repos_min_jours = models.PositiveSmallIntegerField(
        default=2,
        help_text="Repos minimum entre deux tours pour une même personne.",
    )
    effectif_cible = models.PositiveSmallIntegerField(
        default=0,
        help_text="Combien de personnes par créneau et par rotation. N'a de sens qu'avec "
                   "`tours_de_garde`.",
    )

    #: Par quels canaux la campagne part (voir `core/canaux_campagne.py`). Plusieurs sont
    #: possibles : écrire par email ET par SMS double les chances d'être lu, et c'est ce que
    #: l'on fait quand la réponse est urgente — au prix du SMS, que l'écran annonce avant
    #: l'envoi. Email seul par défaut, parce que c'est le canal le moins cher et le seul qui
    #: porte un lien cliquable.
    canaux = models.JSONField(default=list, blank=True)

    statut = models.CharField(
        max_length=12, choices=StatutCampagne.choices, default=StatutCampagne.BROUILLON,
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_envoi = models.DateTimeField(null=True, blank=True)
    date_cloture = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation"]
        constraints = [
            # `condition` et non `check` : ce dernier est déprécié depuis Django 5.1 et
            # disparaît en 6.0. Autant ne pas semer un avertissement dans toute la suite.
            models.CheckConstraint(
                condition=models.Q(periode_fin__gte=models.F("periode_debut")),
                name="ck_campagne_periode_coherente",
            ),
        ]

    def __str__(self):
        return f"{self.intitule} ({self.periode_debut} → {self.periode_fin})"

    @property
    def canaux_effectifs(self):
        """Les canaux retenus, la liste vide valant « email seul ».

        Même parti pris que `creneaux_effectifs` : une campagne créée avant l'ajout des
        canaux, ou enregistrée sans y toucher, continue de partir comme avant."""
        from .canaux_campagne import CANAL_EMAIL

        return list(self.canaux) if self.canaux else [CANAL_EMAIL]

    @property
    def creneaux_effectifs(self):
        """Les créneaux interrogés, la liste vide valant « les quatre »."""
        return list(self.creneaux) if self.creneaux else list(Creneau.values)

    @property
    def nombre_de_jours(self):
        return (self.periode_fin - self.periode_debut).days + 1


class EtatCible(models.TextChoices):
    A_CONTACTER = "A_CONTACTER", "À contacter"
    CONTACTE = "CONTACTE", "Contacté"
    A_REPONDU = "A_REPONDU", "A répondu"
    INJOIGNABLE = "INJOIGNABLE", "Envoi impossible"


class CibleCampagne(EnvironmentScopedModel):
    """Un bénévole retenu par les critères d'une campagne, et ce qu'il en a fait.

    **Pourquoi matérialiser la cible** plutôt que rejouer les critères à la lecture : les
    critères évoluent (un titre obtenu, un déménagement), et le suivi doit rester celui des gens
    à qui on a **réellement** écrit. Sans cette table, « 12 sans réponse » changerait de sens
    d'un jour à l'autre, et relancer les silencieux deviendrait impossible.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    campagne = models.ForeignKey(
        CampagneDisponibilite, on_delete=models.CASCADE, related_name="cibles",
    )
    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="cibles_campagne",
    )
    #: La ressource du bénévole au moment du ciblage : c'est elle qui porte les créneaux.
    ressource = models.ForeignKey(
        "Offer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cibles_campagne",
    )

    etat = models.CharField(
        max_length=12, choices=EtatCible.choices, default=EtatCible.A_CONTACTER,
    )
    date_envoi = models.DateTimeField(null=True, blank=True)
    date_reponse = models.DateTimeField(null=True, blank=True)
    #: Combien de créneaux la personne a déclarés DANS la période, au moment de sa réponse.
    #: Zéro est une réponse : « je ne suis pas disponible » n'est pas un silence, et les
    #: confondre ferait relancer quelqu'un qui a déjà répondu non.
    creneaux_declares = models.PositiveSmallIntegerField(default=0)
    erreur = EncryptedTextField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campagne", "utilisateur"], name="uq_cible_campagne_utilisateur",
            ),
        ]
        ordering = ["utilisateur_id"]   # les noms sont chiffrés : triés en Python à l'affichage

    def __str__(self):
        return f"{self.utilisateur.email} — {self.campagne.intitule} ({self.etat})"


class RotationCampagne(EnvironmentScopedModel):
    """Un tour de garde : une tranche de la période, à armer.

    Découpée mécaniquement par `duree_rotation_jours` : c'est ce qui empêche qu'un bénévole
    reste mobilisé toute la période, demande explicite de Sylvain."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    campagne = models.ForeignKey(
        CampagneDisponibilite, on_delete=models.CASCADE, related_name="rotations",
    )
    numero = models.PositiveSmallIntegerField()
    date_debut = models.DateField()
    date_fin = models.DateField()

    class Meta:
        ordering = ["campagne", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["campagne", "numero"], name="uq_rotation_campagne_numero",
            ),
        ]

    def __str__(self):
        return f"Rotation {self.numero} ({self.date_debut} → {self.date_fin})"


class StatutAffectationRotation(models.TextChoices):
    PROPOSEE = "PROPOSEE", "Proposée par le planificateur"
    CONFIRMEE = "CONFIRMEE", "Confirmée par l'encadrement"
    RETIREE = "RETIREE", "Retirée"


class StatutCreneauEquipe(models.TextChoices):
    """Où en est un créneau du planning. Cinq valeurs, et les trois dernières sont ce qui
    distingue un planning d'une intention : savoir qui a réellement tenu son poste."""

    PREVU = "PREVU", "Prévu"
    CONFIRME = "CONFIRME", "Confirmé"
    ANNULE = "ANNULE", "Annulé"
    REALISE = "REALISE", "Réalisé"
    ABSENT = "ABSENT", "Absent (ne s'est pas présenté)"


class CreneauEquipe(EnvironmentScopedModel):
    """Le planning d'une équipe : qui tient quel créneau, quel jour.

    **Pourquoi cette table existe, alors que trois autres parlent déjà de créneaux.** Chacune
    répond à une question différente, et les confondre produisait exactement l'erreur qu'on
    voulait éviter :

    | Table | Question |
    |---|---|
    | `DisponibiliteOffre` | « quand cette personne PEUT-elle venir ? » — une déclaration du bénévole, jamais une affectation |
    | `AffectationRotation` | « qui arme ce tour de garde de CETTE campagne ? » — maille rotation, pas jour, et n'existe que si la campagne a des tours de garde |
    | `DisponibilitePointEquipe` | « qui tient CE point opérationnel ? » — clé sur un point, pas sur une équipe |
    | `CreneauEquipe` | « qui tient le soir du 14 pour cette équipe ? » |

    Avant le 12/11/2026, la dernière ligne n'avait pas de réponse : pointer un créneau à la
    main dans la grille de l'association ne laissait qu'une trace au journal d'audit, hors
    campagne. Demande de Sylvain : « vas-y, prévois le planning d'équipe et tout le
    nécessaire ».

    **Un créneau n'est pas une disponibilité.** On peut affecter quelqu'un sur un créneau qu'il
    n'a pas déclaré : un chef d'équipe a le droit d'appeler. L'écart est **signalé** (voir
    `core/planning_equipe.py`), jamais bloqué — l'interdire supposerait que la grille déclarée
    est exhaustive, ce qu'elle n'est pas.

    **Le double engagement, en revanche, est un vrai problème** : la même personne sur deux
    équipes au même créneau n'est pas un oubli de saisie, c'est quelqu'un qu'on attend à deux
    endroits. L'API le détecte et le nomme à chaque écriture.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    equipe = models.ForeignKey(
        "Team", on_delete=models.CASCADE, related_name="creneaux_planning",
    )
    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="creneaux_equipe",
    )

    date = models.DateField()
    creneau = models.CharField(max_length=10, choices=Creneau.choices)

    statut = models.CharField(
        max_length=10, choices=StatutCreneauEquipe.choices,
        default=StatutCreneauEquipe.PREVU,
    )

    #: Ce que la personne fait sur ce créneau, quand ce n'est pas évident. Texte libre : les
    #: rôles opérationnels (`RoleOperationnel`) décrivent une qualité durable, pas ce qu'on
    #: tient un samedi soir.
    role = EncryptedTextField(max_length=100, blank=True, default="")

    #: Où. Un planning sans lieu laisse appeler pour demander où se présenter.
    point = models.ForeignKey(
        "PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="creneaux_equipe",
    )
    mission = models.ForeignKey(
        "Mission", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="creneaux_equipe",
    )
    #: Rattachement direct à la crise, pour les bilans. Redondant avec `mission.crise` quand
    #: une mission est posée, mais un créneau peut exister sans mission (une permanence).
    crise = models.ForeignKey(
        "Crisis", on_delete=models.CASCADE, null=True, blank=True,
        related_name="creneaux_equipe",
    )

    commentaire = EncryptedTextField(blank=True, null=True)

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "creneau"]
        constraints = [
            # Une personne ne tient qu'une fois le même créneau pour la même équipe. Deux
            # lignes identiques feraient compter deux présents là où il n'y en a qu'un.
            models.UniqueConstraint(
                fields=["equipe", "utilisateur", "date", "creneau"],
                name="uq_creneau_equipe",
            ),
        ]
        indexes = [
            # Le planning se lit toujours par équipe et par fenêtre de dates.
            models.Index(fields=["equipe", "date"], name="ix_creneau_equipe_date"),
            # …et la détection de double engagement, par personne et par date.
            models.Index(fields=["utilisateur", "date"], name="ix_creneau_perso_date"),
        ]

    def __str__(self) -> str:
        return f"{self.equipe.name} — {self.date} {self.creneau} ({self.statut})"

    @property
    def compte_dans_leffectif(self) -> bool:
        """Les annulés et les absents ne tiennent pas le poste.

        C'est la seule définition qui rende l'effectif d'un créneau utilisable : compter une
        ligne annulée ferait croire une garde armée."""
        return self.statut not in (StatutCreneauEquipe.ANNULE, StatutCreneauEquipe.ABSENT)


class AffectationRotation(EnvironmentScopedModel):
    """Qui tient quel créneau de quel tour de garde.

    `PROPOSEE` par défaut : le planificateur **propose**, l'encadrement tranche. Une affectation
    générée automatiquement et présentée comme acquise ferait partir une garde sur un calcul que
    personne n'a relu — et le planificateur ne connaît ni les brouilles, ni les trajets, ni ce
    qui s'est dit au téléphone.

    Une régénération efface les `PROPOSEE` et **garde les `CONFIRMEE`** : sinon chaque
    recalcul détruirait les décisions prises."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rotation = models.ForeignKey(
        RotationCampagne, on_delete=models.CASCADE, related_name="affectations",
    )
    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="affectations_rotation",
    )
    creneau = models.CharField(max_length=10, choices=Creneau.choices)
    statut = models.CharField(
        max_length=10, choices=StatutAffectationRotation.choices,
        default=StatutAffectationRotation.PROPOSEE,
    )
    #: Pourquoi le planificateur a retenu cette personne. Affiché tel quel : une proposition
    #: qu'on ne peut pas expliquer ne se relit pas, elle se subit.
    motif = EncryptedTextField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rotation", "utilisateur", "creneau"],
                name="uq_affectation_rotation",
            ),
        ]
        ordering = ["rotation", "creneau"]

    def __str__(self):
        return f"{self.utilisateur.email} — {self.rotation} ({self.creneau})"


# ═══════════════════════════════════════════════════════════════════════════════════════════
# APPLICATION MOBILE : APPAREILS ET NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════════════════
#
# Demande de Sylvain du 14/11/2026 : que la messagerie de l'application devienne un moyen de
# mobiliser, « avec un feedback de qui a eu la notif, vu, lu, répondu (une réponse négative est
# une réponse) ».
#
# Ce que les autres canaux ne savent pas dire : un email parti n'est pas un email lu, un SMS
# remis n'est pas un SMS compris. L'application, elle, sait à chaque étape où en est la
# personne — et c'est ce qui permet de relancer par SMS, payant, les seuls que l'application
# n'a pas atteints.


class PlateformeMobile(models.TextChoices):
    ANDROID = "ANDROID", "Android"
    IOS = "IOS", "iPhone"


class AppareilMobile(models.Model):
    """Un téléphone sur lequel une personne a ouvert l'application.

    Sert à une seule question : « l'application peut-elle joindre cette personne ? ». Sans
    cette table, le canal « Application » d'une campagne annoncerait une portée inventée —
    exactement le piège que `canaux_campagne` refuse pour Matrix.

    Aucun identifiant matériel : `installation` est tiré au hasard par l'application à son
    premier lancement, et disparaît avec elle. Pas scopé par environnement : c'est le compte
    qui est joignable, pas ses données.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="appareils_mobiles",
    )
    installation = models.CharField(max_length=64, unique=True)
    plateforme = models.CharField(
        max_length=10, choices=PlateformeMobile.choices, default=PlateformeMobile.ANDROID,
    )
    version = models.CharField(max_length=20, blank=True)
    #: La personne a-t-elle laissé le système afficher nos notifications ? Refusé, le message
    #: attend dans l'application qu'elle l'ouvre : « reçu » ne voudra pas dire « prévenu ».
    notifications_autorisees = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    dernier_contact = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-dernier_contact"]

    def __str__(self):
        return f"{self.utilisateur_id} — {self.plateforme} {self.version}"


class GenreNotification(models.TextChoices):
    CAMPAGNE = "CAMPAGNE", "Demande de disponibilités"
    AFFECTATION = "AFFECTATION", "Tour de garde"
    JUSTIFICATIF = "JUSTIFICATIF", "Justificatif"
    INFORMATION = "INFORMATION", "Information"


class NotificationApplication(EnvironmentScopedModel):
    """Un message adressé à UNE personne dans l'application, et ce qu'il est devenu.

    Quatre étapes datées, dans l'ordre où elles arrivent :

    | Étape | Ce qu'elle atteste |
    |---|---|
    | `date_remise` | le téléphone l'a reçu et a affiché la notification du système |
    | `date_vue` | la personne a ouvert l'application et l'a eu sous les yeux, dans la liste |
    | `date_lue` | elle l'a ouvert |
    | `date_reponse` | elle a répondu — oui OU non (`CibleCampagne` porte le contenu) |

    Chacune n'est écrite qu'une fois : la première remise est la vraie, et réécrire la date
    à chaque relecture ferait croire qu'un message vieux de trois jours vient d'arriver.

    Titre et corps sont chiffrés : ils reprennent le texte d'une campagne, qui décrit une
    situation opérationnelle parfois avant qu'elle soit publique.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications_application",
    )
    genre = models.CharField(max_length=15, choices=GenreNotification.choices)
    titre = EncryptedTextField()
    corps = EncryptedTextField(blank=True)
    urgent = models.BooleanField(default=False)

    institution = models.ForeignKey(
        "Institution", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications_application",
    )
    campagne = models.ForeignKey(
        CampagneDisponibilite, on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications_application",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_remise = models.DateTimeField(null=True, blank=True)
    date_vue = models.DateTimeField(null=True, blank=True)
    date_lue = models.DateTimeField(null=True, blank=True)
    date_reponse = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [
            models.Index(fields=["utilisateur", "-date_creation"],
                         name="ix_notif_app_utilisateur"),
        ]

    def __str__(self):
        return f"{self.genre} → {self.utilisateur_id} ({self.date_creation:%d/%m %H:%M})"


# ── Protection de la connexion (15/11/2026) ───────────────────────────────────────────────────
#
# Trois tables, toutes locales à la machine : aucune n'est synchronisée vers ou depuis un
# satellite (décision de Sylvain : pas de code à usage unique sur un satellite coupé d'Internet,
# donc aucun secret n'y est copié). Logique dans `core/second_facteur.py` et
# `core/frein_connexion.py`.

class SecondFacteur(models.Model):
    """Le secret du code à usage unique (TOTP, RFC 6238) d'un compte.

    `confirme_le` vide = préparé mais pas encore actif : le titulaire a vu le secret, il n'a pas
    encore prouvé que son application d'authentification le connaît. Tant que c'est le cas, la
    connexion ne demande aucun code."""
    utilisateur = models.OneToOneField(User, on_delete=models.CASCADE, related_name="second_facteur")
    # Chiffré au repos : qui lit la base ne doit pas pouvoir fabriquer des codes.
    secret = EncryptedTextField()
    cree_le = models.DateTimeField(auto_now_add=True)
    confirme_le = models.DateTimeField(null=True, blank=True)
    # Dernier pas de 30 s accepté : un code n'est jamais accepté deux fois, même dans sa
    # fenêtre de validité (quelqu'un qui le lit par-dessus l'épaule ne peut pas le rejouer).
    dernier_pas = models.BigIntegerField(default=0)

    # D'où vient le code (15/11/2026, demande de Sylvain) : d'une application d'authentification
    # sur le téléphone, ou d'un e-mail envoyé par le central à chaque connexion. En mode
    # e-mail il n'y a pas de secret : `secret` est vide, et le code du moment est ci-dessous.
    MODE_APPLICATION = "APPLICATION"
    MODE_EMAIL = "EMAIL"
    mode = models.CharField(
        max_length=12, default=MODE_APPLICATION,
        choices=[(MODE_APPLICATION, "Application d'authentification"), (MODE_EMAIL, "Code par e-mail")],
    )
    # Le code envoyé par e-mail : son empreinte seulement, cinq minutes, cinq essais, une fois.
    code_mail_empreinte = models.CharField(max_length=64, blank=True, default="")
    code_mail_expire_le = models.DateTimeField(null=True, blank=True)
    code_mail_essais = models.PositiveSmallIntegerField(default=0)
    code_mail_envoye_le = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Second facteur de {self.utilisateur_id} ({'actif' if self.confirme_le else 'en préparation'})"


class CodeSecours(models.Model):
    """Un code de secours à usage unique, pour qui a perdu son téléphone.

    Seule son empreinte est gardée (HMAC avec la clé du serveur) : le code n'est montré qu'une
    fois, à sa création."""
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="codes_secours")
    empreinte = models.CharField(max_length=64, db_index=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    utilise_le = models.DateTimeField(null=True, blank=True)


class FreinConnexion(models.Model):
    """Le compteur d'échecs d'une étape de connexion pour un compte.

    `cle` est une empreinte (HMAC) de l'étape, de l'adresse saisie et, le cas échéant, de
    l'appareil : ni l'adresse ni l'appareil ne sont lisibles ici, et une adresse qui ne
    correspond à aucun compte a son compteur comme les autres — sans quoi le frein dirait qui
    est inscrit."""
    cle = models.CharField(max_length=64, unique=True)
    echecs = models.PositiveIntegerField(default=0)
    dernier_echec = models.DateTimeField(null=True, blank=True)
    bloque_jusqua = models.DateTimeField(null=True, blank=True)


class CompteurInscription(models.Model):
    """Les compteurs de la création de compte (voir core/defi_inscription.py) : inscriptions
    venues d'une même adresse dans l'heure, défis déjà utilisés, niveau imposé à la main.

    `cle` est une empreinte (HMAC) : ni l'adresse IP ni la signature du navigateur ne sont
    lisibles ici. Chaque ligne porte son échéance et s'efface d'elle-même."""
    cle = models.CharField(max_length=64, unique=True)
    nombre = models.PositiveIntegerField(default=0)
    expire_le = models.DateTimeField(db_index=True)


class AppareilConnu(models.Model):
    """Un appareil (navigateur, téléphone) depuis lequel ce compte s'est déjà connecté.

    Sert à une chose : un appareil connu a son propre compteur d'échecs. Sans cela, quiconque
    connaît l'adresse d'un maire pourrait, en ratant exprès des connexions, l'empêcher d'entrer
    en pleine crise. Un appareil connu ne dispense de rien d'autre : ni du mot de passe, ni du
    code."""
    utilisateur = models.ForeignKey(User, on_delete=models.CASCADE, related_name="appareils_connus")
    # Empreinte du jeton que garde l'appareil ; le jeton lui-même n'est jamais stocké.
    empreinte = models.CharField(max_length=64)
    libelle = EncryptedTextField(blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    dernier_usage = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "empreinte"], name="uq_appareil_connu"),
        ]


class TypeBienSinistre(models.TextChoices):
    VEHICULE = "VEHICULE", "Véhicule (voiture, utilitaire, camion)"
    DEUX_ROUES = "DEUX_ROUES", "Deux-roues"
    BATEAU = "BATEAU", "Bateau"
    CARAVANE = "CARAVANE", "Caravane, camping-car, mobil-home"
    ENGIN = "ENGIN", "Engin, matériel agricole ou de chantier"
    BATIMENT_AGRICOLE = "BATIMENT_AGRICOLE", "Bâtiment agricole, hangar, annexe"
    COMMERCE = "COMMERCE", "Commerce, local professionnel"
    MOBILIER_URBAIN = "MOBILIER_URBAIN", "Voirie, mobilier urbain, réseau"
    AUTRE = "AUTRE", "Autre bien"


class BienSinistre(EnvironmentScopedModel):
    """Un bien sinistré qui n'est pas une habitation : les voitures brûlées d'un feu de forêt,
    un bateau, un hangar, du matériel, de la voirie.

    `Habitation` suit les maisons, adresse par adresse. Tout le reste n'a pas d'adresse à soi,
    se décrit autrement (une immatriculation, un numéro de série) et appartient souvent à
    quelqu'un qu'on ne connaît pas sur le moment. On relève donc ce qu'on voit -- ce que c'est,
    où c'est, ce qui l'a touché, les photos (`Document.bien`) -- et l'on complète le propriétaire
    plus tard, pour lui remettre le dossier (core/rapports_pdf.py).

    Chiffrés : l'identification (une immatriculation désigne une personne), le lieu saisi et les
    coordonnées du propriétaire. Les mêmes états et causes de dommage que pour une habitation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="biens_sinistres")
    institution = models.ForeignKey("Institution", on_delete=models.PROTECT, null=True, blank=True, related_name="biens_sinistres",
                                    help_text="La collectivité qui a relevé le bien.")
    type_bien = models.CharField(max_length=30, choices=TypeBienSinistre.choices, default=TypeBienSinistre.VEHICULE)
    designation = EncryptedTextField(max_length=200, help_text="Ce que c'est, en clair : « Renault Clio grise ».")
    identification = EncryptedTextField(blank=True, default="", help_text="Immatriculation, numéro de série, de coque…")
    description = EncryptedTextField(blank=True, default="")
    adresse = EncryptedTextField(blank=True, default="", help_text="Adresse ou repère : « devant le 14 allée des Pins ».")
    commune_code = models.CharField(max_length=10, blank=True, null=True)
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    nature_degats = models.CharField(max_length=20, choices=NatureDegatsHabitation.choices, blank=True, default="")
    statut_evaluation = models.CharField(max_length=20, choices=StatutEvaluationHabitation.choices,
                                         default=StatutEvaluationHabitation.DEGATS_FORTS)
    proprietaire_nom = EncryptedTextField(blank=True, default="")
    proprietaire_email = EncryptedTextField(blank=True, default="")
    proprietaire_telephone = EncryptedTextField(blank=True, default="")
    rapport_envoye_le = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="biens_sinistres_releves")
    date_creation = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return self.designation


class RapportConserve(EnvironmentScopedModel):
    """Un rapport PDF gardé sur le serveur jusqu'à la clôture de sa crise (core/cloture_crise.py).

    Chiffré sur le disque, comme les autres fichiers sensibles : il porte des noms, des adresses
    et des photos de biens privés. On garde la dernière édition de chaque rapport ; `effacer`
    retire le fichier ET la ligne, parce que supprimer une ligne ne supprime pas son fichier."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    #: « dossier », « mission », « crise » ou « bien ».
    nature = models.CharField(max_length=20)
    objet_id = models.UUIDField()
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, null=True, blank=True, related_name="rapports_conserves")
    #: Pour un rapport de crise : la collectivité dont c'est le point de vue.
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, null=True, blank=True, related_name="rapports_conserves")
    fichier = models.FileField(storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255)
    sha256 = models.CharField(max_length=64)
    taille = models.PositiveIntegerField(default=0)
    toutes_les_photos = models.BooleanField(default=False)
    edite_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="rapports_edites")
    date_edition = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_edition"]
        indexes = [models.Index(fields=["nature", "objet_id"])]

    def effacer(self):
        if self.fichier:
            self.fichier.delete(save=False)
        self.delete()


class DemandeRapport(EnvironmentScopedModel):
    """Le lien personnel envoyé par courriel quand la clôture d'une crise est proposée : il
    permet à la personne de se faire envoyer SON rapport, à l'adresse où le lien est parti.

    Un lien par personne et par rapport. Il ne donne accès à rien d'autre, et disparaît avec la
    clôture. L'adresse est chiffrée, comme partout."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crise = models.ForeignKey("Crisis", on_delete=models.CASCADE, related_name="demandes_rapport")
    nature = models.CharField(max_length=20)       # « dossier » ou « bien »
    objet_id = models.UUIDField()
    email = EncryptedTextField()
    role = models.CharField(max_length=20, blank=True, default="")      # BENEFICIAIRE, PARTICIPANT, PROPRIETAIRE
    # Chiffré ; retrouvé par son empreinte exacte (`jeton_empreinte`, remplie avant
    # chaque enregistrement) : un jeton en clair en base vaut le lien lui-même.
    jeton = EncryptedTextField(max_length=64)
    jeton_empreinte = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    nb_envois = models.PositiveIntegerField(default=0)
    envois_du_jour = models.PositiveIntegerField(default=0)
    dernier_envoi = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)


class DepotStock(EnvironmentScopedModel):
    """Un lieu où une institution range son stock permanent : local, garage, armoire, véhicule
    — ou un site de la commune qui sert aussi à autre chose : le gymnase, l'atelier municipal
    (voir core/stocks.py). Distinct d'un point opérationnel, qui n'existe que le temps d'une
    crise ; mais un point peut s'INSTALLER dans ce lieu (`PointOperationnel.lieu_de_stock`) et
    travailler alors directement sur son stock."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="depots_stock")
    nom = models.CharField(max_length=120)
    adresse = EncryptedTextField(blank=True, default="")
    location = gis_models.PointField(srid=4326, null=True, blank=True)
    commentaire = EncryptedTextField(blank=True, default="")
    #: Renseigné quand ce « dépôt » est le stock d'un point d'accueil ou de regroupement pendant
    #: une crise : le point devient un lieu de stock comme un autre, avec ses mouvements — on le
    #: dote depuis un dépôt, on y distribue, on en rapatrie le reste (voir core/stocks.py).
    point = models.ForeignKey("PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True, related_name="depots_stock")
    #: Moyens du lieu pour les denrées. Pour le dépôt d'un point d'accueil, ce sont ceux du point
    #: qui font foi (voir `moyens`).
    froid_positif = models.BooleanField(default=False)
    froid_negatif = models.BooleanField(default=False)
    cuisson = models.CharField(max_length=12, choices=CuissonLieu.choices, default=CuissonLieu.AUCUNE)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "point"], condition=models.Q(point__isnull=False),
                                    name="uq_depotstock_institution_point"),
        ]

    def __str__(self) -> str:
        return self.nom

    @property
    def moyens(self):
        """Le lieu qui dit ce qu'on peut y garder et y préparer : le point d'accueil, sinon le dépôt."""
        return self.point if self.point_id else self


class ArticleStock(EnvironmentScopedModel):
    """Ce qu'une institution tient en stock. Ne porte AUCUNE quantité : elle se déduit des
    mouvements (voir core/stocks.py)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="articles_stock")
    reference = models.CharField(max_length=60)
    designation = models.CharField(max_length=200)
    categorie = models.CharField(max_length=30, choices=MaterielCatalogueCategorie.choices, blank=True, default="")
    #: Le même objet dans le vocabulaire des centres de crise, pour doter un point depuis le stock.
    catalogue = models.ForeignKey(MaterielCatalogue, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles_stock")
    unite = models.CharField(max_length=20, default="unité")
    seuil_alerte = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                       help_text="Stock total en deçà duquel l'article est signalé. Vide : pas d'alerte.")
    perissable = models.BooleanField(default=False)
    #: Denrées : comment la garder, et ce qu'il faut pour qu'elle soit consommable.
    conservation = models.CharField(max_length=8, choices=ConservationStock.choices, default=ConservationStock.AMBIANT)
    preparation = models.CharField(max_length=12, choices=PreparationStock.choices, blank=True, default="",
                                   help_text="Vide : ce n'est pas une denrée.")
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True,
                                        help_text="Coût moyen pondéré, recalculé aux entrées valorisées. Indicatif.")
    code_barres = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["designation"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "environment", "reference"], name="uq_articlestock_reference"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.designation}"


class TypeMouvementStock(models.TextChoices):
    ENTREE = "ENTREE", "Entrée"
    SORTIE = "SORTIE", "Sortie"
    TRANSFERT = "TRANSFERT", "Transfert"
    INVENTAIRE = "INVENTAIRE", "Inventaire"


class MouvementStock(EnvironmentScopedModel):
    """Une ligne du journal de stock. Ne se modifie ni ne se supprime : une erreur se rattrape
    par un mouvement contraire ou un inventaire. `quantite` est SIGNÉE (positive : le stock du
    dépôt augmente). Un transfert, ce sont deux lignes de même `transfert`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(ArticleStock, on_delete=models.PROTECT, related_name="mouvements")
    depot = models.ForeignKey(DepotStock, on_delete=models.PROTECT, related_name="mouvements")
    type = models.CharField(max_length=12, choices=TypeMouvementStock.choices)
    quantite = models.DecimalField(max_digits=12, decimal_places=3)
    lot = models.CharField(max_length=60, blank=True, default="")
    date_peremption = models.DateField(null=True, blank=True)
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    motif = EncryptedTextField(max_length=300, blank=True, default="")
    #: Fournisseur, donateur ou personne à qui c'est remis : un nom, donc chiffré.
    tiers = EncryptedTextField(blank=True, default="")
    crise = models.ForeignKey("Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="mouvements_stock")
    mission = models.ForeignKey("Mission", on_delete=models.SET_NULL, null=True, blank=True, related_name="mouvements_stock")
    equipe = models.ForeignKey("Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="mouvements_stock")
    transfert = models.UUIDField(null=True, blank=True, db_index=True)
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="mouvements_stock")
    date_mouvement = models.DateTimeField(default=timezone.now)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_mouvement", "-date_creation"]
        indexes = [models.Index(fields=["article", "depot"])]


# ── Stocks, second volet (17/11/2026) : denrées, tiers, commandes, factures, prêts ───────────

class TypeTiersStock(models.TextChoices):
    PARTICULIER = "PARTICULIER", "Particulier"
    PROFESSIONNEL = "PROFESSIONNEL", "Professionnel, entreprise"
    ASSOCIATION = "ASSOCIATION", "Association"
    COLLECTIVITE = "COLLECTIVITE", "Collectivité, service public"


class TiersStock(EnvironmentScopedModel):
    """Quelqu'un avec qui l'institution échange du matériel : fournisseur, donateur, emprunteur,
    prêteur. Tout ce qui l'identifie est chiffré ; la recherche se fait donc après déchiffrement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="tiers_stock")
    type = models.CharField(max_length=14, choices=TypeTiersStock.choices, default=TypeTiersStock.PROFESSIONNEL)
    nom = EncryptedTextField()
    contact = EncryptedTextField(blank=True, default="")
    email = EncryptedTextField(blank=True, default="")
    telephone = EncryptedTextField(blank=True, default="")
    adresse = EncryptedTextField(blank=True, default="")
    siret = EncryptedTextField(blank=True, default="")
    notes = EncryptedTextField(blank=True, default="")
    est_fournisseur = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.nom


class StatutCommandeStock(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    COMMANDEE = "COMMANDEE", "Commandée"
    RECUE_EN_PARTIE = "RECUE_EN_PARTIE", "Reçue en partie"
    RECUE = "RECUE", "Reçue"
    ANNULEE = "ANNULEE", "Annulée"


class CommandeStock(EnvironmentScopedModel):
    """Une commande passée à un fournisseur. Sa réception crée les entrées en stock."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="commandes_stock")
    numero = models.CharField(max_length=30)
    tiers = models.ForeignKey(TiersStock, on_delete=models.PROTECT, related_name="commandes")
    statut = models.CharField(max_length=16, choices=StatutCommandeStock.choices, default=StatutCommandeStock.BROUILLON)
    depot = models.ForeignKey(DepotStock, on_delete=models.SET_NULL, null=True, blank=True, related_name="commandes",
                              help_text="Où la commande sera rangée à réception.")
    date_commande = models.DateField(null=True, blank=True)
    livraison_prevue = models.DateField(null=True, blank=True)
    commentaire = EncryptedTextField(blank=True, default="")
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]
        constraints = [models.UniqueConstraint(fields=["institution", "environment", "numero"], name="uq_commandestock_numero")]


class LigneCommandeStock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commande = models.ForeignKey(CommandeStock, on_delete=models.CASCADE, related_name="lignes")
    article = models.ForeignKey(ArticleStock, on_delete=models.PROTECT, related_name="lignes_commande")
    quantite = models.DecimalField(max_digits=12, decimal_places=3)
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    quantite_recue = models.DecimalField(max_digits=12, decimal_places=3, default=0)


class FactureStock(EnvironmentScopedModel):
    """Une facture de fournisseur, gardée avec la commande qu'elle règle. Ce n'est PAS une
    comptabilité : un numéro, des montants, une échéance, une date de paiement et la pièce
    (chiffrée) — de quoi retrouver ce qu'on a payé pour quel matériel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="factures_stock")
    tiers = models.ForeignKey(TiersStock, on_delete=models.PROTECT, related_name="factures")
    commande = models.ForeignKey(CommandeStock, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures")
    numero = models.CharField(max_length=60)
    date_facture = models.DateField()
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    montant_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    echeance = models.DateField(null=True, blank=True)
    payee_le = models.DateField(null=True, blank=True)
    fichier = models.FileField(storage=get_encrypted_file_storage, upload_to=secure_document_path, max_length=255, null=True, blank=True)
    commentaire = EncryptedTextField(blank=True, default="")
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_facture", "-date_creation"]


class SensPret(models.TextChoices):
    CONSENTI = "CONSENTI", "Prêté par l'institution"
    RECU = "RECU", "Prêté à l'institution"


class EtatMaterielPrete(models.TextChoices):
    NEUF = "NEUF", "Neuf"
    BON = "BON", "Bon état"
    USAGE = "USAGE", "Usagé, fonctionne"
    DEGRADE = "DEGRADE", "Dégradé"
    HORS_SERVICE = "HORS_SERVICE", "Hors service"


class StatutPret(models.TextChoices):
    EN_COURS = "EN_COURS", "En cours"
    RENDU = "RENDU", "Rendu"
    LITIGE = "LITIGE", "Rendu avec réserve"


class PretMateriel(EnvironmentScopedModel):
    """Un prêt de matériel, dans un sens ou dans l'autre : l'institution prête à un particulier
    ou à un professionnel (CONSENTI), ou ceux-ci lui prêtent (RECU). Chaque prêt porte une fiche
    d'état au départ et une au retour, avec photos (`Document.pret`), pour qu'il n'y ait pas à
    discuter de ce qui était abîmé avant.

    Quand le prêt porte sur un article du stock, il fait bouger le stock : un prêt consenti le
    sort du dépôt puis l'y ramène ; un matériel reçu en prêt y entre puis en ressort."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="prets_materiel")
    sens = models.CharField(max_length=10, choices=SensPret.choices)
    tiers = models.ForeignKey(TiersStock, on_delete=models.PROTECT, related_name="prets")
    article = models.ForeignKey(ArticleStock, on_delete=models.PROTECT, null=True, blank=True, related_name="prets")
    depot = models.ForeignKey(DepotStock, on_delete=models.PROTECT, null=True, blank=True, related_name="prets")
    designation = models.CharField(max_length=200)
    identification = EncryptedTextField(blank=True, default="")      # numéro de série, immatriculation
    quantite = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    quantite_rendue = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    date_debut = models.DateField()
    retour_prevu = models.DateField(null=True, blank=True)
    date_retour = models.DateField(null=True, blank=True)
    etat_depart = models.CharField(max_length=14, choices=EtatMaterielPrete.choices, default=EtatMaterielPrete.BON)
    constat_depart = EncryptedTextField(blank=True, default="")
    etat_retour = models.CharField(max_length=14, choices=EtatMaterielPrete.choices, blank=True, default="")
    constat_retour = EncryptedTextField(blank=True, default="")
    statut = models.CharField(max_length=10, choices=StatutPret.choices, default=StatutPret.EN_COURS)
    crise = models.ForeignKey("Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="prets_materiel")
    conditions = EncryptedTextField(blank=True, default="")
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    rendu_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_debut", "-date_creation"]


# ── Appels aux dons (core/appels_dons.py, 17/11/2026) ────────────────────────────────────────

class PublicDon(models.TextChoices):
    HOMME = "HOMME", "Homme"
    FEMME = "FEMME", "Femme"
    GARCON = "GARCON", "Garçon"
    FILLE = "FILLE", "Fille"
    BEBE = "BEBE", "Bébé"


class FoyerSinistre(EnvironmentScopedModel):
    """Un foyer qui a tout perdu, et ce qu'il lui faut. Reste dans l'institution qui l'accompagne :
    un appel aux dons n'en montre que des quantités, jamais un nom ni une composition."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="foyers_sinistres")
    crise = models.ForeignKey("Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="foyers_sinistres")
    reference = models.CharField(max_length=20)
    nom = EncryptedTextField()
    contact = EncryptedTextField(blank=True, default="")
    adresse = EncryptedTextField(blank=True, default="")
    commentaire = EncryptedTextField(blank=True, default="")
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["reference"]


class PersonneFoyer(models.Model):
    """Un membre du foyer : de quoi choisir ses vêtements. Ni nom, ni date de naissance."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    foyer = models.ForeignKey(FoyerSinistre, on_delete=models.CASCADE, related_name="personnes")
    public = models.CharField(max_length=6, choices=PublicDon.choices)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    taille_haut = EncryptedTextField(max_length=12, blank=True, default="")
    taille_bas = EncryptedTextField(max_length=12, blank=True, default="")
    pointure = EncryptedTextField(max_length=6, blank=True, default="")


class BesoinFoyer(models.Model):
    """Une chose qu'il faut à un foyer, précisément : « T-shirt, homme, L, 3 »."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    foyer = models.ForeignKey(FoyerSinistre, on_delete=models.CASCADE, related_name="besoins")
    famille = models.CharField(max_length=30)
    designation = EncryptedTextField(max_length=120)
    public = models.CharField(max_length=6, choices=PublicDon.choices, blank=True, default="")
    taille = EncryptedTextField(max_length=20, blank=True, default="")
    neuf_exige = models.BooleanField(default=False)
    #: `quantite` : ce qu'il faut pour tenir dans la durée. `quantite_urgence` : ce qu'il faut pour
    #: passer les premiers jours. Trois T-shirts dépannent, ils ne couvrent pas le besoin.
    quantite = models.PositiveIntegerField(default=1)
    quantite_urgence = models.PositiveIntegerField(default=1)
    quantite_remise = models.PositiveIntegerField(default=0)
    #: Ce qui rend la demande précise et humaine : « son vélo rose », « ses cartes Pokémon ».
    #: Repris tel quel dans l'appel, donc lu de tous : jamais de nom.
    message = EncryptedTextField(blank=True, default="")

    A_COUVRIR, DEPANNE, COUVERT = "A_COUVRIR", "DEPANNE", "COUVERT"

    @property
    def etat(self) -> str:
        """« À couvrir » tant que le foyer n'a pas de quoi passer les premiers jours ; « dépanné »
        ensuite ; « couvert » quand il a ce qu'il faut pour durer."""
        if self.quantite_remise >= self.quantite:
            return self.COUVERT
        return self.DEPANNE if self.quantite_remise >= min(self.quantite_urgence, self.quantite) and self.quantite_remise > 0 else self.A_COUVRIR


class StatutAppelDons(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    OUVERT = "OUVERT", "Ouvert"
    CLOS = "CLOS", "Clos"


class AppelAuxDons(EnvironmentScopedModel):
    """Ce qu'une institution demande, à la pièce près, aux autres institutions (voir
    core/appels_dons.py). Chaque ligne se ferme quand elle est couverte."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="appels_aux_dons")
    crise = models.ForeignKey("Crisis", on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_aux_dons")
    titre = EncryptedTextField(max_length=200)
    description = EncryptedTextField(blank=True, default="")
    statut = models.CharField(max_length=10, choices=StatutAppelDons.choices, default=StatutAppelDons.BROUILLON)
    #: Où livrer : un point de regroupement de la crise, ou un dépôt de l'institution.
    point = models.ForeignKey("PointOperationnel", on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_aux_dons")
    depot = models.ForeignKey(DepotStock, on_delete=models.SET_NULL, null=True, blank=True, related_name="appels_aux_dons")
    livraison_adresse = EncryptedTextField(blank=True, default="")
    livraison_horaires = EncryptedTextField(max_length=200, blank=True, default="")
    contact_nom = EncryptedTextField(blank=True, default="")
    contact_telephone = EncryptedTextField(blank=True, default="")
    contact_email = EncryptedTextField(blank=True, default="")
    #: Jusqu'où l'appel est lancé, en kilomètres autour de `centre`. Vide : toute la France.
    #: On commence près (les dons arrivent vite, le transport est court) et on élargit si le
    #: besoin n'est pas couvert.
    portee_km = models.PositiveIntegerField(null=True, blank=True)
    #: Le point d'où la distance se mesure : la crise, à défaut la commune de l'institution.
    centre = gis_models.PointField(srid=4326, null=True, blank=True)
    #: Les institutions déjà prévenues de l'appel : quand on élargit le périmètre, seules les
    #: nouvelles venues le sont (core/notifications_dons.prevenir_le_reseau).
    institutions_prevenues = models.JSONField(default=list, blank=True)
    #: Jours laissés à un engagement pour annoncer son envoi avant d'être relâché.
    delai_engagement_jours = models.PositiveSmallIntegerField(default=7)
    date_ouverture = models.DateTimeField(null=True, blank=True)
    date_cloture = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]


class BesoinDon(models.Model):
    """Une ligne d'un appel : quoi, pour qui, quelle taille, combien. `quantite_recue` ne compte
    que ce qui est arrivé et a été compté."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appel = models.ForeignKey(AppelAuxDons, on_delete=models.CASCADE, related_name="besoins")
    famille = models.CharField(max_length=30)
    designation = models.CharField(max_length=120)
    public = models.CharField(max_length=6, choices=PublicDon.choices, blank=True, default="")
    taille = models.CharField(max_length=20, blank=True, default="")
    neuf_exige = models.BooleanField(default=False)
    precision = EncryptedTextField(max_length=200, blank=True, default="")
    #: Le mot personnel d'une demande (« son vélo rose ») : une telle ligne ne se fond pas dans
    #: les autres. Lu de tous, avis public compris : jamais de nom.
    message = EncryptedTextField(max_length=300, blank=True, default="")
    #: Pour combien de personnes (ou de foyers, sans public) : on demande « des T-shirts L pour
    #: 14 personnes », pas « 56 T-shirts ».
    nb_beneficiaires = models.PositiveIntegerField(default=1)
    quantite_voulue = models.PositiveIntegerField()
    #: La part qu'il faut tout de suite, pour passer les premiers jours.
    quantite_urgente = models.PositiveIntegerField(default=0)
    quantite_recue = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["famille", "designation", "public", "taille"]
        constraints = [models.UniqueConstraint(fields=["appel", "famille", "designation", "public", "taille", "message"],
                                               name="uq_besoindon_ligne_message")]


class StatutEnvoiDon(models.TextChoices):
    ANNONCE = "ANNONCE", "Annoncé"
    RECU = "RECU", "Reçu"


class EnvoiDon(EnvironmentScopedModel):
    """Un envoi annoncé par une institution qui s'est engagée : ce qui part, quand, par qui."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appel = models.ForeignKey(AppelAuxDons, on_delete=models.CASCADE, related_name="envois")
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="envois_de_dons")
    statut = models.CharField(max_length=8, choices=StatutEnvoiDon.choices, default=StatutEnvoiDon.ANNONCE)
    date_expedition = models.DateField()
    arrivee_prevue = models.DateField(null=True, blank=True)
    transporteur = EncryptedTextField(max_length=200, blank=True, default="")
    contact = EncryptedTextField(blank=True, default="")
    commentaire = EncryptedTextField(blank=True, default="")
    recu_le = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]


class StatutEngagementDon(models.TextChoices):
    PROMIS = "PROMIS", "Promis"
    EXPEDIE = "EXPEDIE", "Expédié"
    RECU = "RECU", "Reçu"
    RELACHE = "RELACHE", "Relâché (délai dépassé)"
    ANNULE = "ANNULE", "Annulé"


class EngagementDon(models.Model):
    """« J'en fournis 6 sur 14 » : la quantité qu'une institution s'engage à fournir sur une ligne.
    Tant qu'il tient, les autres ne collectent pas cette part."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    besoin = models.ForeignKey(BesoinDon, on_delete=models.CASCADE, related_name="engagements")
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="engagements_de_dons")
    quantite = models.PositiveIntegerField()
    quantite_recue = models.PositiveIntegerField(null=True, blank=True)
    statut = models.CharField(max_length=8, choices=StatutEngagementDon.choices, default=StatutEngagementDon.PROMIS)
    envoi = models.ForeignKey(EnvoiDon, on_delete=models.SET_NULL, null=True, blank=True, related_name="engagements")
    expire_le = models.DateTimeField()
    #: Le rappel « votre engagement sera rendu aux autres dans deux jours » ne part qu'une fois.
    rappel_envoye_le = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_creation"]


class AlerteStockEnvoyee(EnvironmentScopedModel):
    """Le dernier relevé d'alertes de stock envoyé à une institution (core/alertes_stock.py) : son
    empreinte sert à ne pas réécrire tous les matins la même liste à des gens qui l'ont déjà lue."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="alertes_stock_envoyees")
    empreinte = models.CharField(max_length=64)
    nombre = models.PositiveIntegerField(default=0)
    date_envoi = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["institution", "environment"], name="uq_alertestock_institution")]


# ── Stocks, troisième volet (17/11/2026) : demandes de transfert, réservations, lots types, appareils ──

class StatutDemandeTransfert(models.TextChoices):
    DEMANDEE = "DEMANDEE", "Demandée"
    ACCEPTEE = "ACCEPTEE", "Acceptée, transférée"
    REFUSEE = "REFUSEE", "Refusée"
    ANNULEE = "ANNULEE", "Annulée"


class DemandeTransfertStock(EnvironmentScopedModel):
    """« Pouvez-vous nous envoyer 20 couvertures ? » : un transfert entre deux points se DEMANDE
    d'abord (décision de Sylvain du 17/11/2026 : « l'autre institution peut réaliser en avoir
    besoin au dernier moment »). C'est l'acceptation, par ceux qui tiennent le point de départ,
    qui réalise le transfert — pour tout ou partie de la quantité."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey("PointOperationnel", on_delete=models.CASCADE, related_name="transferts_demandes_sortants")
    destination = models.ForeignKey("PointOperationnel", on_delete=models.CASCADE, related_name="transferts_demandes_entrants")
    item = models.ForeignKey(MaterielCatalogue, on_delete=models.PROTECT, related_name="+")
    quantite = models.PositiveIntegerField()
    quantite_accordee = models.PositiveIntegerField(null=True, blank=True)
    message = EncryptedTextField(max_length=300, blank=True, default="")
    statut = models.CharField(max_length=9, choices=StatutDemandeTransfert.choices, default=StatutDemandeTransfert.DEMANDEE)
    reponse = EncryptedTextField(max_length=300, blank=True, default="")
    demande_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decide_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_decision = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation"]


class StatutReservationStock(models.TextChoices):
    ACTIVE = "ACTIVE", "Réservé"
    SERVIE = "SERVIE", "Remis"
    ANNULEE = "ANNULEE", "Annulée"


class ReservationStock(EnvironmentScopedModel):
    """Du stock mis de côté pour quelqu'un : il reste dans le dépôt, mais plus personne d'autre ne
    peut le sortir. Servir la réservation le fait sortir ; l'annuler le rend."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(ArticleStock, on_delete=models.CASCADE, related_name="reservations")
    depot = models.ForeignKey(DepotStock, on_delete=models.CASCADE, related_name="reservations")
    quantite = models.DecimalField(max_digits=12, decimal_places=3)
    #: Pour qui ou pour quoi : une demande d'habitant, une équipe, ou un texte libre.
    demande = models.ForeignKey("Request", on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations_stock")
    equipe = models.ForeignKey("Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="reservations_stock")
    pour = EncryptedTextField(blank=True, default="")
    statut = models.CharField(max_length=8, choices=StatutReservationStock.choices, default=StatutReservationStock.ACTIVE)
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation"]


class LotTypeStock(EnvironmentScopedModel):
    """Une dotation type : le sac d'intervention, la caisse du véhicule, le kit d'accueil. On la
    vérifie, on la sort et on la rentre d'un geste."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="lots_types_stock")
    nom = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]


class LigneLotTypeStock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lot = models.ForeignKey(LotTypeStock, on_delete=models.CASCADE, related_name="lignes")
    article = models.ForeignKey(ArticleStock, on_delete=models.CASCADE, related_name="lignes_lot_type")
    quantite = models.DecimalField(max_digits=12, decimal_places=3)


class EtatAppareilStock(models.TextChoices):
    EN_SERVICE = "EN_SERVICE", "En service"
    EN_PANNE = "EN_PANNE", "En panne"
    REFORME = "REFORME", "Réformé"


class AppareilStock(EnvironmentScopedModel):
    """Un appareil suivi à l'unité : le groupe électrogène n° 2, tel défibrillateur, tel
    extincteur. Le stock compte des quantités ; ici on suit UN objet, son état et son contrôle
    périodique. Le contrôle signale une échéance, il n'interdit rien : en pleine crise on sort
    un groupe dont la révision a huit jours de retard, et on le sait."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, related_name="appareils_stock")
    article = models.ForeignKey(ArticleStock, on_delete=models.SET_NULL, null=True, blank=True, related_name="appareils")
    depot = models.ForeignKey(DepotStock, on_delete=models.SET_NULL, null=True, blank=True, related_name="appareils")
    designation = models.CharField(max_length=200)
    numero = models.CharField(max_length=100, blank=True, default="", help_text="Numéro de série, d'inventaire ou immatriculation.")
    etat = models.CharField(max_length=10, choices=EtatAppareilStock.choices, default=EtatAppareilStock.EN_SERVICE)
    date_acquisition = models.DateField(null=True, blank=True)
    #: Le contrôle périodique, s'il y en a un : « Vérification annuelle », tous les 12 mois.
    controle_libelle = models.CharField(max_length=120, blank=True, default="")
    controle_periodicite_mois = models.PositiveSmallIntegerField(null=True, blank=True)
    controle_dernier_le = models.DateField(null=True, blank=True)
    commentaire = EncryptedTextField(blank=True, default="")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["designation", "numero"]

    @property
    def controle_prochain_le(self):
        """Quand le prochain contrôle est dû ; None s'il n'y en a pas. Jamais contrôlé : dû tout de suite."""
        if not self.controle_periodicite_mois:
            return None
        depuis = self.controle_dernier_le or self.date_acquisition
        if depuis is None:
            return timezone.localdate()
        mois = depuis.month - 1 + self.controle_periodicite_mois
        annee, mois = depuis.year + mois // 12, mois % 12 + 1
        import calendar
        return depuis.replace(year=annee, month=mois, day=min(depuis.day, calendar.monthrange(annee, mois)[1]))


class ControleAppareilStock(models.Model):
    """Un contrôle fait sur un appareil : la date, ce qu'il a donné, par qui."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appareil = models.ForeignKey(AppareilStock, on_delete=models.CASCADE, related_name="controles")
    date = models.DateField()
    conforme = models.BooleanField(default=True)
    commentaire = EncryptedTextField(blank=True, default="")
    auteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-date_creation"]



# ── Jetons chiffrés : leur empreinte, avant chaque enregistrement (18/11/2026) ─────────────────
#: Modèle -> jetons. Un lien envoyé par courriel (modifier sa demande, confirmer une alerte,
#: rejoindre une association…) est retrouvé par l'empreinte du jeton, jamais par le jeton.
JETONS_CHIFFRES = {
    "Request": ("deletion_token", "edition_token"),
    "Information": ("deletion_token", "edition_token"),
    "Offer": ("deletion_token", "reponse_token"),
    "NotificationAlertePCS": ("token_confirmation",),
    "EngagementRessource": ("token_confirmation",),
    "DemandeMobilisation": ("jeton_verification",),
    "AffectationPointBenevole": ("token_confirmation",),
    "InvitationAssociation": ("jeton",),
    "JetonEnrolementSatellite": ("jeton",),
    "DemandeRapport": ("jeton",),
}


def _poser_empreintes(sender, instance, **kwargs):
    from .crypto_fields import empreinte_jeton
    for champ in JETONS_CHIFFRES.get(sender.__name__, ()):
        valeur = getattr(instance, champ)
        setattr(instance, f"{champ}_empreinte", empreinte_jeton(valeur) if valeur else None)


for _nom in JETONS_CHIFFRES:
    models.signals.pre_save.connect(_poser_empreintes, sender=globals()[_nom],
                                    dispatch_uid=f"empreinte-jeton-{_nom}")
