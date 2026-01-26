from rest_framework import serializers
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
    password = serializers.CharField(write_only=True)

    class Meta:
        model = Utilisateur
        fields = ['id', 'username', 'email', 'type', 'photo', 'telephone_utilisateur', 'password']

    def create(self, validated_data):
        user = Utilisateur.objects.create_user(**validated_data)
        return user

class CriseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crise
        fields = '__all__'

class DemandeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Demande
        fields = '__all__'

class OffreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Offre
        fields = '__all__'

class InformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Information
        fields = '__all__'