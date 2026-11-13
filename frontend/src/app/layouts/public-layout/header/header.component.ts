import { Component, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../auth/services/auth.service';
import { User, UserRole } from '../../../shared/models/user.model';
import { FormsModule } from '@angular/forms';

import { RattachementService } from '../../../services/rattachement.service';
import { TeamService } from '../../../services/team.service';
import { UserAvatarComponent } from '../../../shared/components/common/user-avatar/user-avatar.component';
import { Observable } from 'rxjs';
import { BrandingService, Branding } from '../../../services/branding.service';
import { ThemeService } from '../../../services/theme.service';

@Component({
  selector: 'app-header',
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    UserAvatarComponent,
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
  branding$: Observable<Branding>;

  constructor(
    public authService: AuthService, private router: Router, private teamService: TeamService,
    private brandingService: BrandingService, public theme: ThemeService,
    private rattachementService: RattachementService,
  ) {
    this.branding$ = this.brandingService.branding$;
    this.currentUser = this.authService.getCurrentUser();
    this.checkScreenSize();

    if (this.authService.isLoggedIn()) {
      // Un seul raccourci "Mon équipe" affiché : le cas d'un bénévole membre de plusieurs
      // équipes à la fois reste rare, et n'a pas besoin d'un sélecteur dédié dans l'en-tête.
      this.teamService.mesEquipes().subscribe({
        next: (teams) => { this.myTeamId = teams[0]?.id ?? null; },
        error: () => {},
      });
      this.chargerInstitutions();
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

  /** Contrairement à avant, un compte démo-only ne peut plus entrer dans /admin tant qu'il est
   * en PROD (voir AuthService.canEnterAdminArea()) — la bascule PROD/DEMO ci-dessous, elle,
   * reste accessible depuis l'en-tête public dès que canAccessDemo() est vrai, pour que ce
   * compte puisse malgré tout basculer avant de tenter d'entrer dans /admin. */
  get canEnterAdminArea(): boolean {
    return this.authService.canEnterAdminArea();
  }

  get canAccessDemo(): boolean {
    return this.authService.canAccessDemo();
  }

  get isDemoEnv(): boolean {
    return this.authService.getEnvironment() === 'DEMO';
  }

  toggleEnvironment(): void {
    this.authService.setEnvironment(this.isDemoEnv ? 'PROD' : 'DEMO');
  }

  handleUserAction() {
    if (this.authService.isLoggedIn()) {
      this.showUserMenu = !this.showUserMenu;
    } else {
      this.router.navigate(['/login']);
    }
  }

  // ══ Contexte de travail d'un compte multi-appartenance ════════════════════════════════
  //
  // « Un utilisateur peut être membre de plusieurs institutions. Une mairie et une asso »
  // (13/11/2026). `User.institution` n'est qu'un CONTEXTE — il pilote le périmètre
  // territorial — et il était posé au premier rattachement sans jamais pouvoir changer. Le
  // sélecteur n'apparaît qu'au-delà d'une institution : pour tous les autres, il n'y a rien à
  // choisir et un menu de plus serait du bruit.

  institutionsRattachees: { id: string; nom: string; nom_affichage: string; type_libelle: string }[] = [];
  institutionActive: string | null = null;

  private chargerInstitutions(): void {
    if (!this.authService.isLoggedIn()) { return; }
    this.rattachementService.institutionActive().subscribe({
      next: (etat) => {
        this.institutionsRattachees = etat.institutions;
        this.institutionActive = etat.active;
      },
      error: () => this.institutionsRattachees = [],
    });
  }

  get aPlusieursInstitutions(): boolean {
    return this.institutionsRattachees.length > 1;
  }

  get nomInstitutionActive(): string {
    return this.institutionsRattachees.find(i => i.id === this.institutionActive)
      ?.nom_affichage || '';
  }

  changerInstitutionActive(id: string): void {
    if (!id || id === this.institutionActive) { return; }
    this.rattachementService.definirInstitutionActive(id).subscribe({
      // Rechargement complet, et c'est volontaire : le contexte décide du périmètre
      // territorial, donc des données déjà affichées par toutes les pages ouvertes. Les
      // rafraîchir une par une serait long à écrire et faux à la première oubliée.
      next: () => window.location.reload(),
      error: () => undefined,
    });
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
