
import json
import os
import re
from django.db.models import Sum
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .auth_validation import InstitutionEmailValidator
from .geo_lookup import commune_from_code, commune_from_point, commune_center_from_code, commune_risques, commune_risques_date_maj
from .permissions import (
    INSTITUTIONAL_TYPES, get_active_environment, effective_role_or_none, mask_email, mask_phone,
    strip_masked_fields_in_demo, _peut_gerer_stock_point,
)
from .zone_scoping import object_in_viewer_zone
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
    TypePersonneAccueillie,
    ImplicationInstitution,
    TypeImplication,
    StatutImplication,
    User, Crisis, Request, RequestPhoto, Offer, OfferPhoto, OfferMessage, Information,
    RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, RecherchePersonnePhoto, RecherchePersonneCommentairePhoto,
    DossierCommentaire, RecherchePersonne, RecherchePersonneCommentaire, RecherchePersonneHistorique,
    DossierHistorique, Besoin, BesoinCompetence,Dossier, Mission, RequestType, RequestTypeBesoin, OfferType, InformationType, Team, Competence, AffectationCompetence,
    DernierePositionUtilisateur,
    DisponibiliteOffre,
    DisponibilitePointEquipe,
    MaterielPoint,
    MaterielCatalogue,
    ContributionMateriel,
    StatutMateriel,
    RegistrePresence,
    DeclarationSecurite,
    AffectationPointBenevole,
    Notification,
    AuditLog,
    Zone,
    Plan,
    JournalCollectivite,
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
    institution_nom = serializers.SerializerMethodField()
    institution_id = serializers.SerializerMethodField()
    needs_institution_setup = serializers.SerializerMethodField()
    ma_zone = serializers.SerializerMethodField()

    def _active_contact(self, obj):
        # institution_nom et institution_id faisaient chacun leur propre requête pour le même
        # ContactInstitution actif — mémorisé sur l'instance le temps de la sérialisation
        # (utile surtout en liste, ex: UserViewSet).
        cached = getattr(obj, '_active_contact_cache', 'unset')
        if cached != 'unset':
            return cached
        contact = obj.institutions.filter(actif=True).select_related('institution').first()
        obj._active_contact_cache = contact
        return contact

    def get_institution_nom(self, obj):
        contact = self._active_contact(obj)
        return contact.institution.nom if contact else None

    def get_institution_id(self, obj):
        # Utilisé côté frontend pour restreindre les sélecteurs de responsables/équipes d'un
        # point opérationnel aux seuls membres/équipes de SA PROPRE institution (jamais toute
        # la plateforme) — voir point-modal.component.ts.
        contact = self._active_contact(obj)
        return str(contact.institution_id) if contact else None

    def get_ma_zone(self, obj):
        # Niveau/nom déjà calculés et stockés par Institution.save() (secteur_override en
        # priorité, sinon déduit du type) — jamais recalculés ici. Basé sur User.institution
        # (le FK direct), la même source que _institution_commune_or_400/_institution_secteur_or_400
        # (core/views.py) utilisée par la Vue Ma Collectivité — pas ContactInstitution, qui est un
        # mécanisme distinct (voir institution_nom/institution_id ci-dessus).
        institution = getattr(obj, 'institution', None)
        if institution is None or not institution.commune_code:
            return None
        return {
            "niveau": institution.secteur_niveau_effectif,
            "nom": institution.secteur_nom,
            # Aléas de la commune de l'institution (API Géorisques) — simplification volontaire
            # tant que l'institution est de niveau "commune" (le cas le plus courant, une
            # mairie) : pour un secteur plus large (EPCI/département/région), ce sont pour
            # l'instant les seuls risques de LA commune de l'institution, pas l'agrégation de
            # tout le secteur (voir commune_risques).
            "risques": commune_risques(institution.commune_code),
            "risques_date_maj": commune_risques_date_maj(institution.commune_code),
        }

    def get_needs_institution_setup(self, obj):
        # Compte Autorité locale activé, mais pas encore rattaché à une institution (voir
        # UserViewSet.institution_suggestion/confirmer_institution/creer_mon_institution) — sert
        # au frontend à savoir s'il doit proposer l'écran "Finalisez votre inscription", y
        # compris à une reconnexion ultérieure si la personne avait quitté cet écran sans finir.
        return bool(obj.is_active and obj.type == UserRole.LOCAL_AUTHORITY and obj.pending_institution_name)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'type', 'demo_role',
                  'photo', 'phone_number', 'password', 'postal_code', 'enabled', 'is_active',
                  'institution_name', 'institution_type', 'commune_name', 'commune_code',
                  'institution_nom', 'institution_id', 'needs_institution_setup', 'ma_zone']
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'phone_number': {'required': False},
            'photo': {'required': False},
            'postal_code': {'required': False},
            'enabled': {'required': False},
            'demo_role': {'required': False},
            # is_active : jamais modifiable via un PATCH générique — seulement via
            # approve_account/reject_account/UserViewSet.perform_destroy/reactiver, qui
            # journalisent l'action (voir le commentaire "is_active est le champ réellement
            # vérifié par /api/token/" sur approve_account).
            'is_active': {'read_only': True},
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

        for field in ['institution_name', 'institution_type', 'commune_name', 'commune_code']:
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

        # LOCAL_AUTHORITY : rattachement à l'activation du lien magique (voir
        # AccountActivationView). ORGANIZED_RESCUE : pas de lien magique pour ce type (voir
        # register()), le rattachement AASC/RCSC se fait plus tard, à l'approbation du compte
        # (approve_account) — voir attach_secours_user_to_institution.
        if user_type in {UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE}:
            validated_data['pending_institution_name'] = pending_institution_name
            validated_data['pending_institution_type'] = pending_institution_type
            validated_data['pending_commune_name'] = pending_commune_name
            validated_data['pending_commune_code'] = pending_commune_code

        user = User.objects.create_user(**validated_data)

        return user

    def update(self, instance, validated_data):
        # `type`/`demo_role`/`enabled` restent dans Meta.fields pour qu'un acteur institutionnel
        # puisse les régler depuis la page Utilisateurs — mais UserViewSet.get_permissions()
        # autorise aussi un compte à modifier SON PROPRE profil (photo, téléphone...), et sans
        # ce filtre il pouvait au passage se réattribuer type=ADMIN ou s'auto-valider
        # (enabled=True) par la même requête : vérifié en le reproduisant, corrigé ici plutôt
        # qu'au niveau permission puisque le reste de la modification doit rester autorisé.
        request = self.context.get('request')
        is_institutional = bool(
            request and request.user.is_authenticated
            and effective_role_or_none(request) in INSTITUTIONAL_TYPES
        )
        if not is_institutional:
            for field in ('type', 'demo_role', 'enabled'):
                validated_data.pop(field, None)
        validated_data = strip_masked_fields_in_demo(request, validated_data, ('email', 'username', 'phone_number'))
        return super().update(instance, validated_data)

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
    author_nom = serializers.SerializerMethodField()
    commune = serializers.SerializerMethodField()
    has_photo = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()
    has_responsable_actif = serializers.SerializerMethodField()
    # `type` reste le code technique (ex: "INCENDIE") : `type_display` est le libellé humain
    # ("Incendie") à afficher partout côté frontend, jamais le code brut.
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Crisis
        fields = '__all__'
        extra_kwargs = {'photo': {'write_only': True}}

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_author_nom(self, obj):
        if not obj.author:
            return None
        return f"{obj.author.first_name} {obj.author.last_name}".strip() or obj.author.username

    def get_commune(self, obj):
        return commune_from_point(obj.location)

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
        # En Python sur .all() (réutilise prefetch_related('implications')) plutôt qu'un
        # .filter().exists() qui ignorerait le cache et relancerait une requête par crise.
        return any(i.responsable_id and i.actif for i in obj.implications.all())

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
    est_affectee = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = '__all__'
        # actif : jamais modifiable via un PATCH générique, uniquement via destroy/reactiver
        # (qui journalisent l'action, voir RequestViewSet.perform_destroy/reactiver).
        # deletion_token : jamais exposé en lecture, sinon n'importe quel visiteur du détail
        # public de la demande pourrait la supprimer lui-même via ce jeton.
        extra_kwargs = {
            'photo': {'write_only': True}, 'actif': {'read_only': True},
            'deletion_token': {'write_only': True},
        }

    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        # Corrige la faille identifiée par l'audit sécurité (voir zone_scoping.py) : un rôle
        # institutionnel seul ne suffit plus, il faut aussi que la demande soit dans la zone
        # de compétence de l'acteur (object_in_viewer_zone) — sinon n'importe quel acteur
        # institutionnel de la plateforme voyait le détail complet de n'importe quelle demande
        # nationale.
        if effective_role_or_none(request) in INSTITUTIONAL_TYPES and object_in_viewer_zone(request, obj):
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

    def get_est_affectee(self, obj):
        # RequestViewSet.vue_secteur annote nb_equipes_affectees (1 requête pour toute la
        # liste) — sans cette annotation (ex: détail d'une seule demande), retombe sur une
        # requête directe, comme distance_from_crisis_km ci-dessus.
        nb_equipes = getattr(obj, 'nb_equipes_affectees', None)
        if nb_equipes is not None:
            return nb_equipes > 0
        return obj.assigned_teams.exists()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._location_visible(instance):
            # Hors zone/anonyme : aucune donnée personnelle exposée, en PROD comme en DEMO —
            # pas juste un masquage réversible (mask_email/mask_phone), qui n'a de sens que
            # pour un acteur déjà autorisé mais en environnement de démonstration.
            data['location'] = None
            data['first_name_request'] = None
            data['last_name_request'] = None
            data['email_request'] = None
            data['phone_request'] = None
            data['author_email'] = None
        else:
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

    def update(self, instance, validated_data):
        request = self.context.get('request')
        validated_data = strip_masked_fields_in_demo(request, validated_data, ('email_request', 'phone_request'))
        return super().update(instance, validated_data)


