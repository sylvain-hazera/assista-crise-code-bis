
import json
import os
from django.db.models import Sum
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .auth_validation import InstitutionEmailValidator
from .geo_lookup import commune_from_code, commune_from_point
from .permissions import INSTITUTIONAL_TYPES, get_active_environment, effective_role_or_none, mask_email, mask_phone
from .models import (
    Environment,
    UserRole,
    InstitutionType,
    Institution,
    RoleOperationnel,
    ContactInstitution,
    InstitutionDomaine,
    InstitutionCompetence,
    AffectationRoleOperationnel,
    DelegationCompetence,
    DisponibiliteOperationnelle,
    PointType,
    PointOperationnel,
    ImplicationInstitution,
    TypeImplication,
    User, Crisis, Request, Offer, Information,
    RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, RecherchePersonnePhoto, RecherchePersonneCommentairePhoto,
    DossierCommentaire, RecherchePersonne, RecherchePersonneCommentaire, RecherchePersonneHistorique,
    DossierHistorique, Besoin, BesoinCompetence,Dossier, Mission, RequestType, RequestTypeBesoin, OfferType, InformationType, Team, Competence, AffectationCompetence,
    DernierePositionUtilisateur,
    DisponibiliteOffre,
    DisponibilitePointEquipe,
    MaterielPoint,
    MaterielCatalogue,
    RegistrePresence,
    DeclarationSecurite,
    AffectationPointBenevole,
    Notification,
)

class RecherchePersonneCommentairePhotoSerializer(
    serializers.ModelSerializer
):

    preview_url = (
        serializers.SerializerMethodField()
    )

    def get_preview_url(
        self,
        obj
    ):

        return (
            f"/api/"
            f"recherches-personnes-commentaires-photos/"
            f"{obj.id}/preview/"
        )

    class Meta:

        model = (
            RecherchePersonneCommentairePhoto
        )

        fields = "__all__"
        extra_kwargs = {'fichier': {'write_only': True}}

class RequestTypeSerializer(serializers.ModelSerializer):
    """Serializer pour les types de demandes"""
    class Meta:
        model = RequestType
        fields = '__all__'

class OfferTypeSerializer(serializers.ModelSerializer):
    """Serializer pour les types d'offres"""
    class Meta:
        model = OfferType
        fields = '__all__'

class InformationTypeSerializer(serializers.ModelSerializer):
    """Serializer pour les types d'informations"""
    class Meta:
        model = InformationType
        fields = '__all__'

class BesoinSerializer(serializers.ModelSerializer):

    class Meta:
        model = Besoin
        fields = "__all__"

class BesoinCompetenceSerializer(serializers.ModelSerializer):

    besoin_nom = serializers.CharField(
        source='besoin.nom',
        read_only=True
    )

    competence_nom = serializers.CharField(
        source='competence.nom',
        read_only=True
    )

    class Meta:
        model = BesoinCompetence
        fields = "__all__"

class RequestTypeBesoinSerializer(serializers.ModelSerializer):

    request_type_nom = serializers.CharField(
        source='request_type.type',
        read_only=True
    )

    besoin_nom = serializers.CharField(
        source='besoin.nom',
        read_only=True
    )

    class Meta:
        model = RequestTypeBesoin
        fields = "__all__"

