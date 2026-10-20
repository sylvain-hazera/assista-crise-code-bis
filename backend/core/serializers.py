
import json
import os
import re
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .auth_validation import InstitutionEmailValidator
from .geo_lookup import (
    commune_from_code, commune_from_point, commune_from_code_cached, commune_from_point_cached,
    commune_center_from_code, commune_risques, commune_risques_date_maj,
)
from .permissions import (
    INSTITUTIONAL_TYPES, get_active_environment, effective_role_or_none, mask_email, mask_phone,
    strip_masked_fields_in_demo, _peut_gerer_stock_point,
)
from .zone_scoping import object_in_viewer_zone, object_in_viewer_zone_via_commune
from .models import (
    Environment,
    UserRole,
    InstitutionType,
    DemandeMobilisation,
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
    DossierHistorique, Besoin, BesoinCompetence, BesoinMateriel, Dossier, Mission, RequestType, RequestTypeBesoin, OfferType, InformationType, OfferTypeBesoin, InformationTypeBesoin, Team, Competence, AffectationCompetence,
    DernierePositionUtilisateur,
    DisponibiliteOffre,
    DisponibilitePointEquipe,
    MaterielPoint,
    MaterielCatalogue,
    CompagnonMeshCore,
    NoeudMeshUtilisateur,
    MessageMeshLog,
    CommandeMeshCore,
    TracerouteMeshCore,
    AlerteMeshSOS,
    ConfigurationAlerteSismique,
    InterlocuteurAlertePCS,
    NotificationAlertePCS,
    SecteurRecherche,
    RelaisMeshCore,
    Satellite,
    JetonEnrolementSatellite,
    ConflitSynchronisation,
    CanalMeshCore,
    CanalMeshCoreDetecte,
    MessageCanalMeshCore,
    SalonMatrixEquipe,
    SalonMatrixInstitution,
    TypeSalonInstitution,
    ContactMeshCore,
    CompagnonMeshtastic,
    CanalMeshtastic,
    MessageMeshtasticLog,
    MessageCanalMeshtastic,
    ContactMeshtastic,
    NoeudUtilisateurMeshtastic,
    ContributionMateriel,
    StatutMateriel,
    RegistrePresence,
    SuiviMaterielEvenement,
    DeclarationSecurite,
    RisqueMajeurType,
    RisqueCommunal,
    TypeVulnerabilite,
    PersonneVulnerable,
    AffectationPointBenevole,
    Notification,
    AuditLog,
    Zone,
    Plan,
    PlanMissionModele,
    JournalCollectivite,
    Habitation,
    HabitationCommentaire,
    HabitationHistorique,
    RattachementHabitation,
    StatutRattachementHabitation,
    ModuleDegatsCrise,
    PieceIdentiteReserve,
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

class BesoinMaterielSerializer(serializers.ModelSerializer):

    besoin_nom = serializers.CharField(
        source='besoin.nom',
        read_only=True
    )

    materiel_nom = serializers.CharField(
        source='materiel.nom',
        read_only=True
    )

    class Meta:
        model = BesoinMateriel
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

class OfferTypeBesoinSerializer(serializers.ModelSerializer):

    offer_type_nom = serializers.CharField(
        source='offer_type.type',
        read_only=True
    )

    besoin_nom = serializers.CharField(
        source='besoin.nom',
        read_only=True
    )

    class Meta:
        model = OfferTypeBesoin
        fields = "__all__"

class InformationTypeBesoinSerializer(serializers.ModelSerializer):

    information_type_nom = serializers.CharField(
        source='information_type.type',
        read_only=True
    )

    besoin_nom = serializers.CharField(
        source='besoin.nom',
        read_only=True
    )

    class Meta:
        model = InformationTypeBesoin
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
    institution_type_code = serializers.SerializerMethodField()
    needs_institution_setup = serializers.SerializerMethodField()
    reserve_a_verifier = serializers.SerializerMethodField()
    acces_registre_vulnerables = serializers.SerializerMethodField()
    ma_zone = serializers.SerializerMethodField()
    # photo est write_only : l'image passe par l'action preview, qui vérifie les droits à chaque
    # appel.
    photo_url = serializers.SerializerMethodField()

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        return f"/api/users/{obj.id}/preview/"

    def _active_contact(self, obj):
        # ContactInstitution actif mémorisé pendant la sérialisation (institution_nom et
        # institution_id).
        cached = getattr(obj, '_active_contact_cache', 'unset')
        if cached != 'unset':
            return cached
        prefetch = getattr(obj, 'contacts_actifs_prefetch', None)   # UserViewSet, en liste
        if prefetch is not None:
            contact = prefetch[0] if prefetch else None
        else:
            contact = obj.institutions.filter(actif=True).select_related('institution__type').first()
        obj._active_contact_cache = contact
        return contact

    def get_institution_nom(self, obj):
        contact = self._active_contact(obj)
        return contact.institution.nom if contact else None

    def get_institution_type_code(self, obj):
        # Même critère que _institution_est_autorite_locale (core/views.py).
        contact = self._active_contact(obj)
        return contact.institution.type.code if contact and contact.institution.type else None

    def get_institution_id(self, obj):
        # Restreint côté frontend les responsables d'un point aux membres de sa propre institution.
        contact = self._active_contact(obj)
        return str(contact.institution_id) if contact else None

    def get_ma_zone(self, obj):
        # Calculés par Institution.save(), à partir de User.institution (pas de
        # ContactInstitution).
        institution = getattr(obj, 'institution', None)
        if institution is None or not institution.commune_code:
            return None
        # Aléas lus une fois par commune pour toute une liste d'utilisateurs (souvent de la
        # même institution) au lieu de 2 lectures par utilisateur.
        memo = self.context.setdefault('_risques_par_commune', {})
        if institution.commune_code not in memo:
            memo[institution.commune_code] = (
                commune_risques(institution.commune_code),
                commune_risques_date_maj(institution.commune_code),
            )
        risques, risques_date_maj = memo[institution.commune_code]
        return {
            "niveau": institution.secteur_niveau_effectif,
            "nom": institution.secteur_nom,
            # Risques de la seule commune de l'institution, même pour un secteur plus large.
            "risques": risques,
            "risques_date_maj": risques_date_maj,
        }

    def get_needs_institution_setup(self, obj):
        # Autorité locale activée mais sans institution : le frontend propose « Finalisez votre
        # inscription ».
        return bool(obj.is_active and obj.type == UserRole.LOCAL_AUTHORITY and obj.pending_institution_name)

    def get_reserve_a_verifier(self, obj):
        # Candidature à la réserve non encore traitée : bannière « à vérifier ».
        return bool(obj.souhaite_rejoindre_reserve and not obj.reserve_verifiee)

    def get_acces_registre_vulnerables(self, obj):
        # Affichage du menu seulement ; l'accès réel est contrôlé par core/vulnerabilites.py.
        from .vulnerabilites import NOM_COMPETENCE_VULNERABILITES, utilisateur_a_acces_rcsc

        institution = getattr(obj, 'institution', None)
        if institution is None:
            return False
        if obj.type == UserRole.ADMINISTRATOR:
            return True
        if obj.type == UserRole.LOCAL_AUTHORITY:
            return utilisateur_a_acces_rcsc(obj, institution)
        return DelegationCompetence.objects.filter(
            institution_cible=institution,
            competence__nom=NOM_COMPETENCE_VULNERABILITES,
            active=True,
        ).exists()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'type', 'demo_role',
                  'photo', 'photo_url', 'phone_number', 'password', 'postal_code', 'enabled', 'is_active',
                  'institution_name', 'institution_type', 'commune_name', 'commune_code',
                  'institution_nom', 'institution_id', 'institution_type_code',
                  'needs_institution_setup', 'ma_zone',
                  'souhaite_rejoindre_reserve', 'reserve_verifiee', 'reserve_a_verifier',
                  'acces_registre_vulnerables']
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'phone_number': {'required': False},
            'photo': {'required': False, 'write_only': True},
            'postal_code': {'required': False},
            'enabled': {'required': False},
            'demo_role': {'required': False},
            # is_active : seulement via les actions dédiées, qui journalisent.
            'is_active': {'read_only': True},
            # Seulement via UserViewSet.verifier_reserve (sinon un candidat pourrait se valider
            # lui-même).
            'reserve_verifiee': {'read_only': True},
        }

    def to_representation(self, instance):
        """En zone DEMO, email, téléphone et username (souvent l'email) sont masqués à
        l'affichage, jamais en base."""
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
        # Vérification limitée à la création : le formulaire d'édition ne renvoie pas les
        # informations d'inscription.
        if self.instance is None:
            email = attrs.get('email')
            user_type = attrs.get('type')
            request = self.context.get('request')

            if user_type == UserRole.ADMINISTRATOR:
                # ADMIN ne représente pas une institution : pas de domaine email à prouver. Seul un
                # administrateur authentifié peut créer un compte ADMIN (la validation de domaine
                # n'est pas un contrôle d'accès).
                is_requester_admin = bool(
                    request and request.user.is_authenticated
                    and effective_role_or_none(request) == UserRole.ADMINISTRATOR
                )
                if not is_requester_admin:
                    raise serializers.ValidationError(
                        {'type': "Seul un administrateur peut créer un compte Administrateur."}
                    )
            elif user_type == UserRole.LOCAL_AUTHORITY and not (attrs.get('institution_name') or '').strip():
                # Sans institution_name, le rattachement ne peut être ni proposé ni rappelé :
                # l'inscription AUT_LOCALE est rétrogradée en utilisateur simple (les secours RCSC
                # se rattachent à une mairie existante par commune).
                attrs['type'] = UserRole.SIMPLE_USER
            elif user_type in {UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE}:
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
        # Utilisés après confirmation de l'email (core/institution_attachment.py) : jamais de
        # rattachement sur la foi d'un email non vérifié.
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
            # is_active est le champ vérifié à la connexion (/api/token/) : enabled seul ne bloque
            # rien.
            validated_data['enabled'] = False
            validated_data['is_active'] = False

        # AUT_LOCALE : rattachement à l'activation du lien ; SECOURS : à l'approbation du compte
        # (attach_secours_user_to_institution).
        if user_type in {UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE}:
            validated_data['pending_institution_name'] = pending_institution_name
            validated_data['pending_institution_type'] = pending_institution_type
            validated_data['pending_commune_name'] = pending_commune_name
            validated_data['pending_commune_code'] = pending_commune_code

        user = User.objects.create_user(**validated_data)

        return user

    def update(self, instance, validated_data):
        # Un compte peut modifier son propre profil, mais pas type, demo_role ni enabled (sinon il
        # pourrait se donner ADMIN ou s'auto-valider).
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
    """Refuse tout rattachement à une crise clôturée (sans exiger de responsable, contrairement
    à validate_crisis_open_and_monitored). field_name : nom de la FK vers Crisis sur le
    serializer appelant."""
    if crisis is None:
        return
    if crisis.end_date is not None:
        raise serializers.ValidationError(
            {field_name: "Cette crise est clôturée : il n'est plus possible d'y apporter de modification."}
        )