class RequestPhotoSerializer(serializers.ModelSerializer):
    """Photo additionnelle d'une demande d'aide (galerie, 9 max en plus de la principale déjà
    stockée sur Request.photo) — voir RequestPhoto.__doc__."""

    class Meta:
        model = RequestPhoto
        fields = '__all__'
        extra_kwargs = {'image': {'write_only': True}}

    def validate(self, attrs):
        request_obj = attrs.get('request') or (self.instance.request if self.instance else None)
        if request_obj and request_obj.photos.count() >= 9:
            raise serializers.ValidationError({
                "image": "Maximum 9 photos additionnelles (10 au total avec la principale)."
            })
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
    mission_titre = serializers.CharField(source="mission.titre", read_only=True, default=None)
    materiel_catalogue_nom = serializers.CharField(source="materiel_catalogue.nom", read_only=True, default=None)
    # Dénormalisé pour repérer côté client les offres de soins médicaux/paramédicaux (calque
    # carte "Personnel secourisme") sans avoir à résoudre le FK offer_type séparément.
    offer_type_nom = serializers.CharField(source="offer_type.type", read_only=True, default=None)
    has_photo = serializers.SerializerMethodField()
    competences_libelles = serializers.SerializerMethodField()
    commune = serializers.SerializerMethodField()
    distance_from_crisis_km = serializers.SerializerMethodField()
    # Progression réelle d'une ressource affectée à une équipe (en attente/confirmé/en
    # transit/arrivé/décliné) — voir EngagementRessource, absent (None) tant que l'offre n'a
    # jamais été affectée comme ressource à une équipe.
    engagement_statut = serializers.CharField(source='engagement.statut', read_only=True, default=None)
    engagement_statut_libelle = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = '__all__'
        # actif : jamais modifiable via un PATCH générique, uniquement via destroy/reactiver
        # (qui journalisent l'action, voir OfferViewSet.perform_destroy/reactiver).
        # deletion_token/reponse_token : jamais exposés en lecture, sinon n'importe quel
        # visiteur du détail public de l'offre pourrait la supprimer ou usurper son
        # propriétaire (répondre/éditer) via ces jetons.
        extra_kwargs = {
            'photo': {'write_only': True}, 'actif': {'read_only': True},
            'deletion_token': {'write_only': True}, 'reponse_token': {'write_only': True},
        }

    def get_competences_libelles(self, obj):
        return [c.nom for c in obj.competences.all()]

    def get_engagement_statut_libelle(self, obj):
        engagement = getattr(obj, 'engagement', None)
        return engagement.get_statut_display() if engagement else None

    def _location_visible(self, obj) -> bool:
        # Même correctif que RequestSerializer._location_visible (voir son commentaire) : un
        # rôle institutionnel seul ne suffit plus, il faut aussi que l'offre soit dans la zone
        # de compétence de l'acteur. Offer n'a pas de branche "participant du dossier lié"
        # (contrairement à Request/Information) : seul le rôle+zone donne accès.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        return effective_role_or_none(request) in INSTITUTIONAL_TYPES and object_in_viewer_zone(request, obj)

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
        # `location` reste un champ générique auto-généré (écriture WKT inchangée) : on
        # masque juste sa valeur en LECTURE, pas la possibilité de l'écrire à la création.
        data = super().to_representation(instance)
        if not self._location_visible(instance):
            # Hors zone/anonyme : aucune donnée personnelle exposée, en PROD comme en DEMO —
            # voir RequestSerializer.to_representation pour le même principe.
            data['location'] = None
            data['first_name_offer'] = None
            data['last_name_offer'] = None
            data['email_offer'] = None
            data['phone_offer'] = None
            data['author_email'] = None
            data['author_phone'] = None
        else:
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

    def update(self, instance, validated_data):
        request = self.context.get('request')
        validated_data = strip_masked_fields_in_demo(request, validated_data, ('email_offer', 'phone_offer'))
        return super().update(instance, validated_data)


