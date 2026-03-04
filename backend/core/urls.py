from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    ChangePasswordView, MyTokenObtainPairView, RegisterView, UserMeView, 
    UserViewSet, CrisisViewSet, RequestViewSet, 
    OfferViewSet, InformationViewSet,
    RequestTypeViewSet, OfferTypeViewSet, InformationTypeViewSet,
    DeleteRequestView, DeleteOfferView, DeleteInformationView
)

router = DefaultRouter()
router.register(r'users', UserViewSet)
router.register(r'crises', CrisisViewSet)
router.register(r'demandes', RequestViewSet)
router.register(r'offres', OfferViewSet)
router.register(r'informations', InformationViewSet)
router.register(r'types-demande', RequestTypeViewSet)
router.register(r'types-offre', OfferTypeViewSet)
router.register(r'types-information', InformationTypeViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    #add by Laura

    path('token/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('me/', UserMeView.as_view(), name='auth_me'),
    path('change-password/', ChangePasswordView.as_view(), name='auth_change_password'),
    
    # URLs pour la suppression via token
    path('delete-request/<str:token>/', DeleteRequestView.as_view(), name='delete_request'),
    path('delete-offer/<str:token>/', DeleteOfferView.as_view(), name='delete_offer'),
    path('delete-information/<str:token>/', DeleteInformationView.as_view(), name='delete_information'),
]