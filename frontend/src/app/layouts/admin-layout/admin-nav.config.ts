/** Configuration du menu de l'administration : données pures, aucune logique.
 * Ajouter une page = ajouter une entrée ici (voir DOCUMENTATION.md, § 6.4). */

/** `permanent` : toujours visible en haut. Les autres valeurs sont les cadres repliables, groupés
 * par moment d'usage dans le cycle d'une crise. */
export type GroupeNavId = 'permanent' | 'crise' | 'post-critique' | 'preparation' | 'association' | 'communications' | 'administration';

/** Qui voit l'entrée (les gardes de route protègent aussi l'URL) :
 * - `institutionnel` (défaut) : rôle effectif institutionnel ;
 * - `tous` : toujours visible ;
 * - `sysadmin` : administrateur PROD réel ;
 * - `validation-comptes` : rôle effectif admin ou autorité locale ;
 * - `autorite-locale` : collectivités territoriales (isAutoriteLocaleCommunale) ;
 * - `registre-vulnerables` : champ serveur `acces_registre_vulnerables` ;
 * - `membres-association` : champ serveur `acces_membres_association` ;
 * - `campagnes` : champ serveur `acces_campagnes` (qui peut mener une campagne) ;
 * - `radio` : champ serveur `acces_radio` (nœud personnel, passerelle de l'institution, ou
 *   droit accordé — voir backend/core/acces_radio.py). L'entrée « Accueil radio » reste en
 *   `tous` : c'est elle qui explique ce qu'il faut et permet de le demander. */
