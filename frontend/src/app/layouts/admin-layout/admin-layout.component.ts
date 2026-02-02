import { Component, HostListener, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AdminHeaderComponent } from "../../shared/components/admin/admin-header/admin-header.component";
import { AdminSidebarComponent } from "../../shared/components/admin/admin-sidebar/admin-sidebar.component";
import { AuthService } from '../../auth/services/auth.service';
import { User, UserRole } from '../../shared/models/user.model';

// @Component({
//   selector: 'app-admin-layout',
//   standalone: true,
//   imports: [RouterOutlet, AdminHeaderComponent, AdminSidebarComponent],
//   templateUrl: './admin-layout.component.html',
//   styleUrls: ['./admin-layout.component.scss']
// })

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


// export class AdminLayoutComponent implements OnInit {
//   sidebarCollapsed = false;
//   isMobile = false;

//   ngOnInit(): void {
//     this.checkScreenSize();
//   }

//   @HostListener('window:resize')
//   onResize(): void {
//     this.checkScreenSize();
//   }

//   private checkScreenSize(): void {
//     this.isMobile = window.innerWidth <= 768;
//     // Sur mobile, la sidebar est fermée par défaut
//     if (this.isMobile) {
//       this.sidebarCollapsed = true;
//     } else {
//       // Sur desktop, la sidebar est ouverte par défaut
//       this.sidebarCollapsed = false;
//     }
//   }


//   onSidebarToggle(collapsed: boolean): void {
//     this.sidebarCollapsed = collapsed;
//   }
// }

export class AdminLayoutComponent implements OnInit {
  currentUser: User | null = null;
  sidebarCollapsed = false;
  showNotifications = false;
  showUserMenu = false;

  notificationCount = 2;

  // Mock notifications - à remplacer par un service
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
    { icon: 'group', label: 'utilisateurs', route: '/admin/utilisateurs' }
  ];
// UserRole: UserRole;

  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
  }

  isAdmin(): boolean {
    return this.currentUser?.userType !== UserRole.Individual;
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
  }

  get companyName(): string {
    return this.currentUser?.userType === 'organization' 
      ? this.currentUser.lastName 
      : 'Nom de la compagnie';
  }
}