/** Configuration du menu de l'administration : données pures, aucune logique.
 * Ajouter une page = ajouter une entrée ici (voir DOCUMENTATION.md, § 6.4). */

/** `permanent` : toujours visible en haut. Les autres valeurs sont les cadres repliables, groupés
 * par moment d'usage dans le cycle d'une crise. */
export type GroupeNavId = 'permanent' | 'mon-activite' | 'crise' | 'post-critique' | 'preparation' | 'association' | 'communications' | 'administration';

/** Qui voit l'entrée (les gardes de route protègent aussi l'URL) :
 * - `institutionnel` (défaut) : rôle effectif institutionnel ;
 * - `tous` : toujours visible ;
 * - `sysadmin` : les quatre rôles institutionnels en PROD (AuthService.isSysAdmin) ;
 * - `admin-plateforme` : l'administrateur de la plateforme seul (type réel ADMIN) ;
 * - `validation-comptes` : rôle effectif admin ou autorité locale ;
 * - `autorite-locale` : collectivités territoriales (isAutoriteLocaleCommunale) ;
 * - `registre-vulnerables` : champ serveur `acces_registre_vulnerables` ;
 * - `membres-association` : champ serveur `acces_membres_association` ;
 * - `campagnes` : champ serveur `acces_campagnes` (qui peut mener une campagne) ;
 * - `radio` : champ serveur `acces_radio` (nœud personnel, passerelle de l'institution, ou
 *   droit accordé — voir backend/core/acces_radio.py). L'entrée « Accueil radio » reste en
 *   `tous` : c'est elle qui explique ce qu'il faut et permet de le demander. */
export type VisibiliteNav =
  'institutionnel' | 'tous' | 'sysadmin' | 'admin-plateforme' | 'validation-comptes' | 'autorite-locale'
  | 'registre-vulnerables' | 'membres-association' | 'campagnes' | 'radio';

/** Second niveau de replis, à l'intérieur d'un cadre. N'existe que là où un même cadre
 * contient deux familles d'écrans qui ne se mélangent jamais : MeshCore et Meshtastic sont
 * deux protocoles radio distincts, avec leurs propres companions et leurs propres canaux, et
 * les sept entrées à plat se lisaient comme une liste de doublons. */
export type SousGroupeNavId =
  | 'crise-comprendre' | 'crise-alerter' | 'crise-recevoir' | 'crise-agir' | 'crise-suivre'
  | 'prep-connaitre' | 'prep-organiser' | 'prep-moyens' | 'prep-entrainer'
  | 'meshcore' | 'meshtastic';

/** Les compteurs que le serveur sert au menu (GET /api/compteurs-menu/). */
export type CompteurNav = 'signalements' | 'messages_a_relire' | 'demandes_mobilisation';

export interface NavItem {
  icon: string;
  label: string;
  route: string;
  groupe: GroupeNavId;
  /** Absent = entrée affichée directement dans le cadre, avant les sous-cadres. */
  sousGroupe?: SousGroupeNavId;
  visibilite?: VisibiliteNav;
  /** Pastille : le nombre de choses qui attendent sur cette page. */
  compteur?: CompteurNav;
}

export interface SousGroupeNav {
  id: SousGroupeNavId;
  /** Cadre parent : un sous-cadre n'existe jamais seul. */
  groupe: Exclude<GroupeNavId, 'permanent'>;
  label: string;
  icon: string;
  /** Déplié tant que l'utilisateur ne l'a pas replié : les étapes d'une crise se lisent d'un
   * coup d'œil. Les protocoles radio, eux, restent repliés. */
  ouvertParDefaut?: boolean;
}

export interface GroupeNav {
  id: Exclude<GroupeNavId, 'permanent'>;
  label: string;
  icon: string;
}

/** Ordre d'affichage des cadres repliables (revue du menu du 19/11/2026, appliquée telle
 * quelle à la demande de Sylvain). Hors crise ouverte, le menu met « Préparer » devant
 * « Crise en cours » (voir AdminSidebarComponent.groupesNav) ; cet ordre-ci est celui d'une
 * crise en cours. */
