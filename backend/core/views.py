from django.shortcuts import render
from django.http import FileResponse
from rest_framework.decorators import action
from rest_framework import viewsets, status, generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import MyTokenObtainPairSerializer  # if you've defined it in serializers
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from urllib.parse import quote
from django_filters import rest_framework as filters
from django.db.models import Q
from django.utils import timezone
from .auth_validation import InstitutionEmailValidator
import secrets
import uuid
import hashlib
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

from .audit import audit_log, get_client_ip
from .export import build_crisis_export_zip
from .institution_attachment import attach_user_to_institution, resolve_or_invite_responsable
from .permissions import IsInstitutionalActor, IsAdministrator, INSTITUTIONAL_TYPES, user_can_view_photo


GPS_IFD_TAG = 0x8825  # PIL.ExifTags.IFD.GPSInfo


def extract_exif_metadata(filepath):
    """Retourne (metadata_publiques, metadata_privees) : les données de localisation GPS
    embarquées dans la photo (sous-IFD GPSInfo) vont exclusivement dans le second dict,
    jamais dans le premier — cohérent avec le reste de l'app qui traite la localisation
    précise comme une donnée sensible (voir _location_visible() sur les serializers)."""

    metadata_publiques = {}
    metadata_privees = {}

    try:

        image = Image.open(filepath)

        exif = image.getexif()

        if not exif:
            return metadata_publiques, metadata_privees

        gps_ifd = exif.get_ifd(GPS_IFD_TAG)

        if gps_ifd:
            for tag_id, value in gps_ifd.items():
                tag = GPSTAGS.get(tag_id, tag_id)
                metadata_privees[tag] = str(value)

        for tag_id, value in exif.items():

            if tag_id == GPS_IFD_TAG:
                continue

            tag = TAGS.get(tag_id, tag_id)

            metadata_publiques[tag] = str(value)

    except Exception:
        pass

    return metadata_publiques, metadata_privees


from .models import (
    UserRole,
    InstitutionType,
    Institution,
    RoleOperationnel,
    InstitutionCompetence,
    AffectationRoleOperationnel,
    DelegationCompetence,
    DisponibiliteOperationnelle,
    ContactInstitution,
    InstitutionDomaine,
    PointType,
    PointOperationnel,
    ImplicationInstitution,
    TypeImplication,
    User, Crisis, Request, Offer, Information, DisponibiliteOffre, DisponibilitePointEquipe, MaterielPoint,
    MaterielCatalogue, NiveauStock,
    RecherchePersonne, RecherchePersonneCommentaire, Besoin, Notification, DossierParticipant,
    RecherchePersonneCommentairePhoto, RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, DossierCommentaire, DossierHistorique, BesoinCompetence, Competence, Dossier,
    AuditLog, AuditAction,
    RecherchePersonneHistorique, RecherchePersonnePhoto,
    AffectationCompetence, RequestType, RequestTypeBesoin, OfferType, InformationType, Team
)


MAGIC_LINK_SALT = "assista-crise-magic-link"
MAGIC_LINK_SIGNER = TimestampSigner(salt=MAGIC_LINK_SALT)


FRONTEND_MAGIC_LINK_PATHS = {
    "activate-account": "activate-account",
    "magic-login": "connexion-magique",
}


def build_magic_link(request, user, action: str, next_url: str = None) -> str:
    uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = MAGIC_LINK_SIGNER.sign(uidb64)

    frontend_path = FRONTEND_MAGIC_LINK_PATHS.get(action)
    if frontend_path:
        # Doit pointer vers une page du frontend (qui appelle ensuite l'API elle-même côté
        # client), jamais directement sur l'API : sinon le clic affiche du JSON brut.
        frontend_url = settings.SERVER_URL.rstrip('/')
        url = f"{frontend_url}/{frontend_path}/{uidb64}/{token}"
        if next_url:
            url += f"?next={quote(next_url, safe='')}"
        return url

    base_url = request.build_absolute_uri('/').rstrip('/')
    return f"{base_url}/api/{action}/{uidb64}/{token}/"


def get_user_from_magic_link(uidb64: str, token: str):
    try:
        unsigned = MAGIC_LINK_SIGNER.unsign(token, max_age=60 * 60 * 24 * 7)
        if unsigned != uidb64:
            return None
        user_id = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=user_id)
    except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist):
        return None


def send_institution_account_email(request, user):
    activation_link = build_magic_link(request, user, "activate-account")
    login_link = build_magic_link(request, user, "magic-login")

    message = (
        "Bonjour,\n\n"
        "Votre compte institutionnel sur Assista-Crise a été créé.\n\n"
        "Il est encore inactif : cliquez sur le lien ci-dessous pour confirmer que vous êtes bien "
        "le propriétaire de cette adresse email et activer votre compte.\n\n"
        f"- Activation du compte : {activation_link}\n\n"
        f"Vous pourrez ensuite vous reconnecter à tout moment via : {login_link}\n\n"
        "Ces liens sont valables pendant 7 jours.\n\n"
        "Cordialement,\n"
        "L'équipe Assista-Crise"
    )

    send_mail(
        subject="Votre accès institutionnel Assista-Crise",
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_crisis_regulateur_invite_email(request, user, crisis, institution):
    activation_link = build_magic_link(request, user, "activate-account")
    login_link = build_magic_link(request, user, "magic-login")

    message = (
        "Bonjour,\n\n"
        f"Vous avez été désigné(e) responsable/régulateur par {institution.nom} "
        f"pour la crise « {crisis.name} » sur Assista-Crise.\n\n"
        "Votre compte est encore inactif : cliquez sur le lien ci-dessous pour confirmer que "
        "vous êtes bien le propriétaire de cette adresse email et l'activer.\n\n"
        f"- Activation du compte : {activation_link}\n\n"
        f"Vous pourrez ensuite vous reconnecter à tout moment via : {login_link}\n\n"
        "Ces liens sont valables pendant 7 jours.\n\n"
        "Cordialement,\n"
        "L'équipe Assista-Crise"
    )

    send_mail(
        subject="Vous avez été désigné responsable d'une crise sur Assista-Crise",
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )

from .serializers import (
    InstitutionTypeSerializer,
    InstitutionSerializer,
    RoleOperationnelSerializer,
    InstitutionCompetenceSerializer,
    AffectationRoleOperationnelSerializer,
    DelegationCompetenceSerializer,
    DisponibiliteOperationnelleSerializer,
    PointTypeSerializer,
    ContactInstitutionSerializer,
    InstitutionDomaineSerializer,
    PointOperationnelSerializer,
    ImplicationInstitutionSerializer,
    RecherchePersonnePhotoSerializer,
    DocumentSerializer,
    RecherchePersonneSerializer,
    RecherchePersonneCommentaireSerializer,
    RecherchePersonneCommentairePhotoSerializer,
    DossierCommentaireSerializer,
    DossierHistoriqueSerializer,
    NotificationSerializer,
    UserSerializer,
    RecherchePersonneLectureSerializer,
    RecherchePersonneLectureHistoriqueSerializer,
    CrisisSerializer,
    RequestTypeBesoinSerializer,
    RequestSerializer,
    OfferSerializer,
    DisponibiliteOffreSerializer,
    DisponibilitePointEquipeSerializer,
    MaterielPointSerializer,
    MaterielCatalogueSerializer,
    InformationSerializer,
    RequestTypeSerializer,
    OfferTypeSerializer,
    InformationTypeSerializer,
    TeamSerializer,
    CompetenceSerializer,
    DossierSerializer,
    AffectationCompetenceSerializer,
    BesoinSerializer,
    RecherchePersonneHistoriqueSerializer,
    BesoinCompetenceSerializer,
)

class BesoinViewSet(viewsets.ModelViewSet):
    queryset = Besoin.objects.all()
    serializer_class = BesoinSerializer

    def perform_create(self, serializer):
        besoin = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Besoin",
            objet_id=besoin.id,
            commentaire=f"Création besoin : {besoin}",
        )

class BesoinCompetenceViewSet(viewsets.ModelViewSet):
    queryset = BesoinCompetence.objects.all()
    serializer_class = BesoinCompetenceSerializer

class RequestTypeBesoinViewSet(viewsets.ModelViewSet):
    queryset = RequestTypeBesoin.objects.all()
    serializer_class = RequestTypeBesoinSerializer

class TagLikeViewSetMixin:
    """Pour les modèles qui fonctionnent comme des hashtags réutilisables (Competence.nom,
    InformationType.type) : recherche par mots-clés indépendante de l'ordre (`?q=transport
    animaux` remonte la même chose que `?q=animaux transport`) et création qui réutilise
    silencieusement une entrée existante proche (comparaison insensible à la casse) au lieu
    de dupliquer un thème déjà là sous une casse différente — cohérent avec l'usage attendu
    d'un tag : n'importe qui doit pouvoir en "créer" un sans jamais fragmenter le vocabulaire
    partagé par erreur de frappe sur la casse."""

    tag_field = "nom"

    def get_search_queryset(self, queryset, query):
        tokens = [t for t in query.strip().split() if t]
        for token in tokens:
            queryset = queryset.filter(**{f"{self.tag_field}__icontains": token})
        return queryset

    def list(self, request, *args, **kwargs):
        query = request.query_params.get("q", "").strip()
        if not query:
            return super().list(request, *args, **kwargs)

        queryset = self.get_search_queryset(self.filter_queryset(self.get_queryset()), query)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        return (
            self.get_paginated_response(serializer.data)
            if page is not None
            else Response(serializer.data)
        )

    def create(self, request, *args, **kwargs):
        raw_value = " ".join(str(request.data.get(self.tag_field) or "").split())
        if raw_value:
            existing = self.get_queryset().filter(**{f"{self.tag_field}__iexact": raw_value}).first()
            if existing:
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

            data = request.data.copy()
            data[self.tag_field] = raw_value
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

        return super().create(request, *args, **kwargs)


class CompetenceViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    queryset = Competence.objects.all()
    serializer_class = CompetenceSerializer

    def get_search_queryset(self, queryset, query):
        # Élargit la recherche par mots-clés aux compétences reliées à un Besoin dont le nom
        # matche (ex: chercher "animaux" doit aussi remonter une compétence rattachée à un
        # besoin "Sauvetage animalier", même si "animaux" n'apparaît pas dans son propre nom).
        base = super().get_search_queryset(queryset, query)
        tokens = [t for t in query.strip().split() if t]
        via_besoin = Competence.objects.all()
        for token in tokens:
            via_besoin = via_besoin.filter(besoins__besoin__nom__icontains=token)
        return (base | via_besoin).distinct()

    def perform_create(self, serializer):
        competence = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Competence",
            objet_id=competence.id,
            commentaire=f"Création thème/compétence : {competence.nom}",
        )

