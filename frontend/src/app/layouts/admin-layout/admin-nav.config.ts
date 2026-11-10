/** Configuration du menu de l'administration : données pures, aucune logique.
 * Ajouter une page = ajouter une entrée ici (voir DOCUMENTATION.md, § 6.4). */

/** `permanent` : toujours visible en haut. Les autres valeurs sont les cadres repliables, groupés
 * par moment d'usage dans le cycle d'une crise. */
export type GroupeNavId = 'permanent' | 'crise' | 'post-critique' | 'preparation' | 'communications' | 'administration';

/** Qui voit l'entrée (les gardes de route protègent aussi l'URL) :
 * - `institutionnel` (défaut) : rôle effectif institutionnel ;
 * - `tous` : toujours visible ;
 * - `sysadmin` : administrateur PROD réel ;
 * - `validation-comptes` : rôle effectif admin ou autorité locale ;
 * - `autorite-locale` : collectivités territoriales (isAutoriteLocaleCommunale) ;
 * - `registre-vulnerables` : champ serveur `acces_registre_vulnerables` ;
 * - `membres-association` : champ serveur `acces_membres_association` ;
 * - `radio` : champ serveur `acces_radio` (nœud personnel, passerelle de l'institution, ou
 *   droit accordé — voir backend/core/acces_radio.py). L'entrée « Accueil radio » reste en
 *   `tous` : c'est elle qui explique ce qu'il faut et permet de le demander. */
export type VisibiliteNav =
  'institutionnel' | 'tous' | 'sysadmin' | 'validation-comptes' | 'autorite-locale'
  | 'registre-vulnerables' | 'membres-association' | 'radio';

/** Second niveau de replis, à l'intérieur d'un cadre. N'existe que là où un même cadre
 * contient deux familles d'écrans qui ne se mélangent jamais : MeshCore et Meshtastic sont
 * deux protocoles radio distincts, avec leurs propres companions et leurs propres canaux, et
 * les sept entrées à plat se lisaient comme une liste de doublons. */
export type SousGroupeNavId = 'meshcore' | 'meshtastic';

export interface NavItem {
  icon: string;
  label: string;
  route: string;
  groupe: GroupeNavId;
  /** Absent = entrée affichée directement dans le cadre, avant les sous-cadres. */
  sousGroupe?: SousGroupeNavId;
  visibilite?: VisibiliteNav;
}

export interface SousGroupeNav {
  id: SousGroupeNavId;
  /** Cadre parent : un sous-cadre n'existe jamais seul. */
  groupe: Exclude<GroupeNavId, 'permanent'>;
  label: string;
  icon: string;
}

export interface GroupeNav {
  id: Exclude<GroupeNavId, 'permanent'>;
  label: string;
  icon: string;
}

/** Ordre d'affichage des cadres repliables. */
export const GROUPES_NAV: GroupeNav[] = [
  { id: 'crise', label: 'Crise en cours', icon: 'emergency' },
  { id: 'post-critique', label: 'Post-critique — gestion à long terme', icon: 'history' },
  { id: 'preparation', label: 'Préparation', icon: 'event_available' },
  { id: 'communications', label: 'Communications / Radio', icon: 'settings_input_antenna' },
  { id: 'administration', label: 'Administration', icon: 'admin_panel_settings' },
];

/** Ordre d'affichage des sous-cadres, à l'intérieur de leur cadre. */
export const SOUS_GROUPES_NAV: SousGroupeNav[] = [
  { id: 'meshcore', groupe: 'communications', label: 'MeshCore', icon: 'hub' },
  { id: 'meshtastic', groupe: 'communications', label: 'Meshtastic', icon: 'lan' },
];