class UserSerializer(serializers.ModelSerializer):
    """Serializer pour les utilisateurs"""
    password = serializers.CharField(write_only=True, required=True)
    institution_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    institution_type = serializers.CharField(write_only=True, required=False, allow_blank=True)
    commune_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    commune_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    institution_email_hint = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'type', 'demo_role',
                  'photo', 'phone_number', 'password', 'postal_code', 'enabled',
                  'institution_name', 'institution_type', 'commune_name', 'commune_code', 'institution_email_hint']
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'phone_number': {'required': False},
            'photo': {'required': False},
            'postal_code': {'required': False},
            'enabled': {'required': False},
            'demo_role': {'required': False},
        }

    def to_representation(self, instance):
        """En zone DEMO, email/téléphone/username d'un compte réel ne doivent jamais apparaître
        à l'écran pendant une démonstration — même si le compte lui-même (utilisateurs communs
        aux deux zones) est bien réel. `username` vaut souvent l'email en clair par convention
        (compte créé via l'email) : masqué lui aussi, sinon il fuit la même information par un
        autre champ. Masquage à l'affichage uniquement, jamais en base."""
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['email'] = mask_email(data.get('email'))
            data['phone_number'] = mask_phone(data.get('phone_number'))
            data['username'] = mask_email(data.get('username'))
        return data

    def validate_demo_role(self, value):
        # Un formulaire multipart ne peut pas envoyer `null` — une chaîne vide signifie
        # "retirer l'accès démo" (voir page Utilisateurs, option "Aucun accès démo").
        return value or None

    def validate(self, attrs):
        # Cette vérification n'a de sens qu'à la création du compte (l'email doit prouver
        # l'appartenance à une institution pour s'inscrire comme tel) — elle ne doit jamais se
        # redéclencher sur une simple modification d'un compte déjà existant (ex: un admin qui
        # règle le rôle démo d'un compte SECOURS/AUT_LOCALE/ADMIN), sans quoi toute édition de
        # ces comptes échoue puisque le formulaire d'édition ne renvoie pas les informations
        # d'inscription (institution_name/type, commune) qui ne sont capturées qu'une fois.
        if self.instance is None:
            email = attrs.get('email')
            user_type = attrs.get('type')

            if user_type in {UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE, UserRole.ADMINISTRATOR}:
                valid, message, _details = InstitutionEmailValidator.validate_institution_account(
                    email=email,
                    institution_name=attrs.get('institution_name', ''),
                    institution_type=attrs.get('institution_type', ''),
                    commune_name=attrs.get('commune_name', ''),
                    commune_code=attrs.get('commune_code', ''),
                )
                if not valid:
                    raise serializers.ValidationError({'email': message})

        return attrs

    def create(self, validated_data):
        # Conservés pour le rattachement institution après confirmation de l'email (activation) —
        # voir core/institution_attachment.py. Ne JAMAIS rattacher sur la seule foi d'un email non
        # vérifié : n'importe qui peut prétendre être "contact@loire.fr" sans posséder cette boîte.
        pending_institution_name = validated_data.get('institution_name', '')
        pending_institution_type = validated_data.get('institution_type', '')
        pending_commune_name = validated_data.get('commune_name', '')
        pending_commune_code = validated_data.get('commune_code', '')

        for field in ['institution_name', 'institution_type', 'commune_name', 'commune_code', 'institution_email_hint']:
            validated_data.pop(field, None)

        if 'username' not in validated_data:
            validated_data['username'] = validated_data['email']

        user_type = validated_data.get('type')
        if user_type in {UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE, UserRole.ADMINISTRATOR}:
            # is_active est le champ que Django/SimpleJWT vérifie réellement à la connexion
            # (/api/token/) : sans lui, enabled=False seul ne bloque rien — le compte reste
            # utilisable pour se connecter tant que is_active vaut True (valeur par défaut).
            validated_data['enabled'] = False
            validated_data['is_active'] = False

        if user_type == UserRole.LOCAL_AUTHORITY:
            validated_data['pending_institution_name'] = pending_institution_name
            validated_data['pending_institution_type'] = pending_institution_type
            validated_data['pending_commune_name'] = pending_commune_name
            validated_data['pending_commune_code'] = pending_commune_code

        user = User.objects.create_user(**validated_data)

        return user

def validate_crisis_open(crisis, field_name="crisis"):
    """Verrou minimal réutilisé par tout ce qui s'accroche à une crise (implication, point
    opérationnel, délégation de compétence...) : bloque uniquement sur une crise clôturée. Ne
    vérifie pas la présence d'un responsable — condition qui n'a pas de sens pour l'acte même
    qui désigne le premier responsable d'une crise (cf. validate_crisis_open_and_monitored,
    plus stricte, pour les dépôts de demande/offre/information). `field_name` doit correspondre
    au nom du champ FK vers Crisis sur le serializer appelant ('crisis' pour Request/Offer/
    Information, 'crise' pour ImplicationInstitution/PointOperationnel/DelegationCompetence)."""
    if crisis is None:
        return
    if crisis.end_date is not None:
        raise serializers.ValidationError(
            {field_name: "Cette crise est clôturée : il n'est plus possible d'y apporter de modification."}
        )


def validate_crisis_open_and_monitored(crisis):
    """Une demande/offre/information ne peut être déposée sur une crise que si elle est
    encore ouverte (pas de end_date) et qu'un responsable y est activement rattaché — pas
    de dépôt dans le vide sur une crise abandonnée ou dont personne n'a la charge."""
    validate_crisis_open(crisis)
    if crisis is None:
        return
    if not crisis.implications.filter(responsable__isnull=False, actif=True).exists():
        raise serializers.ValidationError(
            {"crisis": "Cette crise n'a pas encore de responsable désigné : dépôt impossible pour le moment."}
        )