def validate_crisis_open_and_monitored(crisis):
    """Dépôt de demande, offre ou information seulement sur une crise ouverte ayant un
    responsable."""
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
        # Pas de géocodage réseau en liste (coût par ligne) ; seulement sur un retrieve.
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return commune_from_point_cached(obj.location)
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
    """Demande d'aide. La localisation n'est visible que de la mairie, des secours et des
    bénévoles affectés au dossier ; null pour les autres."""
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
        # actif : seulement via destroy/reactiver (journalisés). Jetons jamais exposés.
        # email_request_bidx calculé par save(), jamais fourni par le client.
        extra_kwargs = {
            'photo': {'write_only': True}, 'actif': {'read_only': True},
            'deletion_token': {'write_only': True}, 'edition_token': {'write_only': True},
            'email_request_bidx': {'read_only': True},
        }

    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        # Rôle institutionnel et zone de compétence requis (zone_scoping.object_in_viewer_zone).
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
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return commune_from_code_cached(obj.commune_code) or commune_from_point_cached(obj.location)
        return commune_from_code(obj.commune_code) or commune_from_point(obj.location)

    def get_distance_from_crisis_km(self, obj):
        if not self._location_visible(obj):
            return None
        distance = getattr(obj, 'distance_from_crisis', None)
        return round(distance.km, 1) if distance is not None else None

    def get_est_affectee(self, obj):
        # Annoté par vue_secteur en liste ; requête directe sinon.
        nb_equipes = getattr(obj, 'nb_equipes_affectees', None)
        if nb_equipes is not None:
            return nb_equipes > 0
        return obj.assigned_teams.exists()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._location_visible(instance):
            # Hors zone ou anonyme : aucune donnée personnelle (le masquage DEMO ne concerne que
            # les acteurs autorisés).
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


class RequestPublicEditSerializer(serializers.ModelSerializer):
    """Modification par l'auteur via le lien email (edition_token), sans compte. Champs limités
    au contenu : ni status, ni request_type, ni identité."""

    class Meta:
        model = Request
        fields = [
            'description', 'hebergement_duree', 'type_loyer', 'loyer_montant_min',
            'loyer_montant_max', 'type_logement', 'niveau_logement', 'acces_etage',
            'nombre_pieces', 'nombre_chambres', 'capacite_adultes', 'capacite_enfants',
            'animaux_acceptes', 'jardin', 'pmr_compatible', 'zone_recherche_rayon_km',
            'nombre_places_assises',
        ]


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
    """Offre d'aide. La localisation n'est visible que des acteurs institutionnels de la zone ;
    null pour les autres."""
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
    # Progression de la ressource (EngagementRessource) ; None si jamais affectée.
    engagement_statut = serializers.CharField(source='engagement.statut', read_only=True, default=None)
    engagement_statut_libelle = serializers.SerializerMethodField()
    # "Logement intervenants" (24/09) : pratique côté client plutôt que de tester
    # accueil_intervenants_valide_par === null soi-même.
    accueil_intervenants_valide = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = '__all__'
        # actif et validation de l'accueil d'intervenants : seulement via les actions dédiées.
        # Jetons jamais exposés.
        extra_kwargs = {
            'photo': {'write_only': True}, 'actif': {'read_only': True},
            'deletion_token': {'write_only': True}, 'reponse_token': {'write_only': True},
            'accueil_intervenants_valide_par': {'read_only': True},
            'accueil_intervenants_valide_le': {'read_only': True},
            # email_offer_bidx : voir le commentaire équivalent sur RequestSerializer.
            'email_offer_bidx': {'read_only': True},
        }

    def get_accueil_intervenants_valide(self, obj):
        return obj.accueil_intervenants_valide_par_id is not None

    def get_competences_libelles(self, obj):
        return [c.nom for c in obj.competences.all()]

    def get_engagement_statut_libelle(self, obj):
        engagement = getattr(obj, 'engagement', None)
        return engagement.get_statut_display() if engagement else None

    def _location_visible(self, obj) -> bool:
        # Rôle institutionnel et zone requis (pas de branche « participant du dossier » pour une
        # offre).
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
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return commune_from_code_cached(obj.commune_code) or commune_from_point_cached(obj.location)
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