class AffectationCompetenceViewSet(viewsets.ModelViewSet):
    queryset = AffectationCompetence.objects.all()
    serializer_class = AffectationCompetenceSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="AFFECTATION",
            objet_type="AffectationCompetence",
            objet_id=affectation.id,
            commentaire=(
                f"Équipe {affectation.equipe.name} affectée à la compétence "
                f"{affectation.competence.nom} sur la crise {affectation.crise.name}"
            ),
        )

    def perform_update(self, serializer):
        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="AffectationCompetence",
            objet_id=affectation.id,
            commentaire=f"Modification affectation compétence : {affectation}",
        )

class DossierViewSet(viewsets.ModelViewSet):
    queryset = Dossier.objects.all()
    serializer_class = DossierSerializer

    def get_permissions(self):
        # La lecture reste ouverte à tout utilisateur authentifié concerné (filtrée par
        # get_queryset : participant du dossier, ou compte institutionnel). Modifier ou
        # supprimer un dossier restait jusqu'ici possible à n'importe quel participant
        # (ex: un simple demandeur) faute de restriction dédiée — désormais réservé aux
        # comptes institutionnels, comme pour les autres écritures sensibles de l'app.
        if self.action in ("update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Dossier.objects.none()
        if user.type in INSTITUTIONAL_TYPES:
            return Dossier.objects.all()
        return Dossier.objects.filter(participants__utilisateur=user).distinct()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def perform_create(self, serializer):
        dossier = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Dossier",
            objet_id=dossier.id,
            commentaire=f"Création dossier : {dossier}",
        )

    @action(
        detail=True,
        methods=["post"]
    )
    def mark_viewed(self, request, pk=None):

        dossier = self.get_object()

        participant = dossier.participants.filter(
            utilisateur=request.user
        ).first()

        if participant:

            participant.date_derniere_vue = (
                timezone.now()
            )

            participant.save()

        return Response(
            {"status": "ok"}
        )

    @action(detail=False, methods=["get"])
    def ma_file(self, request):
        """Dossiers en attente d'affectation sur les compétences (thèmes) du régulateur
        connecté — contrairement à la liste générale (tous les dossiers pour un compte
        institutionnel), ici filtrée à ce qui concerne réellement l'utilisateur."""
        user = request.user
        if not user.is_authenticated:
            return Response([])

        competence_ids = AffectationRoleOperationnel.objects.filter(
            utilisateur=user, role__code="REGULATEUR", actif=True, competence__isnull=False,
        ).values_list('competence_id', flat=True)

        queryset = Dossier.objects.filter(
            statut__in=[Dossier.Statut.EN_ATTENTE_DISTRIBUTION, Dossier.Statut.EN_ATTENTE_AFFECTATION],
            competence_id__in=competence_ids,
        ).distinct()

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def cloturer(self, request, pk=None):
        """Clôture un dossier (ou le marque résolu, via {"statut": "RESOLU"} dans le corps
        de la requête). Réservé au régulateur affecté à ce dossier précis (DossierParticipant
        role=REGULATION), au responsable désigné de l'institution impliquée sur la crise
        (ImplicationInstitution.responsable), ou à un administrateur — pas open-bar à tout
        compte institutionnel comme le PATCH générique."""
        dossier = self.get_object()
        user = request.user

        est_regulateur_du_dossier = dossier.participants.filter(
            utilisateur=user, role=DossierParticipant.Role.REGULATION,
        ).exists()
        est_responsable_crise = dossier.crise.implications.filter(
            responsable=user, actif=True,
        ).exists()

        if not (est_regulateur_du_dossier or est_responsable_crise or user.type == UserRole.ADMINISTRATOR):
            return Response(
                {"error": "Seul le régulateur affecté à ce dossier ou le responsable de la crise peut le clôturer."},
                status=status.HTTP_403_FORBIDDEN,
            )

        nouveau_statut = request.data.get("statut", Dossier.Statut.CLOTURE)
        if nouveau_statut not in (Dossier.Statut.CLOTURE, Dossier.Statut.RESOLU):
            return Response({"error": "Statut de clôture invalide."}, status=status.HTTP_400_BAD_REQUEST)

        ancien_statut = dossier.statut
        dossier.statut = nouveau_statut
        if nouveau_statut == Dossier.Statut.CLOTURE:
            dossier.date_cloture = timezone.now()
        else:
            dossier.date_resolution = timezone.now()
        dossier.save()

        DossierHistorique.objects.create(
            dossier=dossier, auteur=user,
            evenement=f"Dossier {dossier.get_statut_display().lower()}",
            commentaire=request.data.get("commentaire"),
        )

        audit_log(
            request=request,
            action_code="CLOTURE",
            objet_type="Dossier",
            objet_id=dossier.id,
            crise=dossier.crise,
            ancien_etat=ancien_statut,
            nouvel_etat=nouveau_statut,
            commentaire=f"Dossier {dossier.numero} {dossier.get_statut_display().lower()} par {user.email}",
        )

        return Response({"status": "ok", "statut": dossier.statut})