export type VisibiliteNav =
  'institutionnel' | 'tous' | 'sysadmin' | 'validation-comptes' | 'autorite-locale'
  | 'registre-vulnerables' | 'membres-association' | 'campagnes' | 'radio';

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
  { id: 'preparation', label: 'Préparation — plan de sauvegarde', icon: 'event_available' },
  // Cadre propre à la vie associative, demandé le 11/11/2026 : « ramener tout ce qui est
  // association dans une rubrique association ». Ses entrées étaient dispersées dans
  // « Préparation », entre les sites sensibles et les personnes vulnérables — un président
  // d'association devait les y chercher parmi des écrans de collectivité qui ne le concernent
  // pas. Le cadre entier disparaît pour une mairie : toutes ses entrées portent
  // `membres-association`, et un cadre sans entrée visible n'est pas affiché.
  { id: 'association', label: 'Mon association', icon: 'diversity_3' },
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
  // Relais radio depuis un poste où l'on ne peut rien installer : la radio se branche en USB
  // et le navigateur relaie. Visible de tous — c'est un écran d'urgence, on ne le cherche pas
  // dans un sous-menu le jour où on en a besoin.
  { icon: 'usb', label: 'Devenir passerelle', route: '/devenir-passerelle', groupe: 'permanent', visibilite: 'tous' },
  // Route publique également, et `tous` pour la même raison : un bénévole hébergé chez un
  // particulier n'est pas un compte institutionnel. L'entrée reste visible MÊME SANS ÉQUIPE —
  // la page explique alors ce qu'il faut pour qu'elle se remplisse, au lieu de laisser croire
  // que la fonction n'existe pas (demande du 12/11/2026).
  { icon: 'home_work', label: 'Hébergement', route: '/hebergement', groupe: 'permanent', visibilite: 'tous' },

  // ── Crise en cours ──────────────────────────────────────────────────
  { icon: 'notification_important', label: 'Alerter les habitants', route: '/admin/alerte-habitants', groupe: 'crise' },
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
  // Qui tient quel créneau, jour par jour. Distinct des « Affectations » (qui est dans
  // quelle équipe) : ici c'est le tour de garde, pas l'appartenance.
  { icon: 'calendar_month', label: 'Planning des équipes', route: '/admin/planning-equipes', groupe: 'crise' },
  { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers', groupe: 'crise' },
  { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes', groupe: 'crise' },
  { icon: 'map', label: 'Carte', route: '/admin/carte', groupe: 'crise' },
  // Vigilance Météo-France, événements routiers, stations de carburant : relevés par le
  // serveur et copiés en base (voir core/sources_ouvertes.py). Dans « Crise en cours » parce
  // que c'est l'écran qu'on ouvre quand la situation se tend, pas un réglage.
  { icon: 'radar', label: 'Veille du territoire', route: '/admin/veille', groupe: 'crise' },
  { icon: 'fact_check', label: 'Main courante', route: '/admin/main-courante', groupe: 'crise', visibilite: 'sysadmin' },

  // ── Post-critique — gestion à long terme ────────────────────────────
  // Le relogement des intervenants dure au-delà de la phase aiguë.
  { icon: 'night_shelter', label: 'Logement intervenants', route: '/admin/logement-intervenants', groupe: 'post-critique' },
  // Le pendant pour les sinistres : qui a ete reloge, ou, jusqu'a quand, et ce qui tient.
  { icon: 'family_restroom', label: 'Relogement des familles', route: '/admin/relogement-familles', groupe: 'post-critique' },
  // Page encore vide, gardée dans le menu.
  { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats', groupe: 'post-critique' },
  // Route publique ; les actions de gestion sont contrôlées côté backend (Habitation.peut_gerer).
  { icon: 'home_repair_service', label: 'Référencement des dégâts', route: '/referencement-degats', groupe: 'post-critique' },
  { icon: 'directions_car', label: 'Biens sinistrés', route: '/admin/biens-sinistres', groupe: 'post-critique' },
  // Besoin des foyers sinistrés, à la pièce près, que les autres institutions couvrent ligne par ligne
  // (voir backend/core/appels_dons.py).
  { icon: 'volunteer_activism', label: 'Appels aux dons', route: '/admin/appels-dons', groupe: 'post-critique' },
  // Questionnaires composés par la collectivité et remplis sur place, même sans réseau — voir
  // backend/core/formulaires_terrain.py. Le serveur ne les montre qu'aux collectivités et à
  // leurs délégués.
  { icon: 'fact_check', label: 'Formulaires de terrain', route: '/admin/formulaires-terrain', groupe: 'crise' },

  // ── Préparation ─────────────────────────────────────────────────────
  // Roster réutilisable, préparé à l'avance.
  // Dans l'ordre des paragraphes du plan communal de sauvegarde (demande du 16/11/2026 : « chaque
  // paragraphe du PCS doit avoir son menu ») : le plan et son document, puis 1.1 risques, 1.2
  // enjeux et personnes vulnérables, 2.2 zones, 2.4 annuaire, 3.1 moyens humains. Les lieux
  // d'accueil (2.5, « Centres ») et le matériel (3.2) gardent leur entrée là où on les cherche
  // pendant la crise ; la table des paragraphes de « Mon plan de sauvegarde » y mène.
  { icon: 'fact_check', label: 'Mon plan de sauvegarde', route: '/admin/plans', groupe: 'preparation' },
  { icon: 'warning_amber', label: 'Risques de la commune', route: '/admin/pcs-risques', groupe: 'preparation' },
  { icon: 'domain', label: 'Sites sensibles', route: '/admin/sites-sensibles', groupe: 'preparation' },
  { icon: 'flood', label: 'Enjeux exposés', route: '/admin/pcs-enjeux-exposes', groupe: 'preparation' },
  { icon: 'layers', label: 'Couches cartographiques', route: '/admin/couches-carto', groupe: 'preparation' },
  // Stock permanent de l'institution (dépôts, articles, mouvements) — voir backend/core/stocks.py.
  { icon: 'warehouse', label: 'Stocks', route: '/admin/stocks', groupe: 'preparation' },
  { icon: 'accessible', label: 'Personnes vulnérables', route: '/admin/personnes-vulnerables', groupe: 'preparation', visibilite: 'registre-vulnerables' },
  { icon: 'how_to_reg', label: 'Habilitations registre', route: '/admin/habilitations-registre', groupe: 'preparation', visibilite: 'autorite-locale' },
  { icon: 'account_tree', label: 'Poste de commandement', route: '/admin/pcs-organisation', groupe: 'preparation' },
  { icon: 'layers', label: 'Zones', route: '/admin/zones', groupe: 'preparation', visibilite: 'autorite-locale' },
  { icon: 'contact_phone', label: 'Annuaire de crise', route: '/admin/pcs-annuaire', groupe: 'preparation' },
  { icon: 'campaign', label: 'Alerte de la population', route: '/admin/pcs-alerte', groupe: 'preparation' },
  { icon: 'groups', label: 'Équipes', route: '/admin/equipes', groupe: 'preparation' },
  { icon: 'category', label: 'Compétences', route: '/admin/competences', groupe: 'preparation' },
  { icon: 'campaign', label: 'Campagnes de disponibilité', route: '/admin/campagnes-disponibilite', groupe: 'preparation', visibilite: 'campagnes' },
  { icon: 'water_drop', label: 'Simulation inondation', route: '/admin/simulation-inondation', groupe: 'preparation', visibilite: 'autorite-locale' },
  { icon: 'sports_score', label: 'Exercices', route: '/admin/pcs-exercices', groupe: 'preparation' },

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
  // Reclamer un repeteur, prouver qu'on le controle, puis l'administrer par la radio
  // (backend/core/models.py : TacheAdminMeshCore). La page dit ce qui la distingue de son
  // equivalent Meshtastic : aucun filet cote firmware, donc une preuve exigee avant d'ecrire.
  { icon: 'settings_remote', label: 'Administration MeshCore', route: '/admin/meshcore-administration', groupe: 'communications', sousGroupe: 'meshcore', visibilite: 'radio' },

  // Sous-cadre Meshtastic
  { icon: 'settings_input_antenna', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },
  { icon: 'forum', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },
  // Lire et modifier la configuration d'un noeud par la radio (backend/core/models.py:
  // TacheAdminMeshtastic). La page explique le prealable qui conditionne tout : la cle publique
  // de la passerelle doit figurer dans security.admin_key du noeud vise.
  { icon: 'settings_remote', label: 'Administration Meshtastic', route: '/admin/meshtastic-administration', groupe: 'communications', sousGroupe: 'meshtastic', visibilite: 'radio' },

  // ── Administration ──────────────────────────────────────────────────
  // ── Mon association ───────────────────────────────────────────────
  { icon: 'badge', label: 'Membres', route: '/admin/membres-association', groupe: 'association', visibilite: 'membres-association' },

  // Reste ouvert à tout compte institutionnel, volontairement : c'est par cette page que le
  // bureau d'une association configure ses envois (onglet « Envois »), et la liste est déjà
  // cloisonnée à « chez moi + ma zone » côté serveur. Ce qui posait problème était la
  // CRÉATION, désormais encadrée (voir backend/core/creation_institution.py).
  { icon: 'apartment', label: 'Institutions', route: '/admin/institutions', groupe: 'administration' },
  // Qui est membre de quelle institution — l'entrée par la PERSONNE, qui manquait : on ne
  // pouvait voir que les membres d'une institution à la fois. Recherche et pagination côté
  // serveur, parce qu'une même personne peut appartenir à plusieurs institutions et qu'il y
  // en aura des milliers.
  { icon: 'how_to_reg', label: 'Rattachements', route: '/admin/rattachements', groupe: 'administration' },
  // Messages retenus avant envoi (voir backend/core/brouillons_envoi.py). La fenetre de
  // relecture s'ouvre d'elle-meme apres l'action ; cette page retrouve ce qui a ete manque.
  { icon: 'drafts', label: 'Messages a relire', route: '/admin/messages-a-relire', groupe: 'administration' },
  { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins', groupe: 'administration' },
  { icon: 'inventory_2', label: 'Matériel', route: '/admin/materiel', groupe: 'administration' },
  // Conflits de synchronisation entre le central et un satellite, et correspondances du
  // référentiel métier : deux écrans d'exploitation de la plateforme. Les données sont déjà
  // cloisonnées côté serveur, mais les laisser dans le menu d'un bureau associatif donnait
  // l'impression d'un accès plus large qu'il ne l'est (revue d'accès du 12/11/2026).
  { icon: 'sync_problem', label: 'Conflits de synchronisation', route: '/admin/conflits-synchronisation', groupe: 'administration', visibilite: 'sysadmin' },
  { icon: 'link', label: 'Correspondances', route: '/admin/correspondances', groupe: 'administration', visibilite: 'sysadmin' },
  { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs', groupe: 'administration', visibilite: 'sysadmin' },
  // Comptes Secours en attente de validation (voir accountValidationGuard).
  { icon: 'how_to_reg', label: 'Validations de comptes', route: '/admin/validations-comptes', groupe: 'administration', visibilite: 'validation-comptes' },
  // Tableaux Grafana ; le jeton n'est délivré qu'aux administrateurs (backend/core/grafana.py).
  { icon: 'monitor_heart', label: 'Supervision technique', route: '/admin/monitoring', groupe: 'administration', visibilite: 'sysadmin' },
  // Un compte par passerelle radio du site (backend/core/models.py:CompteMqtt).
  { icon: 'router', label: 'Comptes MQTT', route: '/admin/comptes-mqtt', groupe: 'administration', visibilite: 'sysadmin' },
];
