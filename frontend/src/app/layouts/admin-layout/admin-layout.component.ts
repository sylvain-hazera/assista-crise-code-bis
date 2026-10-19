import { Component, HostListener, OnInit } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../auth/services/auth.service';
import { SuiviPositionPermanentService } from '../../services/suivi-position-permanent.service';
import { User, UserRole } from '../../shared/models/user.model';
import { AdminSidebarComponent } from './admin-sidebar/admin-sidebar.component';
import { AdminNotificationsComponent } from './admin-notifications/admin-notifications.component';

/** Coquille de l'administration : grille, en-tête (bascule PROD/DEMO, suivi de position, menu
 * utilisateur), affichage mobile et <router-outlet>. Le menu et la cloche sont des composants
 * enfants ; les entrées du menu sont dans admin-nav.config.ts (DOCUMENTATION.md, § 6.4). */
@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [CommonModule, RouterOutlet, AdminSidebarComponent, AdminNotificationsComponent],
  templateUrl: './admin-layout.component.html',
  styleUrls: ['./admin-layout.component.scss']
})
export class AdminLayoutComponent implements OnInit {
  currentUser: User | null = null;
  sidebarCollapsed = false;
  sidebarOpen = false; // mobile
  showNotifications = false;
  showUserMenu = false;
  isMobile = false;

  constructor(
    private authService: AuthService,
    private router: Router,
    public suiviPosition: SuiviPositionPermanentService,
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.checkScreenSize();
    // Rafraîchit le profil : getCurrentUser() ne relit que le cache, un droit accordé après la
    // connexion resterait sinon invisible.
    this.authService.fetchMe().subscribe({
      next: (user) => this.currentUser = user,
      error: () => {},
    });
  }

  /** Bascule le suivi de position permanent ; l'accord navigateur n'est demandé qu'une fois. */
  basculerSuiviPosition(): void {
    if (this.suiviPosition.actif) {
      this.suiviPosition.desactiver();
    } else {
      this.suiviPosition.activer();
    }
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

  @HostListener('window:resize')
  onResize(): void {
    this.checkScreenSize();
  }

  private checkScreenSize(): void {
    this.isMobile = window.innerWidth <= 768;
    this.sidebarOpen = false;
    if (this.isMobile) {
      this.sidebarCollapsed = false;
    }
  }

  /** Desktop : réduit/étend le menu. Mobile : l'ouvre/le ferme. */
  toggleSidebar(): void {
    if (this.isMobile) {
      this.sidebarOpen = !this.sidebarOpen;
    } else {
      this.sidebarCollapsed = !this.sidebarCollapsed;
    }
  }

  closeSidebar(): void {
    if (this.isMobile) {
      this.sidebarOpen = false;
    }
  }

  /** Une seule liste déroulante ouverte à la fois ; sur mobile, ouvrir ferme le menu. */
  onNotificationsToggle(ouvert: boolean): void {
    this.showNotifications = ouvert;
    if (ouvert) {
      this.showUserMenu = false;
      this.closeSidebar();
    }
  }

  toggleUserMenu(): void {
    this.showUserMenu = !this.showUserMenu;
    this.showNotifications = false;
    this.closeSidebar();
  }

  closeAllMenus(): void {
    this.showNotifications = false;
    this.showUserMenu = false;
    this.closeSidebar();
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
    this.closeSidebar();
  }

  get companyName(): string {
    // currentUser peut être null le temps que le profil arrive.
    return this.currentUser && this.currentUser.type !== UserRole.SIMPLE_USER
      ? this.currentUser.last_name
      : 'Admin';
  }
}
