from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView
from .views import (
    ChangePasswordView, PasswordResetConfirmView, MyTokenObtainPairView, MyTokenRefreshView, RegisterView, InstitutionValidationView, UserMeView,
    AccountActivationView, MagicLoginView, MaPositionView, PositionsEquipesView,
    UserViewSet, CrisisViewSet, RequestViewSet, 
    RecherchePersonneCommentairePhotoViewSet,
    OfferViewSet, DisponibiliteOffreViewSet, InformationViewSet, RecherchePersonnePhotoViewSet,
    BesoinViewSet, RecherchePersonneCommentaireViewSet, RecherchePersonneViewSet,
    BesoinCompetenceViewSet, RequestTypeBesoinViewSet, RequestTypeViewSet, OfferTypeViewSet, InformationTypeViewSet,
    DeleteRequestView, DeleteOfferView, DeleteInformationView, CompetenceViewSet,
    ConfirmerAffectationBenevoleView,
    EngagementRessourcePublicView,
    RecherchePersonneHistoriqueViewSet, AffectationCompetenceViewSet,
    DossierViewSet, MissionViewSet, DocumentViewSet, DossierCommentaireViewSet, DossierHistoriqueViewSet, NotificationViewSet, TeamViewSet,
    AuditLogViewSet,
    InstitutionTypeViewSet,
    InstitutionViewSet,
    ContactInstitutionViewSet,
    InstitutionDomaineViewSet,
    RoleOperationnelViewSet,
    InstitutionCompetenceViewSet,
    AffectationRoleOperationnelViewSet,
    DelegationCompetenceViewSet,
    DisponibiliteOperationnelleViewSet,
    PointTypeViewSet,
    PointOperationnelViewSet,
    ImplicationInstitutionViewSet,
    DisponibilitePointEquipeViewSet,
    MaterielPointViewSet,
    MaterielCatalogueViewSet,
    ContributionMaterielViewSet,
    RegistrePresenceViewSet,
    DeclarationSecuriteViewSet,
)

router = DefaultRouter()
router.register(
    r'institution-types',
    InstitutionTypeViewSet
)

router.register(
    r'institutions',
    InstitutionViewSet
)

router.register(
    r'roles-operationnels',
    RoleOperationnelViewSet
)

router.register(
    r'contacts-institutions',
    ContactInstitutionViewSet
)


router.register(
    r'institution-competences',
    InstitutionCompetenceViewSet
)

router.register(
    r'institutions-domaines',
    InstitutionDomaineViewSet
)


router.register(
    r'affectations-roles',
    AffectationRoleOperationnelViewSet
)

router.register(
    r'delegations-competences',
    DelegationCompetenceViewSet
)

router.register(
    r'disponibilites',
    DisponibiliteOperationnelleViewSet
)

router.register(
    r'point-types',
    PointTypeViewSet
)

router.register(
    r'points-operationnels',
    PointOperationnelViewSet
)

router.register(
    r'implications-crises',
    ImplicationInstitutionViewSet
)

router.register(r'users', UserViewSet)
router.register(r'crises', CrisisViewSet)
router.register(r'demandes', RequestViewSet)
router.register(r'offres', OfferViewSet)
router.register(r'disponibilites-offres', DisponibiliteOffreViewSet)
router.register(r'disponibilites-points-equipe', DisponibilitePointEquipeViewSet)
router.register(r'materiels-points', MaterielPointViewSet)
router.register(r'materiels-catalogue', MaterielCatalogueViewSet)
router.register(r'contributions-materiel', ContributionMaterielViewSet)
router.register(r'registre-presences', RegistrePresenceViewSet)
router.register(r'declarations-securite', DeclarationSecuriteViewSet)
router.register(r'informations', InformationViewSet)
router.register(r'types-demande', RequestTypeViewSet)
router.register(r'types-offre', OfferTypeViewSet)
router.register(r'types-information', InformationTypeViewSet)
router.register(r'teams', TeamViewSet)
router.register(r'competences',CompetenceViewSet)
router.register(r'affectations',AffectationCompetenceViewSet)
router.register(r'dossiers', DossierViewSet)
router.register(r'missions', MissionViewSet)
router.register(r'besoins', BesoinViewSet)
router.register(r'besoins-competences', BesoinCompetenceViewSet)
router.register(r'request-types-besoins', RequestTypeBesoinViewSet)
router.register(r'documents', DocumentViewSet)
router.register(r'dossier-commentaires', DossierCommentaireViewSet)
router.register(r'dossier-historique', DossierHistoriqueViewSet)
router.register(r'audit-logs', AuditLogViewSet)
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'recherches-personnes', RecherchePersonneViewSet)
router.register(r'recherches-personnes-commentaires', RecherchePersonneCommentaireViewSet)
router.register(r'recherches-personnes-historique', RecherchePersonneHistoriqueViewSet),
router.register(r'recherches-personnes-photos', RecherchePersonnePhotoViewSet)
router.register(r'recherches-personnes-commentaires-photos',RecherchePersonneCommentairePhotoViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    #add by Laura

    path('token/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', MyTokenRefreshView.as_view(), name='token_refresh'),
    path('token/blacklist/', TokenBlacklistView.as_view(), name='token_blacklist'),
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('validate-institution/', InstitutionValidationView.as_view(), name='validate_institution'),
    path('activate-account/<str:uidb64>/<str:token>/', AccountActivationView.as_view(), name='activate_account'),
    path('magic-login/<str:uidb64>/<str:token>/', MagicLoginView.as_view(), name='magic_login'),
    path('me/', UserMeView.as_view(), name='auth_me'),
    path('change-password/', ChangePasswordView.as_view(), name='auth_change_password'),
    path('reset-password/<str:uidb64>/<str:token>/', PasswordResetConfirmView.as_view(), name='reset_password_confirm'),
    path('ma-position/', MaPositionView.as_view(), name='ma_position'),
    path('positions-equipes/', PositionsEquipesView.as_view(), name='positions_equipes'),
    
    # URLs pour la suppression via token
    path('delete-request/<str:token>/', DeleteRequestView.as_view(), name='delete_request'),
    path('delete-offer/<str:token>/', DeleteOfferView.as_view(), name='delete_offer'),
    path('confirmer-affectation-benevole/<str:token>/<str:reponse>/', ConfirmerAffectationBenevoleView.as_view(), name='confirmer_affectation_benevole'),
    path('delete-information/<str:token>/', DeleteInformationView.as_view(), name='delete_information'),
    path('engagement-ressource/<str:token>/', EngagementRessourcePublicView.as_view(), name='engagement_ressource_public'),
]
