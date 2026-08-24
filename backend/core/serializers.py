
import json
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .auth_validation import InstitutionEmailValidator
from .models import (
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
    User, Crisis, Request, Offer, Information,
    RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, RecherchePersonnePhoto, RecherchePersonneCommentairePhoto,
    DossierCommentaire, RecherchePersonne, RecherchePersonneCommentaire, RecherchePersonneHistorique,
    DossierHistorique, Besoin, BesoinCompetence,Dossier, RequestType, RequestTypeBesoin, OfferType, InformationType, Team, Competence, AffectationCompetence
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

class CompetenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Competence
        fields = "__all__"

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
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'type', 
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
        }

    def validate(self, attrs):
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

class CrisisSerializer(serializers.ModelSerializer):
    """Serializer pour les crises"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    zone_geojson = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)

    class Meta:
        model = Crisis
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_zone_geojson(self, obj):
        # GEOSGeometry.geojson est une propriété native de GeoDjango — pas besoin de
        # librairie de parsing WKT côté frontend, qui consomme directement ce GeoJSON.
        return json.loads(obj.zone.geojson) if obj.zone else None

class RequestSerializer(serializers.ModelSerializer):
    """Serializer pour les demandes d'aide"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)

    class Meta:
        model = Request
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None
    
    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

class OfferSerializer(serializers.ModelSerializer):
    """Serializer pour les offres d'aide"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)

    class Meta:
        model = Offer
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None
    
    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

class InformationSerializer(serializers.ModelSerializer):
    """Serializer pour les informations"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    
    class Meta:
        model = Information
        fields = '__all__'
    
    def get_latitude(self, obj):
        return obj.location.y if obj.location else None
    
    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

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

    class Meta:
        model  = Team
        fields = [
            'id', 'name', 'description', 'color', 'created_at',
            'leader',
            'member_ids',
            'assigned_crisis_ids',
            'assigned_offer_ids',
            'assigned_request_ids',
        ]
        read_only_fields = ['id', 'created_at']

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

    has_updates = serializers.SerializerMethodField()

    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Dossier
        fields = "__all__"

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

    class Meta:
        model = Document
        fields = "__all__"

    def get_auteur_nom(self, obj):

        if not obj.auteur:
            return "Inconnu"

        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username

class DossierCommentaireSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = DossierCommentaire
        fields = "__all__"

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
        ]



        read_only_fields = (
            "createur",
            "date_creation",
            "date_retrouvee",
        )


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

    class Meta:

        model = DelegationCompetence

        fields = "__all__"
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

    class Meta:

        model = PointOperationnel

        fields = "__all__"

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.username


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