class OfferPublicEditSerializer(serializers.ModelSerializer):
    """Modification par l'auteur via le lien email (reponse_token), sans compte. Champs limités
    à ceux du formulaire public (offer-reponse.component.ts)."""

    class Meta:
        model = Offer
        fields = [
            'description', 'type_logement', 'type_loyer', 'loyer_montant_min',
            'loyer_montant_max', 'nombre_pieces', 'nombre_chambres', 'capacite_adultes',
            'capacite_enfants', 'animaux_acceptes', 'jardin', 'pmr_compatible', 'status',
        ]


class OfferNationalPartialSerializer(serializers.ModelSerializer):
    """Vue nationale partielle des offres (type, statut, crise, date) pour tout acteur
    institutionnel, sans aucune coordonnée."""
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
        fields = ['id', 'offer', 'auteur_equipe', 'auteur_equipe_nom', 'contenu', 'date_creation', 'lu_par_institution']
        extra_kwargs = {'auteur_equipe': {'read_only': True}, 'lu_par_institution': {'read_only': True}}

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
        # Somme des apports actifs ; None si aucun apport tracé (utiliser quantite).
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


class SuiviMaterielEvenementSerializer(serializers.ModelSerializer):
    """Suivi d'état/maintenance d'une offre de matériel ("fiche matériel", 24/09) — voir
    SuiviMaterielEvenement.__doc__."""

    etat_libelle = serializers.CharField(source="get_etat_display", read_only=True)
    cree_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = SuiviMaterielEvenement
        fields = '__all__'
        read_only_fields = ['id', 'cree_par', 'date_creation']

    def get_cree_par_nom(self, obj):
        if not obj.cree_par:
            return None
        full_name = f"{obj.cree_par.first_name} {obj.cree_par.last_name}".strip()
        return full_name or obj.cree_par.email

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
    # Déclaré explicitement : EncryptedJSONField hérite de TextField, DRF en ferait une chaîne.
    ages_enfants = serializers.JSONField(required=False)

    class Meta:
        model = DeclarationSecurite
        fields = '__all__'
        read_only_fields = ['id', 'date_declaration', 'declare_par', 'registre_presence']
        # Optionnelle à la saisie : déduite de centre_accueil.crise pour une saisie au secrétariat.
        extra_kwargs = {'crise': {'required': False}}

    def get_declare_par_nom(self, obj):
        if not obj.declare_par:
            return None
        full_name = f"{obj.declare_par.first_name} {obj.declare_par.last_name}".strip()
        return full_name or obj.declare_par.email

    # Adresse personnelle : visible des seuls acteurs institutionnels.
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
    """Signalement. La localisation n'est visible que de la mairie, des secours et des bénévoles
    affectés au dossier ; null pour les autres."""
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
        # actif : seulement via destroy/reactiver. Jetons et index aveugle jamais exposés.
        extra_kwargs = {
            'photo': {'write_only': True}, 'actif': {'read_only': True},
            'deletion_token': {'write_only': True}, 'edition_token': {'write_only': True},
            'email_information_bidx': {'read_only': True},
        }

    def _location_visible(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and request):
            return False
        # Rôle institutionnel et zone requis ; Information n'a que commune_code
        # (object_in_viewer_zone_via_commune).
        if effective_role_or_none(request) in INSTITUTIONAL_TYPES and object_in_viewer_zone_via_commune(request, obj):
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
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return commune_from_code_cached(obj.commune_code) or commune_from_point_cached(obj.location)
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


class InformationPublicEditSerializer(serializers.ModelSerializer):
    """Modification par l'auteur via le lien email (edition_token), sans compte : title
    seulement."""

    class Meta:
        model = Information
        fields = ['title']


class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Serializer personnalisé pour l'authentification JWT"""
    username_field = 'email'

    def validate(self, attrs):
        data = super().validate(attrs)
        # On ajoute l'utilisateur sérialisé à la réponse
        data['user'] = UserSerializer(self.user).data
        return data

class RisqueMajeurTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RisqueMajeurType
        fields = "__all__"


class RisqueCommunalSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    risque_nom = serializers.CharField(source='risque_type.nom', read_only=True, default=None)
    risque_generalites = serializers.CharField(source='risque_type.generalites', read_only=True, default=None)

    class Meta:
        model = RisqueCommunal
        fields = "__all__"
        read_only_fields = ['id', 'institution']


class TypeVulnerabiliteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeVulnerabilite
        fields = "__all__"


class PersonneVulnerableSerializer(serializers.ModelSerializer):
    categorie_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=TypeVulnerabilite.objects.all(), source='categories', required=False
    )
    categories_detail = TypeVulnerabiliteSerializer(source='categories', many=True, read_only=True)
    institution_declarante_nom = serializers.CharField(source='institution_declarante.nom', read_only=True, default=None)
    zone_nom = serializers.CharField(source='zone.nom', read_only=True, default=None)
    cree_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = PersonneVulnerable
        fields = "__all__"
        read_only_fields = ['id', 'institution_declarante', 'cree_par', 'date_creation', 'date_maj']

    def get_cree_par_nom(self, obj):
        if not obj.cree_par:
            return None
        return f"{obj.cree_par.first_name} {obj.cree_par.last_name}".strip() or obj.cree_par.username


class ConfigurationAlerteSismiqueSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)

    class Meta:
        model = ConfigurationAlerteSismique
        fields = "__all__"
        read_only_fields = ['id', 'institution']


class InterlocuteurAlertePCSSerializer(serializers.ModelSerializer):
    """institutions en lecture seule : rattacher/détacher par les actions dédiées."""
    utilisateur_nom = serializers.SerializerMethodField()
    institutions_noms = serializers.SerializerMethodField()

    class Meta:
        model = InterlocuteurAlertePCS
        fields = "__all__"
        read_only_fields = ['id', 'institutions', 'departement_code']

    def get_utilisateur_nom(self, obj):
        if not obj.utilisateur:
            return None
        return f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip()

    def get_institutions_noms(self, obj):
        return [i.nom for i in obj.institutions.all()]


class NotificationAlertePCSSerializer(serializers.ModelSerializer):
    """Lecture seule ; écritures par envoyer_lot/confirmer ou l'accusé de réception public."""
    confirme_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = NotificationAlertePCS
        fields = "__all__"
        read_only_fields = [f.name for f in NotificationAlertePCS._meta.fields]

    def get_confirme_par_nom(self, obj):
        if not obj.confirme_par:
            return None
        return f"{obj.confirme_par.first_name} {obj.confirme_par.last_name}".strip()


