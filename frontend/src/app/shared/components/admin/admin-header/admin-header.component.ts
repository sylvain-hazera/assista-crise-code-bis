// shared/components/admin/admin-header/admin-header.component.ts
import { Component, OnInit, HostListener, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { User } from '../../../models/user.model';
import { AuthService } from '../../../../auth/services/auth.service';

@Component({
  selector: 'app-admin-header',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './admin-header.component.html',
  styleUrl: './admin-header.component.scss'
})
export class AdminHeaderComponent implements OnInit {
  @Output() notificationsToggled = new EventEmitter<void>();
  
  currentUser: User | null = null;
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

  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
  }

  @HostListener('document:keydown.escape')
  onEscapeKey(): void {
    this.closeAllDropdowns();
  }

  toggleNotifications(): void {
    this.showNotifications = !this.showNotifications;
    this.showUserMenu = false;
    if (this.showNotifications) {
      this.notificationsToggled.emit();
    }
  }

  toggleUserMenu(): void {
    this.showUserMenu = !this.showUserMenu;
    this.showNotifications = false;
  }

  closeAllDropdowns(): void {
    this.showNotifications = false;
    this.showUserMenu = false;
  }

  goToSettings(): void {
    this.router.navigate(['/admin/settings']);
    this.closeAllDropdowns();
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/auth/login']);
  }

  get companyName(): string {
    return this.currentUser?.last_name || 'Nom de la compagnie';
  }

  get userName(): string {
    if (!this.currentUser) return '';
    return `${this.currentUser.first_name} ${this.currentUser.last_name}`;
  }
}