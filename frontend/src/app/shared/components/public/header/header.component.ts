import { Component, HostListener } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../../auth/services/auth.service';
import { User, UserRole } from '../../../models/user.model';

@Component({
  selector: 'app-header',
  imports: [
    RouterModule
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
})

export class HeaderComponent {
  currentUser: User | null = null;
  showUserMenu = false;
  showMobileMenu = false;
  isMobile = false;

  constructor(public authService: AuthService, private router: Router) {
    this.currentUser = this.authService.getCurrentUser();
    console.log(this.currentUser);
    this.checkScreenSize();
  }

  //Pour les tests
  @HostListener('window:resize')
  onResize() {
    this.checkScreenSize();
  }
  
  private checkScreenSize() {
    this.isMobile = window.innerWidth <= 768;
    if (!this.isMobile) {
      this.showMobileMenu = false;
    }
  }

  get isAdmin(): boolean {
    // return this.currentUser?.userType !== UserRole.Individual;
    return this.authService.isAdmin();
  }

  handleUserAction() {
    if (this.authService.isLoggedIn()) {
      this.showUserMenu = !this.showUserMenu;
    } else {
      this.router.navigate(['/login']);
    }
  }

  goToSettings() {
    this.router.navigate(['/settings']);
    this.closeAllMenus();
  }


  goToProfile() {
    if(this.isAdmin) {
      this.router.navigate(['/admin/dashboard']);
    } 
    this.closeAllMenus();
  }
  logout() {
    this.authService.logout();
    this.router.navigate(['/accueil']);
    this.closeAllMenus()
  }

  //Responsive
  toggleMobileMenu() {
    this.showMobileMenu = !this.showMobileMenu;
    this.showUserMenu = false;
  }

  navigateTo(route: string) {
    this.router.navigate([route]);
    this.closeAllMenus();
  }

  closeAllMenus() {
    this.showUserMenu = false;
    this.showMobileMenu = false;
  }
}
