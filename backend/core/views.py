from django.shortcuts import render
from django.http import FileResponse
from rest_framework.decorators import action
from rest_framework import viewsets, status, generics, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import MyTokenObtainPairSerializer  # if you've defined it in serializers
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django_filters import rest_framework as filters
from django.utils import timezone
from .auth_validation import InstitutionEmailValidator
import secrets
import uuid
import hashlib
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

from .audit import audit_log, get_client_ip
from .institution_attachment import attach_user_to_institution


def extract_exif_metadata(filepath):

    metadata = {}

    try:

        image = Image.open(filepath)

        exif = image.getexif()

        if not exif:
            return metadata

        for tag_id, value in exif.items():

            tag = TAGS.get(tag_id, tag_id)

            metadata[tag] = str(value)

    except Exception:
        pass

    return metadata


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
    User, Crisis, Request, Offer, Information,
    RecherchePersonne, RecherchePersonneCommentaire, Besoin, Notification, DossierParticipant,
    RecherchePersonneCommentairePhoto, RecherchePersonneLecture, RecherchePersonneLectureHistorique,
    Document, DossierCommentaire, DossierHistorique, BesoinCompetence, Competence, Dossier,
    AuditLog, AuditAction,
    RecherchePersonneHistorique, RecherchePersonnePhoto,
    AffectationCompetence, RequestType, RequestTypeBesoin, OfferType, InformationType, Team
)


MAGIC_LINK_SALT = "assista-crise-magic-link"
MAGIC_LINK_SIGNER = TimestampSigner(salt=MAGIC_LINK_SALT)


def build_magic_link(request, user, action: str) -> str:
    uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = MAGIC_LINK_SIGNER.sign(uidb64)
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
    RecherchePersonnePhotoSerializer,
    DocumentSerializer,
    RecherchePersonneSerializer,
    RecherchePersonneCommentaireSerializer,
    RecherchePersonneCommentairePhotoSerializer,
    DossierCommentaireSerializer,
    DossierHistoriqueSerializer,
    UserSerializer,
    RecherchePersonneLectureSerializer,
    RecherchePersonneLectureHistoriqueSerializer,
    CrisisSerializer,
    RequestTypeBesoinSerializer,
    RequestSerializer,
    OfferSerializer,
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

class CompetenceViewSet(viewsets.ModelViewSet):
    queryset = Competence.objects.all()
    serializer_class = CompetenceSerializer

class AffectationCompetenceViewSet(viewsets.ModelViewSet):
    queryset = AffectationCompetence.objects.all()
    serializer_class = AffectationCompetenceSerializer

    def perform_create(self, serializer):
        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="AffectationCompetence",
            objet_id=affectation.id,
            commentaire=f"Création affectation compétence : {affectation}",
        )

class DossierViewSet(viewsets.ModelViewSet):
    queryset = Dossier.objects.all()
    serializer_class = DossierSerializer
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
    permission_classes = [AllowAny] 
    filterset_class = AuthorEmailFilter

    def perform_create(self, serializer):
        # Si l'utilisateur est authentifié, on l'assigne comme auteur
        if self.request.user.is_authenticated:
            serializer.save(author=self.request.user)
        else:
            # Sinon on sauvegarde sans auteur (None)
            serializer.save(author=None)

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
            competence = None

            # RequestType -> Besoin
            mapping_besoin = RequestTypeBesoin.objects.filter(
                request_type=demande.request_type
            ).first()

            if mapping_besoin:

                # Besoin -> Compétence
                mapping_competence = BesoinCompetence.objects.filter(
                    besoin=mapping_besoin.besoin
                ).first()

            if mapping_competence:

                competence = mapping_competence.competence

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

                    affectation = (
                        AffectationCompetence.objects
                        .filter(
                            crise=demande.crisis,
                            competence=competence,
                            active=True
                        )
                        .first()
                    )

                    if affectation:

                        equipe = affectation.equipe

            if competence:

                dossier = Dossier.objects.create(
                    numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                    crise=demande.crisis,
                    competence=competence,
                    equipe=equipe,
                    titre=demande.title,
                    description=f"Demande créée automatiquement : {demande.title}",
                    statut=statut
                )

                if demande.author:

                    DossierParticipant.objects.get_or_create(
                        dossier=dossier,
                        utilisateur=demande.author,
                        role=DossierParticipant.Role.DEMANDEUR
                    )

                    DossierHistorique.objects.create(
                        dossier=dossier,
                        auteur=demande.author,
                        evenement="Demandeur ajouté au dossier"
                    )

                if equipe:

                    DossierHistorique.objects.create(
                        dossier=dossier,
        	        evenement=f"Equipe affectée : {equipe.name}"
                    )

                    for membre in equipe.members.all():

                        DossierParticipant.objects.get_or_create(
                            dossier=dossier,
                            utilisateur=membre,
                            role=DossierParticipant.Role.EQUIPE
                        )

                        DossierHistorique.objects.create(
                            dossier=dossier,
                            auteur=membre,
                            evenement="Intervenant ajouté au dossier"
                        )



            else:

                dossier = Dossier.objects.create(
                    numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
                    crise=demande.crisis,
                    competence=None,
                    equipe=None,
                    titre=demande.title,
                    description=(
                        f"Demande créée automatiquement : "
                        f"{demande.title}"
                    ),
                    statut=Dossier.Statut.EN_ATTENTE_AFFECTATION
                )

                DossierHistorique.objects.create(
                    dossier=dossier,
                    evenement="Aucune compétence trouvée automatiquement",
                    commentaire=(
                        "Le dossier nécessite "
                        "une affectation manuelle."
                    )
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

# --- VIEWSETS SIMPLES POUR LES TYPES ---
class RequestTypeViewSet(viewsets.ModelViewSet):
    queryset = RequestType.objects.all()
    serializer_class = RequestTypeSerializer

class OfferTypeViewSet(viewsets.ModelViewSet):
    queryset = OfferType.objects.all()
    serializer_class = OfferTypeSerializer

class InformationTypeViewSet(viewsets.ModelViewSet):
    queryset = InformationType.objects.all()
    serializer_class = InformationTypeSerializer

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
            auteur=user
        )

    def perform_create(self, serializer):

        document = serializer.save()

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

            document.metadata_publiques = (
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

    def perform_create(self, serializer):

        commentaire = serializer.save()

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

    def perform_create(self, serializer):
        affectation = serializer.save()
        audit_log(
            request=self.request,
            action_code="CREATION",
            objet_type="AffectationRoleOperationnel",
            objet_id=affectation.id,
            commentaire=f"Création affectation rôle opérationnel : {affectation}",
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