class OfferNationalPartialSerializer(serializers.ModelSerializer):
    """Vue "France entière (partiel)" d'OfferViewSet.vue_secteur (niveau national) : donne à
    tout acteur institutionnel, quel que soit son propre niveau de secteur, une vue d'ensemble
    nationale des offres — type/statut/crise/date uniquement, jamais les coordonnées/contact
    d'une institution tierce (nom, email, téléphone, localisation). Contrairement à
    OfferSerializer, jamais complet : ni masquage réversible (DEMO) ni détail nominatif."""
    offer_type_nom = serializers.CharField(source="offer_type.type", read_only=True, default=None)
    crisis_nom = serializers.CharField(source="crisis.name", read_only=True, default=None)

    class Meta:
        model = Offer
        fields = ['id', 'offer_type_nom', 'status', 'crisis_nom', 'created_at']


class OfferPhotoSerializer(serializers.ModelSerializer):
    """Photo additionnelle d'une offre d'aide (galerie, 9 max en plus de la principale déjà
    stockée sur Offer.photo) — voir OfferPhoto.__doc__."""

    class Meta:
        model = OfferPhoto
        fields = '__all__'
        extra_kwargs = {'image': {'write_only': True}}

    def validate(self, attrs):
        offer = attrs.get('offer') or (self.instance.offer if self.instance else None)
        if offer and offer.photos.count() >= 9:
            raise serializers.ValidationError({
                "image": "Maximum 9 photos additionnelles (10 au total avec la principale)."
            })
        return attrs


class OfferMessageSerializer(serializers.ModelSerializer):
    """Message du fil de discussion équipe ↔ propriétaire d'une offre — voir OfferMessage."""
    auteur_equipe_nom = serializers.SerializerMethodField()

    class Meta:
        model = OfferMessage
        fields = ['id', 'offer', 'auteur_equipe', 'auteur_equipe_nom', 'contenu', 'date_creation']
        extra_kwargs = {'auteur_equipe': {'read_only': True}}

    def get_auteur_equipe_nom(self, obj):
        if not obj.auteur_equipe_id:
            return None
        return f"{obj.auteur_equipe.first_name} {obj.auteur_equipe.last_name}".strip() or obj.auteur_equipe.email


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


class ContributionMaterielSerializer(serializers.ModelSerializer):
    """Un apport individuel de matériel — voir ContributionMateriel."""

    responsable_nom = serializers.SerializerMethodField()
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)

    class Meta:
        model = ContributionMateriel
        fields = '__all__'

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.email

    def validate(self, attrs):
        materiel_point = attrs.get('materiel_point') or (self.instance.materiel_point if self.instance else None)
        if materiel_point:
            validate_crisis_open(materiel_point.point.crise, field_name="crise")
        return attrs