class CrisisSerializer(serializers.ModelSerializer):
    """Serializer pour les crises"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    zone_geojson = serializers.SerializerMethodField()
    zone_secteurs_geojson = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    has_photo = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()
    has_responsable_actif = serializers.SerializerMethodField()
    # `type` reste le code technique (ex: "INCEDIE", historique — jamais renommé pour éviter
    # une migration de données sur les crises existantes) : `type_display` est le libellé
    # humain ("Incendie") à afficher partout côté frontend, jamais le code brut.
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Crisis
        fields = '__all__'
        extra_kwargs = {'photo': {'write_only': True}}

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_zone_geojson(self, obj):
        # GEOSGeometry.geojson est une propriété native de GeoDjango — pas besoin de
        # librairie de parsing WKT côté frontend, qui consomme directement ce GeoJSON.
        return json.loads(obj.zone.geojson) if obj.zone else None

    def get_zone_secteurs_geojson(self, obj):
        return json.loads(obj.zone_secteurs.geojson) if obj.zone_secteurs else None

    def get_has_photo(self, obj):
        return bool(obj.photo)

    def get_is_open(self, obj):
        # Pas de champ de statut dédié : une crise sans date de fin est considérée
        # ouverte. Évite un second état à synchroniser avec end_date.
        return obj.end_date is None

    def get_has_responsable_actif(self, obj):
        return obj.implications.filter(responsable__isnull=False, actif=True).exists()

class RequestSerializer(serializers.ModelSerializer):
    """Serializer pour les demandes d'aide.

    La localisation précise (adresse) n'est un renseignement privé que la mairie, les
    services de secours, et les bénévoles effectivement affectés au dossier issu de cette
    demande doivent voir — jamais le grand public. `latitude`/`longitude`/`location`
    renvoient donc null pour tout autre consommateur."""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    author_nom = serializers.SerializerMethodField()
    author_email = serializers.CharField(source="author.email", read_only=True, default=None)
    author_type = serializers.CharField(source="author.type", read_only=True, default=None)
    crisis_nom = serializers.CharField(source="crisis.name", read_only=True, default=None)
    has_photo = serializers.SerializerMethodField()
    commune = serializers.SerializerMethodField()
    distance_from_crisis_km = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = '__all__'
        extra_kwargs = {'photo': {'write_only': True}}

    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        if effective_role_or_none(request) in INSTITUTIONAL_TYPES:
            return True
        return obj.dossiers.filter(participants__utilisateur=user).exists()

    def get_latitude(self, obj):
        if not self._location_visible(obj):
            return None
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        if not self._location_visible(obj):
            return None
        return obj.location.x if obj.location else None

    def get_commune(self, obj):
        if not self._location_visible(obj):
            return None
        return commune_from_code(obj.commune_code) or commune_from_point(obj.location)

    def get_distance_from_crisis_km(self, obj):
        if not self._location_visible(obj):
            return None
        distance = getattr(obj, 'distance_from_crisis', None)
        return round(distance.km, 1) if distance is not None else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._location_visible(instance):
            data['location'] = None
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['email_request'] = mask_email(data.get('email_request'))
            data['phone_request'] = mask_phone(data.get('phone_request'))
            data['author_email'] = mask_email(data.get('author_email'))
        return data

    def get_author_nom(self, obj):
        if not obj.author:
            return None
        full_name = f"{obj.author.first_name} {obj.author.last_name}".strip()
        return full_name or obj.author.email

    def get_has_photo(self, obj):
        return bool(obj.photo)

    def validate(self, attrs):
        validate_crisis_open_and_monitored(attrs.get('crisis'))
        return attrs

class OfferSerializer(serializers.ModelSerializer):
    """Serializer pour les offres d'aide.

    La localisation précise (adresse) n'est un renseignement privé que la mairie et les
    services de secours doivent voir — jamais le grand public. `latitude`/`longitude`/
    `location` renvoient donc null pour tout consommateur non institutionnel."""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    author_nom = serializers.SerializerMethodField()
    author_email = serializers.CharField(source="author.email", read_only=True, default=None)
    author_phone = serializers.CharField(source="author.phone_number", read_only=True, default=None)
    author_type = serializers.CharField(source="author.type", read_only=True, default=None)
    crisis_nom = serializers.CharField(source="crisis.name", read_only=True, default=None)
    has_photo = serializers.SerializerMethodField()
    competences_libelles = serializers.SerializerMethodField()
    commune = serializers.SerializerMethodField()
    distance_from_crisis_km = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = '__all__'
        extra_kwargs = {'photo': {'write_only': True}}

    def get_competences_libelles(self, obj):
        return [c.nom for c in obj.competences.all()]

    def _location_visible(self) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and request and effective_role_or_none(request) in INSTITUTIONAL_TYPES)

    def get_latitude(self, obj):
        if not self._location_visible():
            return None
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        if not self._location_visible():
            return None
        return obj.location.x if obj.location else None

    def get_commune(self, obj):
        if not self._location_visible():
            return None
        return commune_from_point(obj.location)

    def get_distance_from_crisis_km(self, obj):
        if not self._location_visible():
            return None
        distance = getattr(obj, 'distance_from_crisis', None)
        return round(distance.km, 1) if distance is not None else None

    def to_representation(self, instance):
        # `location` reste un champ générique auto-généré (écriture WKT inchangée) : on
        # masque juste sa valeur en LECTURE, pas la possibilité de l'écrire à la création.
        data = super().to_representation(instance)
        if not self._location_visible():
            data['location'] = None
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['email_offer'] = mask_email(data.get('email_offer'))
            data['author_email'] = mask_email(data.get('author_email'))
            data['phone_offer'] = mask_phone(data.get('phone_offer'))
            data['author_phone'] = mask_phone(data.get('author_phone'))
        return data

    def get_author_nom(self, obj):
        if not obj.author:
            return None
        full_name = f"{obj.author.first_name} {obj.author.last_name}".strip()
        return full_name or obj.author.email

    def get_has_photo(self, obj):
        return bool(obj.photo)

    def validate(self, attrs):
        validate_crisis_open_and_monitored(attrs.get('crisis'))
        return attrs

class DisponibiliteOffreSerializer(serializers.ModelSerializer):
    """Créneau de disponibilité (jour + matin/midi/soir/nuit) d'un bénévole."""

    class Meta:
        model = DisponibiliteOffre
        fields = '__all__'

