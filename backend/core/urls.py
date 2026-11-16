from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView
from .grafana import GrafanaTokenView
from .views_connexion import (
    ConnexionCodeView, ConnexionDebutView, ConnexionEnvoyerCodeView,
    SecondFacteurCodesSecoursView, SecondFacteurConfirmerView, SecondFacteurEnvoyerCodeView,
    SecondFacteurEtatView, SecondFacteurPreparerView, SecondFacteurRetirerView,
)
from .views_application import (
    AccuserNotificationsView, MesMobilisationsView, MesNotificationsView, MonAppareilView,
    RepondreIndisponibleView,
)
from .views_adresses import GeocodageInverseView, RechercheAdresseView, ZoneAtteignableView
from .views_veille import (
    AntennesIndisponiblesView, ArretesCirculationView, CirculationView, ConfigurationAlerteFeuViewSet, HauteursEauView, NiveauxMerView, ConfigurationAlerteVigilanceViewSet,
    FoyersActifsView, EvenementsRoutiersView, ImagePluieView, ImagePrecipitationHiverView, ImageRafalesView, PrecipitationsHiverView, QualiteAirView, RafalesPrevuesView,
    DefibrillateursView, MeteoForetsView, ObservationsMeteoView, PluiePrevueView,
    RadioactiviteView, RestrictionsEauView, SeismesView, VolcansView,
    RisqueAvalancheView, SanteUrgencesView,
    StationsCarburantView, VentPrevuView, VigilanceCruesView, ZonesBruleesView,
    VigilanceMeteoView, VignetteVigilanceMeteoView,
)
from .views import (
    BrouillonEnvoiViewSet,
    DefinirMonMotDePasseView,
    CampagneDisponibiliteViewSet,
    CreneauEquipeViewSet,
    DossierRelogementViewSet,
    MaFicheBenevoleView,
    MesDisponibilitesView,
    DemandeAccesRadioViewSet,
    ModeleMessageViewSet,
    NoeudPublicMeshCoreViewSet,
    RattachementNoeudRadioViewSet,
    SourceObservateurMeshCoreViewSet,
    TacheAdminMeshCoreViewSet,
    CandidatureAssociationViewSet,
    InvitationAssociationViewSet,
    QualificationMembreViewSet,
    QualificationViewSet,
    ChangePasswordView, PasswordResetRequestView, PasswordResetConfirmView, MyTokenObtainPairView, MyTokenRefreshView, RegisterView, DefiInscriptionView, InstitutionValidationView, UserMeView,
    AccountActivationView, MagicLoginView, MaPositionView, PositionsEquipesView,
    UserViewSet, CrisisViewSet, RequestViewSet, 
    RecherchePersonneCommentairePhotoViewSet,
    OfferViewSet, OfferPhotoViewSet, RequestPhotoViewSet, DisponibiliteOffreViewSet, InformationViewSet, RecherchePersonnePhotoViewSet,
    BesoinViewSet, RecherchePersonneCommentaireViewSet, RecherchePersonneViewSet,
    BesoinCompetenceViewSet, BesoinMaterielViewSet, RequestTypeBesoinViewSet, OfferTypeBesoinViewSet, InformationTypeBesoinViewSet, TypesALecouteView, CelluleCriseView, SimulationInondationView, SimulationInondationAdressesView, SimulationRuissellementView, SimulationInondationNiveauObserveView, SimulationInondationGeorisquesView, SimulationInondationPerimetreView, RequestTypeViewSet, OfferTypeViewSet, InformationTypeViewSet,
    DeleteRequestView, DeleteOfferView, DeleteInformationView, CompetenceViewSet,
    ConfirmerAffectationBenevoleView,
    EngagementRessourcePublicView,
    AccuserReceptionAlertePCSPublicView,
    OfferReponsePublicView,
    RequestEditionPublicView,
    InformationEditionPublicView,
    RecherchePersonneHistoriqueViewSet, AffectationCompetenceViewSet,
    DossierViewSet, MissionViewSet, DocumentViewSet, DossierCommentaireViewSet, DossierHistoriqueViewSet, NotificationViewSet, TeamViewSet,
    DemandeMobilisationViewSet, VerifierDemandeMobilisationJsonView,
    VerifierDemandeMobilisationView,
    AuditLogViewSet,
    JournalCollectiviteViewSet,
    InstitutionTypeViewSet,
    InstitutionViewSet,
    ContactInstitutionViewSet,
    InstitutionDomaineViewSet,
    CompagnonMeshCoreViewSet, NoeudMeshUtilisateurViewSet, MessageMeshLogViewSet, CommandeMeshCoreViewSet,
    RelaisMeshCoreViewSet, CanalMeshCoreViewSet, CompteMqttViewSet, LiaisonMeshtasticViewSet, MessageCanalMeshCoreViewSet, ContactMeshCoreViewSet,
    TracerouteMeshCoreViewSet, AlerteMeshSOSViewSet,
    CompagnonMeshtasticViewSet, NoeudUtilisateurMeshtasticViewSet, MessageMeshtasticLogViewSet,
    CanalMeshtasticViewSet, MessageCanalMeshtasticViewSet, ContactMeshtasticViewSet,
    TacheAdminMeshtasticViewSet, ConfigurationNoeudMeshtasticViewSet,
    CouvertureRadioSiteViewSet, CalibrationRadioViewSet,
    SatelliteViewSet, VersionSatelliteViewSet,
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
    SiteSensibleViewSet,
    TypeVulnerabiliteViewSet, PersonneVulnerableViewSet,
    HabilitationRegistreVulnerablesViewSet,
    PlanViewSet,
    PlanMissionModeleViewSet,
    DashboardStatsView,
    MeshLocalDetecterView, FederationCarteLiveView,
    ImportApercuView,
    ImportPersonnelCommunalView,
    SaisiePersonnelCommunalView,
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
    ConservationPiecesView,
    RelaisSerieView, RelaisPlanCanauxView, RelaisAnnonceView,
    InstitutionActiveView, PerimetreAdminView,
    PieceIdentiteReserveViewSet,
    BrandingView, BrandingLogoView,
    SondeView,
    ImportHabitationsView,
    ImportHabitationsExempleView,
    SalonMatrixEquipeViewSet,
    SalonMatrixInstitutionViewSet,
    SalonMatrixMissionViewSet,
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
# Versions signées que les satellites acceptent d'installer (core/signature_satellites.py).
router.register(r'versions-satellite', VersionSatelliteViewSet)
router.register(r'conflits-synchronisation', ConflitSynchronisationViewSet)
router.register(r'relais-meshcore', RelaisMeshCoreViewSet)
router.register(r'canaux-meshcore', CanalMeshCoreViewSet)
# Comptes du broker MQTT (administrateurs seulement, voir CompteMqttViewSet).
router.register(r'comptes-mqtt', CompteMqttViewSet)
# Liaisons radio mesurees (lecture seule) : voir core/analyse_liaisons.py.
router.register(r'liaisons-meshtastic', LiaisonMeshtasticViewSet)
router.register(r'messages-canal-meshcore', MessageCanalMeshCoreViewSet)
router.register(r'salons-matrix', SalonMatrixEquipeViewSet)
router.register(r'salons-matrix-institution', SalonMatrixInstitutionViewSet)
router.register(r'salons-matrix-mission', SalonMatrixMissionViewSet)
router.register(r'contacts-meshcore', ContactMeshCoreViewSet)
router.register(r'traceroutes-meshcore', TracerouteMeshCoreViewSet)
router.register(r'alertes-sos-mesh', AlerteMeshSOSViewSet)

router.register(r'compagnons-meshtastic', CompagnonMeshtasticViewSet)
router.register(r'noeuds-meshtastic', NoeudUtilisateurMeshtasticViewSet)
router.register(r'messages-meshtastic', MessageMeshtasticLogViewSet)
router.register(r'canaux-meshtastic', CanalMeshtasticViewSet)
router.register(r'messages-canal-meshtastic', MessageCanalMeshtasticViewSet)
router.register(r'contacts-meshtastic', ContactMeshtasticViewSet)
router.register(r'taches-admin-meshtastic', TacheAdminMeshtasticViewSet)
router.register(r'configurations-noeuds-meshtastic', ConfigurationNoeudMeshtasticViewSet)
router.register(r'couvertures-radio', CouvertureRadioSiteViewSet)
router.register(r'calibrations-radio', CalibrationRadioViewSet)
# Droit d'acces au domaine radio : demande, instruction, et « ou j'en suis »
# (core/acces_radio.py).
router.register(r'demandes-acces-radio', DemandeAccesRadioViewSet)
# « Ce noeud est a nous » : rattachement d'un repeteur a une institution ou a un compte.
router.register(r'rattachements-noeuds-radio', RattachementNoeudRadioViewSet)
# File d'administration a distance des repeteurs MeshCore (voir TacheAdminMeshCore).
router.register(r'taches-admin-meshcore', TacheAdminMeshCoreViewSet)
# Brokers ou des observateurs MeshCore republient ce qu'ils entendent.
router.register(r'sources-observateurs-meshcore', SourceObservateurMeshCoreViewSet)
# Cartographie du reseau MeshCore public, importee d'une instance CoreScope.
router.register(r'noeuds-publics-meshcore', NoeudPublicMeshCoreViewSet)
# Relecture avant envoi, et textes reecrits par une institution.
router.register(r'brouillons-envoi', BrouillonEnvoiViewSet)
router.register(r'modeles-messages', ModeleMessageViewSet)


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
router.register(r'configurations-alerte-vigilance', ConfigurationAlerteVigilanceViewSet)
router.register(r'configurations-alerte-feu', ConfigurationAlerteFeuViewSet)
router.register(r'interlocuteurs-alerte-pcs', InterlocuteurAlertePCSViewSet)
router.register(r'risques-majeurs-types', RisqueMajeurTypeViewSet)
router.register(r'risques-communaux', RisqueCommunalViewSet)
router.register(r'sites-sensibles', SiteSensibleViewSet)
router.register(r'types-vulnerabilite', TypeVulnerabiliteViewSet)
router.register(r'personnes-vulnerables', PersonneVulnerableViewSet)
router.register(r'habilitations-registre-vulnerables', HabilitationRegistreVulnerablesViewSet)
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
# Associations agréées de sécurité civile : catalogue des titres, titres détenus, liens
# d'invitation et circuit de recrutement (voir core/recrutement_association.py).
router.register(r'qualifications', QualificationViewSet)
router.register(r'qualifications-membres', QualificationMembreViewSet)
router.register(r'invitations-association', InvitationAssociationViewSet)
# Campagnes de disponibilite : solliciter en masse ses benevoles sur une periode (voir
# CampagneDisponibiliteViewSet).
router.register(r'campagnes-disponibilite', CampagneDisponibiliteViewSet)
# Suivi du relogement des familles sinistrées (voir core/relogement.py).
router.register(r'dossiers-relogement', DossierRelogementViewSet)
# Planning d'équipe : qui tient quel créneau (voir core/planning_equipe.py).
router.register(r'creneaux-equipe', CreneauEquipeViewSet)
router.register(r'candidatures-association', CandidatureAssociationViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    #add by Laura

    path('token/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    # Connexion en étapes et second facteur (15/11/2026) — voir core/views_connexion.py.
    path('connexion/debut/', ConnexionDebutView.as_view(), name='connexion_debut'),
    path('connexion/code/', ConnexionCodeView.as_view(), name='connexion_code'),
    path('connexion/envoyer-code/', ConnexionEnvoyerCodeView.as_view(), name='connexion_envoyer_code'),
    path('second-facteur/', SecondFacteurEtatView.as_view(), name='second_facteur'),
    path('second-facteur/preparer/', SecondFacteurPreparerView.as_view(), name='second_facteur_preparer'),
    path('second-facteur/confirmer/', SecondFacteurConfirmerView.as_view(), name='second_facteur_confirmer'),
    path('second-facteur/envoyer-code/', SecondFacteurEnvoyerCodeView.as_view(), name='second_facteur_envoyer_code'),
    path('second-facteur/retirer/', SecondFacteurRetirerView.as_view(), name='second_facteur_retirer'),
    path('second-facteur/codes-secours/', SecondFacteurCodesSecoursView.as_view(), name='second_facteur_codes_secours'),
    path('token/refresh/', MyTokenRefreshView.as_view(), name='token_refresh'),
    path('token/blacklist/', TokenBlacklistView.as_view(), name='token_blacklist'),
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('inscription/defi/', DefiInscriptionView.as_view(), name='inscription_defi'),
    # Fiche du benevole connecte : la relire, la completer, et choisir un mot de passe
    # (voir MaFicheBenevoleView). Hors du routeur : elle n'a pas d'identifiant, c'est
    # toujours celle de l'appelant.
    path('ma-fiche-benevole/', MaFicheBenevoleView.as_view(), name='ma_fiche_benevole'),
    path('definir-mon-mot-de-passe/', DefinirMonMotDePasseView.as_view(),
         name='definir_mon_mot_de_passe'),
    # Guichet de declaration de SES disponibilites. Ecrit dans DisponibiliteOperationnelle,
    # le seul moteur du projet : ce n'est pas une seconde source, c'est un acces simplifie
    # (voir MesDisponibilitesView).
    path('mes-disponibilites/', MesDisponibilitesView.as_view(), name='mes_disponibilites'),
    # « Je ne suis pas disponible » : la reponse negative a une campagne, dite en un geste.
    path('mes-disponibilites/indisponible/', RepondreIndisponibleView.as_view(),
         name='repondre_indisponible'),
    # Application mobile : le telephone se presente, lit ses notifications, dit ce qu'il en a
    # fait (voir core/views_application.py).
    # Les demandes de mobilisation adressees a l'appelant : il en presente le QR code.
    path('mes-mobilisations/', MesMobilisationsView.as_view(), name='mes_mobilisations'),
    # Recherche d'adresse relayee par le serveur : le navigateur n'appelle plus la Base adresse
    # (voir core/views_adresses.py).
    path('adresses/recherche/', RechercheAdresseView.as_view(), name='adresses_recherche'),
    path('adresses/inverse/', GeocodageInverseView.as_view(), name='adresses_inverse'),
    path('zone-atteignable/', ZoneAtteignableView.as_view(), name='zone_atteignable'),
    # Vigilance Meteo-France : lecture de la copie en base (voir core/meteo_france.py).
    path('vigilance-meteo/', VigilanceMeteoView.as_view(), name='vigilance_meteo'),
    path('vigilance-meteo/vignette/<str:echeance>/', VignetteVigilanceMeteoView.as_view(),
         name='vigilance_meteo_vignette'),
    # Evenements routiers (Bison Fute) et stations de carburant : copies en base elles aussi.
    path('evenements-routiers/', EvenementsRoutiersView.as_view(), name='evenements_routiers'),
    path('stations-carburant/', StationsCarburantView.as_view(), name='stations_carburant'),
    path('observations-meteo/', ObservationsMeteoView.as_view(), name='observations_meteo'),
    path('pluie-prevue/', PluiePrevueView.as_view(), name='pluie_prevue'),
    path('pluie-prevue/image/', ImagePluieView.as_view(), name='pluie_prevue_image'),
    path('rafales-prevues/', RafalesPrevuesView.as_view(), name='rafales_prevues'),
    path('rafales-prevues/image/', ImageRafalesView.as_view(), name='rafales_prevues_image'),
    path('precipitations-hiver/', PrecipitationsHiverView.as_view(), name='precipitations_hiver'),
    path('precipitations-hiver/image/', ImagePrecipitationHiverView.as_view(), name='precipitations_hiver_image'),
    path('vent-prevu/', VentPrevuView.as_view(), name='vent_prevu'),
    path('vigilance-crues/', VigilanceCruesView.as_view(), name='vigilance_crues'),
    path('restrictions-eau/', RestrictionsEauView.as_view(), name='restrictions_eau'),
    path('zones-brulees/', ZonesBruleesView.as_view(), name='zones_brulees'),
    path('foyers-actifs/', FoyersActifsView.as_view(), name='foyers_actifs'),
    path('meteo-forets/', MeteoForetsView.as_view(), name='meteo_forets'),
    path('risque-avalanche/', RisqueAvalancheView.as_view(), name='risque_avalanche'),
    path('antennes-indisponibles/', AntennesIndisponiblesView.as_view(), name='antennes_indisponibles'),
    path('arretes-circulation/', ArretesCirculationView.as_view(), name='arretes_circulation'),
    path('circulation/', CirculationView.as_view(), name='circulation'),
    path('hauteurs-eau/', HauteursEauView.as_view(), name='hauteurs_eau'),
    path('niveaux-mer/', NiveauxMerView.as_view(), name='niveaux_mer'),
    path('qualite-air/', QualiteAirView.as_view(), name='qualite_air'),
    path('sante-urgences/', SanteUrgencesView.as_view(), name='sante_urgences'),
    path('radioactivite/', RadioactiviteView.as_view(), name='radioactivite'),
    path('seismes/', SeismesView.as_view(), name='seismes'),
    path('volcans/', VolcansView.as_view(), name='volcans'),
    path('defibrillateurs/', DefibrillateursView.as_view(), name='defibrillateurs'),
    path('mon-appareil/', MonAppareilView.as_view(), name='mon_appareil'),
    path('mes-notifications/', MesNotificationsView.as_view(), name='mes_notifications'),
    path('mes-notifications/accuser/', AccuserNotificationsView.as_view(),
         name='accuser_notifications'),
    # Politique de conservation des pièces justificatives : régime, durée, base légale et
    # « pourquoi ». Affichée sur la page de dépôt comme sur la page de validation.
    path('conservation-pieces/', ConservationPiecesView.as_view(), name='conservation_pieces'),
    # Relais série depuis un navigateur : poste verrouillé où l'on ne peut rien installer, mais
    # dont l'USB fonctionne (voir core/relais_navigateur.py). Hors du routeur : la session est
    # toujours celle de l'appelant.
    path('relais-serie/', RelaisSerieView.as_view(), name='relais_serie'),
    # Règle du 14/11/2026 (core/canaux_locaux.py) : plan de canaux proposé au branchement d'une
    # radio Meshtastic, et annonce des canaux de crise et de commune sur Fr_EMCOM en local.
    path('relais-serie/plan-canaux/', RelaisPlanCanauxView.as_view(), name='relais_plan_canaux'),
    path('relais-serie/annoncer/', RelaisAnnonceView.as_view(), name='relais_annoncer'),
    path('branding/', BrandingView.as_view(), name='branding'),
    path('branding/logo/', BrandingLogoView.as_view(), name='branding_logo'),
    path('sonde/', SondeView.as_view(), name='sonde'),
    path('validate-institution/', InstitutionValidationView.as_view(), name='validate_institution'),
    path('activate-account/<str:uidb64>/<str:token>/', AccountActivationView.as_view(), name='activate_account'),
    path('magic-login/<str:uidb64>/<str:token>/', MagicLoginView.as_view(), name='magic_login'),
    path('me/', UserMeView.as_view(), name='auth_me'),
    # Contexte de travail d'un compte multi-appartenance (mairie ET association) : voir
    # core/institution_courante.py. Hors du routeur — c'est toujours celui de l'appelant.
    path('me/institution-active/', InstitutionActiveView.as_view(), name='institution_active'),
    path('me/perimetre/', PerimetreAdminView.as_view(), name='perimetre_admin'),
    path('verifier-mobilisation/<str:jeton>/', VerifierDemandeMobilisationView.as_view(), name='verifier_demande_mobilisation'),
    # Le meme verdict en JSON, pour le scanner integre a l'application (voir
    # VerifierDemandeMobilisationJsonView). Sous le meme prefixe, parce que c'est le meme fait
    # public : le jeton EST l'autorisation.
    path('verifier-mobilisation/<str:jeton>/donnees/',
         VerifierDemandeMobilisationJsonView.as_view(),
         name='verifier_demande_mobilisation_json'),
    path('change-password/', ChangePasswordView.as_view(), name='auth_change_password'),
    path('reset-password/request/', PasswordResetRequestView.as_view(), name='reset_password_request'),
    path('reset-password/<str:uidb64>/<str:token>/', PasswordResetConfirmView.as_view(), name='reset_password_confirm'),
    path('stats/dashboard/', DashboardStatsView.as_view(), name='dashboard_stats'),
    path('monitoring/grafana-token/', GrafanaTokenView.as_view(), name='grafana_token'),
    path('mesh-local/detecter/', MeshLocalDetecterView.as_view(), name='mesh_local_detecter'),
    # Fédération carte-live-meshtastic : relais d'infrastructure publiés pour les cartes des
    # départements voisins. AllowAny par nature du format, désactivée par défaut.
    path('federation/', FederationCarteLiveView.as_view(), name='federation_carte_live'),
    path('imports/apercu/', ImportApercuView.as_view(), name='import_apercu'),
    path('imports/personnel-communal/', ImportPersonnelCommunalView.as_view(), name='import_personnel_communal'),
    path('imports/personnel-communal/exemple/', ImportPersonnelCommunalExempleView.as_view(), name='import_personnel_communal_exemple'),
    path('imports/personnel-communal/saisie/', SaisiePersonnelCommunalView.as_view(), name='saisie_personnel_communal'),
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
    # Avant la route à paramètre : « perimetre » serait sinon capté comme un code commune.
    path('simulation-inondation/perimetre/', SimulationInondationPerimetreView.as_view(), name='simulation_inondation_perimetre'),
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