class AuthorEmailFilter(filters.FilterSet):
    author_email = filters.CharFilter(field_name='author__email', lookup_expr='iexact')

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        """Inscription d'un nouvel utilisateur"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="User",
                objet_id=user.id,
                commentaire=f"Inscription compte : {user.email}",
            )

            if getattr(user, 'type', None) == UserRole.LOCAL_AUTHORITY:
                # Compte créé mais désactivé (enabled=False, posé par UserSerializer.create) tant
                # que l'email n'est pas confirmé : pas de token ici. Le rattachement à une
                # institution n'a lieu qu'après le clic sur le lien d'activation
                # (AccountActivationView) — jamais sur la seule foi d'un email non vérifié.
                try:
                    send_institution_account_email(request, user)
                except Exception as e:
                    print(f"Erreur envoi email institution : {e}")

                return Response({
                    'user': UserSerializer(user).data,
                    'message': "Votre compte a été créé. Vérifiez votre boîte mail et cliquez sur le lien d'activation pour finaliser votre inscription.",
                    'requires_validation': False,
                    'requires_email_confirmation': True,
                }, status=status.HTTP_201_CREATED)

            # Si le compte nécessite validation (Secours, Admin)
            if not user.enabled:
                # Envoyer email à l'utilisateur
                try:
                    send_mail(
                        subject="Compte créé - En attente de validation",
                        message=(
                            f"Bonjour {user.first_name} {user.last_name},\n\n"
                            f"Votre compte ({user.get_type_display()}) a bien été créé.\n"
                            "Cependant, il est en attente de validation par un administrateur.\n"
                            "Vous recevrez un email dès que votre compte sera validé.\n\n"
                            "Cordialement,\n"
                            "L'équipe Assista-Crise"
                        ),
                        from_email=None,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(f"Erreur envoi email utilisateur : {e}")
                
                # Notifier les administrateurs
                admin_emails = User.objects.filter(
                    type='ADMIN', 
                    is_active=True
                ).values_list('email', flat=True)
                
                if admin_emails:
                    try:
                        send_mail(
                            subject=f"Nouvelle demande de validation - {user.get_type_display()}",
                            message=(
                                f"Un nouveau compte nécessite votre validation :\n\n"
                                f"- Nom : {user.first_name} {user.last_name}\n"
                                f"- Email : {user.email}\n"
                                f"- Type : {user.get_type_display()}\n"
                                f"- Code postal : {user.postal_code or 'Non renseigné'}\n\n"
                                f"Connectez-vous au dashboard pour valider ou rejeter ce compte.\n\n"
                                "Cordialement,\n"
                                "Système Assista-Crise"
                            ),
                            from_email=None,
                            recipient_list=list(admin_emails),
                            fail_silently=False,
                        )
                    except Exception as e:
                        print(f"Erreur envoi email admins : {e}")

                if getattr(user, 'type', None) in {'AUT_LOCALE', 'SECOURS', 'ADMIN'}:
                    try:
                        send_mail(
                            subject="Nouvelle création de compte institutionnel",
                            message=(
                                f"Bonjour,\n\n"
                                f"Un nouveau compte institutionnel a été créé sur Assista-Crise.\n\n"
                                f"- Nom : {user.first_name} {user.last_name}\n"
                                f"- Email : {user.email}\n"
                                f"- Type : {user.get_type_display()}\n"
                                f"- Code postal : {user.postal_code or 'Non renseigné'}\n\n"
                                "Une validation est nécessaire avant activation."
                            ),
                            from_email=None,
                            recipient_list=['contact@assista-crise.fr'],
                            fail_silently=False,
                        )
                    except Exception as e:
                        print(f"Erreur envoi email contact institutionnel : {e}")
                
                # NE PAS retourner de token si le compte nécessite validation
                return Response({
                    'user': UserSerializer(user).data,
                    'message': 'Votre demande a été soumise et transmise à l’équipe. Un administrateur la validra prochainement.',
                    'requires_validation': True
                }, status=status.HTTP_201_CREATED)
            
            # Le compte est validé, retourner le token
            refresh = RefreshToken.for_user(user)
            return Response({
                'user': UserSerializer(user).data,
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'message': 'Utilisateur créé avec succès'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login(self, request):
        """Connexion utilisateur"""
        email = request.data.get('email')
        password = request.data.get('password')
        
        if not email or not password:
            return Response(
                {'error': 'Email et mot de passe requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Authentifier par email
        try:
            user = User.objects.get(email=email)
            
            # Vérifier que le compte est actif ET validé
            if not user.is_active:
                return Response(
                    {'error': 'Ce compte a été désactivé'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            if not user.enabled:
                return Response(
                    {'error': 'Votre compte est en attente de validation par un administrateur'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if user.check_password(password):
                refresh = RefreshToken.for_user(user)
                audit_log(
                    request=request,
                    action_code="CONNEXION",
                    objet_type="User",
                    objet_id=user.id,
                    commentaire=(
                        f"Connexion de "
                        f"{user.email}"
                    )
                )
                return Response({
                    'user': UserSerializer(user).data,
                    'token': str(refresh.access_token),
                    'refresh': str(refresh),
                    'message': 'Connexion réussie'
                })
            else:
                return Response(
                    {'error': 'Identifiants invalides'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
        except User.DoesNotExist:
            return Response(
                {'error': 'Identifiants invalides'},
                status=status.HTTP_401_UNAUTHORIZED
            )
    
    @action(detail=False, methods=['post'])
    def logout(self, request):
        """Déconnexion (côté client, le token sera supprimé)"""
        return Response({'message': 'Déconnexion réussie'}, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def pending_validations(self, request):
        """Liste des comptes en attente de validation"""
        user = request.user
        
        # Seuls les admins et institutions peuvent voir les validations
        if user.type not in ['ADMIN', 'AUT_LOCALE']:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Les admins voient tout, les institutions voient leur code postal
        if user.type == 'ADMIN':
            pending_users = User.objects.filter(enabled=False, is_active=True)
        else:
            pending_users = User.objects.filter(
                enabled=False, 
                is_active=True,
                postal_code=user.postal_code
            )
        
        serializer = self.get_serializer(pending_users, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def approve_account(self, request, pk=None):
        """Approuver un compte en attente"""
        user_to_approve = self.get_object()
        validator = request.user
        
        # Vérifier les permissions
        if validator.type not in ['ADMIN', 'AUT_LOCALE']:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Les institutions ne peuvent valider que leur code postal
        if validator.type == 'AUT_LOCALE' and validator.postal_code != user_to_approve.postal_code:
            return Response(
                {'error': 'Vous ne pouvez valider que les comptes de votre territoire'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Activer le compte (is_active est le champ réellement vérifié par /api/token/ ;
        # enabled seul ne suffit pas à bloquer la connexion)
        user_to_approve.enabled = True
        user_to_approve.is_active = True
        user_to_approve.save()
        
        # Envoyer email de confirmation
        try:
            send_mail(
                subject="Votre compte a été validé !",
                message=(
                    f"Bonjour {user_to_approve.first_name} {user_to_approve.last_name},\n\n"
                    f"Bonne nouvelle ! Votre compte ({user_to_approve.get_type_display()}) a été validé.\n"
                    "Vous pouvez maintenant vous connecter et accéder à toutes les fonctionnalités.\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[user_to_approve.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Erreur envoi email validation : {e}")
        
        return Response({
            'message': 'Compte validé avec succès',
            'user': UserSerializer(user_to_approve).data
        })
    
    @action(detail=True, methods=['post'])
    def reject_account(self, request, pk=None):
        """Rejeter un compte en attente"""
        user_to_reject = self.get_object()
        validator = request.user
        reason = request.data.get('reason', 'Non spécifiée')
        
        # Vérifier les permissions
        if validator.type not in ['ADMIN', 'AUT_LOCALE']:
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Les institutions ne peuvent rejeter que leur code postal
        if validator.type == 'AUT_LOCALE' and validator.postal_code != user_to_reject.postal_code:
            return Response(
                {'error': 'Vous ne pouvez rejeter que les comptes de votre territoire'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Envoyer email de rejet
        try:
            send_mail(
                subject="Votre demande de compte a été refusée",
                message=(
                    f"Bonjour {user_to_reject.first_name} {user_to_reject.last_name},\n\n"
                    f"Nous sommes désolés de vous informer que votre demande de compte "
                    f"({user_to_reject.get_type_display()}) n'a pas été acceptée.\n\n"
                    f"Raison : {reason}\n\n"
                    "Pour plus d'informations, vous pouvez nous contacter.\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[user_to_reject.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Erreur envoi email rejet : {e}")
        
        # Désactiver le compte (ou le supprimer)
        user_to_reject.is_active = False
        user_to_reject.save()
        
        return Response({
            'message': 'Compte rejeté',
            'user': UserSerializer(user_to_reject).data
        })

class CrisisViewSet(viewsets.ModelViewSet):
    queryset = Crisis.objects.all()
    serializer_class = CrisisSerializer
    filterset_class = AuthorEmailFilter

    def get_permissions(self):
        # Consultation (liste/détail) : ouverte à tous, transparence publique inchangée.
        # Création/modification : réservées aux acteurs institutionnels.
        # Suppression : réservée aux administrateurs.
        # Ce get_permissions() étant surchargé au niveau de la classe, les permission_classes
        # posées sur un @action ne s'appliquent jamais d'elles-mêmes — chaque action custom
        # doit être explicitement listée ici, sinon elle retombe sur AllowAny (cf. cloturer/
        # reouvrir, découvert en corrigeant ce bug).
        if self.action in ("create", "update", "partial_update"):
            return [IsInstitutionalActor()]
        if self.action == "destroy":
            return [IsAdministrator()]
        if self.action == "cloturer":
            return [IsInstitutionalActor()]
        if self.action == "reouvrir":
            return [IsAdministrator()]
        if self.action == "export":
            return [permissions.IsAuthenticated()]
        if self.action == "stocks_comparaison":
            return [permissions.IsAuthenticated()]
        return [AllowAny()]

    def perform_create(self, serializer):
        crise = serializer.save(author=self.request.user)
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            commentaire=f"Création crise : {crise.name}",
        )

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        crise = self.get_object()
        if not crise.photo or not user_can_view_photo(
            request.user, crise, teams_field='assigned_teams', dossiers_field='dossiers'
        ):
            return Response(status=403)
        return FileResponse(open(crise.photo.path, "rb"))

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def cloturer(self, request, pk=None):
        """Clôture une crise : bloque toute nouvelle implication/point/délégation dessus
        (cf. validate_crisis_open) sans toucher aux dossiers déjà en cours. Réservé au
        responsable actif d'une institution impliquée sur cette crise, ou à un administrateur."""
        crise = self.get_object()
        user = request.user

        est_responsable_crise = crise.implications.filter(responsable=user, actif=True).exists()
        if not (est_responsable_crise or user.type == UserRole.ADMINISTRATOR):
            return Response(
                {"error": "Seul le responsable d'une institution impliquée sur cette crise peut la clôturer."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if crise.end_date is not None:
            return Response({"error": "Cette crise est déjà clôturée."}, status=status.HTTP_400_BAD_REQUEST)

        crise.end_date = timezone.now()
        crise.save()

        audit_log(
            request=request,
            action_code="CLOTURE",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            ancien_etat="OUVERTE",
            nouvel_etat="CLOTUREE",
            commentaire=f"Crise {crise.name} clôturée par {user.email}",
        )

        return Response({"status": "ok", "end_date": crise.end_date})

    @action(detail=True, methods=["post"], permission_classes=[IsAdministrator])
    def reouvrir(self, request, pk=None):
        """Réouvre une crise clôturée par erreur — réservé aux administrateurs."""
        crise = self.get_object()

        if crise.end_date is None:
            return Response({"error": "Cette crise est déjà ouverte."}, status=status.HTTP_400_BAD_REQUEST)

        crise.end_date = None
        crise.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            ancien_etat="CLOTUREE",
            nouvel_etat="OUVERTE",
            commentaire=f"Crise {crise.name} réouverte par {request.user.email}",
        )

        return Response({"status": "ok"})

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Export de la main courante complète de la crise (zip multi-CSV). Réservé au
        responsable actif d'une institution impliquée ou à un administrateur — plus strict
        que IsInstitutionalActor : un acteur institutionnel quelconque n'a pas forcément
        vocation à voir les données de TOUTES les institutions de la crise."""
        crise = self.get_object()
        user = request.user

        est_responsable_crise = crise.implications.filter(responsable=user, actif=True).exists()
        if not (est_responsable_crise or user.type == UserRole.ADMINISTRATOR):
            return Response(
                {"error": "Seul le responsable d'une institution impliquée sur cette crise peut exporter sa main courante."},
                status=status.HTTP_403_FORBIDDEN,
            )

        zip_buffer = build_crisis_export_zip(crise)

        audit_log(
            request=request,
            action_code="EXPORT",
            objet_type="Crisis",
            objet_id=crise.id,
            crise=crise,
            commentaire=f"Export de la main courante de la crise {crise.name} par {user.email}",
        )

        response = FileResponse(zip_buffer, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="crise-{crise.id}-main-courante.zip"'
        return response

    @action(detail=True, methods=["get"], url_path="stocks-comparaison")
    def stocks_comparaison(self, request, pk=None):
        """Niveau de stock de chaque item du catalogue matériel, pour chaque point de la crise
        — de quoi construire directement un tableau comparatif côté frontend (lignes = items,
        colonnes = points) pour organiser une navette entre deux centres."""
        crise = self.get_object()
        points = list(crise.points_operationnels.select_related("type").order_by("nom"))
        materiels = MaterielPoint.objects.filter(point__in=points).select_related("item", "point")

        niveaux = {}
        for m in materiels:
            niveaux.setdefault(str(m.item_id), {})[str(m.point_id)] = {
                "niveau_stock": m.niveau_stock,
                "niveau_stock_libelle": m.get_niveau_stock_display(),
            }

        items = []
        for item in MaterielCatalogue.objects.all().order_by("nom"):
            par_point = niveaux.get(str(item.id), {})
            items.append({
                "item": str(item.id),
                "item_nom": item.nom,
                "niveaux": {
                    str(p.id): par_point.get(str(p.id), {
                        "niveau_stock": NiveauStock.NUL,
                        "niveau_stock_libelle": NiveauStock.NUL.label,
                    })
                    for p in points
                },
            })

        return Response({
            "points": [{"id": str(p.id), "nom": p.nom, "type_libelle": p.type.libelle if p.type else None} for p in points],
            "items": items,
        })

def resolve_or_invite_demandeur(demande, request=None):
    """Résout le compte utilisateur du demandeur d'une aide pour lui permettre de suivre son
    dossier par lien magique : l'auteur de la demande s'il est authentifié, sinon un compte
    existant partageant le même email, sinon un nouveau compte créé à la volée à partir des
    coordonnées saisies dans le formulaire (`email_request`/`first_name_request`/`last_name_request`).
    Contrairement à `resolve_or_invite_responsable`, ce compte n'a besoin d'aucune étape de
    définition de mot de passe : il n'est destiné qu'à recevoir des liens de connexion magique,
    donc `enabled`/`is_active` sont activés directement.

    Retourne (user, created)."""
    if demande.author:
        return demande.author, False

    email = (demande.email_request or '').strip().lower()
    if not email:
        return None, False

    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        return existing, False

    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,
        type=UserRole.SIMPLE_USER,
        first_name=demande.first_name_request,
        last_name=demande.last_name_request,
        enabled=True,
        is_active=True,
    )
    if request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="User",
            objet_id=user.id,
            commentaire=f"Compte créé pour {email} afin de suivre sa demande d'aide",
        )
    return user, True


def department_code_from_commune_code(commune_code):
    """Extrait le code département d'un code commune INSEE : 3 chiffres pour l'outre-mer
    (971-976/98x), 2 caractères sinon (dont '2A'/'2B' pour la Corse, déjà sous cette forme
    dans le code commune)."""
    if not commune_code:
        return None
    code = commune_code.strip().upper()
    if code[:2] in ('2A', '2B'):
        return code[:2]
    if code[:2] in ('97', '98'):
        return code[:3]
    return code[:2]


def team_zone_specificity(team, demande):
    """Score de spécificité de la couverture géographique d'une équipe pour une demande :
    plus le nombre est élevé, plus la correspondance est précise. `None` si l'équipe a
    déclaré une zone mais qu'elle ne couvre pas la demande — dans ce cas l'équipe est
    exclue du matching. Une équipe n'ayant déclaré aucune zone (cas de toutes les équipes
    existantes avant cette fonctionnalité) est considérée disponible partout, pour ne pas
    régresser le comportement précédent."""
    if not (team.departements or team.communes or team.zone_precise):
        return 0

    if team.zone_precise and demande.location and team.zone_precise.contains(demande.location):
        return 3

    commune_code = (demande.commune_code or '').strip()

    if team.communes and commune_code in team.communes:
        return 2

    if team.departements:
        departement = department_code_from_commune_code(commune_code)
        if departement and departement in team.departements:
            return 1

    return None


def resolve_competence_for_request(demande):
    """Compétence déduite du type de demande (RequestType -> Besoin -> Competence),
    utilisée aussi bien pour le matching automatique (perform_create) que pour fiabiliser
    le rattachement d'un dossier créé manuellement (assign_team)."""
    mapping_besoin = RequestTypeBesoin.objects.filter(request_type=demande.request_type).first()
    if not mapping_besoin:
        return None
    mapping_competence = BesoinCompetence.objects.filter(besoin=mapping_besoin.besoin).first()
    return mapping_competence.competence if mapping_competence else None