class DisponibilitePointEquipeSerializer(serializers.ModelSerializer):
    """Créneau de disponibilité d'un membre de l'équipe responsable d'un point opérationnel."""

    membre_nom = serializers.SerializerMethodField()
    affectation_statut = serializers.CharField(source="affectation.statut", read_only=True, default=None)

    class Meta:
        model = DisponibilitePointEquipe
        fields = '__all__'

    def get_membre_nom(self, obj):
        full_name = f"{obj.membre.first_name} {obj.membre.last_name}".strip()
        return full_name or obj.membre.email

    def validate(self, attrs):
        point = attrs.get('point') or (self.instance.point if self.instance else None)
        membre = attrs.get('membre') or (self.instance.membre if self.instance else None)
        if point and membre:
            if not point.equipe or not point.equipe.members.filter(pk=membre.pk).exists():
                raise serializers.ValidationError(
                    {"membre": "Cette personne n'est pas membre de l'équipe responsable de ce point."}
                )
            validate_crisis_open(point.crise, field_name="crise")
        return attrs

class MaterielCatalogueSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterielCatalogue
        fields = '__all__'


class MaterielPointSerializer(serializers.ModelSerializer):
    """État du stock d'un item du catalogue matériel sur un point opérationnel."""

    item_nom = serializers.CharField(source="item.nom", read_only=True)
    niveau_stock_libelle = serializers.CharField(source="get_niveau_stock_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    responsable_nom = serializers.SerializerMethodField()

    class Meta:
        model = MaterielPoint
        fields = '__all__'

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.email

    def validate(self, attrs):
        point = attrs.get('point') or (self.instance.point if self.instance else None)
        if point:
            validate_crisis_open(point.crise, field_name="crise")
        return attrs


class RegistrePresenceSerializer(serializers.ModelSerializer):
    """Registre de présence ("secrétariat") d'un point opérationnel."""

    type_personne_libelle = serializers.CharField(source="get_type_personne_display", read_only=True)
    enregistre_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = RegistrePresence
        fields = '__all__'
        read_only_fields = ['date_arrivee']

    def get_enregistre_par_nom(self, obj):
        if not obj.enregistre_par:
            return None
        full_name = f"{obj.enregistre_par.first_name} {obj.enregistre_par.last_name}".strip()
        return full_name or obj.enregistre_par.email

    def validate(self, attrs):
        point = attrs.get('point') or (self.instance.point if self.instance else None)
        if point:
            validate_crisis_open(point.crise, field_name="crise")
        return attrs


class DeclarationSecuriteSerializer(serializers.ModelSerializer):
    """"Je suis en sécurité" — auto-déclaration publique ou recensement opérateur (secrétariat
    d'un centre d'accueil). Aucun champ santé/médical : voir DeclarationSecurite.__doc__."""

    type_declarant_libelle = serializers.CharField(source="get_type_declarant_display", read_only=True)
    situation_libelle = serializers.CharField(source="get_situation_display", read_only=True)
    centre_accueil_nom = serializers.CharField(source="centre_accueil.nom", read_only=True, default=None)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    declare_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = DeclarationSecurite
        fields = '__all__'
        read_only_fields = ['id', 'date_declaration', 'declare_par', 'registre_presence']

    def get_declare_par_nom(self, obj):
        if not obj.declare_par:
            return None
        full_name = f"{obj.declare_par.first_name} {obj.declare_par.last_name}".strip()
        return full_name or obj.declare_par.email

    def validate(self, attrs):
        crise = attrs.get('crise') or (self.instance.crise if self.instance else None)
        if crise:
            validate_crisis_open(crise)
        return attrs


class AffectationPointBenevoleSerializer(serializers.ModelSerializer):
    """Recrutement d'un bénévole individuel sur un point, depuis une offre d'aide."""

    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    benevole_nom = serializers.SerializerMethodField()
    point_transit_nom = serializers.CharField(source="point_transit.nom", read_only=True, default=None)

    class Meta:
        model = AffectationPointBenevole
        fields = '__all__'
        read_only_fields = ['statut', 'token_confirmation', 'date_reponse', 'affecte_par']

    def get_benevole_nom(self, obj):
        full_name = f"{obj.benevole.first_name} {obj.benevole.last_name}".strip()
        return full_name or obj.benevole.email


class InformationSerializer(serializers.ModelSerializer):
    """Serializer pour les informations.

    La localisation précise (adresse) n'est un renseignement privé que la mairie, les
    services de secours, et les bénévoles effectivement affectés au dossier issu de ce
    signalement doivent voir — jamais le grand public. `latitude`/`longitude`/`location`
    renvoient donc null pour tout autre consommateur."""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    author_nom = serializers.SerializerMethodField()
    author_email = serializers.CharField(source="author.email", read_only=True, default=None)
    author_type = serializers.CharField(source="author.type", read_only=True, default=None)
    crisis_nom = serializers.CharField(source="crisis.name", read_only=True, default=None)
    has_photo = serializers.SerializerMethodField()
    commune = serializers.SerializerMethodField()
    distance_from_crisis_km = serializers.SerializerMethodField()

    class Meta:
        model = Information
        fields = '__all__'
        extra_kwargs = {'photo': {'write_only': True}}

    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        if effective_role_or_none(request) in INSTITUTIONAL_TYPES:
            return True
        return obj.dossiers.filter(participants__utilisateur=user).exists()

    def get_latitude(self, obj):
        if not self._location_visible(obj):
            return None
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        if not self._location_visible(obj):
            return None
        return obj.location.x if obj.location else None

    def get_commune(self, obj):
        if not self._location_visible(obj):
            return None
        return commune_from_point(obj.location)

    def get_distance_from_crisis_km(self, obj):
        if not self._location_visible(obj):
            return None
        distance = getattr(obj, 'distance_from_crisis', None)
        return round(distance.km, 1) if distance is not None else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._location_visible(instance):
            data['location'] = None
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['email_information'] = mask_email(data.get('email_information'))
            data['phone_information'] = mask_phone(data.get('phone_information'))
            data['author_email'] = mask_email(data.get('author_email'))
        return data

    def get_author_nom(self, obj):
        if not obj.author:
            return None
        full_name = f"{obj.author.first_name} {obj.author.last_name}".strip()
        return full_name or obj.author.email

    def get_has_photo(self, obj):
        return bool(obj.photo)

    def validate(self, attrs):
        validate_crisis_open_and_monitored(attrs.get('crisis'))
        return attrs

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Serializer personnalisé pour l'authentification JWT"""
    username_field = 'email'

    def validate(self, attrs):
        data = super().validate(attrs)
        # On ajoute l'utilisateur sérialisé à la réponse
        data['user'] = UserSerializer(self.user).data
        return data

class TeamSerializer(serializers.ModelSerializer):
    member_ids       = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.all(), source='members', required=False
    )
    assigned_crisis_ids  = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Crisis.objects.all(), source='assigned_crises', required=False
    )
    assigned_offer_ids   = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Offer.objects.all(), source='assigned_offers', required=False
    )
    assigned_request_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Request.objects.all(), source='assigned_requests', required=False
    )
    assigned_information_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Information.objects.all(), source='assigned_informations', required=False
    )
    competence_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Competence.objects.all(), source='competences', required=False
    )
    zone_precise_geojson = serializers.SerializerMethodField()
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    members_info = serializers.SerializerMethodField()
    leader_nom = serializers.SerializerMethodField()
    regulateur_nom = serializers.SerializerMethodField()

    class Meta:
        model  = Team
        fields = [
            'id', 'name', 'description', 'color', 'created_at',
            'institution',
            'institution_nom',
            'leader',
            'leader_nom',
            'regulateur',
            'regulateur_nom',
            'member_ids',
            'members_info',
            'assigned_crisis_ids',
            'assigned_offer_ids',
            'assigned_request_ids',
            'assigned_information_ids',
            'competence_ids',
            'departements',
            'communes',
            'zone_precise',
            'zone_precise_geojson',
        ]
        read_only_fields = ['id', 'created_at']

    def get_zone_precise_geojson(self, obj):
        return json.loads(obj.zone_precise.geojson) if obj.zone_precise else None

    def _nom(self, user):
        if not user:
            return None
        return f"{user.first_name} {user.last_name}".strip() or user.username

    def get_members_info(self, obj):
        # Dénormalisé ici (plutôt que de faire fetcher /api/users/ côté frontend) : un simple
        # bénévole membre d'une équipe n'a pas forcément accès à la liste globale des
        # utilisateurs, et n'a de toute façon besoin que du nom de ses coéquipiers, jamais de
        # leur email/téléphone — voir "vue équipe".
        return [{"id": str(m.id), "nom": self._nom(m)} for m in obj.members.all()]

    def get_leader_nom(self, obj):
        return self._nom(obj.leader)

    def get_regulateur_nom(self, obj):
        return self._nom(obj.regulateur)


