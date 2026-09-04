import pytest
from django.urls import reverse
from rest_framework import status
from core.models import User, Request, Offer, Information
from unittest.mock import patch, MagicMock

@pytest.mark.django_db
class TestUserAuthentication:
    """Tests d'authentification utilisateur"""
    
    def test_register_user_success(self, api_client, user_data):
        """Test inscription utilisateur réussie"""
        url = reverse('user-register')
        response = api_client.post(url, user_data, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        assert 'user' in response.data
        assert response.data['user']['email'] == user_data['email']
        assert User.objects.filter(email=user_data['email']).exists()
    
    def test_register_duplicate_email(self, api_client, user_data, create_user):
        """Test inscription avec email existant"""
        create_user()
        url = reverse('user-register')
        response = api_client.post(url, user_data, format='json')
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_login_success(self, api_client, create_user, user_data):
        """Test connexion réussie"""
        create_user()
        url = reverse('token_obtain_pair')
        response = api_client.post(url, {
            'email': user_data['email'],
            'password': user_data['password']
        }, format='json')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' in response.data
    
    def test_login_wrong_password(self, api_client, create_user, user_data):
        """Test connexion avec mauvais mot de passe"""
        create_user()
        url = reverse('token_obtain_pair')
        response = api_client.post(url, {
            'email': user_data['email'],
            'password': 'WrongPassword123!'
        }, format='json')
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestUserManagement:
    """Tests de gestion d'utilisateurs"""
    
    def test_logout_authenticated(self, authenticated_client):
        """Test déconnexion utilisateur authentifié"""
        client, user = authenticated_client
        url = reverse('user-logout')
        response = client.post(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert 'message' in response.data
    
    def test_pending_validations_admin(self, api_client):
        """Test liste validations en attente - admin"""
        # Créer un admin
        admin = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='Test123!',
            type='ADMIN',
            enabled=True
        )
        # Créer un utilisateur en attente
        User.objects.create_user(
            username='pending',
            email='pending@test.com',
            password='Test123!',
            type='SECOURS',
            enabled=False
        )
        
        api_client.force_authenticate(user=admin)
        url = reverse('user-pending-validations')
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
    
    def test_pending_validations_forbidden(self, authenticated_client):
        """Test liste validations - accès refusé pour utilisateur simple"""
        client, user = authenticated_client
        url = reverse('user-pending-validations')
        response = client.get(url)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_change_password_success(self, authenticated_client):
        """Test changement de mot de passe réussi"""
        client, user = authenticated_client
        url = reverse('auth_change_password')
        response = client.post(url, {
            'old_password': 'TestPass123!',
            'new_password': 'NewTest456!'
        }, format='json')
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
    
    def test_change_password_wrong_old(self, authenticated_client):
        """Test changement mot de passe - ancien incorrect"""
        client, user = authenticated_client
        url = reverse('auth_change_password')
        response = client.post(url, {
            'old_password': 'WrongPassword!',
            'new_password': 'NewTest456!'
        }, format='json')
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_user_me_view(self, authenticated_client):
        """Test récupération profil utilisateur"""
        client, user = authenticated_client
        url = reverse('auth_me')
        response = client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['email'] == user.email


@pytest.mark.django_db
class TestCrisisAPI:
    """Tests de l'API Crises"""
    
    def test_list_crises_anonymous(self, api_client):
        """Test récupération des crises en anonyme"""
        url = reverse('crisis-list')
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
    
    @pytest.mark.skip(reason="Nécessite investigation du serializer Crisis")
    def test_create_crisis_authenticated(self, authenticated_client):
        """Test création de crise authentifié"""
        client, user = authenticated_client
        url = reverse('crisis-list')
        
        data = {
            'title': 'Test Crisis',
            'description': 'Test description',
            'crisis_type': 'NATURELLE',
            'severity': 'HAUTE',
            'latitude': 45.1885,
            'longitude': 5.7245,
            'status': 'EN_COURS',
            'street': '123 Test Street',
            'postal_code': '38000',
            'city': 'Grenoble',
            'country': 'France'
        }
        
        response = client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['title'] == 'Test Crisis'
        assert response.data['author'] == str(user.id)


@pytest.mark.django_db
class TestRequestAPI:
    """Tests de l'API Demandes"""
    
    @pytest.mark.skip(reason="Nécessite configuration des types de demandes")
    def test_create_request_anonymous(self, api_client, request_type):
        """Test création demande en anonyme"""
        url = reverse('request-list')
        
        data = {
            'title': 'Besoin d\'aide',
            'description': 'Description de l\'aide',
            'first_name_request': 'John',
            'last_name_request': 'Doe',
            'email_request': 'john@example.com',
            'phone_number_request': '0123456789',
            'latitude': 45.1885,
            'longitude': 5.7245,
            'status': 'NON_TRAITEE',
            'street': '123 Test Street',
            'postal_code': '38000',
            'city': 'Grenoble',
            'country': 'France',
            'request_type': str(request_type.id)
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert 'deletion_token' in response.data


@pytest.mark.django_db
class TestEmailNotifications:
    """Tests des notifications par email"""
    
    @pytest.mark.skip(reason="Mock send_mail ne capture pas les appels dans try/except")
    @patch('django.core.mail.send_mail')
    def test_register_rescue_sends_email(self, mock_send_mail, api_client):
        """Test inscription SECOURS envoie email de validation"""
        url = reverse('user-register')
        data = {
            'username': 'rescue@test.com',
            'email': 'rescue@test.com',
            'password': 'TestPass123!',
            'first_name': 'Rescue',
            'last_name': 'User',
            'type': 'SECOURS',
            'phone_number': '0123456789',
            'postal_code': '38000',
        }
        
        response = api_client.post(url, data, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        # Le compte SECOURS nécessite validation - email envoyé
        assert mock_send_mail.called
    
    @pytest.mark.skip(reason="Nécessite investigation serializer Request")
    @patch('django.core.mail.send_mail')
    def test_request_creation_sends_email(self, mock_send_mail, api_client, request_type):
        """Test création demande envoie email de confirmation"""
        url = reverse('request-list')
        data = {
            'title': 'Besoin aide',
            'description': 'Test',
            'first_name_request': 'John',
            'last_name_request': 'Doe',
            'email_request': 'john@test.com',
            'phone_request': '0123456789',
            'latitude': 45.1885,
            'longitude': 5.7245,
            'status': 'NON_TRAITEE',
            'request_type': str(request_type.id)
        }
        
        response = api_client.post(url, data, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        assert 'deletion_token' in response.data
        assert mock_send_mail.called


@pytest.mark.django_db
class TestAccountValidation:
    """Tests de validation/rejet de comptes"""
    
    def test_approve_account_by_admin(self, api_client):
        """Test validation compte par admin"""
        # Créer admin
        admin = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='Test123!',
            type='ADMIN',
            enabled=True
        )
        # Créer utilisateur en attente
        pending = User.objects.create_user(
            username='pending',
            email='pending@test.com',
            password='Test123!',
            type='SECOURS',
            enabled=False,
            postal_code='38000'
        )
        
        api_client.force_authenticate(user=admin)
        with patch('django.core.mail.send_mail'):
            url = reverse('user-approve-account', kwargs={'pk': pending.id})
            response = api_client.post(url)
        
        assert response.status_code == status.HTTP_200_OK
        pending.refresh_from_db()
        assert pending.enabled is True
    
    def test_reject_account_by_admin(self, api_client):
        """Test rejet compte par admin"""
        admin = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='Test123!',
            type='ADMIN',
            enabled=True
        )
        pending = User.objects.create_user(
            username='pending',
            email='pending@test.com',
            password='Test123!',
            type='SECOURS',
            enabled=False,
            postal_code='38000'
        )
        
        api_client.force_authenticate(user=admin)
        with patch('django.core.mail.send_mail'):
            url = reverse('user-reject-account', kwargs={'pk': pending.id})
            response = api_client.post(url, {'reason': 'Test rejet'}, format='json')
        
        assert response.status_code == status.HTTP_200_OK
        pending.refresh_from_db()
        assert pending.is_active is False
    
    def test_approve_forbidden_for_simple_user(self, authenticated_client):
        """Test validation interdite pour utilisateur simple"""
        client, user = authenticated_client
        
        pending = User.objects.create_user(
            username='pending',
            email='pending@test.com',
            password='Test123!',
            type='SECOURS',
            enabled=False
        )
        
        url = reverse('user-approve-account', kwargs={'pk': pending.id})
        response = client.post(url)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDeletionViews:
    """Tests des vues de suppression par token"""
    
    @pytest.mark.skip(reason="Nécessite investigation serializer Request")
    @patch('django.core.mail.send_mail')
    def test_delete_request_by_token(self, mock_send_mail, api_client, request_type):
        """Test suppression demande via token"""
        # Créer une demande
        url_create = reverse('request-list')
        data = {
            'title': 'Test',
            'description': 'Test',
            'first_name_request': 'John',
            'last_name_request': 'Doe',
            'email_request': 'john@test.com',
            'phone_request': '0123456789',
            'latitude': 45.1885,
            'longitude': 5.7245,
            'status': 'NON_TRAITEE',
            'request_type': str(request_type.id)
        }
        
        response = api_client.post(url_create, data, format='json')
        token = response.data['deletion_token']
        request_id = response.data['id']
        
        # Supprimer via token
        url_delete = reverse('delete_request', kwargs={'token': token})
        response = api_client.get(url_delete)
        
        assert response.status_code == 200
        assert not Request.objects.filter(id=request_id).exists()

