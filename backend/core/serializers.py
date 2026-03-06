from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import (
    User, Crisis, Request, Offer, Information,
    RequestType, OfferType, InformationType, Team
)

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


class UserSerializer(serializers.ModelSerializer):
    """Serializer pour les utilisateurs"""
    password = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'type', 
                  'photo', 'phone_number', 'password', 'postal_code', 'enabled']
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'phone_number': {'required': False},
            'photo': {'required': False},
            'postal_code': {'required': False},
            'enabled': {'required': False},
        }

    def create(self, validated_data):
        # Créer username à partir de l'email si non fourni
        if 'username' not in validated_data:
            validated_data['username'] = validated_data['email']
        
        user = User.objects.create_user(**validated_data)
        return user

class CrisisSerializer(serializers.ModelSerializer):
    """Serializer pour les crises"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    author = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    
    class Meta:
        model = Crisis
        fields = '__all__'

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None
    
    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

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