class DernierePositionUtilisateurSerializer(serializers.ModelSerializer):
    """Lecture seule : l'écriture passe exclusivement par MaPositionView (auto-déclaration par
    l'utilisateur concerné), jamais via ce serializer générique."""

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    utilisateur_nom = serializers.SerializerMethodField()
    team_ids = serializers.PrimaryKeyRelatedField(source='utilisateur.teams', many=True, read_only=True)
    team_noms = serializers.SerializerMethodField()

    class Meta:
        model = DernierePositionUtilisateur
        fields = [
            'id', 'utilisateur', 'utilisateur_nom', 'latitude', 'longitude',
            'horodatage', 'team_ids', 'team_noms',
        ]
        read_only_fields = fields

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_utilisateur_nom(self, obj):
        return f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip() or obj.utilisateur.username

    def get_team_noms(self, obj):
        return list(obj.utilisateur.teams.values_list('name', flat=True))


class CompetenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Competence
        fields = "__all__"


class AffectationCompetenceSerializer(serializers.ModelSerializer):

    crise_nom = serializers.CharField(
        source='crise.name',
        read_only=True
    )

    competence_nom = serializers.CharField(
        source='competence.nom',
        read_only=True
    )

    equipe_nom = serializers.CharField(
        source='equipe.name',
        read_only=True
    )

    class Meta:
        model = AffectationCompetence
        fields = "__all__"