class MaterielPointSerializer(serializers.ModelSerializer):
    """État du stock d'un item du catalogue matériel sur un point opérationnel."""

    item_nom = serializers.CharField(source="item.nom", read_only=True)
    niveau_stock_libelle = serializers.CharField(source="get_niveau_stock_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    responsable_nom = serializers.SerializerMethodField()
    quantite_totale = serializers.SerializerMethodField()

    class Meta:
        model = MaterielPoint
        fields = '__all__'

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.email

    def get_quantite_totale(self, obj):
        # Somme des apports actifs (voir ContributionMateriel) — None si aucun apport n'a
        # jamais été tracé sur cette ligne, pour distinguer "pas d'apport suivi" (utiliser
        # `quantite` manuel) de "0 apport actif restant" (tout a été retiré).
        result = obj.contributions.exclude(statut=StatutMateriel.RETIRE).aggregate(total=Sum('quantite'))
        return result['total']

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
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = DeclarationSecurite
        fields = '__all__'
        read_only_fields = ['id', 'date_declaration', 'declare_par', 'registre_presence']
        # `crise` reste obligatoire en base (jamais nullable), mais optionnelle à la saisie :
        # une entrée via le secrétariat d'un centre (voir DeclarationSecuriteViewSet.
        # perform_create) la déduit de centre_accueil.crise plutôt que de la faire ressaisir.
        extra_kwargs = {'crise': {'required': False}}

    def get_declare_par_nom(self, obj):
        if not obj.declare_par:
            return None
        full_name = f"{obj.declare_par.first_name} {obj.declare_par.last_name}".strip()
        return full_name or obj.declare_par.email

    # Même règle de confidentialité qu'InformationSerializer._location_visible : une adresse
    # personnelle, potentiellement celle d'une personne vulnérable/déplacée — jamais exposée
    # au grand public, seulement aux acteurs institutionnels.
    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        return effective_role_or_none(request) in INSTITUTIONAL_TYPES

    def get_latitude(self, obj):
        if not self._location_visible(obj):
            return None
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        if not self._location_visible(obj):
            return None
        return obj.location.x if obj.location else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._location_visible(instance):
            data['location'] = None
        return data

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
        # actif : jamais modifiable via un PATCH générique, uniquement via destroy/reactiver
        # (qui journalisent l'action, voir InformationViewSet.perform_destroy/reactiver).
        # deletion_token : jamais exposé en lecture, sinon n'importe quel visiteur du détail
        # public du signalement pourrait le supprimer lui-même via ce jeton.
        extra_kwargs = {
            'photo': {'write_only': True}, 'actif': {'read_only': True},
            'deletion_token': {'write_only': True},
        }

    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        # Même correctif que RequestSerializer._location_visible (voir son commentaire) : un
        # rôle institutionnel seul ne suffit plus, il faut aussi que le signalement soit dans
        # la zone de compétence de l'acteur.
        if effective_role_or_none(request) in INSTITUTIONAL_TYPES and object_in_viewer_zone(request, obj):
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
            # Hors zone/anonyme : aucune donnée personnelle exposée, en PROD comme en DEMO —
            # voir RequestSerializer.to_representation pour le même principe.
            data['location'] = None
            data['first_name_information'] = None
            data['last_name_information'] = None
            data['email_information'] = None
            data['phone_information'] = None
            data['author_email'] = None
        else:
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

    def update(self, instance, validated_data):
        request = self.context.get('request')
        validated_data = strip_masked_fields_in_demo(request, validated_data, ('email_information', 'phone_information'))
        return super().update(instance, validated_data)

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Serializer personnalisé pour l'authentification JWT"""
    username_field = 'email'

    def validate(self, attrs):
        data = super().validate(attrs)
        # On ajoute l'utilisateur sérialisé à la réponse
        data['user'] = UserSerializer(self.user).data
        return data

class ZoneSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    zone_precise_geojson = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = "__all__"
        # institution n'est jamais réaffectable via un PATCH générique — voir
        # ZoneViewSet.perform_create (résolue côté serveur), même politique que PlanSerializer.
        read_only_fields = ['id', 'institution']

    def get_zone_precise_geojson(self, obj):
        return json.loads(obj.zone_precise.geojson) if obj.zone_precise else None


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
    theme_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Besoin.objects.all(), source='themes', required=False
    )
    themes_libelles = serializers.SerializerMethodField()
    zone_precise_geojson = serializers.SerializerMethodField()
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    institution_delegataire_nom = serializers.CharField(
        source='institution_delegataire.nom', read_only=True, default=None
    )
    members_info = serializers.SerializerMethodField()
    leader_nom = serializers.SerializerMethodField()
    regulateur_nom = serializers.SerializerMethodField()
    vehicules_count = serializers.SerializerMethodField()
    mission_active_titre = serializers.CharField(source='mission_active.titre', read_only=True, default=None)
    mission_active_crise_id = serializers.CharField(source='mission_active.crise_id', read_only=True, default=None)
    mission_active_crise_nom = serializers.CharField(source='mission_active.crise.name', read_only=True, default=None)
    equipe_parente_nom = serializers.CharField(source='equipe_parente.name', read_only=True, default=None)
    sous_equipes_info = serializers.SerializerMethodField()
    commune_centre = serializers.SerializerMethodField()

    def get_commune_centre(self, obj):
        # Centre la minimap de la fiche équipe sur la commune de son institution — repli
        # simple et toujours disponible, indépendant de la zone d'intervention précise
        # (souvent non dessinée) — voir commune_center_from_code.
        code = obj.institution.commune_code if obj.institution_id else None
        return commune_center_from_code(code) if code else None

    class Meta:
        model  = Team
        fields = [
            'id', 'name', 'description', 'color', 'created_at', 'actif',
            'institution',
            'institution_nom',
            'commune_centre',
            'institution_delegataire',
            'institution_delegataire_nom',
            'equipe_parente',
            'equipe_parente_nom',
            'sous_equipes_info',
            'leader',
            'leader_nom',
            'regulateur',
            'regulateur_nom',
            'mission_active',
            'mission_active_titre',
            'mission_active_crise_id',
            'mission_active_crise_nom',
            'member_ids',
            'members_info',
            'vehicules_count',
            'assigned_crisis_ids',
            'assigned_offer_ids',
            'assigned_request_ids',
            'assigned_information_ids',
            'competence_ids',
            'theme_ids',
            'themes_libelles',
            'departements',
            'communes',
            'zone_precise',
            'zone_precise_geojson',
        ]
        # institution_delegataire/equipe_parente ne sont pas modifiables ici : elles ne doivent
        # changer que via les actions dédiées (definir_delegation/retirer_delegation,
        # rattacher_equipe/detacher_equipe), qui appliquent leurs propres gardes (historique,
        # anti-cycle) — un PATCH générique les contournerait.
        read_only_fields = ['id', 'created_at', 'actif', 'institution_delegataire', 'equipe_parente']

    def get_zone_precise_geojson(self, obj):
        return json.loads(obj.zone_precise.geojson) if obj.zone_precise else None

    def get_sous_equipes_info(self, obj):
        return [{"id": str(s.id), "nom": s.name} for s in obj.sous_equipes.all()]

    def get_themes_libelles(self, obj):
        return [t.nom for t in obj.themes.all()]

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

    def get_vehicules_count(self, obj):
        # Ressources de type Transport affectées à l'équipe — même source que "leur matériel"
        # (Team.assigned_offers), voir PointOperationnelViewSet.vue_operationnelle. Filtré en
        # Python (pas .filter() côté DB) pour réutiliser le prefetch_related('assigned_offers')
        # de TeamViewSet.queryset — un .filter() sur un manager déjà prefetch ignore le cache et
        # relance une requête par équipe.
        return sum(1 for o in obj.assigned_offers.all() if o.offer_type_id and o.offer_type.type == "Transport")

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
        read_only=True,
        default=None,
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


