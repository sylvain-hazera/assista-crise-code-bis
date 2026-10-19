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

// Polling de la cloche, suspendu quand l'onglet est en arrière-plan (pollWhileVisible).
const INTERVALLE_POLLING_NOTIFICATIONS_MS = 20_000;

/** `permanent` : toujours visible en haut. Les autres valeurs sont les cadres repliables, groupés
 * par moment d'usage dans le cycle d'une crise (voir DOCUMENTATION.md, § 6.4). */
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
  // null avant le premier résumé : pas de notification navigateur au premier chargement.
  private dernierResume: ResumeNotifications | null = null;

  /** Ordre d'affichage des cadres repliables. */
  readonly groupesNav: { id: GroupeNavId; label: string; icon: string }[] = [
    { id: 'crise', label: 'Crise en cours', icon: 'emergency' },
    { id: 'post-critique', label: 'Post-critique — gestion à long terme', icon: 'history' },
    { id: 'preparation', label: 'Préparation', icon: 'event_available' },
    { id: 'communications', label: 'Communications / Radio', icon: 'settings_input_antenna' },
    { id: 'administration', label: 'Administration', icon: 'admin_panel_settings' },
  ];

  navItems: NavItem[] = [
    { icon: 'home', label: 'Accueil', route: '/admin/dashboard', groupe: 'permanent' },

    // Page à 3 panneaux pensée comme l'outil quotidien d'une cellule de crise.
    { icon: 'dashboard_customize', label: 'Cellule de crise', route: '/admin/cellule-crise', groupe: 'permanent' },

    { icon: 'flag', label: 'Signalements', route: '/admin/signalements', groupe: 'crise' },

    { icon: 'verified_user', label: 'Sécurité', route: '/admin/declarations-securite', groupe: 'crise' },

    // Vue filtrée sur la commune de l'institution (typiquement une mairie), hors crise.
    { icon: 'location_city', label: 'Vue Ma Collectivité', route: '/admin/vue-mairie', groupe: 'permanent' },

    // Roster réutilisable, préparé à l'avance.
    { icon: 'groups', label: 'Équipes', route: '/admin/equipes', groupe: 'preparation' },

    // Démarrer/clôturer une mission (Team.mission_active), condition du suivi de position MeshCore.
    { icon: 'flag_circle', label: 'Missions', route: '/admin/missions', groupe: 'crise' },

    // Route publique : un chef d'équipe peut être un simple citoyen (voir isNavItemVisible).
    { icon: 'checklist', label: 'Mes interventions', route: '/mes-interventions', groupe: 'permanent' },

    { icon: 'apartment', label: 'Institutions', route: '/admin/institutions', groupe: 'administration' },

    { icon: 'local_fire_department', label: 'Crises', route: '/admin/crises', groupe: 'crise' },

    { icon: 'home_work', label: 'Centres', route: '/admin/centres', groupe: 'crise' },

    // Le relogement des intervenants dure au-delà de la phase aiguë.
    { icon: 'night_shelter', label: 'Logement intervenants', route: '/admin/logement-intervenants', groupe: 'post-critique' },

    { icon: 'layers', label: 'Zones', route: '/admin/zones', groupe: 'preparation' },

    // Planification préventive pour les mairies ; visibilité restreinte comme Zones.
    { icon: 'water_drop', label: 'Simulation inondation', route: '/admin/simulation-inondation', groupe: 'preparation' },

    // Dispositif PCS préparé à l'avance, activable sur une crise (PlanViewSet.activer).
    { icon: 'fact_check', label: 'Mon plan de sauvegarde', route: '/admin/plans', groupe: 'preparation' },

    { icon: 'category', label: 'Compétences', route: '/admin/competences', groupe: 'preparation' },

    // Registre des personnes vulnérables : RCSC/RESPONSABLE d'une mairie ou délégation active
    // (acces_registre_vulnerables, core/vulnerabilites.py).
    { icon: 'accessible', label: 'Personnes vulnérables', route: '/admin/personnes-vulnerables', groupe: 'preparation' },

    { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins', groupe: 'administration' },

    { icon: 'inventory_2', label: 'Matériel', route: '/admin/materiel', groupe: 'administration' },

    { icon: 'groups', label: 'Ressources mobilisées', route: '/admin/ressources-mobilisees', groupe: 'crise' },

    // Communications / Radio : seul cadre transversal. Ces canaux sont généralistes ; en crise,
    // ce sont les canaux d'équipe qui servent.
    { icon: 'settings_input_antenna', label: 'Companions MeshCore (test)', route: '/admin/meshcore-companions', groupe: 'communications' },
    { icon: 'forum', label: 'Canaux MeshCore (test)', route: '/admin/meshcore-canaux', groupe: 'communications' },

    { icon: 'settings_input_antenna', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions', groupe: 'communications' },
    { icon: 'forum', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux', groupe: 'communications' },

    // Boîtiers Raspberry Pi déployés sur site (voir satellite/README.md).
    { icon: 'router', label: 'Satellites', route: '/admin/satellites', groupe: 'communications' },

    { icon: 'visibility', label: 'Supervision PC Crise', route: '/admin/supervision-pc-crise', groupe: 'crise' },

    { icon: 'campaign', label: 'Demandes de mobilisation', route: '/admin/demandes-mobilisation', groupe: 'crise' },

    { icon: 'sync_problem', label: 'Conflits de synchronisation', route: '/admin/conflits-synchronisation', groupe: 'administration' },

    { icon: 'link', label: 'Correspondances', route: '/admin/correspondances', groupe: 'administration' },

    { icon: 'assignment', label: 'Affectations', route: '/admin/affectations', groupe: 'crise' },

    { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers', groupe: 'crise' },

    { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes', groupe: 'crise' },

    { icon: 'map', label: 'Carte', route: '/admin/carte', groupe: 'crise' },

    // Page encore vide, gardée dans le menu.
    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats', groupe: 'post-critique' },

    { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs', groupe: 'administration' },

    { icon: 'fact_check', label: 'Main courante', route: '/admin/main-courante', groupe: 'crise' },

    // Comptes Secours en attente de validation : admin ou mairie du territoire seulement
    // (voir accountValidationGuard).
    { icon: 'how_to_reg', label: 'Validations de comptes', route: '/admin/validations-comptes', groupe: 'administration' },

    // Route publique ; les actions de gestion sont contrôlées côté backend (Habitation.peut_gerer).
    { icon: 'home_repair_service', label: 'Référencement des dégâts', route: '/referencement-degats', groupe: 'post-critique' },

];

  /** État replié/déplié par cadre, préférence locale (localStorage). « Crise en cours » déplié par défaut. */
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
      // localStorage indisponible : repli silencieux sur le défaut.
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
    }
  }

  /** Bascule le suivi de position permanent ; l'accord navigateur n'est demandé qu'une fois. */
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
    // Rafraîchit le profil : getCurrentUser() ne relit que le cache, un droit accordé après la
    // connexion resterait sinon invisible.
    this.authService.fetchMe().subscribe({
      next: (user) => this.currentUser = user,
      error: () => {},
    });
  }

  ngOnDestroy(): void {
    this.pollingNotificationsSub?.unsubscribe();
  }

  /** Poll léger du résumé (compteur + date) toutes les 20 s, suspendu en arrière-plan ; la liste
   * complète n'est rechargée que si le résumé change. */
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

  /** Notification navigateur seulement s'il y a du nouveau et que l'onglet n'est pas au premier plan. */
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
    // Une notification liée à une crise ouvre cette crise (?id=).
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

  /** Rôle effectif (AuthService.getEffectiveRole) : masque ce qui ne pourrait pas charger.
   * institutionalEffectiveGuard protège aussi les routes. */
  get isInstitutionalEffective(): boolean {
    return this.authService.isInstitutionalEffective();
  }

  /** Utilisateurs : admins PROD réels. Mes interventions : toujours visible. Le reste : rôle
   * effectif institutionnel requis. */
  isNavItemVisible(item: NavItem): boolean {
    if (item.label === 'Utilisateurs' || item.label === 'Main courante') return this.isSysAdmin();
    if (item.label === 'Mes interventions') return true;
    if (item.label === 'Validations de comptes') {
      const role = this.authService.getEffectiveRole();
      return role === UserRole.ADMIN || role === UserRole.LOCAL_AUTH;
    }
    // Zones : mairies/EPCI seulement (zonesGuard protège aussi l'URL).
    if (item.label === 'Zones' || item.label === 'Simulation inondation') return this.authService.isAutoriteLocaleCommunale();
    // Registre : champ calculé côté serveur, jamais recalculé ici (vulnerabilitesGuard protège l'URL).
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