export const GROUPES_NAV: GroupeNav[] = [
  { id: 'mon-activite', label: 'Mon activité', icon: 'person' },
  { id: 'crise', label: 'Crise en cours', icon: 'emergency' },
  { id: 'post-critique', label: 'Après la crise', icon: 'history' },
  { id: 'preparation', label: 'Préparer', icon: 'event_available' },
  // Cadre propre à la vie associative (11/11/2026). Il disparaît pour une mairie : toutes ses
  // entrées portent `membres-association`, et un cadre sans entrée visible n'est pas affiché.
  { id: 'association', label: 'Mon association', icon: 'diversity_3' },
  { id: 'communications', label: 'Radio', icon: 'settings_input_antenna' },
  { id: 'administration', label: 'Administration', icon: 'admin_panel_settings' },
];

/** Ordre d'affichage des sous-cadres, à l'intérieur de leur cadre. « Crise en cours » suit le
 * geste réel : comprendre, alerter, recevoir, agir, suivre. « Préparer » suit le plan
 * communal de sauvegarde : connaître, s'organiser, les moyens, s'entraîner. */
export const SOUS_GROUPES_NAV: SousGroupeNav[] = [
  { id: 'crise-comprendre', groupe: 'crise', label: 'Comprendre', icon: 'insights', ouvertParDefaut: true },
  { id: 'crise-alerter', groupe: 'crise', label: 'Alerter', icon: 'campaign', ouvertParDefaut: true },
  { id: 'crise-recevoir', groupe: 'crise', label: 'Recevoir', icon: 'call_received', ouvertParDefaut: true },
  { id: 'crise-agir', groupe: 'crise', label: 'Agir', icon: 'bolt', ouvertParDefaut: true },
  { id: 'crise-suivre', groupe: 'crise', label: 'Suivre', icon: 'track_changes', ouvertParDefaut: true },
  { id: 'prep-connaitre', groupe: 'preparation', label: 'Connaître', icon: 'travel_explore', ouvertParDefaut: true },
  { id: 'prep-organiser', groupe: 'preparation', label: "S'organiser", icon: 'account_tree', ouvertParDefaut: true },
  { id: 'prep-moyens', groupe: 'preparation', label: 'Moyens', icon: 'inventory', ouvertParDefaut: true },
  { id: 'prep-entrainer', groupe: 'preparation', label: "S'entraîner", icon: 'sports_score', ouvertParDefaut: true },
  { id: 'meshcore', groupe: 'communications', label: 'MeshCore', icon: 'hub' },
  { id: 'meshtastic', groupe: 'communications', label: 'Meshtastic', icon: 'lan' },
];

