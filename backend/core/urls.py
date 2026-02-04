from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    UtilisateurViewSet, CriseViewSet, DemandeViewSet, 
    OffreViewSet, InformationViewSet,
    TypeDemandeViewSet, TypeOffreViewSet, TypeInformationViewSet
)

router = DefaultRouter()
router.register(r'users', UtilisateurViewSet)
router.register(r'crises', CriseViewSet)
router.register(r'demandes', DemandeViewSet)
router.register(r'offres', OffreViewSet)
router.register(r'informations', InformationViewSet)
router.register(r'types-demande', TypeDemandeViewSet)
router.register(r'types-offre', TypeOffreViewSet)
router.register(r'types-information', TypeInformationViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]