import { Component, EventEmitter, HostBinding, Input, Output } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../../auth/services/auth.service';
import { SuiviPositionPermanentService } from '../../../services/suivi-position-permanent.service';
import { User, UserRole } from '../../../shared/models/user.model';
import { AdminNotificationsComponent } from './admin-notifications/admin-notifications.component';

/** En-tête de l'administration : logo, bannière démo, suivi de position, bascule PROD/DEMO,
 * cloche et menu utilisateur. Arbitre ses listes déroulantes (une seule ouverte à la fois) et
 * signale au layout qu'une liste est ouverte : le layout affiche le fond qui les ferme. */
@Component({
  selector: 'app-admin-header',
  standalone: true,
  imports: [AdminNotificationsComponent],
  templateUrl: './admin-header.component.html',
  styleUrl: './admin-header.component.scss',
})
export class AdminHeaderComponent {
  @Input() currentUser: User | null = null;
  @Input() isMobile = false;
  @Input() sidebarCollapsed = false;

  @Output() toggleSidebar = new EventEmitter<void>();
  /** true dès qu'une liste déroulante est ouverte ; émis à chaque ouverture ou fermeture. */
  @Output() menusOuvertsChange = new EventEmitter<boolean>();
  @Output() deconnexion = new EventEmitter<void>();

  showNotifications = false;
  showUserMenu = false;

  constructor(
    private authService: AuthService,
    private router: Router,
    public suiviPosition: SuiviPositionPermanentService,
  ) {}

  @HostBinding('class.demo-mode')
  get isDemo(): boolean {
    return this.authService.getEnvironment() === 'DEMO';
  }

  get canAccessDemo(): boolean {
    return this.authService.canAccessDemo();
  }

  toggleEnvironment(): void {
    this.authService.setEnvironment(this.isDemo ? 'PROD' : 'DEMO');
  }

  /** Bascule le suivi de position permanent ; l'accord navigateur n'est demandé qu'une fois. */
  basculerSuiviPosition(): void {
    if (this.suiviPosition.actif) {
      this.suiviPosition.desactiver();
    } else {
      this.suiviPosition.activer();
    }
  }

  onNotificationsToggle(ouvert: boolean): void {
    this.showNotifications = ouvert;
    if (ouvert) this.showUserMenu = false;
    this.signalerMenus();
  }

  toggleUserMenu(): void {
    this.showUserMenu = !this.showUserMenu;
    this.showNotifications = false;
    this.signalerMenus();
  }

  /** Appelé par le layout (clic sur le fond) et après chaque action du menu utilisateur. */
  fermerMenus(): void {
    this.showNotifications = false;
    this.showUserMenu = false;
    this.signalerMenus();
  }

  goToSettings(): void {
    this.router.navigate(['/settings']);
    this.fermerMenus();
  }

  goToHome(): void {
    this.router.navigate(['/accueil']);
    this.fermerMenus();
  }

  logout(): void {
    this.fermerMenus();
    this.deconnexion.emit();
  }

  get companyName(): string {
    // currentUser peut être null le temps que le profil arrive.
    return this.currentUser && this.currentUser.type !== UserRole.SIMPLE_USER
      ? this.currentUser.last_name
      : 'Admin';
  }

  private signalerMenus(): void {
    this.menusOuvertsChange.emit(this.showNotifications || this.showUserMenu);
  }
}
