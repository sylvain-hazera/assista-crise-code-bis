import { Component, HostListener, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../auth/services/auth.service';
import { Utilisateur, RoleUtilisateur } from '../../shared/models/user.model';

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
  currentUser: Utilisateur | null = null;
  sidebarCollapsed = false;
  sidebarOpen = false; // Pour mobile
  showNotifications = false;
  showUserMenu = false;
  isMobile = false;
  
  notifications = [
    {
      icon: 'warning',
      title: 'Nouvelle crise signalée',
      time: 'Il y a 5 minutes',
      type: 'warning'
    },
    {
      icon: 'info',
      title: 'Mise à jour du système',
      time: 'Il y a 1 heure',
      type: 'info'
    }
  ];

  navItems: NavItem[] = [
    { icon: 'home', label: 'Accueil', route: '/admin/dashboard' },
    { icon: 'flag', label: 'Signalements', route: '/admin/signalements' },
    { icon: 'groups', label: 'Equipes', route: '/admin/equipes' },
    { icon: 'map', label: 'Carte', route: '/admin/carte' },
    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats' },
    { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs' }
  ];

  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.checkScreenSize();
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
    this.router.navigate(['/user/settings']);
    this.closeAllMenus();
  }

  goToHome(): void {
    this.router.navigate(['/accueil']);
    this.closeAllMenus();
  }

  logout(): void {
    this.authService.logout();
  }

  onNavItemClick(): void {
    // Fermer la sidebar sur mobile après navigation
    if (this.isMobile) {
      this.closeSidebar();
    }
  }

  get companyName(): string {
    return this.currentUser?.type !== RoleUtilisateur.UTIL_SIMPLE
      ? this.currentUser!.last_name 
      : 'Admin';
  }

  get notificationCount(): number {
    return this.notifications.length;
  }
}