class SecteurRechercheSerializer(serializers.ModelSerializer):
    polygone_geojson = serializers.SerializerMethodField()
    equipe_nom = serializers.CharField(source='equipe.name', read_only=True, default=None)

    class Meta:
        model = SecteurRecherche
        fields = "__all__"
        read_only_fields = ['id']

    def get_polygone_geojson(self, obj):
        return json.loads(obj.polygone.geojson) if obj.polygone else None


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
    # Permet d'afficher/déclencher le bouton "Démarrer" (EN_PREPARATION -> EN_COURS)
    # directement depuis la fiche équipe, sans devoir passer par la page Missions séparée.
    mission_active_statut = serializers.CharField(source='mission_active.statut', read_only=True, default=None)
    equipe_parente_nom = serializers.CharField(source='equipe_parente.name', read_only=True, default=None)
    sous_equipes_info = serializers.SerializerMethodField()
    commune_centre = serializers.SerializerMethodField()
    # Canal MeshCore privé de l'équipe (voir TeamViewSet.provisionner_canal_meshcore) — permet
    # à la fiche équipe d'afficher son statut sans appel API séparé.
    canal_meshcore_id = serializers.CharField(source='canal_meshcore.id', read_only=True, default=None)
    canal_meshcore_nom = serializers.CharField(source='canal_meshcore.nom', read_only=True, default=None)
    canal_meshcore_provisionne = serializers.SerializerMethodField()
    # Pas d'état « provisionné » pour Meshtastic : chaque destinataire configure le canal sur son
    # appareil.
    canal_meshtastic_id = serializers.CharField(source='canal_meshtastic.id', read_only=True, default=None)
    canal_meshtastic_nom = serializers.CharField(source='canal_meshtastic.nom', read_only=True, default=None)
    # Salon Matrix privé de l'équipe (voir TeamViewSet.provisionner_salon_matrix) — même
    # principe que canal_meshcore_id ci-dessus, indépendant.
    salon_matrix_id = serializers.CharField(source='salon_matrix.id', read_only=True, default=None)
    salon_matrix_room_id = serializers.CharField(source='salon_matrix.room_id', read_only=True, default=None)

    # L'appelant peut-il gérer cette équipe (ressources, mission, dossiers) ? La liste des
    # équipes couvre toute sa zone, mais seules celles de son institution (ou déléguées à
    # elle) acceptent ses affectations -- ex. « Affecter à une équipe existante » sur la page
    # Signalements n'en propose pas d'autres.
    peut_gerer = serializers.SerializerMethodField()

    def get_peut_gerer(self, obj):
        # Même règle que _appartient_a_equipe (core/views.py), avec les institutions de
        # l'appelant lues une seule fois pour toute la liste (contexte partagé).
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        if 'mes_institutions_equipe' not in self.context:
            if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
                self.context['mes_institutions_equipe'] = None
            else:
                self.context['mes_institutions_equipe'] = set(ContactInstitution.objects.filter(
                    utilisateur=request.user, actif=True,
                ).values_list('institution_id', flat=True))
        mes_institutions = self.context['mes_institutions_equipe']
        if mes_institutions is None:
            return True
        return obj.institution_id in mes_institutions or (
            obj.institution_delegataire_id is not None and obj.institution_delegataire_id in mes_institutions
        )

    def get_canal_meshcore_provisionne(self, obj):
        canal = getattr(obj, 'canal_meshcore', None)
        return canal is not None and canal.canal_idx is not None

    def get_commune_centre(self, obj):
        # Centre de la minimap : commune de l'institution.
        code = obj.institution.commune_code if obj.institution_id else None
        return commune_center_from_code(code) if code else None

    class Meta:
        model  = Team
        fields = [
            'id', 'name', 'description', 'color', 'created_at', 'actif',
            'est_equipe_rcsc',
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
            'mission_active_statut',
            'member_ids',
            'members_info',
            'vehicules_count',
            'peut_gerer',
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
            'canal_meshcore_id',
            'canal_meshcore_nom',
            'canal_meshcore_provisionne',
            'canal_meshtastic_id',
            'canal_meshtastic_nom',
            'salon_matrix_id',
            'salon_matrix_room_id',
        ]
        # Modifiables seulement par les actions dédiées (historique, anti-cycle, permissions).
        read_only_fields = ['id', 'created_at', 'actif', 'institution_delegataire', 'equipe_parente', 'est_equipe_rcsc']

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
        # Noms des coéquipiers seulement (un bénévole n'a pas accès à la liste des utilisateurs).
        return [{"id": str(m.id), "nom": self._nom(m)} for m in obj.members.all()]

    def get_vehicules_count(self, obj):
        # Filtré en Python pour profiter du prefetch assigned_offers (un .filter() relancerait une
        # requête).
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
        # Préfixé par l'institution : la carte mêle des équipes de plusieurs institutions.
        return [
            f"{nom_institution} - {nom}" if nom_institution else nom
            for nom, nom_institution in obj.utilisateur.teams.values_list('name', 'institution__nom')
        ]


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
    """Copie de views._regulateurs_pour_dossier : l'importer créerait un cycle d'imports."""
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

    # Nature du Besoin capturé à la création (COMPETENCE/MATERIEL/MIXTE) -- classe le dossier
    # ressource/matériel sur la page Cellule de crise, voir Dossier.besoin.
    besoin_nature = serializers.CharField(
        source='besoin.nature',
        read_only=True,
        default=None,
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

    def validate(self, attrs):
        # Refuse un dossier rattaché à une mission d'une autre crise (mission sans crise tolérée).
        crise = attrs.get('crise', getattr(self.instance, 'crise', None))
        mission = attrs.get('mission', getattr(self.instance, 'mission', None))
        if crise and mission and mission.crise_id and mission.crise_id != crise.id:
            raise serializers.ValidationError({
                'mission': "Cette mission appartient à une autre crise que celle du dossier.",
            })
        return attrs

    def _origine(self, obj):
        return obj.demande or obj.information

    def get_description_origine(self, obj):
        # Description saisie sur la demande d'origine (Dossier.description est générée).
        if obj.demande:
            return obj.demande.description
        return None

    def get_latitude(self, obj):
        # Pas de contrôle ici : DossierViewSet.get_queryset limite déjà l'accès.
        origine = self._origine(obj)
        return origine.location.y if origine and origine.location else None

    def get_longitude(self, obj):
        origine = self._origine(obj)
        return origine.location.x if origine and origine.location else None

    def get_has_photo(self, obj):
        # Indique au frontend si preview peut être appelée.
        origine = self._origine(obj)
        return bool(origine and origine.photo)

    def get_commune(self, obj):
        origine = self._origine(obj)
        if not origine or not origine.location:
            return None
        # En liste : lecture du cache seule, jamais d'appel réseau (même règle que
        # RequestSerializer.get_commune).
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            code = obj.demande.commune_code if obj.demande else None
            return commune_from_code_cached(code) or commune_from_point_cached(origine.location)
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
        # Contact du régulateur pour les intervenants (accès déjà limité par get_queryset ; masqué
        # en DEMO). Mêmes régulateurs pour une même compétence (ou équipe) : calculés une fois par liste.
        memo = self.context.setdefault('_regulateurs_par_cle', {})
        cle = ('competence', obj.competence_id) if obj.competence_id else ('equipe', obj.equipe_id)
        if cle not in memo:
            memo[cle] = list(_regulateurs_pour_dossier(obj, obj.equipe))
        regulateurs = memo[cle]
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
        # get_unread_count mémorisé : utilisé par has_updates et unread_count.
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
        # En DEMO, contacts masqués pour tous, comme sur la demande d'origine.
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
    """Convertit un GPS EXIF (deg, min, sec) en degrés décimaux ; None si illisible."""
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
        # EXIF (GPS) réservés à l'auteur et aux institutionnels, et aux participants pour une photo
        # de dossier (minimap de suivi).
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
    """Entrée du journal de bord, non modifiable après création."""

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
    """Main courante complète (IP, user-agent, institution, succès) pour la consultation globale
    par un administrateur."""

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

class DemandeMobilisationSerializer(serializers.ModelSerializer):
    """Cible résolue en cible_type/cible_nom/cible_contact pour le frontend."""

    crise_nom = serializers.CharField(source="crise.name", read_only=True)
    institution_emettrice_nom = serializers.CharField(source="institution_emettrice.nom", read_only=True)
    emetteur_nom = serializers.SerializerMethodField()
    point_operationnel_nom = serializers.CharField(source="point_operationnel.nom", read_only=True, default=None)
    type_demande_libelle = serializers.CharField(source="get_type_demande_display", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)

    cible_type = serializers.SerializerMethodField()
    cible_nom = serializers.SerializerMethodField()
    cible_contact = serializers.SerializerMethodField()

    class Meta:
        model = DemandeMobilisation
        fields = "__all__"
        read_only_fields = [
            "emetteur", "statut", "date_creation", "date_revocation", "jeton_verification",
        ]

    def get_emetteur_nom(self, obj):
        if not obj.emetteur_id:
            return None
        return f"{obj.emetteur.first_name} {obj.emetteur.last_name}".strip() or obj.emetteur.email

    def get_cible_type(self, obj):
        if obj.cible_utilisateur_id:
            return "utilisateur"
        if obj.cible_institution_id:
            return "institution"
        if obj.cible_offre_id:
            return "offre"
        return None

    def get_cible_nom(self, obj):
        if obj.cible_utilisateur_id:
            u = obj.cible_utilisateur
            return f"{u.first_name} {u.last_name}".strip() or u.email
        if obj.cible_institution_id:
            return obj.cible_institution.nom
        if obj.cible_offre_id:
            o = obj.cible_offre
            return f"{o.first_name_offer} {o.last_name_offer}".strip() or o.email_offer
        return None

    def get_cible_contact(self, obj):
        if obj.cible_utilisateur_id:
            return obj.cible_utilisateur.email
        if obj.cible_institution_id:
            return obj.cible_institution.email
        if obj.cible_offre_id:
            return obj.cible_offre.email_offer
        return None

    def validate(self, attrs):
        def valeur(champ):
            if champ in attrs:
                return attrs[champ]
            return getattr(self.instance, champ, None) if self.instance else None

        cibles = [valeur("cible_utilisateur"), valeur("cible_institution"), valeur("cible_offre")]
        if len([c for c in cibles if c is not None]) != 1:
            raise serializers.ValidationError({
                "cible": "Exactement une cible doit être renseignée : un utilisateur, une "
                         "institution déjà inscrite, ou une offre d'aide déposée sans compte.",
            })
        return attrs


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
        # Dernier commentaire mémorisé (utilisé par quatre champs).
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

    # Deux clés toujours présentes (None si non provisionné). Le queryset doit faire
    # prefetch_related('salons_matrix').
    salons_matrix = serializers.SerializerMethodField()

    class Meta:

        model = Institution

        fields = "__all__"
        # Posés seulement par _traiter_acceptation_convention (core/views.py), jamais par le
        # payload.
        read_only_fields = [
            "convention_sous_traitance_acceptee_le",
            "convention_sous_traitance_acceptee_par",
            "convention_sous_traitance_version",
        ]

    def get_salons_matrix(self, obj):
        salons = {s.type: s for s in obj.salons_matrix.all()}
        return {
            type_salon: (
                {"id": str(salons[type_salon].id), "room_id": salons[type_salon].room_id}
                if type_salon in salons else None
            )
            for type_salon in TypeSalonInstitution.values
        }

    def to_representation(self, instance):
        # Une institution réelle reste visible en DEMO, coordonnées masquées à l'affichage.
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['email'] = mask_email(data.get('email'))
            data['telephone'] = mask_phone(data.get('telephone'))
        return data

    def update(self, instance, validated_data):
        # secteur_override peut ouvrir une vue nationale : superuser en PROD, membre de
        # l'institution en DEMO.
        if "secteur_override" in validated_data:
            request = self.context.get("request")
            if not self._can_edit_secteur_override(request, instance):
                validated_data.pop("secteur_override")
        # Ignore un email/téléphone renvoyé masqué, pour ne pas écraser la vraie valeur en DEMO.
        request = self.context.get("request")
        validated_data = strip_masked_fields_in_demo(request, validated_data, ('email', 'telephone'))
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
        # Sans crise dans le PATCH, vérifier celle de l'instance.
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
    # Contacts de tous les responsables (point_responsables_contacts()).
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
    # Distance à la crise du point (annotation du queryset) ; None sans coordonnées.
    distance_from_crisis_km = serializers.SerializerMethodField()

    class Meta:

        model = PointOperationnel

        fields = "__all__"

    def get_commune_nom(self, obj):
        # Même mécanisme de reverse-géocodage que le scoping zone (_filter_points_to_viewer_zone) —
        # PointOperationnel n'a pas de commune_code dénormalisé, seulement un point GPS.
        return commune_from_point(obj.location)

    def get_distance_from_crisis_km(self, obj):
        distance = getattr(obj, 'distance_from_crisis', None)
        return round(distance.km, 1) if distance is not None else None

    def get_peut_gerer(self, obj):
        # Mêmes règles que l'API (secrétariat, stock), pour n'afficher que les boutons utilisables.
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
        # Sans crise dans le PATCH, vérifier celle de l'instance.
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
    risques_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=RisqueCommunal.objects.all(), source='risques', required=False
    )
    risques_noms = serializers.SerializerMethodField()
    contacts_internes_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=ContactInstitution.objects.all(), source='contacts_internes', required=False
    )
    contacts_internes_noms = serializers.SerializerMethodField()
    interlocuteurs_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=InterlocuteurAlertePCS.objects.all(), source='interlocuteurs', required=False
    )
    interlocuteurs_noms = serializers.SerializerMethodField()

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

    def get_risques_noms(self, obj):
        return [r.risque_type.nom for r in obj.risques.select_related('risque_type').all()]

    def get_contacts_internes_noms(self, obj):
        return [
            f"{c.utilisateur.first_name} {c.utilisateur.last_name}".strip() or c.utilisateur.username
            for c in obj.contacts_internes.select_related('utilisateur').all()
        ]

    def get_interlocuteurs_noms(self, obj):
        return [i.nom or i.organisme for i in obj.interlocuteurs.all()]


