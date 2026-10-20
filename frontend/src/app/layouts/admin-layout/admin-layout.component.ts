import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { AuthService } from '../../auth/services/auth.service';
import { NotificationService } from '../../services/notification.service';
import { SuiviPositionPermanentService } from '../../services/suivi-position-permanent.service';
import { User, UserRole } from '../../shared/models/user.model';
import { AppNotification, ResumeNotifications } from '../../shared/models/notification.model';
import { pollWhileVisible } from '../../shared/utils/polling.util';
import {
  afficherNotificationNavigateur,
  demanderPermissionNotificationNavigateur,
} from '../../shared/utils/browser-notification.util';

// Intervalle de polling de la cloche — voir pollWhileVisible (suspendu tant que l'onglet est en
// arrière-plan, ne réveille jamais un onglet minimisé pour rien).
const INTERVALLE_POLLING_NOTIFICATIONS_MS = 20_000;

/** `permanent` : toujours visible en haut, jamais dans un cadre repliable (pages consultées au
 * quotidien, replier ajouterait un clic à chaque connexion) -- les cinq autres valeurs
 * correspondent aux cadres dépliables de `groupesNav` ci-dessous, dans cet ordre précis
 * (demande utilisateur du 12/10, plusieurs allers-retours de reclassement) : une entrée reste
 * groupée par UTILITÉ (à quel moment du cycle de vie d'une crise on s'en sert), pas par domaine
 * technique -- sauf "Communications / Radio", seul regroupement transversal explicitement
 * demandé (gérer l'infra radio est le même geste qu'on soit en préparation ou en crise). */
type GroupeNavId = 'permanent' | 'crise' | 'post-critique' | 'preparation' | 'communications' | 'administration';

interface NavItem {
  icon: string;
  label: string;
  route: string;
  active?: boolean;
  groupe: GroupeNavId;
}

@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './admin-layout.component.html',
  styleUrls: ['./admin-layout.component.scss']
})
export class AdminLayoutComponent implements OnInit, OnDestroy {
  currentUser: User | null = null;
  sidebarCollapsed = false;
  sidebarOpen = false; // Pour mobile
  showNotifications = false;
  showUserMenu = false;
  isMobile = false;

  notifications: AppNotification[] = [];

  private pollingNotificationsSub?: Subscription;
  // null tant qu'aucun résumé n'a encore été reçu — sert à ne jamais déclencher de notification
  // navigateur au tout premier chargement (rien de "nouveau" par rapport à... rien).
  private dernierResume: ResumeNotifications | null = null;

  /** Ordre d'affichage des cadres dépliables -- voir docstring de GroupeNavId. */
  readonly groupesNav: { id: GroupeNavId; label: string; icon: string }[] = [
    { id: 'crise', label: 'Crise en cours', icon: 'emergency' },
    { id: 'post-critique', label: 'Post-critique — gestion à long terme', icon: 'history' },
    { id: 'preparation', label: 'Préparation', icon: 'event_available' },
    { id: 'communications', label: 'Communications / Radio', icon: 'settings_input_antenna' },
    { id: 'administration', label: 'Administration', icon: 'admin_panel_settings' },
  ];