def _regulateurs_pour_dossier(dossier, equipe=None):
    """Duplique volontairement `views._regulateurs_pour_dossier` (même logique exacte) plutôt
    que d'importer depuis views.py, qui importe déjà ce module — importer dans l'autre sens
    créerait un cycle. Même patron déjà accepté ailleurs dans ce fichier pour de petites
    fonctions de garde partagées."""
    if dossier.competence:
        return User.objects.filter(
            affectations_roles__competence=dossier.competence,
            affectations_roles__role__code="REGULATEUR",
            affectations_roles__actif=True,
        ).distinct()
    if equipe:
        member_ids = equipe.members.values_list('id', flat=True)
        regulateur_affectations = AffectationRoleOperationnel.objects.filter(
            utilisateur_id__in=member_ids, role__code="REGULATEUR", actif=True,
        )
        competence_ids = list(equipe.competences.values_list('id', flat=True))
        if competence_ids:
            regulateur_affectations = regulateur_affectations.filter(competence_id__in=competence_ids)
        return User.objects.filter(
            id__in=regulateur_affectations.values_list('utilisateur_id', flat=True)
        ).distinct()
    return User.objects.none()


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

    priorite_libelle = serializers.CharField(
        source='get_priorite_display',
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
    has_photo = serializers.SerializerMethodField()
    commune = serializers.SerializerMethodField()
    contact_nom = serializers.SerializerMethodField()
    contact_telephone = serializers.SerializerMethodField()
    contact_email = serializers.SerializerMethodField()
    description_origine = serializers.SerializerMethodField()
    regulateurs = serializers.SerializerMethodField()

    class Meta:
        model = Dossier
        fields = "__all__"
        # important/date_signalement_important : jamais modifiables via un PATCH générique,
        # uniquement via DossierViewSet.marquer_important (qui notifie les régulateurs).
        extra_kwargs = {
            'important': {'read_only': True},
            'date_signalement_important': {'read_only': True},
        }

    def _origine(self, obj):
        return obj.demande or obj.information

    def get_description_origine(self, obj):
        # `description` sur Dossier lui-même est un texte généré automatiquement à
        # l'affectation ("Demande affectée à l'équipe X : <titre>"), jamais ce que la personne
        # a réellement écrit — ce champ-ci restitue la vraie description saisie sur la demande
        # d'origine (un signalement n'a pas de description séparée, voir Information.__doc__
        # ailleurs dans ce fichier : son titre porte déjà l'information complète).
        if obj.demande:
            return obj.demande.description
        return None

    def get_latitude(self, obj):
        # Pas de gating supplémentaire ici : un Dossier n'est jamais listable publiquement
        # (DossierViewSet.get_queryset le restreint déjà aux institutionnels ou aux
        # participants), donc quiconque peut voir CE dossier peut voir sa localisation.
        origine = self._origine(obj)
        return origine.location.y if origine and origine.location else None

    def get_longitude(self, obj):
        origine = self._origine(obj)
        return origine.location.x if origine and origine.location else None

    def get_has_photo(self, obj):
        # Sert à décider côté frontend s'il faut tenter RequestViewSet.preview /
        # InformationViewSet.preview (même contrôle d'accès que la demande/le signalement
        # d'origine, via user_can_view_photo(..., dossiers_field='dossiers') — un participant
        # du dossier y a déjà droit) plutôt que d'appeler l'endpoint à l'aveugle.
        origine = self._origine(obj)
        return bool(origine and origine.photo)

    def get_commune(self, obj):
        origine = self._origine(obj)
        if not origine or not origine.location:
            return None
        if obj.demande and obj.demande.commune_code:
            return commune_from_code(obj.demande.commune_code) or commune_from_point(origine.location)
        return commune_from_point(origine.location)

    def get_contact_nom(self, obj):
        # Même logique de visibilité que latitude/longitude ci-dessus : pas de gating
        # supplémentaire, l'accès au dossier lui-même suffit.
        if obj.demande:
            full_name = f"{obj.demande.first_name_request} {obj.demande.last_name_request}".strip()
            return full_name or None
        if obj.information:
            full_name = f"{obj.information.first_name_information} {obj.information.last_name_information}".strip()
            return full_name or None
        return None

    def get_contact_telephone(self, obj):
        if obj.demande:
            return obj.demande.phone_request
        if obj.information:
            return obj.information.phone_information
        return None

    def get_contact_email(self, obj):
        if obj.demande:
            return obj.demande.email_request
        if obj.information:
            return obj.information.email_information
        return None

    def get_regulateurs(self, obj):
        # Rappel logistique pour les intervenants terrain (voir dossier-suivi) : contrairement
        # aux autres coordonnées ci-dessus, jamais exposées nulle part pour un Dossier avant ce
        # correctif. get_queryset() de DossierViewSet garantit déjà que seul un participant du
        # dossier (ou un institutionnel) peut lire CE dossier — pas de garde supplémentaire ici,
        # seul le masquage DEMO ci-dessous s'applique (comme les autres contacts de ce
        # serializer).
        regulateurs = _regulateurs_pour_dossier(obj, obj.equipe)
        return [
            {
                'id': str(r.id),
                'nom': (f"{r.first_name} {r.last_name}".strip() or r.email),
                'email': r.email,
                'telephone': r.phone_number,
            }
            for r in regulateurs
        ]

    def get_has_updates(self, obj):
        # get_unread_count() coûte jusqu'à 3 requêtes (participant + 2 count()) : les deux
        # champs le déclenchaient chacun séparément (has_updates ET unread_count sont tous les
        # deux exposés), doublant inutilement ce coût pour chaque dossier d'une liste. Mémorisé
        # sur l'instance le temps de la sérialisation.
        return self.get_unread_count(obj) > 0

    def get_unread_count(self, obj):
        cached = getattr(obj, '_unread_count_cache', None)
        if cached is not None:
            return cached
        result = self._compute_unread_count(obj)
        obj._unread_count_cache = result
        return result

    def _compute_unread_count(self, obj):
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

    def to_representation(self, instance):
        # Même politique que RequestSerializer/InformationSerializer : en zone DEMO, jamais de
        # vraie coordonnée de contact affichée, même à un compte institutionnel ou à un chef
        # d'équipe — sinon ce serializer contournerait le masquage déjà en place sur la
        # demande/le signalement d'origine. Idem pour le contact régulateur (rappel logistique,
        # voir get_regulateurs) : mêmes coordonnées personnelles, même garde.
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['contact_email'] = mask_email(data.get('contact_email'))
            data['contact_telephone'] = mask_phone(data.get('contact_telephone'))
            for regulateur in data.get('regulateurs') or []:
                regulateur['email'] = mask_email(regulateur.get('email'))
                regulateur['telephone'] = mask_phone(regulateur.get('telephone'))
        return data

def _gps_dms_to_decimal(dms_str, ref):
    """Convertit un tag GPS EXIF degrés/minutes/secondes tel que stringifié par
    extract_exif_metadata ("(deg, min, sec)", voir views.py) en degrés décimaux. None si le
    format est illisible plutôt que de faire échouer tout le serializer pour une photo."""
    match = re.match(r'\(([\d.]+),\s*([\d.]+),\s*([\d.]+)\)', dms_str or '')
    if not match:
        return None
    degrees, minutes, seconds = (float(g) for g in match.groups())
    decimal = degrees + minutes / 60 + seconds / 3600
    return -decimal if ref in ('S', 'W') else decimal


class DocumentSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()
    nom_fichier = serializers.SerializerMethodField()
    metadata_privees = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    azimuth = serializers.SerializerMethodField()

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

    def _metadata_privees_visible(self, obj) -> bool:
        # Métadonnées EXIF sensibles (GPS notamment) : réservées à l'auteur du document et aux
        # acteurs institutionnels — SAUF pour une photo rattachée à un Dossier, où tout
        # participant du dossier y a accès aussi (décision explicite : les coéquipiers d'un
        # même dossier ont besoin de la localisation des photos les uns des autres pour la
        # minimap de suivi terrain, voir dossier-suivi). Une photo d'offre/demande (obj.dossier
        # absent) garde la restriction stricte d'origine.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if user.id == obj.auteur_id or effective_role_or_none(request) in INSTITUTIONAL_TYPES:
            return True
        return bool(obj.dossier_id and obj.dossier.participants.filter(utilisateur=user).exists())

    def get_metadata_privees(self, obj):
        return obj.metadata_privees if self._metadata_privees_visible(obj) else {}

    def get_latitude(self, obj):
        if not self._metadata_privees_visible(obj):
            return None
        meta = obj.metadata_privees
        lat = meta.get('GPSLatitude')
        ref = meta.get('GPSLatitudeRef')
        return _gps_dms_to_decimal(lat, ref) if lat and ref else None

    def get_longitude(self, obj):
        if not self._metadata_privees_visible(obj):
            return None
        meta = obj.metadata_privees
        lon = meta.get('GPSLongitude')
        ref = meta.get('GPSLongitudeRef')
        return _gps_dms_to_decimal(lon, ref) if lon and ref else None

    def get_azimuth(self, obj):
        if not self._metadata_privees_visible(obj):
            return None
        direction = obj.metadata_privees.get('GPSImgDirection')
        if direction is None:
            return None
        try:
            return float(direction)
        except ValueError:
            return None

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


class JournalCollectiviteSerializer(serializers.ModelSerializer):
    """Entrée du journal de bord de la Vue Ma Collectivité — auteur/institution/date_creation en
    lecture seule (posés par JournalCollectiviteViewSet.perform_create, jamais par le client) ;
    aucun champ n'est modifiable après création, cohérent avec l'absence de route update/delete
    (voir JournalCollectiviteViewSet)."""

    auteur_nom = serializers.SerializerMethodField()
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)

    class Meta:
        model = JournalCollectivite
        fields = ['id', 'institution', 'crise', 'crise_nom', 'auteur', 'auteur_nom', 'contenu', 'date_creation']
        read_only_fields = ['id', 'institution', 'auteur', 'date_creation']

    def get_auteur_nom(self, obj):
        if not obj.auteur:
            return "Inconnu"
        return (
            f"{obj.auteur.first_name} "
            f"{obj.auteur.last_name}"
        ).strip() or obj.auteur.username