class PlanMissionModeleSerializer(serializers.ModelSerializer):
    equipe_nom = serializers.CharField(source='equipe.name', read_only=True, default=None)
    referent_nom = serializers.SerializerMethodField()

    class Meta:
        model = PlanMissionModele
        fields = "__all__"
        # plan n'est jamais réaffectable via un PATCH générique — voir
        # PlanMissionModeleViewSet.perform_create (résolu depuis l'URL/le payload initial).
        read_only_fields = ['id', 'plan']

    def get_referent_nom(self, obj):
        if not obj.referent:
            return None
        full_name = f"{obj.referent.first_name} {obj.referent.last_name}".strip()
        return full_name or obj.referent.email


class PointOperationnelPublicSerializer(serializers.ModelSerializer):
    """Point opérationnel à champs restreints, pour les formulaires et la carte publics."""

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    personnes_presentes = serializers.SerializerMethodField()
    # Type public : distingue centres d'accueil et postes de secours.
    type_code = serializers.CharField(source="type.code", read_only=True, default=None)
    type_libelle = serializers.CharField(source="type.libelle", read_only=True, default=None)

    class Meta:
        model = PointOperationnel
        fields = ['id', 'nom', 'adresse', 'latitude', 'longitude', 'capacite_accueil', 'personnes_presentes', 'crise', 'type_code', 'type_libelle', 'accepte_animaux']

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
    # statut posé seulement par perform_create et valider/refuser (sinon auto-validation possible).
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
        """True si l'utilisateur peut valider ou refuser cette déclaration (même calcul que
        l'action)."""
        if obj.statut != StatutImplication.EN_ATTENTE:
            return False
        request = self.context.get('request')
        if request is None:
            return False
        from .permissions import is_regulateur_aut_locale_de_la_crise
        return is_regulateur_aut_locale_de_la_crise(request, obj.crise)

    def validate(self, attrs):
        # Sans crise dans le PATCH, vérifier celle de l'instance.
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

        # Pas de validateur auto pour uq_contact_principal_institution : un nouveau contact
        # principal REMPLACE l'ancien (ContactInstitutionViewSet._liberer_contact_principal),
        # il n'est pas refusé (demande utilisateur du 19/10).
        validators = []

    def get_utilisateur_nom(self, obj):
        if not obj.utilisateur:
            return None
        full_name = f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip()
        if full_name:
            return full_name
        # Jamais l'email en clair en DEMO.
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            return mask_email(obj.utilisateur.email)
        return obj.utilisateur.email

    def to_representation(self, instance):
        # Un contact réel reste visible en DEMO, email masqué à l'affichage.
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['utilisateur_email'] = mask_email(data.get('utilisateur_email'))
        return data

