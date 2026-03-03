from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import (
    Utilisateur, Crise, Demande, Offre, Information,
    TypeDemande, TypeOffre, TypeInformation
)

class TypeDemandeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeDemande
        fields = '__all__'

class TypeOffreSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeOffre
        fields = '__all__'

class TypeInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeInformation
        fields = '__all__'


class UtilisateurSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = Utilisateur
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'type', 
                  'photo', 'telephone_utilisateur', 'password', 'code_postal', 'enable']
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'telephone_utilisateur': {'required': False},
            'photo': {'required': False},
            'code_postal': {'required': False},
            'enable': {'required': False},
        }

    def create(self, validated_data):
        # Créer username à partir de l'email si non fourni
        if 'username' not in validated_data:
            validated_data['username'] = validated_data['email']
        
        user = Utilisateur.objects.create_user(**validated_data)
        return user

class CriseSerializer(serializers.ModelSerializer):
    
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    
    class Meta:
        model = Crise
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None
    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

class DemandeSerializer(serializers.ModelSerializer):

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Demande
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.localisation.y if obj.localisation else None
    def get_longitude(self, obj):
        return obj.localisation.x if obj.localisation else None

class OffreSerializer(serializers.ModelSerializer):

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Offre
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.localisation.y if obj.localisation else None
    def get_longitude(self, obj):
        return obj.localisation.x if obj.localisation else None

class InformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Information
        fields = '__all__'

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    sername_field = 'email'  

    def validate(self, attrs):
        data = super().validate(attrs)
        # On ajoute l'utilisateur sérialisé à la réponse
        data['user'] = UtilisateurSerializer(self.user).data
        return data
    
