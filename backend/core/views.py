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
from django_filters import rest_framework as filters
from .models import (
    Utilisateur, Crise, Demande, Offre, Information,
    TypeDemande, TypeOffre, TypeInformation
)
from .serializers import (
    UtilisateurSerializer, CriseSerializer, DemandeSerializer,
    OffreSerializer, InformationSerializer,
    TypeDemandeSerializer, TypeOffreSerializer, TypeInformationSerializer
)

class AuteurEmailFilter(filters.FilterSet):
    auteur_email = filters.CharFilter(field_name='auteur__email', lookup_expr='iexact')

class UtilisateurViewSet(viewsets.ModelViewSet):
    queryset = Utilisateur.objects.all()
    serializer_class = UtilisateurSerializer
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        """Inscription d'un nouvel utilisateur"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'user': UtilisateurSerializer(user).data,
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
            user = Utilisateur.objects.get(email=email)
            if user.check_password(password):
                refresh = RefreshToken.for_user(user)
                return Response({
                    'user': UtilisateurSerializer(user).data,
                    'token': str(refresh.access_token),
                    'refresh': str(refresh),
                    'message': 'Connexion réussie'
                })
            else:
                return Response(
                    {'error': 'Identifiants invalides'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
        except Utilisateur.DoesNotExist:
            return Response(
                {'error': 'Identifiants invalides'},
                status=status.HTTP_401_UNAUTHORIZED
            )
    
    @action(detail=False, methods=['post'])
    def logout(self, request):
        """Déconnexion (côté client, le token sera supprimé)"""
        return Response({'message': 'Déconnexion réussie'}, status=status.HTTP_200_OK)

class CriseViewSet(viewsets.ModelViewSet):
    queryset = Crise.objects.all()
    serializer_class = CriseSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_class = AuteurEmailFilter

class DemandeViewSet(viewsets.ModelViewSet):
    queryset = Demande.objects.all()
    serializer_class = DemandeSerializer
    permission_classes = [AllowAny]
    filterset_class = AuteurEmailFilter

class OffreViewSet(viewsets.ModelViewSet):
    queryset = Offre.objects.all()
    serializer_class = OffreSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_class = AuteurEmailFilter

class InformationViewSet(viewsets.ModelViewSet):
    queryset = Information.objects.all()
    serializer_class = InformationSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

# --- VIEWSETS SIMPLES POUR LES TYPES ---
class TypeDemandeViewSet(viewsets.ModelViewSet):
    queryset = TypeDemande.objects.all()
    serializer_class = TypeDemandeSerializer

class TypeOffreViewSet(viewsets.ModelViewSet):
    queryset = TypeOffre.objects.all()
    serializer_class = TypeOffreSerializer

class TypeInformationViewSet(viewsets.ModelViewSet):
    queryset = TypeInformation.objects.all()
    serializer_class = TypeInformationSerializer

    #  --------------------------- add by Laura ------------------------------------

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

class RegisterView(generics.CreateAPIView):
    queryset = Utilisateur.objects.all()
    serializer_class = UtilisateurSerializer # Ajoute la logique de mot de passe dans le serializer
    permission_classes = [permissions.AllowAny]

class UserMeView(generics.RetrieveUpdateAPIView):
    serializer_class = UtilisateurSerializer
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