class InstitutionDomaineSerializer(
    serializers.ModelSerializer
):

    class Meta:

        model = InstitutionDomaine

        fields = "__all__"


class CompagnonMeshCoreSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = CompagnonMeshCore
        fields = "__all__"
        # Renseignés uniquement par le service-pont (voir docstring du modèle), jamais par un
        # appel humain via l'API.
        read_only_fields = ['pubkey_hex', 'derniere_connexion', 'dernier_etat', 'derniere_erreur', 'derniere_batterie_niveau', 'derniere_batterie_date']

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    # Même patron que RelaisMeshCoreSerializer._avec_position : latitude/longitude reçues à
    # plat (pas un WKT), converties en Point ici plutôt que côté frontend.
    def create(self, validated_data):
        return self._avec_position(CompagnonMeshCore(), validated_data)

    def update(self, instance, validated_data):
        return self._avec_position(instance, validated_data)

    def _avec_position(self, instance, validated_data):
        from django.contrib.gis.geos import Point
        lat = self.initial_data.get('latitude')
        lon = self.initial_data.get('longitude')
        for champ, valeur in validated_data.items():
            setattr(instance, champ, valeur)
        if lat is not None and lon is not None:
            instance.location = Point(float(lon), float(lat), srid=4326)
        instance.save()
        return instance

    def to_representation(self, instance):
        """En DEMO, la topologie réseau du pont est masquée à l'affichage."""
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            for champ in ('tcp_host', 'tcp_port', 'serie_device', 'ble_adresse', 'pubkey_hex'):
                data[champ] = None
        return data


class NoeudMeshUtilisateurSerializer(serializers.ModelSerializer):
    utilisateur_nom = serializers.SerializerMethodField()

    class Meta:
        model = NoeudMeshUtilisateur
        fields = "__all__"

    def get_utilisateur_nom(self, obj):
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            return "Nœud de terrain"
        return f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip() or obj.utilisateur.email

    def to_representation(self, instance):
        """En DEMO, le compte rattaché au nœud est masqué ; pubkey_hex reste pour l'adressage."""
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and get_active_environment(request) == Environment.DEMO:
            data['utilisateur'] = None
        return data


class MessageMeshLogSerializer(serializers.ModelSerializer):
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True)
    expediteur_nom = serializers.SerializerMethodField()
    equipe_nom = serializers.CharField(source='equipe.name', read_only=True, default=None)

    class Meta:
        model = MessageMeshLog
        fields = "__all__"
        # equipe et expediteur sont résolus par le serveur.
        # statut, erreur et date_envoi doivent rester modifiables : le pont les met à jour par
        # PATCH (DRF ignore sans erreur un champ read_only reçu).
        read_only_fields = ['expediteur', 'equipe']
        # Optionnel : vide = choix automatique du companion (core/routage_mesh.py).
        extra_kwargs = {'compagnon': {'required': False}}

    def get_expediteur_nom(self, obj):
        if not obj.expediteur_id:
            return None
        return f"{obj.expediteur.first_name} {obj.expediteur.last_name}".strip() or obj.expediteur.email


class AlerteMeshSOSSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)

    class Meta:
        model = AlerteMeshSOS
        fields = "__all__"
        # Lecture seule (historique) -- écrite uniquement par core.views._signaler_sos_mesh,
        # jamais via un POST/PATCH direct sur ce serializer.
        read_only_fields = [
            'protocole', 'institution', 'canal_nom', 'expediteur_identifiant', 'expediteur_nom',
            'contenu', 'mot_cle_detecte', 'notification_envoyee',
        ]


class CommandeMeshCoreSerializer(serializers.ModelSerializer):
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True)
    type_commande_libelle = serializers.CharField(source='get_type_commande_display', read_only=True)

    class Meta:
        model = CommandeMeshCore
        fields = "__all__"
        # Modifiables par le PATCH du pont (même piège que MessageMeshLogSerializer).


class TracerouteMeshCoreSerializer(serializers.ModelSerializer):
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True)

    class Meta:
        model = TracerouteMeshCore
        fields = "__all__"
        # Écrit seulement par lancer_traceroute/rapporter_traceroute.
        read_only_fields = ['compagnon', 'tag', 'statut', 'chemin', 'erreur', 'date_reponse']


class RelaisMeshCoreSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = RelaisMeshCore
        fields = "__all__"

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def create(self, validated_data):
        return self._avec_position(RelaisMeshCore(), validated_data)

    def update(self, instance, validated_data):
        return self._avec_position(instance, validated_data)

    def _avec_position(self, instance, validated_data):
        from django.contrib.gis.geos import Point
        lat = self.initial_data.get('latitude')
        lon = self.initial_data.get('longitude')
        for champ, valeur in validated_data.items():
            setattr(instance, champ, valeur)
        if lat is not None and lon is not None:
            instance.location = Point(float(lon), float(lat), srid=4326)
        instance.save()
        return instance


class SalonMatrixEquipeSerializer(serializers.ModelSerializer):
    """membres : identifiants Matrix calculés par Django pour matrix-bridge."""

    equipe_nom = serializers.CharField(source='equipe.name', read_only=True)
    membres = serializers.SerializerMethodField()
    # Sujet du salon (régulateur et coordonnées) ; None = le pont ne touche pas au sujet.
    sujet_salon = serializers.SerializerMethodField()
    # La cellule de crise n'a pas de membres formels : le pont ne doit expulser personne de son
    # salon.
    expulsion_activee = serializers.SerializerMethodField()

    class Meta:
        model = SalonMatrixEquipe
        fields = ['id', 'equipe', 'equipe_nom', 'room_id', 'membres', 'sujet_salon', 'expulsion_activee', 'date_creation', 'derniere_synchronisation']
        read_only_fields = ['id', 'equipe', 'date_creation']

    def get_sujet_salon(self, obj):
        regulateur = obj.equipe.regulateur
        if not regulateur:
            return None
        nom = f"{regulateur.first_name} {regulateur.last_name}".strip() or regulateur.email
        coordonnees = " / ".join(c for c in [regulateur.email, regulateur.phone_number] if c)
        return f"Régulateur : {nom}" + (f" ({coordonnees})" if coordonnees else "")

    def get_membres(self, obj):
        from .matrix import matrix_user_id
        return [
            {"id": str(m.id), "matrix_user_id": matrix_user_id(m),
             "nom": f"{m.first_name} {m.last_name}".strip() or m.email}
            for m in obj.equipe.members.filter(is_active=True)
        ]

    def get_expulsion_activee(self, obj):
        from .models import PointOperationnel
        return not PointOperationnel.objects.filter(equipe=obj.equipe, type__code="CELLULE_CRISE").exists()


