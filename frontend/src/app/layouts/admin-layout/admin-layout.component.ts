import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { AuthService } from '../../auth/services/auth.service';
import { NotificationService } from '../../services/notification.service';
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

interface NavItem {
  icon: string;
  label: string;
  route: string;
  active?: boolean;
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

  navItems: NavItem[] = [
    { icon: 'home', label: 'Accueil', route: '/admin/dashboard' },

    { icon: 'flag', label: 'Signalements', route: '/admin/signalements' },

    // Vue filtrée sur la commune de l'institution de l'utilisateur (typiquement une mairie) —
    // existait déjà côté route/composant/backend mais n'apparaissait dans AUCUN menu (seul
    // AdminSidebarComponent la référençait, un composant orphelin jamais instancié nulle part) :
    // la page était donc inatteignable sans connaître son URL exacte.
    { icon: 'location_city', label: 'Vue Ma Collectivité', route: '/admin/vue-mairie' },

    { icon: 'groups', label: 'Équipes', route: '/admin/equipes' },

    // Absente du menu jusqu'ici (page atteignable seulement en connaissant son URL exacte,
    // même défaut que 'Vue Ma Collectivité' ci-dessus) — c'est pourtant ici qu'on démarre/
    // clôture une mission (Team.mission_active), condition du suivi de position MeshCore.
    { icon: 'flag_circle', label: 'Missions', route: '/admin/missions' },

    // Route publique (hors /admin) volontairement : un chef d'équipe de terrain peut être un
    // simple citoyen (UTIL_SIMPLE), pas forcément un acteur institutionnel — contrairement au
    // reste de cette barre, cette rubrique reste visible/accessible même sans rôle effectif
    // institutionnel (voir isNavItemVisible).
    { icon: 'checklist', label: 'Mes interventions', route: '/mes-interventions' },

    { icon: 'apartment', label: 'Institutions', route: '/admin/institutions' },

    { icon: 'local_fire_department', label: 'Crises', route: '/admin/crises' },

    { icon: 'home_work', label: 'Centres', route: '/admin/centres' },

    { icon: 'layers', label: 'Zones', route: '/admin/zones' },

    // Dispositif pré-enregistré (PCS) : équipes/points/zones préparés à l'avance, activables
    // en un geste sur une crise réelle — voir PlanViewSet.activer.
    { icon: 'fact_check', label: 'Plans', route: '/admin/plans' },

    { icon: 'category', label: 'Compétences', route: '/admin/competences' },

    { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins' },

    { icon: 'inventory_2', label: 'Matériel', route: '/admin/materiel' },

    { icon: 'groups', label: 'Ressources mobilisées', route: '/admin/ressources-mobilisees' },

    { icon: 'settings_input_antenna', label: 'Companions MeshCore (test)', route: '/admin/meshcore-companions' },
    { icon: 'forum', label: 'Canaux MeshCore (test)', route: '/admin/meshcore-canaux' },

    // Jamais ajouté au menu jusqu'ici (même défaut que MeshCore avant correction) : page
    // atteignable seulement en connaissant son URL exacte.
    { icon: 'settings_input_antenna', label: 'Companions Meshtastic (test)', route: '/admin/meshtastic-companions' },
    { icon: 'forum', label: 'Canaux Meshtastic (test)', route: '/admin/meshtastic-canaux' },

    // Boîtiers Raspberry Pi déployés sur site — voir le cadrage "Chantier B" (plan).
    { icon: 'router', label: 'Satellites', route: '/admin/satellites' },
    { icon: 'visibility', label: 'Supervision PC Crise', route: '/admin/supervision-pc-crise' },

    { icon: 'campaign', label: 'Demandes de mobilisation', route: '/admin/demandes-mobilisation' },
    { icon: 'sync_problem', label: 'Conflits de synchronisation', route: '/admin/conflits-synchronisation' },

    { icon: 'link', label: 'Correspondances', route: '/admin/correspondances' },

    { icon: 'assignment', label: 'Affectations', route: '/admin/affectations' },

    { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers' },

    { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes'},

    { icon: 'map', label: 'Carte', route: '/admin/carte' },

    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats' },

    { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs' },

    { icon: 'fact_check', label: 'Main courante', route: '/admin/main-courante' },

    // Comptes Secours organisés en attente (auto-inscription bloquée jusqu'à décision d'un
    // admin ou de la mairie de leur territoire — voir accountValidationGuard) : réservé à ces
    // deux rôles, pas à tout institutionnel (un régulateur ou un autre Secours n'a rien à y
    // faire).
    { icon: 'how_to_reg', label: 'Validations de comptes', route: '/admin/validations-comptes' },

];




  constructor(
    private authService: AuthService,
    private notificationService: NotificationService,
    private router: Router
  ) {}

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
    if (item.label === 'Utilisateurs' || item.label === 'Main courante') return this.isSysAdmin();
    if (item.label === 'Mes interventions') return true;
    if (item.label === 'Validations de comptes') {
      const role = this.authService.getEffectiveRole();
      return role === UserRole.ADMIN || role === UserRole.LOCAL_AUTH;
    }
    // Zones = découpage PCS/PICS, réservé aux mairies/EPCI (voir zonesGuard, qui protège
    // aussi l'accès direct par URL) — inutile de montrer une entrée qui mènerait à un refus.
    if (item.label === 'Zones') return this.authService.isAutoriteLocaleCommunale();
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
