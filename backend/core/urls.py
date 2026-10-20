from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView
from .grafana_acces import GrafanaSessionView, grafana_verifier
from .views import (
    ChangePasswordView, PasswordResetRequestView, PasswordResetConfirmView, MyTokenObtainPairView, MyTokenRefreshView, RegisterView, InstitutionValidationView, UserMeView,
    AccountActivationView, MagicLoginView, MaPositionView, PositionsEquipesView,
    UserViewSet, CrisisViewSet, RequestViewSet, 
    RecherchePersonneCommentairePhotoViewSet,
    OfferViewSet, OfferPhotoViewSet, RequestPhotoViewSet, DisponibiliteOffreViewSet, InformationViewSet, RecherchePersonnePhotoViewSet,
    BesoinViewSet, RecherchePersonneCommentaireViewSet, RecherchePersonneViewSet,
    BesoinCompetenceViewSet, BesoinMaterielViewSet, RequestTypeBesoinViewSet, OfferTypeBesoinViewSet, InformationTypeBesoinViewSet, TypesALecouteView, CelluleCriseView, SimulationInondationView, SimulationInondationAdressesView, SimulationRuissellementView, SimulationInondationNiveauObserveView, SimulationInondationGeorisquesView, RequestTypeViewSet, OfferTypeViewSet, InformationTypeViewSet,
    DeleteRequestView, DeleteOfferView, DeleteInformationView, CompetenceViewSet,
    ConfirmerAffectationBenevoleView,
    EngagementRessourcePublicView,
    AccuserReceptionAlertePCSPublicView,
    OfferReponsePublicView,
    RequestEditionPublicView,
    InformationEditionPublicView,
    RecherchePersonneHistoriqueViewSet, AffectationCompetenceViewSet,
    DossierViewSet, MissionViewSet, DocumentViewSet, DossierCommentaireViewSet, DossierHistoriqueViewSet, NotificationViewSet, TeamViewSet,
    DemandeMobilisationViewSet, VerifierDemandeMobilisationView,
    AuditLogViewSet,
    JournalCollectiviteViewSet,
    InstitutionTypeViewSet,
    InstitutionViewSet,
    ContactInstitutionViewSet,
    InstitutionDomaineViewSet,
    CompagnonMeshCoreViewSet, NoeudMeshUtilisateurViewSet, MessageMeshLogViewSet, CommandeMeshCoreViewSet,
    RelaisMeshCoreViewSet, CanalMeshCoreViewSet, MessageCanalMeshCoreViewSet, ContactMeshCoreViewSet,
    TracerouteMeshCoreViewSet, AlerteMeshSOSViewSet,
    CompagnonMeshtasticViewSet, NoeudUtilisateurMeshtasticViewSet, MessageMeshtasticLogViewSet,
    CanalMeshtasticViewSet, MessageCanalMeshtasticViewSet, ContactMeshtasticViewSet,
    SatelliteViewSet,
    ConflitSynchronisationViewSet,
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
    SuiviMaterielEvenementViewSet,
    FicheMaterielView,
    DeclarationSecuriteViewSet,
    ZoneViewSet,
    ConfigurationAlerteSismiqueViewSet, SecteurRechercheViewSet,
    InterlocuteurAlertePCSViewSet, NotificationAlertePCSViewSet,
    RisqueMajeurTypeViewSet, RisqueCommunalViewSet,
    TypeVulnerabiliteViewSet, PersonneVulnerableViewSet,
    PlanViewSet,
    PlanMissionModeleViewSet,
    DashboardStatsView,
    MeshLocalDetecterView,
    ImportApercuView,
    ImportPersonnelCommunalView,
    ImportPersonnelCommunalExempleView,
    ImportInstitutionsView,
    ImportInstitutionsExempleView,
    ImportCorrespondantsPCSView,
    ImportCorrespondantsPCSExempleView,
    ImportInterlocuteursPCSView,
    ImportInterlocuteursPCSExempleView,
    ImportMaterielPointView,
    ImportMaterielPointExempleView,
    HabitationViewSet,
    HabitationCommentaireViewSet,
    HabitationHistoriqueViewSet,
    RattachementHabitationViewSet,
    ModuleDegatsCriseViewSet,
    PieceIdentiteReserveViewSet,
    BrandingView,
    ImportHabitationsView,
    ImportHabitationsExempleView,
    SalonMatrixEquipeViewSet,
    SalonMatrixInstitutionViewSet,
    PositionMatrixView,
    LogementsDisponiblesView,
    AffecterLogementView,
    FicheIntervenantView,
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

router.register(r'compagnons-meshcore', CompagnonMeshCoreViewSet)
router.register(r'noeuds-meshcore', NoeudMeshUtilisateurViewSet)
router.register(r'messages-meshcore', MessageMeshLogViewSet)
router.register(r'commandes-meshcore', CommandeMeshCoreViewSet)
router.register(r'satellites', SatelliteViewSet)
router.register(r'conflits-synchronisation', ConflitSynchronisationViewSet)
router.register(r'relais-meshcore', RelaisMeshCoreViewSet)
router.register(r'canaux-meshcore', CanalMeshCoreViewSet)
router.register(r'messages-canal-meshcore', MessageCanalMeshCoreViewSet)
router.register(r'salons-matrix', SalonMatrixEquipeViewSet)
router.register(r'salons-matrix-institution', SalonMatrixInstitutionViewSet)
router.register(r'contacts-meshcore', ContactMeshCoreViewSet)
router.register(r'traceroutes-meshcore', TracerouteMeshCoreViewSet)
router.register(r'alertes-sos-mesh', AlerteMeshSOSViewSet)

router.register(r'compagnons-meshtastic', CompagnonMeshtasticViewSet)
router.register(r'noeuds-meshtastic', NoeudUtilisateurMeshtasticViewSet)
router.register(r'messages-meshtastic', MessageMeshtasticLogViewSet)
router.register(r'canaux-meshtastic', CanalMeshtasticViewSet)
router.register(r'messages-canal-meshtastic', MessageCanalMeshtasticViewSet)
router.register(r'contacts-meshtastic', ContactMeshtasticViewSet)


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
router.register(r'photos-demandes', RequestPhotoViewSet)
router.register(r'photos-offres', OfferPhotoViewSet)
router.register(r'disponibilites-offres', DisponibiliteOffreViewSet)
router.register(r'disponibilites-points-equipe', DisponibilitePointEquipeViewSet)
router.register(r'materiels-points', MaterielPointViewSet)
router.register(r'materiels-catalogue', MaterielCatalogueViewSet)
router.register(r'contributions-materiel', ContributionMaterielViewSet)
router.register(r'registre-presences', RegistrePresenceViewSet)
router.register(r'suivi-materiel', SuiviMaterielEvenementViewSet)
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
router.register(r'besoins-materiels', BesoinMaterielViewSet)
router.register(r'request-types-besoins', RequestTypeBesoinViewSet)
router.register(r'offer-types-besoins', OfferTypeBesoinViewSet)
router.register(r'information-types-besoins', InformationTypeBesoinViewSet)
router.register(r'documents', DocumentViewSet)
router.register(r'dossier-commentaires', DossierCommentaireViewSet)
router.register(r'dossier-historique', DossierHistoriqueViewSet)
router.register(r'audit-logs', AuditLogViewSet)
router.register(r'journal-collectivite', JournalCollectiviteViewSet, basename='journal-collectivite')
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'demandes-mobilisation', DemandeMobilisationViewSet, basename='demandemobilisation')
router.register(r'recherches-personnes', RecherchePersonneViewSet)
router.register(r'recherches-personnes-commentaires', RecherchePersonneCommentaireViewSet)
router.register(r'recherches-personnes-historique', RecherchePersonneHistoriqueViewSet),
router.register(r'recherches-personnes-photos', RecherchePersonnePhotoViewSet)
router.register(r'recherches-personnes-commentaires-photos',RecherchePersonneCommentairePhotoViewSet)
router.register(r'zones', ZoneViewSet)
router.register(r'configurations-alerte-sismique', ConfigurationAlerteSismiqueViewSet)
router.register(r'interlocuteurs-alerte-pcs', InterlocuteurAlertePCSViewSet)
router.register(r'risques-majeurs-types', RisqueMajeurTypeViewSet)
router.register(r'risques-communaux', RisqueCommunalViewSet)
router.register(r'types-vulnerabilite', TypeVulnerabiliteViewSet)
router.register(r'personnes-vulnerables', PersonneVulnerableViewSet)
router.register(r'notifications-alerte-pcs', NotificationAlertePCSViewSet)
router.register(r'secteurs-recherche', SecteurRechercheViewSet)
router.register(r'plans', PlanViewSet)
router.register(r'habitations', HabitationViewSet)
router.register(r'habitations-commentaires', HabitationCommentaireViewSet)
router.register(r'habitations-historique', HabitationHistoriqueViewSet)
router.register(r'rattachements-habitations', RattachementHabitationViewSet)
router.register(r'modules-degats', ModuleDegatsCriseViewSet)
router.register(r'pieces-identite-reserve', PieceIdentiteReserveViewSet)
router.register(r'plans-missions-modeles', PlanMissionModeleViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    #add by Laura

    path('token/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', MyTokenRefreshView.as_view(), name='token_refresh'),
    path('token/blacklist/', TokenBlacklistView.as_view(), name='token_blacklist'),
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('branding/', BrandingView.as_view(), name='branding'),
    path('validate-institution/', InstitutionValidationView.as_view(), name='validate_institution'),
    path('activate-account/<str:uidb64>/<str:token>/', AccountActivationView.as_view(), name='activate_account'),
    path('magic-login/<str:uidb64>/<str:token>/', MagicLoginView.as_view(), name='magic_login'),
    path('me/', UserMeView.as_view(), name='auth_me'),
    path('verifier-mobilisation/<str:jeton>/', VerifierDemandeMobilisationView.as_view(), name='verifier_demande_mobilisation'),
    path('change-password/', ChangePasswordView.as_view(), name='auth_change_password'),
    path('reset-password/request/', PasswordResetRequestView.as_view(), name='reset_password_request'),
    path('reset-password/<str:uidb64>/<str:token>/', PasswordResetConfirmView.as_view(), name='reset_password_confirm'),
    path('stats/dashboard/', DashboardStatsView.as_view(), name='dashboard_stats'),
    path('monitoring/grafana-session/', GrafanaSessionView.as_view(), name='grafana_session'),
    path('monitoring/grafana-verifier/', grafana_verifier, name='grafana_verifier'),
    path('mesh-local/detecter/', MeshLocalDetecterView.as_view(), name='mesh_local_detecter'),
    path('imports/apercu/', ImportApercuView.as_view(), name='import_apercu'),
    path('imports/personnel-communal/', ImportPersonnelCommunalView.as_view(), name='import_personnel_communal'),
    path('imports/personnel-communal/exemple/', ImportPersonnelCommunalExempleView.as_view(), name='import_personnel_communal_exemple'),
    path('imports/institutions/', ImportInstitutionsView.as_view(), name='import_institutions'),
    path('imports/institutions/exemple/', ImportInstitutionsExempleView.as_view(), name='import_institutions_exemple'),
    path('imports/correspondants-pcs/', ImportCorrespondantsPCSView.as_view(), name='import_correspondants_pcs'),
    path('imports/correspondants-pcs/exemple/', ImportCorrespondantsPCSExempleView.as_view(), name='import_correspondants_pcs_exemple'),
    path('imports/interlocuteurs-pcs/', ImportInterlocuteursPCSView.as_view(), name='import_interlocuteurs_pcs'),
    path('imports/interlocuteurs-pcs/exemple/', ImportInterlocuteursPCSExempleView.as_view(), name='import_interlocuteurs_pcs_exemple'),
    path('imports/materiel-point/', ImportMaterielPointView.as_view(), name='import_materiel_point'),
    path('imports/materiel-point/exemple/', ImportMaterielPointExempleView.as_view(), name='import_materiel_point_exemple'),
    path('types-a-lecoute/', TypesALecouteView.as_view(), name='types_a_lecoute'),
    path('crises/<str:crise_id>/cellule/', CelluleCriseView.as_view(), name='cellule_crise'),
    path('simulation-inondation/<str:commune_code>/', SimulationInondationView.as_view(), name='simulation_inondation'),
    path('simulation-inondation/<str:commune_code>/adresses/', SimulationInondationAdressesView.as_view(), name='simulation_inondation_adresses'),
    path('simulation-inondation/<str:commune_code>/ruissellement/', SimulationRuissellementView.as_view(), name='simulation_ruissellement'),
    path('simulation-inondation/<str:commune_code>/niveau-observe/', SimulationInondationNiveauObserveView.as_view(), name='simulation_inondation_niveau_observe'),
    path('simulation-inondation/<str:commune_code>/georisques/', SimulationInondationGeorisquesView.as_view(), name='simulation_inondation_georisques'),
    path('imports/habitations/', ImportHabitationsView.as_view(), name='import_habitations'),
    path('imports/habitations/exemple/', ImportHabitationsExempleView.as_view(), name='import_habitations_exemple'),
    path('ma-position/', MaPositionView.as_view(), name='ma_position'),
    path('positions-equipes/', PositionsEquipesView.as_view(), name='positions_equipes'),
    path('matrix/positions/', PositionMatrixView.as_view(), name='matrix_positions'),
    path('logements-disponibles/', LogementsDisponiblesView.as_view(), name='logements_disponibles'),
    path('affecter-logement/', AffecterLogementView.as_view(), name='affecter_logement'),
    path('fiche-intervenant/', FicheIntervenantView.as_view(), name='fiche_intervenant'),
    path('fiche-materiel/', FicheMaterielView.as_view(), name='fiche_materiel'),
    
    # URLs pour la suppression via token
    path('delete-request/<str:token>/', DeleteRequestView.as_view(), name='delete_request'),
    path('delete-offer/<str:token>/', DeleteOfferView.as_view(), name='delete_offer'),
    path('confirmer-affectation-benevole/<str:token>/<str:reponse>/', ConfirmerAffectationBenevoleView.as_view(), name='confirmer_affectation_benevole'),
    path('delete-information/<str:token>/', DeleteInformationView.as_view(), name='delete_information'),
    path('engagement-ressource/<str:token>/', EngagementRessourcePublicView.as_view(), name='engagement_ressource_public'),
    path('accuser-reception-pcs/<str:token>/', AccuserReceptionAlertePCSPublicView.as_view(), name='accuser_reception_alerte_pcs'),
    path('repondre-offre/<str:token>/', OfferReponsePublicView.as_view(), name='offer_reponse_public'),
    path('edit-request/<str:token>/', RequestEditionPublicView.as_view(), name='request_edition_public'),
    path('edit-information/<str:token>/', InformationEditionPublicView.as_view(), name='information_edition_public'),
]