# Rôles permanents d'une institution (même ensemble que AuthService.isAdmin() côté frontend).
ROLES_PERMANENTS_INSTITUTION = [
    UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE, UserRole.REGULATEUR,
]


class SalonMatrixInstitutionSerializer(serializers.ModelSerializer):
    """membres recalculé à chaque lecture selon le type de salon."""

    institution_nom = serializers.CharField(source='institution.nom', read_only=True)
    membres = serializers.SerializerMethodField()

    class Meta:
        model = SalonMatrixInstitution
        fields = ['id', 'institution', 'institution_nom', 'type', 'room_id', 'membres', 'date_creation', 'derniere_synchronisation']
        read_only_fields = ['id', 'institution', 'type', 'date_creation']

    def get_membres(self, obj):
        from .matrix import matrix_user_id

        if obj.type == TypeSalonInstitution.PERMANENTS:
            queryset = obj.institution.utilisateurs.filter(is_active=True, type__in=ROLES_PERMANENTS_INSTITUTION)
        else:
            # Union des membres de toutes les équipes ACTIVES de l'institution -- une équipe
            # désactivée (mission terminée) n'alimente plus ce salon, voir docstring du modèle.
            queryset = User.objects.filter(
                is_active=True, teams__institution=obj.institution, teams__actif=True,
            ).distinct()

        return [
            {"id": str(m.id), "matrix_user_id": matrix_user_id(m),
             "nom": f"{m.first_name} {m.last_name}".strip() or m.email}
            for m in queryset
        ]


class CanalMeshCoreSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    crise_nom = serializers.CharField(source='crise.name', read_only=True, default=None)
    equipe_nom = serializers.CharField(source='equipe.name', read_only=True, default=None)
    provisionne = serializers.SerializerMethodField()

    class Meta:
        model = CanalMeshCore
        fields = "__all__"
        extra_kwargs = {'cle_partagee_hex': {'write_only': True, 'required': False}}

    def get_provisionne(self, obj):
        return obj.canal_idx is not None

    def validate(self, attrs):
        # Canal public « #nom » : clé dérivée du nom, nécessaire au provisionnement par le pont.
        nom = attrs.get('nom', getattr(self.instance, 'nom', ''))
        deja_une_cle = attrs.get('cle_partagee_hex') or (self.instance and self.instance.cle_partagee_hex)
        if nom.startswith('#') and not deja_une_cle:
            cle = CanalMeshCore.derive_cle_publique(nom)
            attrs['cle_partagee_hex'] = cle
            # Nommer un canal public permet de nettoyer les canaux détectés de même chan_hash, dans
            # tout l'environnement.
            request = self.context.get('request')
            if request is not None:
                chan_hash = CanalMeshCore.chan_hash_pour_secret(cle)
                CanalMeshCoreDetecte.objects.filter(
                    chan_hash=chan_hash, environment=get_active_environment(request),
                ).delete()
        elif not nom.startswith('#') and not deja_une_cle:
            raise serializers.ValidationError({
                'cle_partagee_hex': "Requis pour un canal privé (seul un nom préfixé « # » a une clé publique dérivable).",
            })
        return attrs


class ContactMeshCoreSerializer(serializers.ModelSerializer):
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    # Déjà utilisé ailleurs (NoeudMeshUtilisateur) pour indiquer qu'un contact est déjà associé
    # à un compte — évite un aller-retour supplémentaire côté frontend pour filtrer la liste.
    deja_associe = serializers.SerializerMethodField()

    class Meta:
        model = ContactMeshCore
        fields = "__all__"

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_deja_associe(self, obj):
        return NoeudMeshUtilisateur.objects.filter(pubkey_hex=obj.pubkey_hex).exists()


class CompagnonMeshtasticSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    # Dérivée de x25519_private_key_hex, jamais l'inverse — à communiquer au correspondant pour
    # qu'il puisse nous envoyer un DM chiffré par clé publique en retour (voir crypto.py).
    x25519_public_key_hex = serializers.CharField(read_only=True)

    class Meta:
        model = CompagnonMeshtastic
        # x25519_private_key_hex exclue : jamais exposée par l'API.
        exclude = ['x25519_private_key_hex']
        extra_kwargs = {'mqtt_password': {'write_only': True}}


class CanalMeshtasticSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True, default=None)
    crise_nom = serializers.CharField(source='crise.name', read_only=True, default=None)
    equipe_nom = serializers.CharField(source='equipe.name', read_only=True, default=None)
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True, default=None)

    class Meta:
        model = CanalMeshtastic
        fields = "__all__"
        extra_kwargs = {'psk_hex': {'write_only': True}}


class ContactMeshtasticSerializer(serializers.ModelSerializer):
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    deja_associe = serializers.SerializerMethodField()

    class Meta:
        model = ContactMeshtastic
        fields = "__all__"

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_deja_associe(self, obj):
        return NoeudUtilisateurMeshtastic.objects.filter(node_num=obj.node_num).exists()


class NoeudUtilisateurMeshtasticSerializer(serializers.ModelSerializer):
    utilisateur_nom = serializers.SerializerMethodField()

    class Meta:
        model = NoeudUtilisateurMeshtastic
        fields = "__all__"

    def get_utilisateur_nom(self, obj):
        return f"{obj.utilisateur.first_name} {obj.utilisateur.last_name}".strip() or obj.utilisateur.email


class MessageMeshtasticLogSerializer(serializers.ModelSerializer):
    compagnon_nom = serializers.CharField(source='compagnon.nom', read_only=True)
    expediteur_nom = serializers.SerializerMethodField()
    equipe_nom = serializers.CharField(source='equipe.name', read_only=True, default=None)

    class Meta:
        model = MessageMeshtasticLog
        fields = "__all__"
        read_only_fields = ['expediteur', 'equipe']

    def get_expediteur_nom(self, obj):
        if not obj.expediteur_id:
            return None
        return f"{obj.expediteur.first_name} {obj.expediteur.last_name}".strip() or obj.expediteur.email


class MessageCanalMeshtasticSerializer(serializers.ModelSerializer):
    canal_nom = serializers.CharField(source='canal.nom', read_only=True)
    expediteur_nom = serializers.SerializerMethodField()
    # Nom annoncé par le nœud (distinct du compte affecté, expediteur_nom).
    node_nom = serializers.SerializerMethodField()

    class Meta:
        model = MessageCanalMeshtastic
        fields = "__all__"
        read_only_fields = ['expediteur']

    def get_expediteur_nom(self, obj):
        if not obj.expediteur_id:
            return None
        return f"{obj.expediteur.first_name} {obj.expediteur.last_name}".strip() or obj.expediteur.email

    def get_node_nom(self, obj):
        if obj.contact_node_num is None:
            return None
        contact = (
            ContactMeshtastic.objects.filter(node_num=obj.contact_node_num)
            .order_by('-date_synchronisation')
            .first()
        )
        if not contact:
            return None
        return contact.long_name or contact.short_name or None