export const NAV_ITEMS: NavItem[] = [
  // ── En haut, toujours visibles : les quatre piliers ──────────────────
  { icon: 'home', label: 'Accueil', route: '/admin/dashboard', groupe: 'permanent' },
  // Page à 3 panneaux pensée comme l'outil quotidien d'une cellule de crise.
  { icon: 'dashboard_customize', label: 'Cellule de crise', route: '/admin/cellule-crise', groupe: 'permanent' },
  { icon: 'map', label: 'Carte', route: '/admin/carte', groupe: 'permanent' },
  // Le journal de bord de la crise. Réservé aux comptes système (droit inchangé).
  { icon: 'fact_check', label: 'Main courante', route: '/admin/main-courante', groupe: 'permanent', visibilite: 'sysadmin' },

  // ── Mon activité : ce qui me concerne, moi ───────────────────────────
  // Route publique : un chef d'équipe peut être un simple citoyen.
  { icon: 'checklist', label: 'Mes interventions', route: '/mes-interventions', groupe: 'mon-activite', visibilite: 'tous' },
  // « Je pars », « je rentre » (backend/core/engagements_personnels.py). Un bénévole
  // d'association est un compte ordinaire.
  { icon: 'schedule', label: "Mon relevé d'heures", route: '/mon-releve', groupe: 'mon-activite', visibilite: 'tous' },
  // Visible même sans équipe : la page explique ce qu'il faut pour qu'elle se remplisse.
  { icon: 'bed', label: 'Hébergement', route: '/hebergement', groupe: 'mon-activite', visibilite: 'tous' },

  // ── Crise en cours › Comprendre ──────────────────────────────────────
  { icon: 'local_fire_department', label: 'Crises', route: '/admin/crises', groupe: 'crise', sousGroupe: 'crise-comprendre' },
  // Vigilance, routes, carburant : relevés par le serveur (core/sources_ouvertes.py).
  { icon: 'radar', label: 'Veille du territoire', route: '/admin/veille', groupe: 'crise', sousGroupe: 'crise-comprendre' },
  // Les chiffres de la crise, pour le point avec la préfecture (core/point_situation.py).
  { icon: 'summarize', label: 'Point de situation', route: '/admin/point-de-situation', groupe: 'crise', sousGroupe: 'crise-comprendre' },
  { icon: 'visibility', label: 'Supervision PC Crise', route: '/admin/supervision-pc-crise', groupe: 'crise', sousGroupe: 'crise-comprendre' },

  // ── Crise en cours › Alerter ─────────────────────────────────────────
  { icon: 'notification_important', label: 'Alerter les habitants', route: '/admin/alerte-habitants', groupe: 'crise', sousGroupe: 'crise-alerter' },
  // Messages retenus avant envoi (core/brouillons_envoi.py) : ici, et non plus en
  // Administration, parce que ce sont des envois de la crise qui attendent qu'on les relise.
  { icon: 'drafts', label: 'Messages à relire', route: '/admin/messages-a-relire', groupe: 'crise', sousGroupe: 'crise-alerter', compteur: 'messages_a_relire' },

  // ── Crise en cours › Recevoir ────────────────────────────────────────
  // Une fiche par appel reçu au standard de la mairie (core/standard_crise.py) : le premier
  // écran dont on a besoin quand le téléphone sonne.
  { icon: 'support_agent', label: 'Standard de crise', route: '/admin/standard-crise', groupe: 'crise', sousGroupe: 'crise-recevoir' },
  { icon: 'flag', label: 'Signalements', route: '/admin/signalements', groupe: 'crise', sousGroupe: 'crise-recevoir', compteur: 'signalements' },
  { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes', groupe: 'crise', sousGroupe: 'crise-recevoir' },
  // Les personnes qui se déclarent en sécurité (« Sécurité » se lisait comme des réglages).
  { icon: 'verified_user', label: 'Personnes en sécurité', route: '/admin/declarations-securite', groupe: 'crise', sousGroupe: 'crise-recevoir' },

  // ── Crise en cours › Agir ────────────────────────────────────────────
  // Démarrer/clôturer une mission (Team.mission_active), condition du suivi de position MeshCore.
  { icon: 'directions_run', label: 'Missions', route: '/admin/missions', groupe: 'crise', sousGroupe: 'crise-agir' },
  { icon: 'campaign', label: 'Demandes de mobilisation', route: '/admin/demandes-mobilisation', groupe: 'crise', sousGroupe: 'crise-agir', compteur: 'demandes_mobilisation' },
  { icon: 'assignment', label: 'Affectations', route: '/admin/affectations', groupe: 'crise', sousGroupe: 'crise-agir' },
  // Qui tient quel créneau, jour par jour (le tour de garde, pas l'appartenance).
  { icon: 'calendar_month', label: 'Planning des équipes', route: '/admin/planning-equipes', groupe: 'crise', sousGroupe: 'crise-agir' },
  { icon: 'groups', label: 'Ressources mobilisées', route: '/admin/ressources-mobilisees', groupe: 'crise', sousGroupe: 'crise-agir' },
  { icon: 'home_work', label: 'Centres', route: '/admin/centres', groupe: 'crise', sousGroupe: 'crise-agir' },
  // Questionnaires remplis sur place, même sans réseau (core/formulaires_terrain.py).
  { icon: 'edit_note', label: 'Formulaires de terrain', route: '/admin/formulaires-terrain', groupe: 'crise', sousGroupe: 'crise-agir' },

  // ── Crise en cours › Suivre ──────────────────────────────────────────
  { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers', groupe: 'crise', sousGroupe: 'crise-suivre' },

  // ── Après la crise ───────────────────────────────────────────────────
  // Qui a été relogé, où, jusqu'à quand, et ce qui tient.
  { icon: 'family_restroom', label: 'Relogement des familles', route: '/admin/relogement-familles', groupe: 'post-critique' },
  // Le relogement des intervenants dure au-delà de la phase aiguë.
  { icon: 'night_shelter', label: 'Logement intervenants', route: '/admin/logement-intervenants', groupe: 'post-critique' },
  // « Résultats » retiré du menu le 18/11/2026 : la page n'a jamais été écrite.
  // Route publique ; les actions de gestion sont contrôlées côté backend (Habitation.peut_gerer).
  { icon: 'home_repair_service', label: 'Référencement des dégâts', route: '/referencement-degats', groupe: 'post-critique' },
  { icon: 'directions_car', label: 'Biens sinistrés', route: '/admin/biens-sinistres', groupe: 'post-critique' },
  // Besoins des foyers sinistrés, à la pièce près (core/appels_dons.py).
  { icon: 'volunteer_activism', label: 'Appels aux dons', route: '/admin/appels-dons', groupe: 'post-critique' },

  // ── Préparer ─────────────────────────────────────────────────────────
  // Dans l'ordre du plan communal de sauvegarde (16/11/2026 : « chaque paragraphe du PCS doit
  // avoir son menu ») : le plan et son document d'abord, puis les quatre temps.
  { icon: 'policy', label: 'Mon plan de sauvegarde', route: '/admin/plans', groupe: 'preparation' },
  // Vue filtrée sur la commune de l'institution, hors crise.
  { icon: 'location_city', label: 'Vue ma collectivité', route: '/admin/vue-mairie', groupe: 'preparation' },

  // Préparer › Connaître
  { icon: 'warning_amber', label: 'Risques de la commune', route: '/admin/pcs-risques', groupe: 'preparation', sousGroupe: 'prep-connaitre' },
  { icon: 'flood', label: 'Enjeux exposés', route: '/admin/pcs-enjeux-exposes', groupe: 'preparation', sousGroupe: 'prep-connaitre' },
  { icon: 'domain', label: 'Sites sensibles', route: '/admin/sites-sensibles', groupe: 'preparation', sousGroupe: 'prep-connaitre' },
  { icon: 'accessible', label: 'Personnes vulnérables', route: '/admin/personnes-vulnerables', groupe: 'preparation', sousGroupe: 'prep-connaitre', visibilite: 'registre-vulnerables' },
  { icon: 'verified', label: 'Habilitations registre', route: '/admin/habilitations-registre', groupe: 'preparation', sousGroupe: 'prep-connaitre', visibilite: 'autorite-locale' },
  { icon: 'border_outer', label: 'Zones', route: '/admin/zones', groupe: 'preparation', sousGroupe: 'prep-connaitre', visibilite: 'autorite-locale' },
  { icon: 'layers', label: 'Couches cartographiques', route: '/admin/couches-carto', groupe: 'preparation', sousGroupe: 'prep-connaitre' },
  { icon: 'water_drop', label: 'Simulation inondation', route: '/admin/simulation-inondation', groupe: 'preparation', sousGroupe: 'prep-connaitre', visibilite: 'autorite-locale' },

  // Préparer › S'organiser
  { icon: 'account_tree', label: 'Poste de commandement', route: '/admin/pcs-organisation', groupe: 'preparation', sousGroupe: 'prep-organiser' },
  { icon: 'menu_book', label: 'Fiches réflexes et conseils', route: '/admin/pcs-fiches', groupe: 'preparation', sousGroupe: 'prep-organiser' },
  { icon: 'contact_phone', label: 'Annuaire de crise', route: '/admin/pcs-annuaire', groupe: 'preparation', sousGroupe: 'prep-organiser' },
  { icon: 'workspaces', label: 'Équipes', route: '/admin/equipes', groupe: 'preparation', sousGroupe: 'prep-organiser' },
  { icon: 'category', label: 'Compétences', route: '/admin/competences', groupe: 'preparation', sousGroupe: 'prep-organiser' },
  { icon: 'event_repeat', label: 'Campagnes de disponibilité', route: '/admin/campagnes-disponibilite', groupe: 'preparation', sousGroupe: 'prep-organiser', visibilite: 'campagnes' },

  // Préparer › Moyens
  { icon: 'speaker_phone', label: 'Alerte de la population', route: '/admin/pcs-alerte', groupe: 'preparation', sousGroupe: 'prep-moyens' },
  // Stock permanent de l'institution (core/stocks.py).
  { icon: 'warehouse', label: 'Stocks', route: '/admin/stocks', groupe: 'preparation', sousGroupe: 'prep-moyens' },
  // Catalogues : ramenés près des stocks (ils étaient en Administration).
  { icon: 'inventory_2', label: 'Matériel', route: '/admin/materiel', groupe: 'preparation', sousGroupe: 'prep-moyens' },
  { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins', groupe: 'preparation', sousGroupe: 'prep-moyens' },

  // Préparer › S'entraîner
  { icon: 'sports_score', label: 'Exercices', route: '/admin/pcs-exercices', groupe: 'preparation', sousGroupe: 'prep-entrainer' },

  // ── Mon association ──────────────────────────────────────────────────
  { icon: 'badge', label: 'Membres', route: '/admin/membres-association', groupe: 'association', visibilite: 'membres-association' },

  // ── Communications / Radio ───────────────────────────────────────────
  // « Accueil radio » est en `tous` : une institution sans radio doit pouvoir apprendre ce
  // qu'il lui faut et demander le droit. C'est aussi là que `radioGuard` renvoie.
  { icon: 'settings_input_antenna', label: 'Accueil radio', route: '/admin/radio', groupe: 'communications', visibilite: 'tous' },
  // Relais radio depuis un poste où l'on ne peut rien installer. Visible de tous, en tête de
  // la radio : on ne doit pas le chercher le jour où on en a besoin.
  { icon: 'usb', label: 'Devenir passerelle', route: '/devenir-passerelle', groupe: 'communications', visibilite: 'tous' },
  // Toute la carte du réseau radio (10/11/2026).
  { icon: 'travel_explore', label: 'Carte radio', route: '/admin/carte-radio', groupe: 'communications', visibilite: 'radio' },
  // Relais sourds, liaisons à sens unique (backend/core/analyse_liaisons.py).
  { icon: 'troubleshoot', label: 'Diagnostic radio', route: '/admin/diagnostic-radio', groupe: 'communications', visibilite: 'radio' },
  // Jusqu'où porte un site (backend/core/relief_radio.py).
  { icon: 'cell_tower', label: 'Planification radio', route: '/admin/couverture-radio', groupe: 'communications', visibilite: 'radio' },
  // Boîtiers déployés sur site (satellite/README.md) : une machine, pas un poste radio.
  { icon: 'router', label: 'Satellites', route: '/admin/satellites', groupe: 'communications' },

  // Sous-cadre MeshCore
  { icon: 'smartphone', label: 'Companions MeshCore (test)', route: '/admin/meshcore-companions', groupe: 'communications', sousGroupe: 'meshcore', visibilite: 'radio' },
  { icon: 'forum', label: 'Canaux MeshCore (test)', route: '/admin/meshcore-canaux', groupe: 'communications', sousGroupe: 'meshcore', visibilite: 'radio' },
  // Réclamer un répéteur, prouver qu'on le contrôle, puis l'administrer (TacheAdminMeshCore).
  { icon: 'settings_remote', label: 'Administration MeshCore', route: '/admin/meshcore-administration', groupe: 'communications', sousGroupe: 'meshcore', visibilite: 'radio' },

  // Sous-cadre Meshtastic
  { icon: 'phone_android', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },
  { icon: 'chat', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },
  // Lire et modifier la configuration d'un nœud par la radio (TacheAdminMeshtastic).
  { icon: 'tune', label: 'Administration Meshtastic', route: '/admin/meshtastic-administration', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },

  // ── Administration : la plateforme et ses comptes ────────────────────
  // Ouvert à tout compte institutionnel : c'est là que le bureau d'une association configure
  // ses envois ; la CRÉATION est encadrée (core/creation_institution.py).
  { icon: 'apartment', label: 'Institutions', route: '/admin/institutions', groupe: 'administration' },
  // Qui est membre de quelle institution, par la personne.
  { icon: 'switch_account', label: 'Rattachements', route: '/admin/rattachements', groupe: 'administration' },
  { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs', groupe: 'administration', visibilite: 'sysadmin' },
  // Comptes Secours en attente de validation (accountValidationGuard).
  { icon: 'how_to_reg', label: 'Validations de comptes', route: '/admin/validations-comptes', groupe: 'administration', visibilite: 'validation-comptes' },
  // Deux écrans d'exploitation de la plateforme (revue d'accès du 12/11/2026).
  { icon: 'sync_problem', label: 'Conflits de synchronisation', route: '/admin/conflits-synchronisation', groupe: 'administration', visibilite: 'sysadmin' },
  { icon: 'link', label: 'Correspondances', route: '/admin/correspondances', groupe: 'administration', visibilite: 'sysadmin' },
  // Tableaux Grafana ; le jeton n'est délivré qu'aux administrateurs (core/grafana.py).
  { icon: 'monitor_heart', label: 'Supervision technique', route: '/admin/monitoring', groupe: 'administration', visibilite: 'admin-plateforme' },
  // Un compte par passerelle radio du site (CompteMqtt).
  { icon: 'vpn_key', label: 'Comptes MQTT', route: '/admin/comptes-mqtt', groupe: 'administration', visibilite: 'admin-plateforme' },
];
