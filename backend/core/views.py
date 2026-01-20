from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from .models import (
    Utilisateur, Crise, Demande, Offre, Information, Materiel,
    TypeDemande, TypeOffre, TypeInformation
)
from .serializers import (
    UtilisateurSerializer, CriseSerializer, DemandeSerializer,
    OffreSerializer, InformationSerializer, MaterielSerializer,
    TypeDemandeSerializer, TypeOffreSerializer, TypeInformationSerializer
)

class UtilisateurViewSet(viewsets.ModelViewSet):
    queryset = Utilisateur.objects.all()
    serializer_class = UtilisateurSerializer

class CriseViewSet(viewsets.ModelViewSet):
    queryset = Crise.objects.all()
    serializer_class = CriseSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

class DemandeViewSet(viewsets.ModelViewSet):
    queryset = Demande.objects.all()
    serializer_class = DemandeSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

class OffreViewSet(viewsets.ModelViewSet):
    queryset = Offre.objects.all()
    serializer_class = OffreSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

class InformationViewSet(viewsets.ModelViewSet):
    queryset = Information.objects.all()
    serializer_class = InformationSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

class MaterielViewSet(viewsets.ModelViewSet):
    queryset = Materiel.objects.all()
    serializer_class = MaterielSerializer

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