class MissionSerializer(serializers.ModelSerializer):

    crise_nom = serializers.CharField(
        source='crise.name',
        read_only=True
    )

    equipe_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Team.objects.all(), source='equipes', required=False
    )

    equipes_noms = serializers.SerializerMethodField()

    class Meta:
        model = Mission
        fields = [
            'id', 'titre', 'description', 'crise', 'crise_nom',
            'equipe_ids', 'equipes_noms', 'statut',
            'date_creation', 'date_cloture',
        ]
        read_only_fields = ['id', 'date_creation']

    def get_equipes_noms(self, obj):
        return [e.name for e in obj.equipes.all()]


class DossierSerializer(serializers.ModelSerializer):

    crise_nom = serializers.CharField(
        source='crise.name',
        read_only=True
    )

    competence_nom = serializers.CharField(
        source='competence.nom',
        read_only=True
    )

    equipe_nom = serializers.CharField(
        source='equipe.name',
        read_only=True
    )

    mission_titre = serializers.CharField(
        source='mission.titre',
        read_only=True,
        default=None
    )

    information_titre = serializers.CharField(
        source='information.title',
        read_only=True,
        default=None
    )

    has_updates = serializers.SerializerMethodField()

    unread_count = serializers.SerializerMethodField()

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Dossier
        fields = "__all__"

    def _origine(self, obj):
        return obj.demande or obj.information

    def get_latitude(self, obj):
        # Pas de gating supplémentaire ici : un Dossier n'est jamais listable publiquement
        # (DossierViewSet.get_queryset le restreint déjà aux institutionnels ou aux
        # participants), donc quiconque peut voir CE dossier peut voir sa localisation.
        origine = self._origine(obj)
        return origine.location.y if origine and origine.location else None

    def get_longitude(self, obj):
        origine = self._origine(obj)
        return origine.location.x if origine and origine.location else None

    def get_has_updates(self, obj):

        return (
            self.get_unread_count(obj)
            > 0
        )

    def get_unread_count(self, obj):

        request = self.context.get(
            "request"
        )

        if (
            not request
            or
            not request.user.is_authenticated
        ):
            return 0

        participant = (
            obj.participants
            .filter(
                utilisateur=request.user
            )
            .first()
        )

        if (
            not participant
            or
            not participant.date_derniere_vue
        ):
            return 0

        commentaires = (
            obj.commentaires
            .filter(
                date_creation__gt=
                participant.date_derniere_vue
            )
            .count()
        )

        documents = (
            obj.documents
            .filter(
                date_upload__gt=
                participant.date_derniere_vue
            )
            .count()
        )

        return (
            commentaires
            +
            documents
        )

class DocumentSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()
    nom_fichier = serializers.SerializerMethodField()
    metadata_privees = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = "__all__"
        extra_kwargs = {
            'auteur': {'read_only': True},
            'fichier': {'write_only': True},
        }

    def get_auteur_nom(self, obj):

        if not obj.auteur:
            return "Inconnu"

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username

    def get_nom_fichier(self, obj):
        if not obj.fichier:
            return None
        return os.path.basename(obj.fichier.name)

    def get_metadata_privees(self, obj):
        # Métadonnées EXIF sensibles (GPS notamment) : réservées à l'auteur du document
        # et aux acteurs institutionnels, jamais aux autres participants du dossier.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return {}
        if user.id == obj.auteur_id or effective_role_or_none(request) in INSTITUTIONAL_TYPES:
            return obj.metadata_privees
        return {}

class DossierCommentaireSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = DossierCommentaire
        fields = "__all__"
        extra_kwargs = {'auteur': {'read_only': True}}

    def get_auteur_nom(self, obj):

        if not obj.auteur:
            return "Inconnu"

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username


class DossierHistoriqueSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = DossierHistorique
        fields = "__all__"

    def get_auteur_nom(self, obj):

        if not obj.auteur:
            return "Système"

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username

class NotificationSerializer(serializers.ModelSerializer):

    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True, default=None)

    class Meta:
        model = Notification
        fields = "__all__"
        read_only_fields = ["utilisateur", "dossier", "titre", "message", "date_creation"]

