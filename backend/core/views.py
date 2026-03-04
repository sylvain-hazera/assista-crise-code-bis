from django.shortcuts import render
from rest_framework import viewsets, status, generics, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import MyTokenObtainPairSerializer  # if you've defined it in serializers
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django_filters import rest_framework as filters
import secrets
from .models import (
    User, Crisis, Request, Offer, Information,
    RequestType, OfferType, InformationType
)
from .serializers import (
    UserSerializer, CrisisSerializer, RequestSerializer,
    OfferSerializer, InformationSerializer,
    RequestTypeSerializer, OfferTypeSerializer, InformationTypeSerializer
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
            
            # Si le compte nécessite validation (Institution, Secours, Admin)
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
                
                # NE PAS retourner de token si le compte nécessite validation
                return Response({
                    'user': UserSerializer(user).data,
                    'message': 'Compte créé, en attente de validation par un administrateur',
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
        
        # Activer le compte
        user_to_approve.enabled = True
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
        
        # Construire l'URL de suppression (automatique selon l'environnement)
        deletion_url = self.request.build_absolute_uri(f'/api/delete-request/{deletion_token}/')
        
        try:
            print(f"Tentative d'envoi de mail à {demande.email_request}...")
            
            send_mail(
                subject=f"Confirmation : Votre demande '{demande.title}' a bien été reçue",
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

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer # Ajoute la logique de mot de passe dans le serializer
    permission_classes = [permissions.AllowAny]

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