class MessageCanalMeshCoreSerializer(serializers.ModelSerializer):
    canal_nom = serializers.CharField(source='canal.nom', read_only=True)
    # Index local du canal, nécessaire à send_chan_msg côté pont.
    canal_idx = serializers.IntegerField(source='canal.canal_idx', read_only=True)
    expediteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = MessageCanalMeshCore
        fields = "__all__"
        # Modifiables par le PATCH du pont (même piège que MessageMeshLogSerializer).
        read_only_fields = ['expediteur']

    def get_expediteur_nom(self, obj):
        if not obj.expediteur_id:
            return None
        return f"{obj.expediteur.first_name} {obj.expediteur.last_name}".strip() or obj.expediteur.email


class SatelliteSerializer(serializers.ModelSerializer):
    institution_nom = serializers.CharField(source='institution.nom', read_only=True)
    profil_libelle = serializers.CharField(source='get_profil_display', read_only=True)
    statut_enrolement_libelle = serializers.CharField(source='get_statut_enrolement_display', read_only=True)
    etat = serializers.SerializerMethodField()

    class Meta:
        model = Satellite
        # Jamais le hash du secret de récupération des identifiants ; compte_service posé
        # seulement par SatelliteViewSet.valider.
        exclude = ['secret_recuperation_hash']
        read_only_fields = ['statut_enrolement', 'compte_service', 'dernier_contact']

    def get_etat(self, obj):
        # Dérivé de dernier_contact et des seuils SATELLITE_* ; None avant le premier contact.
        if obj.dernier_contact is None:
            return None
        silence_minutes = (timezone.now() - obj.dernier_contact).total_seconds() / 60
        if silence_minutes > settings.SATELLITE_SEUIL_PERDU_MINUTES:
            return "PERDU"
        if silence_minutes > settings.SATELLITE_SEUIL_INACTIF_MINUTES:
            return "INACTIF"
        return "ACTIF"


class JetonEnrolementSatelliteSerializer(serializers.ModelSerializer):
    class Meta:
        model = JetonEnrolementSatellite
        fields = ['id', 'institution', 'jeton', 'profil', 'expiration', 'utilise', 'date_creation']
        read_only_fields = fields


class ConflitSynchronisationSerializer(serializers.ModelSerializer):
    satellite_nom = serializers.CharField(source='satellite.nom', read_only=True)
    modele_libelle = serializers.CharField(source='get_modele_display', read_only=True)

    class Meta:
        model = ConflitSynchronisation
        fields = "__all__"
        # Jamais écrit directement — uniquement créé par SatelliteViewSet.synchroniser et
        # tranché via ConflitSynchronisationViewSet.resoudre (voir leurs docstrings).
        read_only_fields = [
            'satellite', 'modele', 'objet_id', 'payload_local', 'etat_central_au_conflit',
            'statut', 'resolu_le', 'resolu_par',
        ]


class HabitationCommentaireSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = HabitationCommentaire
        fields = "__all__"
        extra_kwargs = {'auteur': {'read_only': True}}

    def get_auteur_nom(self, obj):
        if not obj.auteur:
            return "Inconnu"
        return (f"{obj.auteur.first_name} {obj.auteur.last_name}").strip() or obj.auteur.username


class HabitationHistoriqueSerializer(serializers.ModelSerializer):

    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = HabitationHistorique
        fields = "__all__"

    def get_auteur_nom(self, obj):
        if not obj.auteur:
            return "Système"
        return (f"{obj.auteur.first_name} {obj.auteur.last_name}").strip() or obj.auteur.username


class HabitationSerializer(serializers.ModelSerializer):
    """latitude/longitude séparées, comme PointOperationnelSerializer."""

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    zone_nom = serializers.CharField(source="zone.nom", read_only=True, default=None)
    nb_rattachements_en_attente = serializers.SerializerMethodField()
    peut_gerer = serializers.SerializerMethodField()

    class Meta:
        model = Habitation
        fields = "__all__"
        read_only_fields = ['evalue_par', 'date_derniere_evaluation', 'date_creation', 'modifie_le']

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def get_nb_rattachements_en_attente(self, obj):
        return obj.rattachements.filter(statut=StatutRattachementHabitation.EN_ATTENTE).count()

    def get_peut_gerer(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        from .habitations import institution_accede_commune
        return institution_accede_commune(request, obj.commune_code, crise=obj.crise)

    def create(self, validated_data):
        latitude = self.initial_data.get('latitude')
        longitude = self.initial_data.get('longitude')
        if latitude is not None and longitude is not None:
            from django.contrib.gis.geos import Point
            validated_data['location'] = Point(float(longitude), float(latitude), srid=4326)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        latitude = self.initial_data.get('latitude')
        longitude = self.initial_data.get('longitude')
        if latitude is not None and longitude is not None:
            from django.contrib.gis.geos import Point
            validated_data['location'] = Point(float(longitude), float(latitude), srid=4326)
        return super().update(instance, validated_data)


class RattachementHabitationSerializer(serializers.ModelSerializer):

    habitation_adresse = serializers.CharField(source="habitation.adresse", read_only=True)
    traite_par_nom = serializers.SerializerMethodField()
    a_justificatif = serializers.SerializerMethodField()

    class Meta:
        model = RattachementHabitation
        fields = "__all__"
        read_only_fields = [
            'utilisateur', 'statut', 'traite_par', 'date_traitement', 'motif_refus', 'date_demande',
        ]
        # justificatif seulement via preview (contrôle d'accès). Index aveugle jamais exposé.
        extra_kwargs = {'justificatif': {'write_only': True}, 'email_demandeur_bidx': {'read_only': True}}

    def get_traite_par_nom(self, obj):
        if not obj.traite_par:
            return None
        return (f"{obj.traite_par.first_name} {obj.traite_par.last_name}").strip() or obj.traite_par.username

    def get_a_justificatif(self, obj):
        return bool(obj.justificatif)


class PieceIdentiteReserveSerializer(serializers.ModelSerializer):
    """utilisateur forcé à request.user par la vue. Permis en write_only, téléchargés déchiffrés
    via les actions dédiées après contrôle d'accès."""

    a_recto = serializers.SerializerMethodField()
    a_verso = serializers.SerializerMethodField()

    class Meta:
        model = PieceIdentiteReserve
        fields = ['id', 'utilisateur', 'permis_recto', 'permis_verso', 'a_recto', 'a_verso', 'date_depot']
        read_only_fields = ['utilisateur', 'date_depot']
        extra_kwargs = {
            'permis_recto': {'write_only': True, 'required': False},
            'permis_verso': {'write_only': True, 'required': False},
        }

    def get_a_recto(self, obj):
        return bool(obj.permis_recto)

    def get_a_verso(self, obj):
        return bool(obj.permis_verso)


class ModuleDegatsCriseSerializer(serializers.ModelSerializer):

    institution_nom = serializers.CharField(source="institution.nom", read_only=True)
    zone_nom = serializers.CharField(source="zone.nom", read_only=True, default=None)
    crise_nom = serializers.CharField(source="crise.name", read_only=True)

    class Meta:
        model = ModuleDegatsCrise
        fields = "__all__"
        read_only_fields = ['active_par', 'date_activation', 'date_desactivation']