class AuditLogSerializer(serializers.ModelSerializer):
    """Lecture seule — voir AuditLogViewSet, toujours interrogé avec ?objet_type=&objet_id=,
    jamais en liste globale."""

    utilisateur_nom = serializers.SerializerMethodField()
    action_libelle = serializers.CharField(source='action.libelle', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ['id', 'date_action', 'utilisateur_nom', 'action_libelle', 'objet_type', 'objet_id', 'commentaire']

    def get_utilisateur_nom(self, obj):
        if not obj.utilisateur:
            return "Système"
        return f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip() or obj.utilisateur.username


class AuditLogAdminSerializer(serializers.ModelSerializer):
    """Vue complète de la main courante, réservée à AuditLogViewSet.list/export en mode
    consultation globale (administrateur, sans ?objet_type=&objet_id=) — contrairement à
    AuditLogSerializer (widget d'historique par fiche), expose aussi l'adresse IP, le
    user-agent, l'institution et le statut succès/échec : c'est le registre RGPD complet, pas
    un simple fil d'activité."""

    utilisateur_email = serializers.CharField(source='utilisateur.email', read_only=True, default=None)
    utilisateur_nom = serializers.SerializerMethodField()
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    action_code = serializers.CharField(source='action.code', read_only=True, default=None)
    action_libelle = serializers.CharField(source='action.libelle', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'date_action', 'utilisateur_email', 'utilisateur_nom', 'institution_nom',
            'adresse_ip', 'user_agent', 'action_code', 'action_libelle', 'objet_type',
            'objet_id', 'commentaire', 'succes', 'environment',
        ]

    def get_utilisateur_nom(self, obj):
        if not obj.utilisateur:
            return "Système / anonyme"
        return f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip() or obj.utilisateur.username


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
        read_only_fields = ["utilisateur", "dossier", "crise", "titre", "message", "date_creation"]

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

    def _dernier_commentaire(self, obj):
        # dernier_commentaire/date_dernier_commentaire/nb_photos_dernier_commentaire et
        # etat_utilisateur refaisaient chacun la même requête "dernier commentaire" — mémorisé
        # sur l'instance le temps de la sérialisation (jusqu'à 4 requêtes identiques par fiche
        # en liste).
        cached = getattr(obj, '_dernier_commentaire_cache', 'unset')
        if cached != 'unset':
            return cached
        commentaire = obj.commentaires.order_by("-date_creation").first()
        obj._dernier_commentaire_cache = commentaire
        return commentaire

    def get_dernier_commentaire(
        self,
        obj
    ):

        commentaire = self._dernier_commentaire(obj)

        if not commentaire:
            return ""

        return commentaire.commentaire

    def get_date_dernier_commentaire(
        self,
        obj
    ):

        commentaire = self._dernier_commentaire(obj)

        if not commentaire:
            return None

        return commentaire.date_creation


    def get_nb_photos_dernier_commentaire(
        self,
        obj
    ):

        commentaire = self._dernier_commentaire(obj)

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

            commentaire = self._dernier_commentaire(obj)

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

    def update(self, instance, validated_data):
        # secteur_override élargit potentiellement la visibilité jusqu'à "national" — jamais
        # laissé passer par la permission générale d'édition d'institution
        # (IsInstitutionMemberOrAdministrator, voir InstitutionViewSet.get_permissions).
        # Restriction supplémentaire ici, à dessein plus stricte et différente selon
        # l'environnement actif : en PROD, réservé au(x) super-admin(s) Django (is_superuser) ;
        # en DEMO (bac à sable, enjeu moindre), tout membre actif de CETTE institution peut le
        # régler — usage prévu : simuler un secteur de test (voir Institution.secteur_override).
        if "secteur_override" in validated_data:
            request = self.context.get("request")
            if not self._can_edit_secteur_override(request, instance):
                validated_data.pop("secteur_override")
        return super().update(instance, validated_data)

    def _can_edit_secteur_override(self, request, institution):
        if request is None or not getattr(request.user, "is_authenticated", False):
            return False
        if get_active_environment(request) == Environment.PROD:
            return request.user.is_superuser
        return ContactInstitution.objects.filter(
            institution=institution, utilisateur=request.user, actif=True,
            environment=get_active_environment(request),
        ).exists()
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
                statut=StatutImplication.VALIDEE,
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
                statut=StatutImplication.VALIDEE,
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
    # Dénormalisé pour filtrer côté client de façon fiable (ex: "SECOURS" pour le calque carte
    # "Centres secours/soins") sans dépendre du libellé humain, qui peut changer.
    type_code = serializers.CharField(source="type.code", read_only=True, default=None)
    responsable_nom = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    competences_requises_libelles = serializers.SerializerMethodField()
    equipe_nom = serializers.CharField(source="equipe.name", read_only=True, default=None)
    crise_nom = serializers.CharField(source="crise.name", read_only=True, default=None)
    personnes_presentes = serializers.SerializerMethodField()
    responsables_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.all(), source='responsables', required=False
    )
    # Contact complet (nom/email/téléphone) de tous les responsables de ce point — `responsable`
    # (champ historique) + `responsables` (M2M) + chefs des équipes de gestion, dédoublonnés :
    # voir point_responsables_contacts(). Affiché dans la comparaison de stocks entre centres.
    responsables_contacts = serializers.SerializerMethodField()
    equipes_gestion_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Team.objects.all(), source='equipes_gestion', required=False
    )
    equipes_gestion_noms = serializers.SerializerMethodField()
    equipes_ravitaillement_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Team.objects.all(), source='equipes_ravitaillement', required=False
    )
    equipes_ravitaillement_noms = serializers.SerializerMethodField()
    civils_accueillis = serializers.SerializerMethodField()
    peut_gerer = serializers.SerializerMethodField()
    commune_nom = serializers.SerializerMethodField()

    class Meta:

        model = PointOperationnel

        fields = "__all__"

    def get_commune_nom(self, obj):
        # Même mécanisme de reverse-géocodage que le scoping zone (_filter_points_to_viewer_zone) —
        # PointOperationnel n'a pas de commune_code dénormalisé, seulement un point GPS.
        return commune_from_point(obj.location)

    def get_peut_gerer(self, obj):
        # Reflète exactement la règle déjà appliquée côté API (RegistrePresenceViewSet.
        # _can_manage / _peut_gerer_stock_point) — les boutons "Secrétariat"/"Stock" du détail
        # centre n'étaient conditionnés côté frontend que par isEdit (point déjà créé), sans
        # refléter les droits réels : n'importe quel utilisateur authentifié voyait ces
        # boutons, y compris s'ils menaient ensuite à un 403.
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return _peut_gerer_stock_point(request, obj)

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

    def get_civils_accueillis(self, obj):
        # Sous-ensemble de personnes_presentes : uniquement les évacués (pas les pompiers/
        # bénévoles d'autres équipes, déjà comptés ailleurs comme personnel).
        return obj.registre_presences.filter(
            date_depart__isnull=True, type_personne=TypePersonneAccueillie.EVACUE
        ).aggregate(total=Sum('nombre'))['total'] or 0

    def get_responsable_nom(self, obj):
        if not obj.responsable:
            return None
        full_name = f"{obj.responsable.first_name} {obj.responsable.last_name}".strip()
        return full_name or obj.responsable.username

    def get_responsables_contacts(self, obj):
        return [
            {
                "id": str(u.id),
                "nom": (f"{u.first_name} {u.last_name}".strip() or u.username),
                "email": u.email,
                "telephone": u.phone_number,
            }
            for u in obj.responsables_effectifs()
        ]

    def get_equipes_gestion_noms(self, obj):
        noms = [t.name for t in obj.equipes_gestion.all()]
        if obj.equipe and obj.equipe.name not in noms:
            noms.append(obj.equipe.name)
        return noms

    def get_equipes_ravitaillement_noms(self, obj):
        return [t.name for t in obj.equipes_ravitaillement.all()]

    def validate(self, attrs):
        # attrs['crise'] est absent sur un PATCH qui ne touche pas ce champ — retomber sur la
        # crise déjà rattachée à l'instance pour que le verrou s'applique à TOUTE modification
        # d'un objet lié à une crise fermée, pas seulement à une réaffectation de crise.
        crise = attrs.get('crise') or (self.instance.crise if self.instance else None)
        validate_crisis_open(crise, field_name="crise")
        return attrs


class PlanSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    zones_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Zone.objects.all(), source='zones', required=False
    )
    zones_noms = serializers.SerializerMethodField()
    equipes_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Team.objects.all(), source='equipes', required=False
    )
    equipes_noms = serializers.SerializerMethodField()
    points_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=PointOperationnel.objects.all(), source='points', required=False
    )
    points_noms = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = "__all__"
        # institution n'est jamais réaffectable via un PATCH générique — voir
        # PlanViewSet.perform_create (résolue côté serveur).
        read_only_fields = ['id', 'institution']

    def get_zones_noms(self, obj):
        return [z.nom for z in obj.zones.all()]

    def get_equipes_noms(self, obj):
        return [t.name for t in obj.equipes.all()]

    def get_points_noms(self, obj):
        return [p.nom for p in obj.points.all()]


class PointOperationnelPublicSerializer(serializers.ModelSerializer):
    """Version publique, à champs restreints, d'un point opérationnel — utilisée par le
    formulaire public "je suis en sécurité" (choix d'un centre d'accueil, suggestions de
    centres disponibles). Volontairement distincte de PointOperationnelSerializer : celui-ci
    expose aussi des champs internes (commentaire, responsable...) qui n'ont rien à faire
    devant le grand public."""

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    personnes_presentes = serializers.SerializerMethodField()
    # Le type lui-même n'a rien de sensible (un centre d'accueil doit justement être identifiable
    # publiquement) — utile pour distinguer centres d'accueil / postes de secours sur la carte
    # publique (voir PointOperationnelViewSet.carte_publique).
    type_code = serializers.CharField(source="type.code", read_only=True, default=None)
    type_libelle = serializers.CharField(source="type.libelle", read_only=True, default=None)

    class Meta:
        model = PointOperationnel
        fields = ['id', 'nom', 'adresse', 'latitude', 'longitude', 'capacite_accueil', 'personnes_presentes', 'crise', 'type_code', 'type_libelle']

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
    # Jamais posé par le client (création/modification) : uniquement par perform_create (voir
    # ImplicationInstitutionViewSet) et par les actions valider/refuser dédiées, sans quoi une
    # institution non-AUT_LOCALE pourrait s'auto-valider en envoyant simplement statut=VALIDEE.
    statut = serializers.ChoiceField(choices=StatutImplication.choices, read_only=True)
    peut_valider = serializers.SerializerMethodField()

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

    def get_peut_valider(self, obj):
        """True si l'utilisateur courant peut valider/refuser CETTE déclaration en attente —
        régulateur AUT_LOCALE d'une institution elle-même impliquée (validée, active) sur la
        même crise. Piloté par le même calcul que ImplicationInstitutionViewSet.valider/refuser,
        pour que le bouton n'apparaisse jamais là où l'action serait de toute façon refusée."""
        if obj.statut != StatutImplication.EN_ATTENTE:
            return False
        request = self.context.get('request')
        if request is None:
            return False
        from .permissions import is_regulateur_aut_locale_de_la_crise
        return is_regulateur_aut_locale_de_la_crise(request, obj.crise)

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


