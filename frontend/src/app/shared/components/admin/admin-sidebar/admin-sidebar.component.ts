import { Component, Input, Output, EventEmitter } from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../../../auth/services/auth.service';

interface NavItem {
  icon: string;
  label: string;
  route: string;
}

@Component({
  selector: 'app-admin-sidebar',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './admin-sidebar.component.html',
  styleUrl: './admin-sidebar.component.scss'
})
export class AdminSidebarComponent {
  @Input() collapsed = false;
  @Output() sidebarToggled = new EventEmitter<boolean>();

  navItems: NavItem[] = [
    { icon: 'dashboard', label: 'Tableau de bord', route: '/admin/dashboard' },
    { icon: 'flag', label: 'Signalements', route: '/admin/signalements' },
    { icon: 'groups', label: 'Équipes', route: '/admin/equipes' },
    { icon: 'apartment', label: 'Institutions', route: '/admin/institutions' },
    { icon: 'map', label: 'Carte', route: '/admin/carte' },
    { icon: 'category', label: 'Compétences', route: '/admin/competences' },
    { icon: 'playlist_add_check', label: 'Besoins', route: '/admin/besoins' },
    { icon: 'link', label: 'Correspondances', route: '/admin/correspondances' },
    { icon: 'check_circle', label: 'Résultats', route: '/admin/resultats' },
    { icon: 'folder', label: 'Dossiers', route: '/admin/dossiers' },
    { icon: 'flag_circle', label: 'Missions', route: '/admin/missions' },
    { icon: 'apartment', label: 'Vue Mairie', route: '/admin/vue-mairie' },
    { icon: 'assignment', label: 'Affectations', route: '/admin/affectations'}
];

  constructor(
    private router: Router,
    private authService: AuthService
  ) {}

  toggleSidebar(): void {
    this.collapsed = !this.collapsed;
    this.sidebarToggled.emit(this.collapsed);
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/auth/login']);
  }
}