export const NAV_ITEMS: NavItem[] = [
  // ── Toujours visibles en haut du menu ──────────────────────────────
  { icon: 'home', label: 'Accueil', route: '/admin/dashboard', groupe: 'permanent' },
  // Page à 3 panneaux pensée comme l'outil quotidien d'une cellule de crise.
  { icon: 'dashboard_customize', label: 'Cellule de crise', route: '/admin/cellule-crise', groupe: 'permanent' },
  // Vue filtrée sur la commune de l'institution (typiquement une mairie), hors crise.
  { icon: 'location_city', label: 'Vue Ma Collectivité', route: '/admin/vue-mairie', groupe: 'permanent' },
  // Route publique : un chef d'équipe peut être un simple citoyen.
  { icon: 'checklist', label: 'Mes interventions', route: '/mes-interventions', groupe: 'permanent', visibilite: 'tous' },

  // ── Crise en cours ──────────────────────────────────────────────────
  { icon: 'flag', label: 'Signalements', route: '/admin/signalements', groupe: 'crise' },
  { icon: 'verified_user', label: 'Sécurité', route: '/admin/declarations-securite', groupe: 'crise' },
  // Démarrer/clôturer une mission (Team.mission_active), condition du suivi de position MeshCore.
  { icon: 'flag_circle', label: 'Missions', route: '/admin/missions', groupe: 'crise' },
  { icon: 'local_fire_department', label: 'Crises', route: '/admin/crises', groupe: 'crise' },
  { icon: 'home_work', label: 'Centres', route: '/admin/centres', groupe: 'crise' },
  { icon: 'groups', label: 'Ressources mobilisées', route: '/admin/ressources-mobilisees', groupe: 'crise' },
  { icon: 'visibility', label: 'Supervision PC Crise', route: '/admin/supervision-pc-crise', groupe: 'crise' },
  { icon: 'campaign', label: 'Demandes de mobilisation', route: '/admin/demandes-mobilisation', groupe: 'crise' },
  { icon: 'assignment', label: 'Affectations', route: '/admin/affectations', groupe: 'crise' },
  { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers', groupe: 'crise' },
  { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes', groupe: 'crise' },
  { icon: 'map', label: 'Carte', route: '/admin/carte', groupe: 'crise' },
  { icon: 'fact_check', label: 'Main courante', route: '/admin/main-courante', groupe: 'crise', visibilite: 'sysadmin' },

  // ── Post-critique — gestion à long terme ────────────────────────────
  // Le relogement des intervenants dure au-delà de la phase aiguë.
  { icon: 'night_shelter', label: 'Logement intervenants', route: '/admin/logement-intervenants', groupe: 'post-critique' },
  // Page encore vide, gardée dans le menu.
  { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats', groupe: 'post-critique' },
  // Route publique ; les actions de gestion sont contrôlées côté backend (Habitation.peut_gerer).
  { icon: 'home_repair_service', label: 'Référencement des dégâts', route: '/referencement-degats', groupe: 'post-critique' },

  // ── Préparation ─────────────────────────────────────────────────────
  // Roster réutilisable, préparé à l'avance.
  { icon: 'groups', label: 'Équipes', route: '/admin/equipes', groupe: 'preparation' },
  { icon: 'layers', label: 'Zones', route: '/admin/zones', groupe: 'preparation', visibilite: 'autorite-locale' },
  // Planification préventive pour les mairies.
  { icon: 'water_drop', label: 'Simulation inondation', route: '/admin/simulation-inondation', groupe: 'preparation', visibilite: 'autorite-locale' },
  // Dispositif PCS préparé à l'avance, activable sur une crise (PlanViewSet.activer).
  { icon: 'fact_check', label: 'Mon plan de sauvegarde', route: '/admin/plans', groupe: 'preparation' },
  // Enjeux du territoire (écoles, soins, industrie, salles) pré-alimentés depuis l'open data
  // national, puis validés un à un par la commune — voir core/opendata/ côté serveur.
  { icon: 'domain', label: 'Sites sensibles', route: '/admin/sites-sensibles', groupe: 'preparation' },
  { icon: 'category', label: 'Compétences', route: '/admin/competences', groupe: 'preparation' },
  // Associations agréées de sécurité civile : annuaire des membres, circuit de recrutement,
  // qualifications avec échéances, disponibilités à quinze jours. Champ serveur
  // `acces_membres_association` : « être au bureau » est un attribut du rattachement et non un
  // rôle de compte, donc invérifiable depuis le menu. Une institution non associative ne voit
  // pas l'entrée.
  { icon: 'badge', label: 'Membres association', route: '/admin/membres-association', groupe: 'preparation', visibilite: 'membres-association' },
  // RCSC/RESPONSABLE d'une mairie ou délégation active (core/vulnerabilites.py).
  { icon: 'accessible', label: 'Personnes vulnérables', route: '/admin/personnes-vulnerables', groupe: 'preparation', visibilite: 'registre-vulnerables' },
  // Qui tient le registre, designe nominativement par le maire. Visible a toute collectivite
  // et NON conditionnee a `registre-vulnerables` : une commune ou personne n'est encore
  // habilite doit pouvoir atteindre cette page, sinon le dispositif n'a aucune porte d'entree.
  { icon: 'how_to_reg', label: 'Habilitations registre', route: '/admin/habilitations-registre', groupe: 'preparation', visibilite: 'autorite-locale' },

  // ── Communications / Radio ──────────────────────────────────────────
  // Seul cadre transversal, et le seul à deux niveaux : MeshCore et Meshtastic sont deux
  // protocoles sans rien en commun, leurs écrans sont donc dans deux sous-cadres.
  //
  // « Accueil radio » est en `tous` et NON en `radio` : une institution sans aucune radio doit
  // pouvoir ouvrir cette page, apprendre ce qu'il lui faut (un nœud, ou une passerelle) et
  // demander le droit. La masquer supprimerait la porte d'entrée du domaine -- même
  // raisonnement que « Habilitations registre ». C'est aussi là que `radioGuard` renvoie.
  { icon: 'settings_input_antenna', label: 'Accueil radio', route: '/admin/radio', groupe: 'communications', visibilite: 'tous' },
  // Toute la carte du réseau radio : relais, passerelles, répéteurs entendus, liaisons
  // mesurées, couverture calculée. Séparée de /admin/carte, qui ne garde du mesh que les
  // positions des intervenants en mission (demande du 10/11/2026).
  { icon: 'travel_explore', label: 'Carte radio', route: '/admin/carte-radio', groupe: 'communications', visibilite: 'radio' },
  // Ce que les mesures disent du reseau : relais sourds, liaisons a sens unique, desequilibrees,
  // noeuds inaudibles (backend/core/analyse_liaisons.py).
  { icon: 'troubleshoot', label: 'Diagnostic radio', route: '/admin/diagnostic-radio', groupe: 'communications', visibilite: 'radio' },
  // Jusqu'ou porte un site, et est-ce que ca passe entre deux points (backend/core/relief_radio.py,
  // porte de relief.js de carte-live-meshtastic).
  { icon: 'cell_tower', label: 'Planification radio', route: '/admin/couverture-radio', groupe: 'communications', visibilite: 'radio' },
  // Boîtiers Raspberry Pi déployés sur site (voir satellite/README.md). Reste institutionnel :
  // un satellite est une machine, pas un poste radio -- il héberge aussi la synchronisation et
  // les sauvegardes.
  { icon: 'router', label: 'Satellites', route: '/admin/satellites', groupe: 'communications' },

  // Sous-cadre MeshCore
  { icon: 'settings_input_antenna', label: 'Companions MeshCore (test)', route: '/admin/meshcore-companions', groupe: 'communications', sousGroupe: 'meshcore', visibilite: 'radio' },
  { icon: 'forum', label: 'Canaux MeshCore (test)', route: '/admin/meshcore-canaux', groupe: 'communications', sousGroupe: 'meshcore', visibilite: 'radio' },

  // Sous-cadre Meshtastic
  { icon: 'settings_input_antenna', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },
  { icon: 'forum', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },
  // Lire et modifier la configuration d'un noeud par la radio (backend/core/models.py:
  // TacheAdminMeshtastic). La page explique le prealable qui conditionne tout : la cle publique
  // de la passerelle doit figurer dans security.admin_key du noeud vise.
  { icon: 'settings_remote', label: 'Administration Meshtastic', route: '/admin/meshtastic-administration', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },

  // ── Administration ──────────────────────────────────────────────────
  { icon: 'apartment', label: 'Institutions', route: '/admin/institutions', groupe: 'administration' },
  { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins', groupe: 'administration' },
  { icon: 'inventory_2', label: 'Matériel', route: '/admin/materiel', groupe: 'administration' },
  { icon: 'sync_problem', label: 'Conflits de synchronisation', route: '/admin/conflits-synchronisation', groupe: 'administration' },
  { icon: 'link', label: 'Correspondances', route: '/admin/correspondances', groupe: 'administration' },
  { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs', groupe: 'administration', visibilite: 'sysadmin' },
  // Comptes Secours en attente de validation (voir accountValidationGuard).
  { icon: 'how_to_reg', label: 'Validations de comptes', route: '/admin/validations-comptes', groupe: 'administration', visibilite: 'validation-comptes' },
  // Tableaux Grafana ; le jeton n'est délivré qu'aux administrateurs (backend/core/grafana.py).
  { icon: 'monitor_heart', label: 'Supervision technique', route: '/admin/monitoring', groupe: 'administration', visibilite: 'sysadmin' },
  // Un compte par passerelle radio du site (backend/core/models.py:CompteMqtt).
  { icon: 'router', label: 'Comptes MQTT', route: '/admin/comptes-mqtt', groupe: 'administration', visibilite: 'sysadmin' },
];
