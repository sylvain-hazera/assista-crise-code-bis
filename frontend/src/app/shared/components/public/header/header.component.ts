import { Component } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../../auth/services/auth.service';
import { User, UserRole } from '../../../models/user.model';

@Component({
  selector: 'app-header',
  imports: [
    RouterModule
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss'
})
export class HeaderComponent {
  currentUser: User | null = null;
  showUserMenu = false;

  constructor(public authService: AuthService, private router: Router) {
    this.currentUser = this.authService.getCurrentUser();
  }

  get isAdmin(): boolean {
    return this.currentUser ? this.currentUser['userType'] !== UserRole.Individual : true;
  }

  handleUserAction() {
    if (this.authService.isLoggedIn()) {
      this.showUserMenu = !this.showUserMenu;
    } else {
      this.router.navigate(['/login']);
    }
  }

  goToSettings() {
    if(this.isAdmin) {
      this.router.navigate(['/admin/settings']);
    } else {
      this.router.navigate(['/settings']);
    }
    this.showUserMenu = false;
  }

  goToProfile() {
    if(this.isAdmin) {
      this.router.navigate(['/admin/dashboard']);
    } 
  }
  logout() {
    this.authService.logout();
  }
}