class RecherchePersonneSerializer(
    serializers.ModelSerializer
):

    crise_nom = serializers.CharField(
       source="crise.name",
       read_only=True
    )


    dernier_commentaire = serializers.SerializerMethodField()

    nb_photos_dernier_commentaire = (
        serializers.SerializerMethodField()
    )

    date_dernier_commentaire = (
        serializers.SerializerMethodField()
    )

    etat_utilisateur = (
        serializers.SerializerMethodField()
    )

    has_photo = serializers.SerializerMethodField()

    def get_has_photo(self, obj):
        return bool(obj.photo)

    def get_dernier_commentaire(
        self,
        obj
    ):

        commentaire = (
            obj.commentaires
            .order_by("-date_creation")
            .first()
        )

        if not commentaire:
            return ""

        return commentaire.commentaire

    def get_date_dernier_commentaire(
        self,
        obj
    ):

        commentaire = (
            obj.commentaires
            .order_by("-date_creation")
            .first()
        )

        if not commentaire:
            return None

        return commentaire.date_creation


    def get_nb_photos_dernier_commentaire(
        self,
        obj
    ):

        commentaire = (
            obj.commentaires
            .order_by("-date_creation")
            .first()
        )

        if not commentaire:
            return 0

        return commentaire.photos.count()




    def get_etat_utilisateur(
            self,
            obj
        ):

            request = self.context.get(
                "request"
            )

            if (
                not request
                or not request.user.is_authenticated
            ):
                return "NOUVEAU"

            lecture = (
                RecherchePersonneLecture.objects
                .filter(
                    recherche=obj,
                    utilisateur=request.user
                )
                .first()
            )

            if not lecture:
                return "NOUVEAU"

            derniere_activite = obj.date_creation

            commentaire = (
                obj.commentaires
                .order_by("-date_creation")
                .first()
            )

            if commentaire:
                derniere_activite = max(
                    derniere_activite,
                    commentaire.date_creation
                )

            if (
                lecture.date_dernier_acquittement
                and
                lecture.date_dernier_acquittement
                >= derniere_activite
            ):
                return "ACQUITTE"

            if (
                lecture.date_derniere_lecture
                and
                lecture.date_derniere_lecture
                >= derniere_activite
            ):
                return "VU"

            return "NOUVEAU"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['contact_email'] = mask_email(data.get('contact_email'))
            data['contact_telephone'] = mask_phone(data.get('contact_telephone'))
        return data

    class Meta:
        model = RecherchePersonne

        fields = [
            "id",
            "nom",
            "prenom",
            "age",  
            "photo",
            "description",
            "source",
            "ville",
            "adresse",
            "ehpad_nom",
            "ehpad_adresse",
            "contact_nom",
            "contact_email",
            "contact_telephone",
            "statut",
            "date_creation",
            "date_retrouvee",
            "createur",
            "crise",
            "crise_nom",
            "dernier_commentaire",
            "nb_photos_dernier_commentaire",
            "date_dernier_commentaire",
            "etat_utilisateur",
            "has_photo",
        ]



        read_only_fields = (
            "createur",
            "date_creation",
            "date_retrouvee",
        )

        extra_kwargs = {
            "photo": {"write_only": True},
        }


class RecherchePersonneCommentaireSerializer(
    serializers.ModelSerializer
):

    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = RecherchePersonneCommentaire
        fields = "__all__"

        read_only_fields = (
        "auteur",
        "date_creation",
    )

    def get_auteur_nom(self, obj):

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username

class RecherchePersonneHistoriqueSerializer(
    serializers.ModelSerializer
):
    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = RecherchePersonneHistorique
        fields = "__all__"

    def get_auteur_nom(self, obj):

        if not obj.auteur:
            return "Système"

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip()

class RecherchePersonnePhotoSerializer(
    serializers.ModelSerializer
):

    auteur_nom = serializers.SerializerMethodField()

    preview_url = (
        serializers.SerializerMethodField()
    )

    def get_preview_url(
        self,
        obj
    ):

        return (
            f"/api/"
            f"recherches-personnes-photos/"
            f"{obj.id}/preview/"
        )

    class Meta:

        model = RecherchePersonnePhoto

        fields = [
            "id",
            "recherche",
            "fichier",
            "auteur",
            "auteur_nom",
            "commentaire",
            "date_creation",
            "preview_url",
        ] 

        read_only_fields = (
            "auteur",
            "date_creation",
        )

        extra_kwargs = {'fichier': {'write_only': True}}

    def get_auteur_nom(self, obj):

        if not obj.auteur:
            return "Inconnu"

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username


class Meta:
    model = RecherchePersonneCommentaire
    fields = "__all__"
    read_only_fields = (
        "auteur",
    )

class RecherchePersonneLectureSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = RecherchePersonneLecture

        fields = "__all__"


class RecherchePersonneLectureHistoriqueSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = (
            RecherchePersonneLectureHistorique
        )

        fields = "__all__"

class InstitutionTypeSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = InstitutionType

        fields = "__all__"
class InstitutionSerializer(
    serializers.ModelSerializer
):

    type_libelle = serializers.CharField(
        source="type.libelle",
        read_only=True,
        default=None,
    )

    class Meta:

        model = Institution

        fields = "__all__"
class RoleOperationnelSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = RoleOperationnel

        fields = "__all__"
class InstitutionCompetenceSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = InstitutionCompetence

        fields = "__all__"
class AffectationRoleOperationnelSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = AffectationRoleOperationnel

        fields = "__all__"
