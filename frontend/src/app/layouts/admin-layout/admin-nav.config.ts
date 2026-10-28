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
 * - `registre-vulnerables` : champ serveur `acces_registre_vulnerables`. */
export type VisibiliteNav =
  'institutionnel' | 'tous' | 'sysadmin' | 'validation-comptes' | 'autorite-locale' | 'registre-vulnerables';

export interface NavItem {
  icon: string;
  label: string;
  route: string;
  groupe: GroupeNavId;
  visibilite?: VisibiliteNav;
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
  // qualifications avec échéances, disponibilités à quinze jours. Visible à tout rôle
  // institutionnel : « être au bureau » est un attribut du rattachement et non un rôle de
  // compte, donc invérifiable depuis le menu — la page le dit elle-même à qui n'y a pas accès.
  { icon: 'badge', label: 'Membres association', route: '/admin/membres-association', groupe: 'preparation' },
  // RCSC/RESPONSABLE d'une mairie ou délégation active (core/vulnerabilites.py).
  { icon: 'accessible', label: 'Personnes vulnérables', route: '/admin/personnes-vulnerables', groupe: 'preparation', visibilite: 'registre-vulnerables' },
  // Qui tient le registre, designe nominativement par le maire. Visible a toute collectivite
  // et NON conditionnee a `registre-vulnerables` : une commune ou personne n'est encore
  // habilite doit pouvoir atteindre cette page, sinon le dispositif n'a aucune porte d'entree.
  { icon: 'how_to_reg', label: 'Habilitations registre', route: '/admin/habilitations-registre', groupe: 'preparation', visibilite: 'autorite-locale' },

  // ── Communications / Radio ──────────────────────────────────────────
  // Seul cadre transversal. Ces canaux sont généralistes ; en crise, ce sont les canaux
  // d'équipe qui servent.
  { icon: 'settings_input_antenna', label: 'Companions MeshCore (test)', route: '/admin/meshcore-companions', groupe: 'communications' },
  { icon: 'forum', label: 'Canaux MeshCore (test)', route: '/admin/meshcore-canaux', groupe: 'communications' },
  { icon: 'settings_input_antenna', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions', groupe: 'communications' },
  { icon: 'forum', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux', groupe: 'communications' },
  // Boîtiers Raspberry Pi déployés sur site (voir satellite/README.md).
  { icon: 'router', label: 'Satellites', route: '/admin/satellites', groupe: 'communications' },

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
];
