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

    { icon: 'groups', label: 'Équipes', route: '/admin/equipes' },

    { icon: 'apartment', label: 'Institutions', route: '/admin/institutions' },

    { icon: 'local_fire_department', label: 'Crises', route: '/admin/crises' },

    { icon: 'home_work', label: 'Centres', route: '/admin/centres' },

    { icon: 'category', label: 'Compétences', route: '/admin/competences' },

    { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins' },

    { icon: 'link', label: 'Correspondances', route: '/admin/correspondances' },

    { icon: 'assignment', label: 'Affectations', route: '/admin/affectations' },

    { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers' },

    { icon: 'search', label: 'Recherches de personnes', route: '/admin/recherches-personnes'},

    { icon: 'map', label: 'Carte', route: '/admin/carte' },

    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats' },

    { icon: 'group', label: 'Utilisateurs', route: '/admin/utilisateurs' }

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