def populate_dossier_participants_and_notify(
    dossier, demandeur=None, equipe=None,
    notification_titre="Nouveau dossier à affecter",
    notification_message=None,
):
    """Peuple les DossierParticipant (demandeur, équipe, régulation) et notifie les
    régulateurs concernés d'un dossier fraîchement créé. Logique partagée entre le chemin
    automatique (perform_create) et le chemin manuel (assign_team), qui divergeaient
    jusqu'ici : l'un ajoutait l'équipe comme participants mais ne notifiait jamais de
    régulateur sur simple base de compétence, l'autre notifiait sans jamais peupler le rôle
    REGULATION ni ajouter l'équipe comme participants."""
    if demandeur:
        DossierParticipant.objects.get_or_create(
            dossier=dossier, utilisateur=demandeur, role=DossierParticipant.Role.DEMANDEUR,
        )
        DossierHistorique.objects.create(
            dossier=dossier, auteur=demandeur, evenement="Demandeur ajouté au dossier",
        )

    if equipe:
        DossierHistorique.objects.create(
            dossier=dossier, evenement=f"Équipe affectée : {equipe.name}",
        )
        for membre in equipe.members.all():
            DossierParticipant.objects.get_or_create(
                dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE,
            )
            DossierHistorique.objects.create(
                dossier=dossier, auteur=membre, evenement="Intervenant ajouté au dossier",
            )

    if dossier.competence:
        # Régulateur·s affecté·s à cette compétence, indépendamment de leur équipe.
        regulateurs = User.objects.filter(
            affectations_roles__competence=dossier.competence,
            affectations_roles__role__code="REGULATEUR",
            affectations_roles__actif=True,
        ).distinct()
    elif equipe:
        # Pas de compétence rattachée au dossier (ex: mapping RequestType->Besoin absent) :
        # à défaut, régulateur·s parmi les membres de l'équipe affectée, sur l'une de ses
        # compétences déclarées (ou n'importe laquelle des leurs si l'équipe n'en a aucune).
        member_ids = equipe.members.values_list('id', flat=True)
        regulateur_affectations = AffectationRoleOperationnel.objects.filter(
            utilisateur_id__in=member_ids, role__code="REGULATEUR", actif=True,
        )
        competence_ids = list(equipe.competences.values_list('id', flat=True))
        if competence_ids:
            regulateur_affectations = regulateur_affectations.filter(competence_id__in=competence_ids)
        regulateurs = User.objects.filter(
            id__in=regulateur_affectations.values_list('utilisateur_id', flat=True)
        ).distinct()
    else:
        regulateurs = User.objects.none()

    for regulateur in regulateurs:
        DossierParticipant.objects.get_or_create(
            dossier=dossier, utilisateur=regulateur, role=DossierParticipant.Role.REGULATION,
        )
        Notification.objects.create(
            utilisateur=regulateur,
            dossier=dossier,
            titre=notification_titre,
            message=notification_message or f"Le dossier {dossier.numero} ({dossier.titre}) nécessite une affectation.",
        )
        DossierHistorique.objects.create(
            dossier=dossier, auteur=regulateur,
            evenement=f"{regulateur.email} notifié en tant que régulateur",
        )

    return regulateurs


