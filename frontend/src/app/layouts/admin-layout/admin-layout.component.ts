import { Component, HostListener, OnInit, ViewChild } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { User } from '../../shared/models/user.model';
import { AdminHeaderComponent } from './admin-header/admin-header.component';
import { AdminSidebarComponent } from './admin-sidebar/admin-sidebar.component';

/** Coquille de l'administration : grille, affichage mobile, fonds semi-transparents et
 * <router-outlet>. En-tête, menu et cloche sont des composants enfants ; les entrées du menu
 * sont dans admin-nav.config.ts (DOCUMENTATION.md, § 6.4). */
@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [RouterOutlet, AdminHeaderComponent, AdminSidebarComponent],
  templateUrl: './admin-layout.component.html',
  styleUrls: ['./admin-layout.component.scss']
})
export class AdminLayoutComponent implements OnInit {
  @ViewChild(AdminHeaderComponent) private header?: AdminHeaderComponent;

  currentUser: User | null = null;
  sidebarCollapsed = false;
  sidebarOpen = false; // mobile
  isMobile = false;
  /** Une liste déroulante de l'en-tête est ouverte : affiche le fond qui la ferme. */
  menusOuverts = false;

  constructor(
    private authService: AuthService,
    private router: Router,
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

  /** Sur mobile, toute action sur les listes de l'en-tête ferme le menu latéral. */
  onMenusOuverts(ouverts: boolean): void {
    this.menusOuverts = ouverts;
    this.closeSidebar();
  }

  closeAllMenus(): void {
    this.header?.fermerMenus();
    this.closeSidebar();
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
    this.closeAllMenus();
  }

  onNavItemClick(): void {
    this.closeSidebar();
  }
}