class DelegationCompetenceSerializer(
    serializers.ModelSerializer
):

    institution_source_nom = serializers.CharField(source="institution_source.nom", read_only=True)
    institution_cible_nom = serializers.CharField(source="institution_cible.nom", read_only=True)
    competence_libelle = serializers.CharField(source="competence.nom", read_only=True)

    class Meta:

        model = DelegationCompetence

        fields = "__all__"

    def validate(self, attrs):
        # attrs['crise'] est absent sur un PATCH qui ne touche pas ce champ — retomber sur la
        # crise déjà rattachée à l'instance pour que le verrou s'applique à TOUTE modification
        # d'un objet lié à une crise fermée, pas seulement à une réaffectation de crise.
        crise = attrs.get('crise') or (self.instance.crise if self.instance else None)
        validate_crisis_open(crise, field_name="crise")

        institution_source = attrs.get('institution_source') or (
            self.instance.institution_source if self.instance else None
        )
        if crise and institution_source:
            deja_impliquee = ImplicationInstitution.objects.filter(
                crise=crise,
                institution=institution_source,
                type_implication__in=[TypeImplication.ACTEUR, TypeImplication.IMPLIQUE],
                actif=True,
            ).exists()
            if not deja_impliquee:
                raise serializers.ValidationError({
                    "institution_source": (
                        "Cette institution doit déjà être impliquée sur la crise pour"
                        " pouvoir déléguer une compétence."
                    )
                })

        institution_cible = attrs.get('institution_cible') or (
            self.instance.institution_cible if self.instance else None
        )
        if crise and institution_cible:
            cible_actrice = ImplicationInstitution.objects.filter(
                crise=crise,
                institution=institution_cible,
                type_implication=TypeImplication.ACTEUR,
                actif=True,
            ).exists()
            if not cible_actrice:
                raise serializers.ValidationError({
                    "institution_cible": (
                        "Cette institution doit être déclarée acteur opérationnel sur la"
                        " crise pour pouvoir recevoir une délégation de compétence."
                    )
                })

        return attrs
class DisponibiliteOperationnelleSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = DisponibiliteOperationnelle

        fields = "__all__"
class PointTypeSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = PointType

        fields = "__all__"
class PointOperationnelSerializer(
    serializers.ModelSerializer
):

    type_libelle = serializers.CharField(source="type.libelle", read_only=True, default=None)
    responsable_nom = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    competences_requises_libelles = serializers.SerializerMethodField()
    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    personnes_presentes = serializers.SerializerMethodField()

    class Meta:

        model = PointOperationnel

        fields = "__all__"

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_competences_requises_libelles(self, obj):
        return [c.nom for c in obj.competences_requises.all()]

    def get_personnes_presentes(self, obj):
        # Somme de `nombre` sur les lignes encore présentes (date_depart NULL) — affichage
        # immédiat dans le tableau des points, sans appel séparé au registre.
        return obj.registre_presences.filter(date_depart__isnull=True).aggregate(
            total=Sum('nombre')
        )['total'] or 0

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.username

    def validate(self, attrs):
        # attrs['crise'] est absent sur un PATCH qui ne touche pas ce champ — retomber sur la
        # crise déjà rattachée à l'instance pour que le verrou s'applique à TOUTE modification
        # d'un objet lié à une crise fermée, pas seulement à une réaffectation de crise.
        crise = attrs.get('crise') or (self.instance.crise if self.instance else None)
        validate_crisis_open(crise, field_name="crise")
        return attrs


class PointOperationnelPublicSerializer(serializers.ModelSerializer):
    """Version publique, à champs restreints, d'un point opérationnel — utilisée par le
    formulaire public "je suis en sécurité" (choix d'un centre d'accueil, suggestions de
    centres disponibles). Volontairement distincte de PointOperationnelSerializer : celui-ci
    expose aussi des champs internes (commentaire, responsable...) qui n'ont rien à faire
    devant le grand public."""

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    personnes_presentes = serializers.SerializerMethodField()

    class Meta:
        model = PointOperationnel
        fields = ['id', 'nom', 'adresse', 'latitude', 'longitude', 'capacite_accueil', 'personnes_presentes', 'crise']

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_personnes_presentes(self, obj):
        return obj.registre_presences.filter(date_depart__isnull=True).aggregate(
            total=Sum('nombre')
        )['total'] or 0


class ImplicationInstitutionSerializer(
    serializers.ModelSerializer
):

    institution_nom = serializers.CharField(source="institution.nom", read_only=True, default=None)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    utilisateur = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    responsable_nom = serializers.SerializerMethodField()
    themes_libelles = serializers.SerializerMethodField()
    responsable_email = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:

        model = ImplicationInstitution

        fields = "__all__"

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.email

    def get_themes_libelles(self, obj):
        return [t.nom for t in obj.themes.all()]

    def validate(self, attrs):
        # attrs['crise'] est absent sur un PATCH qui ne touche pas ce champ — retomber sur la
        # crise déjà rattachée à l'instance pour que le verrou s'applique à TOUTE modification
        # d'un objet lié à une crise fermée, pas seulement à une réaffectation de crise.
        crise = attrs.get('crise') or (self.instance.crise if self.instance else None)
        validate_crisis_open(crise, field_name="crise")
        return attrs



class ContactInstitutionSerializer(
    serializers.ModelSerializer
):

    utilisateur_nom = serializers.SerializerMethodField()
    utilisateur_email = serializers.CharField(source="utilisateur.email", read_only=True, default=None)

    class Meta:

        model = ContactInstitution

        fields = "__all__"

    def get_utilisateur_nom(self, obj):
        if not obj.utilisateur:
            return None
        full_name = f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip()
        return full_name or obj.utilisateur.email

class InstitutionDomaineSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = InstitutionDomaine

        fields = "__all__"