class RequestViewSet(viewsets.ModelViewSet):
    queryset = Request.objects.all()
    serializer_class = RequestSerializer
    permission_classes = [AllowAny]
    filterset_class = AuthorEmailFilter


    def perform_create(self, serializer):
        # Générer un token de suppression unique
        deletion_token = secrets.token_urlsafe(32)
        
        # Définir l'auteur si authentifié, sinon None
        author = self.request.user if self.request.user.is_authenticated else None
        demande = serializer.save(author=author, deletion_token=deletion_token)
        
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Request",
            objet_id=demande.id,
            crise=demande.crisis,
            commentaire=(
                f"Création demande : "
                f"{demande.title}"
            )
        )

        try:

            statut = Dossier.Statut.EN_ATTENTE_AFFECTATION

            equipe = None
            competence = resolve_competence_for_request(demande)

            if competence:

                regulateurs_disponibles = (
                    AffectationRoleOperationnel.objects
                    .filter(
                        competence=competence,
                        role__code="REGULATEUR",
                        actif=True,
                        disponibilites__disponible=True,
                        disponibilites__date_fin__isnull=True
                    )
                    .distinct()
                )

                if regulateurs_disponibles.exists():

                    statut = Dossier.Statut.AFFECTE

                else:

                    statut = (
                        Dossier.Statut
                        .EN_ATTENTE_DISTRIBUTION
                    )

                if demande.crisis:

                    # Parmi les équipes affectées à cette compétence sur cette crise, on
                    # retient celle dont la zone d'intervention déclarée couvre le mieux
                    # la localisation de la demande (zone précise > commune > département
                    # > aucune zone déclarée = disponible partout).
                    affectations = (
                        AffectationCompetence.objects
                        .filter(
                            crise=demande.crisis,
                            competence=competence,
                            active=True
                        )
                        .select_related('equipe')
                    )

                    meilleur_score = None

                    for affectation in affectations:

                        score = team_zone_specificity(affectation.equipe, demande)

                        if score is not None and (meilleur_score is None or score > meilleur_score):
                            meilleur_score = score
                            equipe = affectation.equipe

            if competence:

                dossier = Dossier.objects.create(
                    numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                    crise=demande.crisis,
                    competence=competence,
                    equipe=equipe,
                    demande=demande,
                    titre=demande.title,
                    description=f"Demande créée automatiquement : {demande.title}",
                    statut=statut
                )

                demandeur, _ = resolve_or_invite_demandeur(demande, request=self.request)
                # Notifie aussi les régulateurs actifs sur cette compétence : sans ça, un
                # dossier créé automatiquement n'était visible qu'en parcourant la liste
                # complète des dossiers — contrairement au chemin manuel (assign_team) qui
                # notifie déjà. Ils le retrouvent aussi via /dossiers/ma_file/.
                populate_dossier_participants_and_notify(dossier, demandeur=demandeur, equipe=equipe)

                audit_log(
                    request=self.request,
                    action_code="CREATION",
                    objet_type="Dossier",
                    objet_id=dossier.id,
                    crise=dossier.crise,
                    commentaire=f"Dossier {dossier.numero} créé automatiquement pour la demande : {demande.title}",
                )

            else:

                # Dossier.crise est obligatoire (NOT NULL) : sans crise associée à la
                # demande, il n'y a de toute façon aucun contexte auquel rattacher un
                # dossier de suivi automatique — le créer plantait silencieusement
                # (IntegrityError avalée par le except englobant) pour toute demande
                # anonyme sans crise dont le type n'a pas de compétence mappée.
                if demande.crisis:

                    dossier = Dossier.objects.create(
                        numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                        crise=demande.crisis,
                        competence=None,
                        equipe=None,
                        demande=demande,
                        titre=demande.title,
                        description=(
                            f"Demande créée automatiquement : "
                            f"{demande.title}"
                        ),
                        statut=Dossier.Statut.EN_ATTENTE_AFFECTATION
                    )

                    demandeur, _ = resolve_or_invite_demandeur(demande, request=self.request)
                    # Sans compétence ni équipe identifiée, seul le demandeur peut être
                    # rattaché ici (aucun régulateur à notifier) — mais c'est déjà mieux que
                    # zéro participant : sans ça ce dossier restait invisible au demandeur
                    # (le suivi passe par DossierParticipant, pas seulement par institution).
                    populate_dossier_participants_and_notify(dossier, demandeur=demandeur)

                    DossierHistorique.objects.create(
                        dossier=dossier,
                        evenement="Aucune compétence trouvée automatiquement",
                        commentaire=(
                            "Le dossier nécessite "
                            "une affectation manuelle."
                        )
                    )

                    audit_log(
                        request=self.request,
                        action_code="CREATION",
                        objet_type="Dossier",
                        objet_id=dossier.id,
                        crise=dossier.crise,
                        commentaire=f"Dossier {dossier.numero} créé automatiquement (sans compétence) pour la demande : {demande.title}",
                    )

                print(
                    f"Aucune compétence trouvée pour "
                    f"{demande.request_type}"
                )

        except Exception as e:
            print(f"Erreur création dossier automatique : {e}")

        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = self.request.build_absolute_uri(f'/api/delete-request/{deletion_token}/')
        
        try:
            print(f"Tentative d'envoi de mail à {demande.email_request}...")
            
            send_mail(
                subject="Confirmation de votre demande",
                message=(
                    f"Bonjour {demande.first_name_request},\n\n"
                    f"Nous accusons réception de votre demande d'aide : {demande.title}.\n"
                    "Elle est actuellement en attente de traitement par nos services.\n\n"
                    f"Si vous souhaitez annuler cette demande, cliquez sur le lien suivant :\n"
                    f"{deletion_url}\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,  # Utilise DEFAULT_FROM_EMAIL défini dans settings.py
                recipient_list=[demande.email_request],
                fail_silently=False,
            )
            print("Succès : Email de confirmation envoyé.")
            
        except Exception as e:
            print(f"Erreur critique : L'envoi de l'email a échoué. Détails : {e}")

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def assign_team(self, request, pk=None):
        """Affecte la demande à une équipe : crée un dossier de suivi, notifie le·s
        régulateur·s de l'équipe (AffectationRoleOperationnel role=REGULATEUR) et informe le
        demandeur par email. Ré-affecter à la même équipe est un no-op (pas de doublon)."""
        demande = self.get_object()
        team = get_object_or_404(Team, pk=request.data.get("team"))

        if team.assigned_requests.filter(pk=demande.pk).exists():
            return Response({"already_assigned": True})

        if not demande.crisis:
            return Response(
                {"error": "Cette demande n'est liée à aucune crise : impossible de créer un dossier de suivi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        team.assigned_requests.add(demande)

        dossier = Dossier.objects.create(
            numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
            crise=demande.crisis,
            competence=resolve_competence_for_request(demande),
            equipe=team,
            demande=demande,
            titre=demande.title,
            description=f"Demande affectée à l'équipe {team.name} : {demande.title}",
            statut=Dossier.Statut.AFFECTE,
        )

        demandeur, _ = resolve_or_invite_demandeur(demande, request=request)

        # Régulateur·s à notifier : ceux affectés à la compétence du dossier si elle a pu
        # être déduite, sinon (à défaut) les membres de l'équipe ayant un rôle opérationnel
        # REGULATEUR actif pour l'une des compétences de l'équipe — pour ne pas notifier
        # personne juste parce que le mapping RequestType->Besoin est absent.
        regulateurs = populate_dossier_participants_and_notify(
            dossier, demandeur=demandeur, equipe=team,
            notification_titre="Nouvelle demande affectée à votre équipe",
            notification_message=f"La demande « {demande.title} » a été affectée à l'équipe {team.name} (dossier {dossier.numero}).",
        )

        try:
            suivi_paragraph = ""
            if demandeur:
                suivi_link = build_magic_link(
                    request, demandeur, "magic-login", next_url=f"/dossier-suivi/{dossier.id}"
                )
                suivi_paragraph = (
                    f"\nVous pouvez suivre l'avancement de votre dossier, ajouter des "
                    f"commentaires et des photos ici :\n{suivi_link}\n"
                )
            send_mail(
                subject=f"Votre demande « {demande.title} » a été prise en charge",
                message=(
                    f"Bonjour {demande.first_name_request},\n\n"
                    f"Votre demande d'aide « {demande.title} » a été affectée à l'équipe {team.name}, "
                    f"qui va la traiter (dossier {dossier.numero}).\n"
                    f"{suivi_paragraph}\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[demande.email_request],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Erreur envoi email affectation demande : {e}")

        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Dossier",
            objet_id=dossier.id,
            crise=demande.crisis,
            commentaire=f"Dossier {dossier.numero} créé suite à l'affectation de la demande à {team.name}",
        )

        return Response({"dossier": str(dossier.id), "numero": dossier.numero, "regulateurs_notifies": regulateurs.count()})

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        demande = self.get_object()
        if not demande.photo or not user_can_view_photo(
            request.user, demande, teams_field='assigned_teams', dossiers_field='dossiers'
        ):
            return Response(status=403)
        return FileResponse(open(demande.photo.path, "rb"))

class TeamViewSet(viewsets.ModelViewSet):
    queryset           = Team.objects.prefetch_related(
        'members', 'assigned_crises', 'assigned_offers', 'assigned_requests'
    ).select_related('leader').all()
    serializer_class   = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        team = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Team",
            objet_id=team.id,
            commentaire=f"Création équipe : {team.name}",
        )

class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.all()
    serializer_class = OfferSerializer
    permission_classes = [AllowAny]
    filterset_class = AuthorEmailFilter

    def perform_create(self, serializer):
        # Générer un token de suppression unique
        deletion_token = secrets.token_urlsafe(32)
        
        # Si user authentifié, il est autheur
        if self.request.user.is_authenticated:
            offre = serializer.save(author=self.request.user, deletion_token=deletion_token)
        else:
            # Sinon il est none
            offre = serializer.save(author=None, deletion_token=deletion_token)
        
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Offer",
            objet_id=offre.id,
            commentaire=f"Création offre : {offre.title}",
        )

        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = self.request.build_absolute_uri(f'/api/delete-offer/{deletion_token}/')

        try:
            print(f"Tentative d'envoi de mail à {offre.email_offer}...")
            
            send_mail(
                subject=f"Confirmation : Votre offre '{offre.title}' a bien été enregistrée",
                message=(
                    f"Bonjour {offre.first_name_offer},\n\n"
                    f"Nous vous remercions pour votre offre d'aide : {offre.title}.\n"
                    "Elle est maintenant visible et disponible pour les personnes dans le besoin.\n\n"
                    f"Si vous souhaitez retirer cette offre, cliquez sur le lien suivant :\n"
                    f"{deletion_url}\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[offre.email_offer],
                fail_silently=False,
            )
            print("Succès : Email de confirmation envoyé.")
            
        except Exception as e:
            print(f"Erreur critique : L'envoi de l'email a échoué. Détails : {e}")

    @action(detail=True, methods=["post"], permission_classes=[IsInstitutionalActor])
    def assign_dossier(self, request, pk=None):
        """Affecte l'auteur de l'offre à un dossier (participant OFFRANT). L'offre doit avoir un
        auteur identifié (compte utilisateur) : une offre anonyme ne peut pas être rattachée."""
        offer = self.get_object()
        if not offer.author:
            return Response(
                {"error": "Cette offre n'a pas d'auteur identifié : impossible de l'affecter à un dossier."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dossier = get_object_or_404(Dossier, pk=request.data.get("dossier"))
        participant, created = DossierParticipant.objects.get_or_create(
            dossier=dossier, utilisateur=offer.author, role=DossierParticipant.Role.OFFRANT
        )
        if created:
            DossierHistorique.objects.create(
                dossier=dossier, auteur=offer.author,
                evenement=f"Offrant ajouté au dossier (offre : {offer.title})",
            )
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="DossierParticipant",
                objet_id=participant.id,
                commentaire=f"{offer.author.email} affecté au dossier {dossier.numero} en tant qu'offrant",
            )

        return Response({"id": str(participant.id), "dossier": str(dossier.id), "created": created})

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        offer = self.get_object()
        if not offer.photo or not user_can_view_photo(
            request.user, offer, teams_field='assigned_teams'
        ):
            return Response(status=403)
        return FileResponse(open(offer.photo.path, "rb"))

class DisponibiliteOffreViewSet(viewsets.ModelViewSet):
    """Créneaux de disponibilité (matin/midi/soir/nuit, 8 jours) déclarés avec une offre d'aide."""
    queryset = DisponibiliteOffre.objects.all()
    serializer_class = DisponibiliteOffreSerializer
    permission_classes = [AllowAny]
    filterset_fields = ["offer"]

class InformationViewSet(viewsets.ModelViewSet):
    queryset = Information.objects.all()
    serializer_class = InformationSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        # Générer un token de suppression unique
        deletion_token = secrets.token_urlsafe(32)
        
        # Si l'utilisateur est authentifié, on l'assigne comme auteur
        if self.request.user.is_authenticated:
            info = serializer.save(author=self.request.user, deletion_token=deletion_token)
        else:
            # Sinon on sauvegarde sans auteur (None)
            info = serializer.save(author=None, deletion_token=deletion_token)
        
        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = self.request.build_absolute_uri(f'/api/delete-information/{deletion_token}/')
        
        try:
            print(f"Tentative d'envoi de mail à {info.email_information}...")
            
            send_mail(
                subject=f"Confirmation : Votre information '{info.title}' a bien été partagée",
                message=(
                    f"Bonjour {info.first_name_information},\n\n"
                    f"Nous vous remercions pour le partage de cette information : {info.title}.\n"
                    "Elle est maintenant visible par la communauté.\n\n"
                    f"Si vous souhaitez retirer cette information, cliquez sur le lien suivant :\n"
                    f"{deletion_url}\n\n"
                    "Cordialement,\n"
                    "L'équipe Assista-Crise"
                ),
                from_email=None,
                recipient_list=[info.email_information],
                fail_silently=False,
            )
            print("Succès : Email de confirmation envoyé.")
            
        except Exception as e:
            print(f"Erreur critique : L'envoi de l'email a échoué. Détails : {e}")

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        info = self.get_object()
        if not info.photo or not user_can_view_photo(request.user, info):
            return Response(status=403)
        return FileResponse(open(info.photo.path, "rb"))

# --- VIEWSETS SIMPLES POUR LES TYPES ---
class RequestTypeViewSet(viewsets.ModelViewSet):
    # AllowAny : le formulaire public "demander de l'aide" (request-help-form) n'a pas de
    # garde d'authentification — sans ça, un visiteur anonyme recevait un 401 en listant les
    # types, d'où le menu "Choisissez votre besoin" vide (même bug que déjà corrigé sur
    # InformationTypeViewSet pour le signalement, et déjà bon sur OfferTypeViewSet).
    queryset = RequestType.objects.all()
    serializer_class = RequestTypeSerializer
    permission_classes = [AllowAny]

class OfferTypeViewSet(viewsets.ModelViewSet):
    queryset = OfferType.objects.all()
    serializer_class = OfferTypeSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return OfferType.objects.filter(actif=True)

class InformationTypeViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    # AllowAny : la page de signalement (other-declaration-form) est accessible sans compte,
    # au même titre que les autres formulaires publics (demande/offre/crise) — un passant qui
    # signale un arbre sur la chaussée ne doit pas avoir à se connecter, y compris pour lister
    # les types existants ou en proposer un nouveau.
    queryset = InformationType.objects.all()
    serializer_class = InformationTypeSerializer
    permission_classes = [AllowAny]
    tag_field = "type"

    def perform_create(self, serializer):
        information_type = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InformationType",
            objet_id=information_type.id,
            commentaire=f"Création type de signalement : {information_type.type}",
        )

# --- VUES POUR LA SUPPRESSION VIA TOKEN ---
from django.views import View
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

class DeleteRequestView(View):
    """Vue pour supprimer une demande via token"""
    def get(self, request, token):
        demande = get_object_or_404(Request, deletion_token=token)
        titre = demande.title
        demande.delete()
        return HttpResponse(f"<h1>Demande supprimée</h1><p>La demande '{titre}' a bien été supprimée.</p>")

class DeleteOfferView(View):
    """Vue pour supprimer une offre via token"""
    def get(self, request, token):
        offre = get_object_or_404(Offer, deletion_token=token)
        titre = offre.title
        offre.delete()
        return HttpResponse(f"<h1>Offre supprimée</h1><p>L'offre '{titre}' a bien été supprimée.</p>")

class DeleteInformationView(View):
    """Vue pour supprimer une information via token"""
    def get(self, request, token):
        info = get_object_or_404(Information, deletion_token=token)
        titre = info.title
        info.delete()
        return HttpResponse(f"<h1>Information supprimée</h1><p>L'information '{titre}' a bien été supprimée.</p>")

    #  --------------------------- add by Laura ------------------------------------

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

class MyTokenRefreshView(TokenRefreshView):
    """Rafraîchir un token ne nécessite qu'un refresh token valide, pas une session déjà authentifiée."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer # Ajoute la logique de mot de passe dans le serializer
    permission_classes = [permissions.AllowAny]

class InstitutionValidationView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email", "")
        institution_name = request.data.get("institution_name", "")
        institution_type = request.data.get("institution_type", "")
        commune_name = request.data.get("commune_name", "")
        commune_code = request.data.get("commune_code", "")

        valid, message, details = InstitutionEmailValidator.validate_institution_account(
            email=email,
            institution_name=institution_name,
            institution_type=institution_type,
            commune_name=commune_name,
            commune_code=commune_code,
        )

        return Response({
            "valid": valid,
            "message": message,
            "details": details,
        }, status=status.HTTP_200_OK if valid else status.HTTP_400_BAD_REQUEST)

class AccountActivationView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token, *args, **kwargs):
        user = get_user_from_magic_link(uidb64, token)
        if not user:
            return Response({'error': 'Lien invalide ou expiré'}, status=status.HTTP_400_BAD_REQUEST)

        already_enabled = user.enabled

        user.enabled = True
        user.is_active = True
        user.save(update_fields=['enabled', 'is_active'])

        # Le rattachement à une institution (contact + rôle opérationnel) ne doit se faire qu'ici,
        # une fois la possession de la boîte mail prouvée par ce clic — jamais à la simple
        # inscription. Idempotent (get_or_create) : un second clic ne duplique rien.
        if not already_enabled and getattr(user, 'type', None) == UserRole.LOCAL_AUTHORITY:
            attach_user_to_institution(user, request)
            audit_log(
                request=request,
                action_code="CONNEXION",
                objet_type="User",
                objet_id=user.id,
                commentaire=f"Activation de compte confirmée par email : {user.email}",
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'message': 'Compte activé avec succès',
        }, status=status.HTTP_200_OK)


class MagicLoginView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token, *args, **kwargs):
        user = get_user_from_magic_link(uidb64, token)
        if not user or not user.enabled:
            return Response({'error': 'Lien invalide ou expiré'}, status=status.HTTP_400_BAD_REQUEST)

        user.enabled = True
        user.is_active = True
        user.save(update_fields=['enabled', 'is_active'])

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'message': 'Connexion réussie sans mot de passe'
        }, status=status.HTTP_200_OK)


class UserMeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

class ChangePasswordView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")
        if not user.check_password(old_password):
            return Response({"error": "Ancien mot de passe incorrect"}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

class DocumentViewSet(viewsets.ModelViewSet):

    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    def get_queryset(self):

        user = self.request.user

        if not user.is_authenticated:
            return Document.objects.none()

        if user.type in [
            "ADMIN",
            "AUT_LOCALE"
        ]:
            return Document.objects.all()

        return Document.objects.filter(
            Q(auteur=user) | Q(dossier__participants__utilisateur=user)
        ).distinct()

    def perform_create(self, serializer):

        user = self.request.user
        dossier = serializer.validated_data.get('dossier')
        if dossier and user.type not in INSTITUTIONAL_TYPES:
            if not dossier.participants.filter(utilisateur=user).exists():
                raise PermissionDenied("Vous n'êtes pas participant de ce dossier.")

        document = serializer.save(auteur=user)

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Document",
            objet_id=document.id,
            crise=(
                document.dossier.crise
                if document.dossier
                else None
            ),
            commentaire="Création document"
        )

        try:

            with open(document.fichier.path, "rb") as f:

                sha256 = hashlib.sha256(
                    f.read()
                ).hexdigest()

            document.sha256 = sha256

            document.metadata_publiques, document.metadata_privees = (
                extract_exif_metadata(
                    document.fichier.path
                )
            )

            document.save()

        except Exception as e:
            print("DOCUMENT ERROR:", e)

        if document.dossier:

            DossierHistorique.objects.create(
                dossier=document.dossier,
                auteur=document.auteur,
                evenement="Document ajouté",
                commentaire=document.commentaire or ""
            )

        if document.dossier:

            participants = (
                document.dossier
                .participants
                .all()
            )

            for participant in participants:

                if (
                    participant.utilisateur_id ==
                    document.auteur_id
                ):
                    continue

                Notification.objects.create(
                    utilisateur=participant.utilisateur,
                    dossier=document.dossier,
                    titre="Nouvelle photo",
                    message=document.commentaire or ""
                )

    def check_document_access(
        self,
        request,
        document
    ):

        user = request.user

        print(
            "DOCUMENT ACCESS :",
            request.user.username,
            request.user.type
        )

        if not user.is_authenticated:
            return False

        if user.type in [
            "ADMIN",
            "AUT_LOCALE"
        ]:
            return True

        if document.auteur_id == user.id:
            return True

        dossier = document.dossier

        if not dossier:
            return False

        if dossier.equipe:

            if dossier.equipe.leader_id == user.id:
                return True

            if dossier.equipe.members.filter(
                id=user.id
            ).exists():
                return True

        if dossier.participants.filter(utilisateur=user).exists():
            return True

        return False

    @action(
        detail=True,
        methods=["get"]
    )
    def download(self, request, pk=None):

        document = Document.objects.get(
            pk=pk
        )

        if not self.check_document_access(
            request,
            document
        ):

            audit_log(
                request=request,
                action_code="TELECHARGEMENT",
                objet_type="Document",
                objet_id=document.id,
                commentaire="Accès refusé",
                succes=False
            )

            return Response(
                status=403
            )

        audit_log(
            request=request,
            action_code="TELECHARGEMENT",
            objet_type="Document",
            objet_id=document.id,
            crise=(
                document.dossier.crise
                if document.dossier
                else None
            ),
            commentaire=(
                f"Téléchargement document "
                f"{document.id}"
            )
        )

        return FileResponse(
            open(
                document.fichier.path,
                "rb"
            ),
            as_attachment=True
        )

    @action(
        detail=True,
        methods=["get"]
    )
    def preview(self, request, pk=None):

        document = Document.objects.get(pk=pk)

        if not self.check_document_access(
            request,
            document
        ):
            return Response(
                status=403
            )

        return FileResponse(
            open(document.fichier.path, "rb")
        )

class DossierCommentaireViewSet(viewsets.ModelViewSet):

    queryset = DossierCommentaire.objects.all()
    serializer_class = DossierCommentaireSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return DossierCommentaire.objects.none()
        if user.type in INSTITUTIONAL_TYPES:
            return DossierCommentaire.objects.all()
        return DossierCommentaire.objects.filter(
            dossier__participants__utilisateur=user
        ).distinct()

    def perform_create(self, serializer):

        user = self.request.user
        dossier = serializer.validated_data.get('dossier')
        if dossier and user.type not in INSTITUTIONAL_TYPES:
            if not dossier.participants.filter(utilisateur=user).exists():
                raise PermissionDenied("Vous n'êtes pas participant de ce dossier.")

        commentaire = serializer.save(auteur=user)

        DossierHistorique.objects.create(
            dossier=commentaire.dossier,
            auteur=commentaire.auteur,
            evenement="Commentaire ajouté",
            commentaire=commentaire.commentaire
        )

        participants = (
            commentaire.dossier
            .participants
            .all()
        )

        for participant in participants:

            if (
                participant.utilisateur_id ==
                commentaire.auteur_id
            ):
                continue

            Notification.objects.create(
                utilisateur=participant.utilisateur,
                dossier=commentaire.dossier,
                titre="Nouveau commentaire",
                message=commentaire.commentaire[:250]
            )

class DossierHistoriqueViewSet(viewsets.ModelViewSet):
    queryset = DossierHistorique.objects.all()
    serializer_class = DossierHistoriqueSerializer

class NotificationViewSet(viewsets.ModelViewSet):
    """Notifications de l'utilisateur connecté (ex: régulateur d'équipe averti d'une nouvelle
    affectation). Chacun ne voit et ne modifie que les siennes."""
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(utilisateur=self.request.user).order_by('-date_creation')

class RecherchePersonneViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonne.objects
        .order_by("-date_creation")
    )

    serializer_class = (
        RecherchePersonneSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return RecherchePersonne.objects.none()
        if not self.request.user.enabled:
            return RecherchePersonne.objects.none()
        return RecherchePersonne.objects.all().order_by(
            "-date_creation"
        )
    
    def perform_create(self, serializer):

        if not self.request.user.enabled:
            raise PermissionDenied(
                "Compte non validé"
            )

        recherche = serializer.save(
            createur=self.request.user
        )

        RecherchePersonneHistorique.objects.create(
            recherche=recherche,
            auteur=self.request.user,
            evenement="Recherche créée",
            commentaire="Création de la fiche de recherche."
        )

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            crise=getattr(recherche, "crise", None),
            commentaire="Création de la fiche de recherche.",
        )

    @action(detail=True, methods=["post"])
    def archiver(self, request, pk=None):

        recherche = self.get_object()
        recherche.statut = "ARCHIVEE"
        ancien_statut = recherche.statut
        recherche.save()

        RecherchePersonneHistorique.objects.create(
            recherche=recherche,
            auteur=request.user,
            evenement="Recherche archivée",
            commentaire="Recherche masquée."
        )
        audit_log(
            request=request,
            action_code="LECTURE",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            commentaire="Consultation recherche personne"
        )
        return Response({"status": "ok"})

    @action(
        detail=True,
        methods=["post"]
    )
    def retrouver(
        self,
        request,
        pk=None
    ):


        recherche = self.get_object()

        ancien_statut = recherche.statut

        recherche.statut = (
            RecherchePersonne
            .Statut
            .RETROUVEE
        )

        recherche.save()

        audit_log(
            request=request,
            action_code="MODIFICATION",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            ancien_etat={
                "statut": ancien_statut
            },
            nouvel_etat={
                "statut": recherche.statut
            },
            commentaire="Personne déclarée retrouvée"
        )

        RecherchePersonneHistorique.objects.create(
            recherche=recherche,
            auteur=request.user,
            evenement="Personne retrouvée",
            commentaire="La personne a été déclarée retrouvée"
        )

        return Response(
            {"status": "ok"}
        )

    @action(
        detail=True,
        methods=["post"]
    )
    def lecture(
        self,
        request,
        pk=None
    ):
    
        recherche = self.get_object()

        lecture, _ = (
            RecherchePersonneLecture.objects
            .get_or_create(
                recherche=recherche,
                utilisateur=request.user
            )
        )

        lecture.date_derniere_lecture = (
            timezone.now()
        )

        lecture.save()

        RecherchePersonneLectureHistorique.objects.create(
            recherche=recherche,
            utilisateur=request.user,
            action=(
                RecherchePersonneLectureHistorique
                .ActionLecture
                .LECTURE
            )
        )

        audit_log(
            request=request,
            action_code="LECTURE",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            commentaire=(
                f"Consultation recherche "
                f"{recherche.prenom} "
                f"{recherche.nom}"
            )
        )


        return Response(
            {"status": "ok"}
        )


    @action(
        detail=True,
        methods=["post"]
    )
    def acquitter(
        self,
        request,
        pk=None
    ):

        recherche = self.get_object()

        lecture, _ = (
            RecherchePersonneLecture.objects
            .get_or_create(
                recherche=recherche,
                utilisateur=request.user
            )
        )

        lecture.date_dernier_acquittement = (
            timezone.now()
        )

        lecture.save()

        RecherchePersonneLectureHistorique.objects.create(
            recherche=recherche,
            utilisateur=request.user,
            action=(
                RecherchePersonneLectureHistorique
                .ActionLecture
                .ACQUITTEMENT
            )
        )

        audit_log(
            request=request,
            action_code="ACQUITTEMENT",
            objet_type="RecherchePersonne",
            objet_id=recherche.id,
            commentaire="Recherche acquittée"
        )


        return Response(
            {"status": "ok"}
        )

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        recherche = self.get_object()
        if not recherche.photo or not user_can_view_photo(
            request.user, recherche, author_field='createur'
        ):
            return Response(status=403)
        return FileResponse(open(recherche.photo.path, "rb"))



class RecherchePersonneCommentaireViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonneCommentaire
        .objects
        .all()
    )

    serializer_class = (
        RecherchePersonneCommentaireSerializer
    )

    def perform_create(self, serializer):

        commentaire = serializer.save(
            auteur=self.request.user
        )

        recherche = commentaire.recherche

        if (
            recherche.createur
            != commentaire.auteur
        ):

            Notification.objects.create(
                utilisateur=
                    recherche.createur,

                dossier=None,

                titre=
                    "Nouveau commentaire",

                message=(
                    f"Un commentaire a été "
                    f"ajouté sur la "
                    f"recherche de "
                    f"{recherche.prenom}"
                )
            )

        RecherchePersonneHistorique.objects.create(
            recherche=commentaire.recherche,
            auteur=self.request.user,
            evenement="Commentaire ajouté",
            commentaire=commentaire.commentaire
        )

class RecherchePersonneHistoriqueViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonneHistorique
        .objects
        .all()
        .order_by('-date_creation')
    )

    serializer_class = (
        RecherchePersonneHistoriqueSerializer
    )

class RecherchePersonnePhotoViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonnePhoto
        .objects
        .all()
    )

    serializer_class = (
        RecherchePersonnePhotoSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def perform_create(
        self,
        serializer
    ):

        serializer.save(
            auteur=self.request.user
        )

    @action(
        detail=True,
        methods=["get"]
    )
    def preview(
        self,
        request,
        pk=None
    ):

        photo = self.get_object()

        if not request.user.is_authenticated:
            return Response(status=403)

        return FileResponse(
            open(photo.fichier.path, "rb")
        )

class RecherchePersonneCommentairePhotoViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RecherchePersonneCommentairePhoto
        .objects
        .all()
    )

    serializer_class = (
        RecherchePersonneCommentairePhotoSerializer
    )

    permission_classes = [
        permissions.IsAuthenticated
    ]

    @action(
        detail=True,
        methods=["get"]
    )
    def preview(
        self,
        request,
        pk=None
    ):

        photo = self.get_object()

        if not request.user.is_authenticated:
            return Response(status=403)

        return FileResponse(
            open(photo.fichier.path, "rb")
        )



class InstitutionTypeViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        InstitutionType.objects.all()
    )

    serializer_class = (
        InstitutionTypeSerializer
    )

    def perform_create(self, serializer):
        institution_type = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InstitutionType",
            objet_id=institution_type.id,
            commentaire=f"Création type d'institution : {institution_type.libelle}",
        )

class InstitutionViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        Institution.objects.all()
    )

    serializer_class = (
        InstitutionSerializer
    )

    def perform_create(self, serializer):
        institution = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="Institution",
            objet_id=institution.id,
            commentaire=f"Création institution : {institution.nom}",
        )

        if self.request.user.is_authenticated:
            contact, created = ContactInstitution.objects.get_or_create(
                institution=institution,
                utilisateur=self.request.user,
                defaults={
                    "fonction": "Créateur",
                    "contact_principal": True,
                    "actif": True,
                },
            )
            if created:
                audit_log(
                    request=self.request,
                    action_code="CREATION",
                    objet_type="ContactInstitution",
                    objet_id=contact.id,
                    commentaire=f"Rattachement automatique du créateur à l'institution {institution.nom}",
                )

class RoleOperationnelViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        RoleOperationnel.objects.all()
    )

    serializer_class = (
        RoleOperationnelSerializer
    )

    def perform_create(self, serializer):
        role = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="RoleOperationnel",
            objet_id=role.id,
            commentaire=f"Création rôle opérationnel : {role.libelle}",
        )
class InstitutionCompetenceViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        InstitutionCompetence.objects.all()
    )

    serializer_class = (
        InstitutionCompetenceSerializer
    )
class AffectationRoleOperationnelViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        AffectationRoleOperationnel.objects.all()
    )

    serializer_class = (
        AffectationRoleOperationnelSerializer
    )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def _check_own_institution(self, institution):
        is_own_institution = ContactInstitution.objects.filter(
            utilisateur=self.request.user, institution=institution, actif=True
        ).exists()
        if not is_own_institution and self.request.user.type != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Vous ne pouvez gérer les affectations que pour une institution à laquelle vous êtes rattaché."
            )

    def perform_create(self, serializer):
        institution = serializer.validated_data.get("institution")
        self._check_own_institution(institution)

        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="AFFECTATION",
            objet_type="AffectationRoleOperationnel",
            objet_id=affectation.id,
            commentaire=(
                f"Affectation de {affectation.utilisateur.email} en tant que "
                f"{affectation.role.libelle} pour {institution.nom}"
                + (f" sur le thème {affectation.competence.nom}" if affectation.competence else "")
            ),
        )

    def perform_update(self, serializer):
        institution = serializer.instance.institution
        self._check_own_institution(institution)

        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="AffectationRoleOperationnel",
            objet_id=affectation.id,
            commentaire=f"Modification affectation rôle opérationnel : {affectation}",
        )

    @action(
        detail=False,
        methods=["get"]
    )
    def par_competence(
        self,
        request
    ):

        competence_id = request.GET.get(
            "competence"
        )

        queryset = (
            AffectationRoleOperationnel.objects
            .filter(
                competence_id=competence_id,
                role__code="REGULATEUR",
                actif=True,
                disponibilites__disponible=True,
                disponibilites__date_fin__isnull=True
            )
            .distinct()
        )

        serializer = self.get_serializer(
            queryset,
            many=True
        )

        return Response(
            serializer.data
        )


    @action(
        detail=False,
        methods=["get"]
    )
    def regulateurs_disponibles(
        self,
        request
    ):

        queryset = (
            AffectationRoleOperationnel.objects
            .filter(
                role__code="REGULATEUR",
                disponibilites__disponible=True,
                disponibilites__date_fin__isnull=True
            )
            .distinct()
        )

        serializer = self.get_serializer(
            queryset,
            many=True
        )

        return Response(
            serializer.data
        )

class DelegationCompetenceViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        DelegationCompetence.objects.all()
    )

    serializer_class = (
        DelegationCompetenceSerializer
    )

    filterset_fields = ["crise"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_update(self, serializer):
        delegation = serializer.save()
        audit_log(
            request=self.request,
            action_code="DELEGATION_COMPETENCE",
            objet_type="DelegationCompetence",
            objet_id=delegation.id,
            crise=delegation.crise,
            commentaire=(
                f"Modification délégation {delegation.institution_source} -> {delegation.institution_cible}"
                f" ({delegation.competence})"
            )
        )

    def perform_create(
        self,
        serializer
    ):

        delegation = serializer.save()

        audit_log(
            request=self.request,
            action_code="DELEGATION_COMPETENCE",
            objet_type="DelegationCompetence",
            objet_id=delegation.id,
            crise=delegation.crise,
            commentaire=(
                f"{delegation.institution_source}"
                f" -> "
                f"{delegation.institution_cible}"
            )
        )

class DisponibiliteOperationnelleViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        DisponibiliteOperationnelle.objects.all()
    )

    serializer_class = (
        DisponibiliteOperationnelleSerializer
    )

    @action(
        detail=True,
        methods=["post"]
    )
    def prendre_permanence(
        self,
        request,
        pk=None
    ):

        disponibilite = self.get_object()

        disponibilite.disponible = True

        disponibilite.date_fin = None

        disponibilite.save()

        audit_log(
            request=request,
            action_code="PRISE_PERMANENCE",
            objet_type="DisponibiliteOperationnelle",
            objet_id=disponibilite.id,
            commentaire="Prise de permanence"
        )

        return Response(
            {
                "status": "ok",
                "disponible": True
            }
        )

    @action(
        detail=True,
        methods=["post"]
    )
    def quitter_permanence(
        self,
        request,
        pk=None
    ):

        disponibilite = self.get_object()

        disponibilite.disponible = False

        disponibilite.date_fin = timezone.now()

        disponibilite.save()

        audit_log(
            request=request,
            action_code="FIN_PERMANENCE",
            objet_type="DisponibiliteOperationnelle",
            objet_id=disponibilite.id,
            commentaire="Fin de permanence"
        )

        return Response(
            {
                "status": "ok",
                "disponible": False
            }
        )

    @action(
        detail=False,
        methods=["get"]
    )
    def actives(
        self,
        request
    ):

        queryset = (
            DisponibiliteOperationnelle.objects
            .filter(
                disponible=True,
                date_fin__isnull=True
            )
        )

        serializer = self.get_serializer(
            queryset,
            many=True
        )

        return Response(
            serializer.data
        )

class PointTypeViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        PointType.objects.all()
    )

    serializer_class = (
        PointTypeSerializer
    )
class PointOperationnelViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        PointOperationnel.objects.all()
    )

    serializer_class = (
        PointOperationnelSerializer
    )

    filterset_fields = ["crise"]

    def get_permissions(self):
        # Avant ce correctif, seul `create` était restreint : n'importe quel compte connecté
        # pouvait modifier ou supprimer le point opérationnel d'une institution tierce.
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_update(self, serializer):
        point = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="PointOperationnel",
            objet_id=point.id,
            crise=point.crise,
            commentaire=f"Modification point opérationnel : {point.nom}",
        )

    def perform_create(self, serializer):
        point = serializer.save(responsable=self.request.user)

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="PointOperationnel",
            objet_id=point.id,
            crise=point.crise,
            commentaire=f"Création point opérationnel : {point.nom}",
        )

        # Devenir responsable d'un point sur une crise vaut déclaration "acteur" pour
        # l'institution — pas besoin de le déclarer une seconde fois. `institution` n'est pas un
        # champ de PointOperationnel : c'est un choix fait dans le formulaire de création, lu
        # directement depuis le payload. Si l'utilisateur n'a pas le droit de déclarer pour cette
        # institution (pas contact, pas admin), on retombe sur l'ancienne heuristique (son propre
        # rattachement) plutôt que d'échouer silencieusement.
        if point.crise_id:
            institution = None
            institution_id = self.request.data.get('institution')
            if institution_id:
                candidate = Institution.objects.filter(pk=institution_id).first()
                is_own = candidate and ContactInstitution.objects.filter(
                    utilisateur=self.request.user, institution=candidate, actif=True
                ).exists()
                if candidate and (is_own or self.request.user.type == UserRole.ADMINISTRATOR):
                    institution = candidate

            if institution is None:
                contact = ContactInstitution.objects.filter(
                    utilisateur=self.request.user, actif=True
                ).select_related("institution").first()
                institution = contact.institution if contact else None

            if institution:
                implication, created = ImplicationInstitution.objects.get_or_create(
                    crise=point.crise,
                    institution=institution,
                    type_implication=TypeImplication.ACTEUR,
                    defaults={"utilisateur": self.request.user, "actif": True},
                )
                if created:
                    audit_log(
                        request=self.request,
                        action_code="CREATION",
                        objet_type="ImplicationInstitution",
                        objet_id=implication.id,
                        crise=point.crise,
                        commentaire=(
                            f"{institution.nom} déclarée acteur sur la crise "
                            f"{point.crise.name} (gestion de {point.nom})"
                        ),
                    )

    @action(detail=True, methods=["get"])
    def equipe(self, request, pk=None):
        """Membres de l'équipe responsable de ce point + leurs disponibilités déclarées sur
        ce point précis, en un seul appel (évite un aller-retour Team + Dispo séparé côté
        frontend)."""
        point = self.get_object()
        if not point.equipe:
            return Response({"membres": [], "disponibilites": []})

        membres = point.equipe.members.all()
        disponibilites = DisponibilitePointEquipe.objects.filter(point=point)

        return Response({
            "membres": [
                {
                    "id": str(m.id),
                    "nom": f"{m.first_name} {m.last_name}".strip() or m.email,
                    "email": m.email,
                }
                for m in membres
            ],
            "disponibilites": DisponibilitePointEquipeSerializer(disponibilites, many=True).data,
        })

    @action(detail=True, methods=["get"])
    def stocks(self, request, pk=None):
        """État du stock de CHAQUE item du catalogue matériel pour ce point, y compris ceux
        qu'il n'a encore jamais touchés (complétés à la volée avec niveau_stock=NUL, sans rien
        écrire en base) — c'est ce mécanisme qui fait qu'un item ajouté sur un centre apparaît
        immédiatement, à niveau nul, dans la liste de tous les autres centres."""
        point = self.get_object()
        existants = {m.item_id: m for m in point.materiels.select_related("item", "responsable")}

        resultats = []
        for item in MaterielCatalogue.objects.all().order_by("nom"):
            materiel = existants.get(item.id)
            if materiel:
                resultats.append(MaterielPointSerializer(materiel).data)
            else:
                resultats.append({
                    "id": None,
                    "point": str(point.id),
                    "item": str(item.id),
                    "item_nom": item.nom,
                    "niveau_stock": NiveauStock.NUL,
                    "niveau_stock_libelle": NiveauStock.NUL.label,
                    "nom": "",
                    "quantite": 1,
                    "unite": "unité",
                    "statut": None,
                    "statut_libelle": None,
                    "responsable": None,
                    "responsable_nom": None,
                    "commentaire": None,
                    "date_maj": None,
                })
        return Response(resultats)


class DisponibilitePointEquipeViewSet(viewsets.ModelViewSet):
    """Planning de disponibilité des membres de l'équipe responsable d'un point opérationnel."""

    queryset = DisponibilitePointEquipe.objects.select_related("point", "membre").all()
    serializer_class = DisponibilitePointEquipeSerializer
    filterset_fields = ["point", "membre"]

    def _can_manage(self, user, point, membre):
        # Le membre lui-même déclare sa propre disponibilité ; le leader de l'équipe ou le
        # responsable du point peuvent la gérer pour toute l'équipe ; un admin, toujours.
        if user.type == UserRole.ADMINISTRATOR:
            return True
        if user.id == membre.id:
            return True
        if point.equipe and point.equipe.leader_id == user.id:
            return True
        if point.responsable_id == user.id:
            return True
        return False

    def perform_create(self, serializer):
        point = serializer.validated_data.get('point')
        membre = serializer.validated_data.get('membre')
        if not self._can_manage(self.request.user, point, membre):
            raise PermissionDenied(
                "Vous ne pouvez déclarer une disponibilité que pour vous-même, ou pour l'équipe "
                "dont vous êtes le·la leader / le·la responsable du point."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not self._can_manage(self.request.user, instance.point, instance.membre):
            raise PermissionDenied(
                "Vous ne pouvez retirer qu'une disponibilité vous concernant, ou celles de "
                "l'équipe dont vous êtes le·la leader / le·la responsable du point."
            )
        instance.delete()


class MaterielCatalogueViewSet(TagLikeViewSetMixin, viewsets.ModelViewSet):
    """Vocabulaire partagé des besoins matériel — recherche/création façon hashtag, comme
    Competence/InformationType : n'importe quel centre peut ajouter un item, immédiatement
    réutilisable par tous les autres (voir PointOperationnelViewSet.stocks)."""

    queryset = MaterielCatalogue.objects.all()
    serializer_class = MaterielCatalogueSerializer
    permission_classes = [permissions.IsAuthenticated]


class MaterielPointViewSet(viewsets.ModelViewSet):
    """État du stock (niveau qualitatif + suivi quantitatif optionnel) d'un item du catalogue
    matériel sur un point opérationnel."""

    queryset = MaterielPoint.objects.select_related("point", "item", "responsable").all()
    serializer_class = MaterielPointSerializer
    filterset_fields = ["point", "statut", "item"]

    def _can_manage(self, user, point):
        # Même logique que DisponibilitePointEquipeViewSet._can_manage (pas de notion de
        # "membre" ici — n'importe quel membre de l'équipe peut mettre à jour un stock).
        if user.type == UserRole.ADMINISTRATOR:
            return True
        if point.responsable_id == user.id:
            return True
        if point.equipe:
            if point.equipe.leader_id == user.id:
                return True
            if point.equipe.members.filter(id=user.id).exists():
                return True
        return False

    def perform_create(self, serializer):
        point = serializer.validated_data.get('point')
        if not self._can_manage(self.request.user, point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier son stock."
            )
        materiel = serializer.save(responsable=self.request.user)
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="MaterielPoint",
            objet_id=materiel.id,
            crise=materiel.point.crise,
            commentaire=f"Stock « {materiel.item.nom} » ({materiel.get_niveau_stock_display()}) sur le point {materiel.point.nom}",
        )

    def perform_update(self, serializer):
        point = serializer.instance.point
        if not self._can_manage(self.request.user, point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier son stock."
            )
        materiel = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="MaterielPoint",
            objet_id=materiel.id,
            crise=materiel.point.crise,
            commentaire=f"Stock « {materiel.item.nom} » mis à jour ({materiel.get_niveau_stock_display()})",
        )

    def perform_destroy(self, instance):
        if not self._can_manage(self.request.user, instance.point):
            raise PermissionDenied(
                "Seul le responsable, un membre de l'équipe du point, ou un administrateur "
                "peut modifier son stock."
            )
        instance.delete()


class ImplicationInstitutionViewSet(
    viewsets.ModelViewSet
):
    """Rattachement d'une institution à une crise : impliquée et/ou acteur opérationnel."""

    queryset = ImplicationInstitution.objects.select_related("institution", "crise", "utilisateur").all()
    serializer_class = ImplicationInstitutionSerializer
    filterset_fields = ["crise", "institution", "type_implication"]

    def get_permissions(self):
        if self.action == "create":
            return [IsInstitutionalActor()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        institution = serializer.validated_data.get("institution")

        is_own_institution = ContactInstitution.objects.filter(
            utilisateur=self.request.user, institution=institution, actif=True
        ).exists()
        if not is_own_institution and self.request.user.type != UserRole.ADMINISTRATOR:
            raise PermissionDenied(
                "Vous ne pouvez déclarer une implication que pour une institution à laquelle vous êtes rattaché."
            )

        responsable_email = serializer.validated_data.pop("responsable_email", "")
        responsable = serializer.validated_data.get("responsable")
        responsable_id = responsable.pk if responsable else None

        resolved_responsable, invited = None, False
        if responsable_id or responsable_email:
            resolved_responsable, invited = resolve_or_invite_responsable(
                responsable_id, responsable_email, institution, self.request
            )

        implication = serializer.save(utilisateur=self.request.user, responsable=resolved_responsable)

        if invited:
            send_crisis_regulateur_invite_email(self.request, resolved_responsable, implication.crise, institution)

        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="ImplicationInstitution",
            objet_id=implication.id,
            crise=implication.crise,
            commentaire=(
                f"{implication.institution.nom} déclarée "
                f"{implication.get_type_implication_display().lower()} sur la crise {implication.crise.name}"
            ),
        )

    def perform_destroy(self, instance):
        if not self._can_manage(instance):
            raise PermissionDenied("Seul l'auteur de cette déclaration, un contact de l'institution ou un administrateur peut la retirer.")
        instance.delete()

    def perform_update(self, serializer):
        # Avant ce correctif, seul `create` était restreint : n'importe quel compte
        # authentifié pouvait modifier (thèmes, commentaire, responsable...) l'implication
        # déclarée par une institution tierce.
        if not self._can_manage(serializer.instance):
            raise PermissionDenied("Seul l'auteur de cette déclaration, un contact de l'institution ou un administrateur peut la modifier.")
        implication = serializer.save()
        audit_log(
            request=self.request,
            action_code="MODIFICATION",
            objet_type="ImplicationInstitution",
            objet_id=implication.id,
            crise=implication.crise,
            commentaire=f"Modification implication {implication.institution.nom} sur la crise {implication.crise.name}",
        )

    def _can_manage(self, instance: ImplicationInstitution) -> bool:
        user = self.request.user
        if user.type == UserRole.ADMINISTRATOR:
            return True
        if instance.utilisateur_id == user.id:
            return True
        return ContactInstitution.objects.filter(
            utilisateur=user, institution=instance.institution, actif=True
        ).exists()

class ContactInstitutionViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        ContactInstitution.objects.all()
    )

    serializer_class = (
        ContactInstitutionSerializer
    )

    def perform_create(self, serializer):
        contact = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="ContactInstitution",
            objet_id=contact.id,
            commentaire=f"Création contact institution : {contact.utilisateur} pour {contact.institution.nom}",
        )

class InstitutionDomaineViewSet(
    viewsets.ModelViewSet
):

    queryset = (
        InstitutionDomaine.objects.all()
    )

    serializer_class = (
        InstitutionDomaineSerializer
    )

    def perform_create(self, serializer):
        domaine = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="InstitutionDomaine",
            objet_id=domaine.id,
            commentaire=f"Création domaine institution : {domaine.domaine} pour {domaine.institution.nom}",
        )

