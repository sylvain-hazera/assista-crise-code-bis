import { Component, HostListener, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../auth/services/auth.service';
import { NotificationService } from '../../services/notification.service';
import { User, UserRole } from '../../shared/models/user.model';
import { AppNotification } from '../../shared/models/notification.model';

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
export class AdminLayoutComponent implements OnInit {
  currentUser: User | null = null;
  sidebarCollapsed = false;
  sidebarOpen = false; // Pour mobile
  showNotifications = false;
  showUserMenu = false;
  isMobile = false;
  
  notifications: AppNotification[] = [];

  navItems: NavItem[] = [
    { icon: 'home', label: 'Accueil', route: '/admin/dashboard' },

    { icon: 'flag', label: 'Signalements', route: '/admin/signalements' },

    // Vue filtrée sur la commune de l'institution de l'utilisateur (typiquement une mairie) —
    // existait déjà côté route/composant/backend mais n'apparaissait dans AUCUN menu (seul
    // AdminSidebarComponent la référençait, un composant orphelin jamais instancié nulle part) :
    // la page était donc inatteignable sans connaître son URL exacte.
    { icon: 'location_city', label: 'Vue Mairie', route: '/admin/vue-mairie' },

    { icon: 'groups', label: 'Équipes', route: '/admin/equipes' },

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

    { icon: 'link', label: 'Correspondances', route: '/admin/correspondances' },

    { icon: 'assignment', label: 'Affectations', route: '/admin/affectations' },

    { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers' },

    { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes'},

    { icon: 'map', label: 'Carte', route: '/admin/carte' },

    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats' },

    { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs' },

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
    this.loadNotifications();
    // Rafraîchit le profil depuis l'API : sans ça, un accès démo (ou tout autre changement de
    // droits) accordé après la connexion resterait invisible tant que l'utilisateur ne se
    // reconnecte pas, puisque `getCurrentUser()` ne fait que relire le cache local du login.
    this.authService.fetchMe().subscribe({
      next: (user) => this.currentUser = user,
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

  private loadNotifications(): void {
    this.notificationService.getAll().subscribe({
      next: (list) => this.notifications = list,
      error: () => {},
    });
  }

  onNotificationClick(notification: AppNotification): void {
    this.showNotifications = false;
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
    if (item.label === 'Utilisateurs') return this.isSysAdmin();
    if (item.label === 'Mes interventions') return true;
    if (item.label === 'Validations de comptes') {
      const role = this.authService.getEffectiveRole();
      return role === UserRole.ADMIN || role === UserRole.LOCAL_AUTH;
    }
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
