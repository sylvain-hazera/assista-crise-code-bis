import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from core.models import RequestType, OfferType, InformationType

User = get_user_model()

@pytest.fixture
def api_client():
    """Client API pour les tests"""
    return APIClient()

@pytest.fixture
def user_data():
    """Données utilisateur pour les tests"""
    return {
        'username': 'test@test.com',
        'email': 'test@test.com',
        'password': 'TestPass123!',
        'first_name': 'Test',
        'last_name': 'User',
        'type': 'UTIL_SIMPLE',
        'phone_number': '0123456789',
        'postal_code': '38000',
    }

@pytest.fixture
def create_user(db, user_data):
    """Fixture pour créer un utilisateur"""
    def make_user(**kwargs):
        data = user_data.copy()
        data.update(kwargs)
        password = data.pop('password')
        user = User.objects.create_user(**data)
        user.set_password(password)
        user.enabled = True
        user.save()
        return user
    return make_user

@pytest.fixture
def authenticated_client(api_client, create_user):
    """Client authentifié"""
    user = create_user()
    api_client.force_authenticate(user=user)
    return api_client, user

@pytest.fixture
def request_type(db):
    """Créer un type de demande"""
    return RequestType.objects.create(
        type='Aide urgente',
        description='Demande d\'aide urgente'
    )

@pytest.fixture
def offer_type(db):
    """Créer un type d'offre"""
    return OfferType.objects.create(
        type='Hébergement',
        description='Offre d\'hébergement'
    )

@pytest.fixture
def information_type(db):
    """Créer un type d'information"""
    return InformationType.objects.create(
        type='Info utile',
        description='Information utile'
    )
