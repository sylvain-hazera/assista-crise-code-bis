import { Component, OnInit } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive, Router } from '@angular/router';
import { AuthService, User } from '../../auth/auth.service';
// import { AuthMockService, User } from '../../shared/services/auth-mock.service';

interface NavItem {
  icon: string;
  label: string;
  route: string;
  active?: boolean;
}

@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './admin-layout.component.html',
  styleUrls: ['./admin-layout.component.scss']
})
export class AdminLayoutComponent implements OnInit {
  currentUser: User | null = null;
  sidebarCollapsed = false;
  showNotifications = false;
  showUserMenu = false;

  navItems: NavItem[] = [
    { icon: 'home', label: 'Accueil', route: '/admin/dashboard' },
    { icon: 'flag', label: 'Signalements', route: '/admin/signalements' },
    { icon: 'groups', label: 'Equipes', route: '/admin/equipes' },
    { icon: 'map', label: 'Carte', route: '/admin/carte' },
    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats' }
  ];

  constructor(
    // private authService: AuthMockService,
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
  }

  toggleSidebar(): void {
    this.sidebarCollapsed = !this.sidebarCollapsed;
  }

  toggleNotifications(): void {
    this.showNotifications = !this.showNotifications;
    this.showUserMenu = false;
  }

  toggleUserMenu(): void {
    this.showUserMenu = !this.showUserMenu;
    this.showNotifications = false;
  }

  goToSettings(): void {
    this.router.navigate(['/settings']);
    this.showUserMenu = false;
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
  }

  get companyName(): string {
    return this.currentUser?.userType === 'organization' 
      ? this.currentUser.lastName 
      : 'Nom de la compagnie';
  }
}