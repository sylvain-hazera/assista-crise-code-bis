import { Component, HostListener } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../../auth/services/auth.service';
import { User, UserRole } from '../../../models/user.model';
import { TeamService } from '../../../../services/team.service';

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
  myTeamId: string | null = null;

  constructor(public authService: AuthService, private router: Router, private teamService: TeamService) {
    this.currentUser = this.authService.getCurrentUser();
    this.checkScreenSize();

    if (this.authService.isLoggedIn()) {
      // Un seul raccourci "Mon équipe" affiché : le cas d'un bénévole membre de plusieurs
      // équipes à la fois reste rare, et n'a pas besoin d'un sélecteur dédié dans l'en-tête.
      this.teamService.mesEquipes().subscribe({
        next: (teams) => { this.myTeamId = teams[0]?.id ?? null; },
        error: () => {},
      });
    }
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

  /** Un compte n'ayant reçu qu'un accès démo (demo_role réglé, type PROD resté simple) doit
   * quand même pouvoir atteindre /admin : c'est le seul endroit où se trouve la bascule
   * PROD/DEMO — voir AuthService.canEnterAdminArea(). Sans ce accesseur, ce compte n'aurait
   * strictement aucun moyen de découvrir/atteindre cette bascule. */
  get canEnterAdminArea(): boolean {
    return this.authService.canEnterAdminArea();
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
    if(this.canEnterAdminArea) {
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