  navItems: NavItem[] = [
    { icon: 'home', label: 'Accueil', route: '/admin/dashboard', groupe: 'permanent' },

    // Placée haut dans le menu à dessein (demande utilisateur du 26/09) : page unique à 3
    // panneaux repliables (ressource/moyen/coordination) pensée comme l'outil quotidien d'une
    // cellule de crise, pas une page annexe.
    { icon: 'dashboard_customize', label: 'Cellule de crise', route: '/admin/cellule-crise', groupe: 'permanent' },

    { icon: 'flag', label: 'Signalements', route: '/admin/signalements', groupe: 'crise' },

    // Jamais ajoutée au menu jusqu'ici (même défaut que Missions/Companions Meshtastic
    // ci-dessous) : page, route et service existaient déjà côté front/back, mais seul
    // AdminSidebarComponent (orphelin, jamais instancié) la référençait -- inatteignable sans
    // connaître son URL exacte.
    { icon: 'verified_user', label: 'Sécurité', route: '/admin/declarations-securite', groupe: 'crise' },

    // Vue filtrée sur la commune de l'institution de l'utilisateur (typiquement une mairie) —
    // existait déjà côté route/composant/backend mais n'apparaissait dans AUCUN menu (seul
    // AdminSidebarComponent la référençait, un composant orphelin jamais instancié nulle part) :
    // la page était donc inatteignable sans connaître son URL exacte. Permanente (demande
    // utilisateur du 12/10) : une mairie la consulte en dehors de toute crise.
    { icon: 'location_city', label: 'Vue Ma Collectivité', route: '/admin/vue-mairie', groupe: 'permanent' },

    // Préparation, pas Crise en cours (demande utilisateur du 12/10) : "tu la prépares, puis tu
    // l'utilises, et si ça se passe bien tu la récupères pour la prochaine fois" -- même logique
    // que "Mon plan de sauvegarde" (un roster réutilisable, pas un geste du jour J).
    { icon: 'groups', label: 'Équipes', route: '/admin/equipes', groupe: 'preparation' },

    // Absente du menu jusqu'ici (page atteignable seulement en connaissant son URL exacte,
    // même défaut que 'Vue Ma Collectivité' ci-dessus) — c'est pourtant ici qu'on démarre/
    // clôture une mission (Team.mission_active), condition du suivi de position MeshCore.
    { icon: 'flag_circle', label: 'Missions', route: '/admin/missions', groupe: 'crise' },

    // Route publique (hors /admin) volontairement : un chef d'équipe de terrain peut être un
    // simple citoyen (UTIL_SIMPLE), pas forcément un acteur institutionnel — contrairement au
    // reste de cette barre, cette rubrique reste visible/accessible même sans rôle effectif
    // institutionnel (voir isNavItemVisible). Permanente : usage quotidien d'un chef d'équipe.
    { icon: 'checklist', label: 'Mes interventions', route: '/mes-interventions', groupe: 'permanent' },

    { icon: 'apartment', label: 'Institutions', route: '/admin/institutions', groupe: 'administration' },

    { icon: 'local_fire_department', label: 'Crises', route: '/admin/crises', groupe: 'crise' },

    { icon: 'home_work', label: 'Centres', route: '/admin/centres', groupe: 'crise' },

    // Post-critique (demande utilisateur du 12/10) : le relogement des intervenants déborde
    // largement la phase aiguë d'une crise, c'est un suivi qui dure.
    { icon: 'night_shelter', label: 'Logement intervenants', route: '/admin/logement-intervenants', groupe: 'post-critique' },

    { icon: 'layers', label: 'Zones', route: '/admin/zones', groupe: 'preparation' },

    // Outil de planification préventive pour les mairies (demande explicite du 29/09) --
    // visibilité restreinte comme Zones, voir isNavItemVisible.
    { icon: 'water_drop', label: 'Simulation inondation', route: '/admin/simulation-inondation', groupe: 'preparation' },

    // Dispositif pré-enregistré (PCS) : équipes/points/zones préparés à l'avance, activables
    // en un geste sur une crise réelle — voir PlanViewSet.activer.
    { icon: 'fact_check', label: 'Mon plan de sauvegarde', route: '/admin/plans', groupe: 'preparation' },

    { icon: 'category', label: 'Compétences', route: '/admin/competences', groupe: 'preparation' },

    // Registre communal des personnes vulnérables (recensement PCS) -- visibilité restreinte à
    // la RCSC/au RESPONSABLE désigné d'une mairie, ou à une institution avec délégation de
    // compétence active, voir isNavItemVisible et acces_registre_vulnerables (calculé côté
    // serveur, core/vulnerabilites.py).
    { icon: 'accessible', label: 'Personnes vulnérables', route: '/admin/personnes-vulnerables', groupe: 'preparation' },

    // Administration (demande utilisateur du 12/10) : gestion du catalogue partagé, pas un
    // geste du jour J d'une crise précise.
    { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins', groupe: 'administration' },

    { icon: 'inventory_2', label: 'Matériel', route: '/admin/materiel', groupe: 'administration' },

    { icon: 'groups', label: 'Ressources mobilisées', route: '/admin/ressources-mobilisees', groupe: 'crise' },

    // Communications / Radio (demande utilisateur du 12/10) : gérer l'infra radio est le même
    // geste qu'on soit en préparation ou en pleine crise, d'où un cadre à part plutôt que
    // d'éclater companions/canaux entre les autres groupes. Les canaux ici (chat généraliste
    // public/privé) sont une communication HORS crise à proprement parler -- en crise, ce sont
    // les canaux d'ÉQUIPE qui servent, rattachés à chaque équipe, pas cette page généraliste.
    { icon: 'settings_input_antenna', label: 'Companions MeshCore (test)', route: '/admin/meshcore-companions', groupe: 'communications' },
    { icon: 'forum', label: 'Canaux MeshCore (test)', route: '/admin/meshcore-canaux', groupe: 'communications' },

    // Jamais ajouté au menu jusqu'ici (même défaut que MeshCore avant correction) : page
    // atteignable seulement en connaissant son URL exacte.
    { icon: 'settings_input_antenna', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions', groupe: 'communications' },
    { icon: 'forum', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux', groupe: 'communications' },

    // Boîtiers Raspberry Pi déployés sur site — voir le cadrage "Chantier B" (plan).
    { icon: 'router', label: 'Satellites', route: '/admin/satellites', groupe: 'communications' },

    { icon: 'visibility', label: 'Supervision PC Crise', route: '/admin/supervision-pc-crise', groupe: 'crise' },

    { icon: 'campaign', label: 'Demandes de mobilisation', route: '/admin/demandes-mobilisation', groupe: 'crise' },

    // Administration (demande utilisateur du 12/10) : suivi technique transversal, pas propre à
    // une crise précise.
    { icon: 'sync_problem', label: 'Conflits de synchronisation', route: '/admin/conflits-synchronisation', groupe: 'administration' },

    { icon: 'link', label: 'Correspondances', route: '/admin/correspondances', groupe: 'administration' },

    { icon: 'assignment', label: 'Affectations', route: '/admin/affectations', groupe: 'crise' },

    { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers', groupe: 'crise' },

    { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes', groupe: 'crise' },

    { icon: 'map', label: 'Carte', route: '/admin/carte', groupe: 'crise' },

    // Page stub ("results works!") -- gardée dans le menu malgré tout (le site est encore en
    // dev, demande utilisateur du 12/10), classée ici en pressentant un bilan post-crise.
    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats', groupe: 'post-critique' },

    { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs', groupe: 'administration' },

    // Grafana (demande utilisateur du 19/10) : administrateurs de la plateforme uniquement.
    { icon: 'monitor_heart', label: 'Monitoring', route: '/admin/monitoring', groupe: 'administration' },

    // Journaux du WAF et de fail2ban dans Grafana (demande utilisateur du 20/10), mêmes droits.
    { icon: 'shield', label: 'Supervision WAF', route: '/admin/supervision-waf', groupe: 'administration' },

    { icon: 'block', label: 'Fail2ban', route: '/admin/fail2ban', groupe: 'administration' },

    { icon: 'fact_check', label: 'Main courante', route: '/admin/main-courante', groupe: 'crise' },

    // Comptes Secours organisés en attente (auto-inscription bloquée jusqu'à décision d'un
    // admin ou de la mairie de leur territoire — voir accountValidationGuard) : réservé à ces
    // deux rôles, pas à tout institutionnel (un régulateur ou un autre Secours n'a rien à y
    // faire).
    { icon: 'how_to_reg', label: 'Validations de comptes', route: '/admin/validations-comptes', groupe: 'administration' },

    // Route publique (hors /admin) : un particulier atteint la carte/le formulaire de
    // rattachement par un lien direct, pas par ce menu (réservé au personnel institutionnel,
    // voir isNavItemVisible) -- les actions de gestion restent conditionnées côté backend
    // (Habitation.peut_gerer, HabitationViewSet).
    { icon: 'home_repair_service', label: 'Référencement des dégâts', route: '/referencement-degats', groupe: 'post-critique' },

];

  /** État replié/déplié de chaque cadre, par id -- juste une préférence d'affichage pour CE
   * visiteur (voir artifact-capabilities, même principe appliqué ici au localStorage du
   * navigateur), jamais rien à synchroniser côté serveur. "Crise en cours" déplié par défaut :
   * le plus consulté au quotidien. */
  groupesOuverts: Partial<Record<GroupeNavId, boolean>> = { crise: true };

  private static readonly CLE_STOCKAGE_GROUPES = 'admin-sidebar-groupes-ouverts';

  constructor(
    private authService: AuthService,
    private notificationService: NotificationService,
    private router: Router,
    public suiviPosition: SuiviPositionPermanentService,
  ) {
    try {
      const sauvegarde = localStorage.getItem(AdminLayoutComponent.CLE_STOCKAGE_GROUPES);
      if (sauvegarde) this.groupesOuverts = JSON.parse(sauvegarde);
    } catch {
      // localStorage indisponible (navigation privée, quota...) -- repli silencieux sur le
      // défaut ("Crise en cours" déplié), jamais bloquant pour l'affichage du menu.
    }
  }

  itemsDuGroupe(id: GroupeNavId): NavItem[] {
    return this.navItems.filter(item => item.groupe === id && this.isNavItemVisible(item));
  }

  get itemsPermanents(): NavItem[] {
    return this.itemsDuGroupe('permanent');
  }

  estGroupeOuvert(id: GroupeNavId): boolean {
    return !!this.groupesOuverts[id];
  }

  toggleGroupe(id: GroupeNavId): void {
    this.groupesOuverts = { ...this.groupesOuverts, [id]: !this.groupesOuverts[id] };
    try {
      localStorage.setItem(AdminLayoutComponent.CLE_STOCKAGE_GROUPES, JSON.stringify(this.groupesOuverts));
    } catch {
      // Pas grave : juste une préférence d'affichage non retenue d'une session à l'autre.
    }
  }

  /** Bascule le suivi de position permanent (voir SuiviPositionPermanentService) -- accord
   * navigateur demandé une seule fois, à la première activation. */
  basculerSuiviPosition(): void {
    if (this.suiviPosition.actif) {
      this.suiviPosition.desactiver();
    } else {
      this.suiviPosition.activer();
    }
  }

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.checkScreenSize();
    demanderPermissionNotificationNavigateur();
    this.demarrerPollingNotifications();
    // Rafraîchit le profil depuis l'API : sans ça, un accès démo (ou tout autre changement de
    // droits) accordé après la connexion resterait invisible tant que l'utilisateur ne se
    // reconnecte pas, puisque `getCurrentUser()` ne fait que relire le cache local du login.
    this.authService.fetchMe().subscribe({
      next: (user) => this.currentUser = user,
      error: () => {},
    });
  }

  ngOnDestroy(): void {
    this.pollingNotificationsSub?.unsubscribe();
  }

  /** Remplace l'ancien chargement "une fois au montage, jamais rafraîchi" — la cloche restait
   * périmée jusqu'au prochain rechargement complet de page, ce qui pouvait laisser un régulateur
   * sans nouvelle information pendant toute la durée de sa session. Poll léger (resume : juste
   * compteur + date) toutes les 20s, suspendu en arrière-plan (voir pollWhileVisible) ; la liste
   * complète n'est redemandée que si ce résumé a effectivement changé. */
  private demarrerPollingNotifications(): void {
    this.pollingNotificationsSub = pollWhileVisible(
      () => this.notificationService.resume(), INTERVALLE_POLLING_NOTIFICATIONS_MS,
    ).subscribe({
      next: (resume) => {
        const changement = !this.dernierResume
          || resume.count_non_lues !== this.dernierResume.count_non_lues
          || resume.derniere_notification_le !== this.dernierResume.derniere_notification_le;
        const nouvellesNotifications = !!this.dernierResume && resume.count_non_lues > this.dernierResume.count_non_lues;
        this.dernierResume = resume;
        if (changement) {
          this.loadNotifications(nouvellesNotifications && typeof document !== 'undefined' && document.hidden);
        }
      },
      error: () => {},
    });
  }

  get isDemo(): boolean {
    return this.authService.getEnvironment() === 'DEMO';
  }

  get canAccessDemo(): boolean {
    return this.authService.canAccessDemo();
  }

  toggleEnvironment(): void {
    this.authService.setEnvironment(this.isDemo ? 'PROD' : 'DEMO');
  }

  /** `notifierSiArrierePlan` : true uniquement quand le résumé polling vient de détecter au
   * moins une notification en plus ET que l'onglet n'est pas au premier plan — inutile de
   * doubler d'une popup navigateur une cloche que l'utilisateur regarde déjà. */
  private loadNotifications(notifierSiArrierePlan = false): void {
    this.notificationService.getAll().subscribe({
      next: (list) => {
        if (notifierSiArrierePlan) {
          const anciensIds = new Set(this.notifications.map(n => n.id));
          for (const n of list) {
            if (!n.lu && !anciensIds.has(n.id)) {
              afficherNotificationNavigateur(n.titre, { body: n.message });
            }
          }
        }
        this.notifications = list;
      },
      error: () => {},
    });
  }

  onNotificationClick(notification: AppNotification): void {
    this.showNotifications = false;
    // Une notification liée à une crise (ex: déclaration acteur en attente de validation) mène
    // directement à cette crise (?id=, déjà géré par CrisesComponent) plutôt que de se
    // contenter d'informer.
    if (notification.crise) {
      this.router.navigate(['/admin/crises'], { queryParams: { id: notification.crise } });
    }
    if (notification.lu) return;
    this.notificationService.markAsRead(notification.id).subscribe({
      next: (updated) => {
        const idx = this.notifications.findIndex(n => n.id === updated.id);
        if (idx !== -1) this.notifications[idx] = updated;
      },
    });
  }

  notificationTime(dateStr: string): string {
    const diffMs = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(diffMs / 60000);
    if (minutes < 1) return "à l'instant";
    if (minutes < 60) return `il y a ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `il y a ${hours} h`;
    const days = Math.floor(hours / 24);
    return `il y a ${days} j`;
  }

  @HostListener('window:resize')
  onResize(): void {
    this.checkScreenSize();
  }

  private checkScreenSize(): void {
    this.isMobile = window.innerWidth <= 768;
    
    // Sur mobile, fermer les menus
    if (this.isMobile) {
      this.sidebarOpen = false;
      this.sidebarCollapsed = false;
    } else {
      // Sur desktop, la sidebar est visible
      this.sidebarOpen = false;
    }
  }

  isSysAdmin(): boolean {
    return this.authService.isSysAdmin();
  }

  /** Rôle EFFECTIF (voir AuthService.getEffectiveRole) : contrairement à isSysAdmin (toujours
   * basé sur le rôle PROD réel), détermine ce qui a une chance de charger MAINTENANT — masque
   * de la barre latérale toute rubrique qu'un compte démo-only avec un rôle démo non
   * institutionnel ne pourrait de toute façon pas utiliser (voir institutionalEffectiveGuard,
   * qui protège aussi ces routes côté navigation directe). */
  get isInstitutionalEffective(): boolean {
    return this.authService.isInstitutionalEffective();
  }

  /** Utilisateurs : réservé aux vrais admins PROD (isSysAdmin). Mes interventions : toujours
   * visible (route publique pour un chef d'équipe possiblement non institutionnel, voir
   * navItems). Tout le reste : masqué si le rôle effectif courant n'est pas institutionnel. */
  isNavItemVisible(item: NavItem): boolean {
    if (item.label === 'Utilisateurs' || item.label === 'Main courante' || item.label === 'Monitoring'
        || item.label === 'Supervision WAF' || item.label === 'Fail2ban') return this.isSysAdmin();
    if (item.label === 'Mes interventions') return true;
    if (item.label === 'Validations de comptes') {
      const role = this.authService.getEffectiveRole();
      return role === UserRole.ADMIN || role === UserRole.LOCAL_AUTH;
    }
    // Zones = découpage PCS/PICS, réservé aux mairies/EPCI (voir zonesGuard, qui protège
    // aussi l'accès direct par URL) — inutile de montrer une entrée qui mènerait à un refus.
    if (item.label === 'Zones' || item.label === 'Simulation inondation') return this.authService.isAutoriteLocaleCommunale();
    // Registre des personnes vulnérables : contrairement à Zones (dérivable du type
    // d'institution côté client), la règle RCSC/RESPONSABLE dépend de l'appartenance à une
    // Team précise -- piloté par le champ calculé côté serveur, jamais recalculé ici (voir
    // vulnerabilitesGuard, qui protège aussi l'accès direct par URL).
    if (item.label === 'Personnes vulnérables') return !!this.authService.getCurrentUser()?.acces_registre_vulnerables;
    return this.isInstitutionalEffective;
  }

  toggleSidebar(): void {
    if (this.isMobile) {
      // Sur mobile, toggle open/close
      this.sidebarOpen = !this.sidebarOpen;
    } else {
      // Sur desktop, toggle collapsed
      this.sidebarCollapsed = !this.sidebarCollapsed;
    }
  }

  closeSidebar(): void {
    if (this.isMobile) {
      this.sidebarOpen = false;
    }
  }

  toggleNotifications(): void {
    this.showNotifications = !this.showNotifications;
    this.showUserMenu = false;
    
    // Fermer la sidebar mobile si ouverte
    if (this.isMobile) {
      this.sidebarOpen = false;
    }
  }

  toggleUserMenu(): void {
    this.showUserMenu = !this.showUserMenu;
    this.showNotifications = false;
    
    // Fermer la sidebar mobile si ouverte
    if (this.isMobile) {
      this.sidebarOpen = false;
    }
  }

  closeAllMenus(): void {
    this.showNotifications = false;
    this.showUserMenu = false;
    if (this.isMobile) {
      this.sidebarOpen = false;
    }
  }

  goToSettings(): void {
    this.router.navigate(['/settings']);
    this.closeAllMenus();
  }

  goToHome(): void {
    this.router.navigate(['/accueil']);
    this.closeAllMenus();
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
    this.closeAllMenus();
  }

  onNavItemClick(): void {
    // Fermer la sidebar sur mobile après navigation
    if (this.isMobile) {
      this.closeSidebar();
    }
  }

  get companyName(): string {
    return this.currentUser?.type !== UserRole.SIMPLE_USER
      ? this.currentUser!.last_name 
      : 'Admin';
  }

  get notificationCount(): number {
    return this.notifications.filter(n => !n.lu).length;
  }
}
