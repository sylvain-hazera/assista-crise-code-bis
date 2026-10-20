import { Component, HostListener, OnInit, ViewChild } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { User } from '../../shared/models/user.model';
import { AdminHeaderComponent } from './admin-header/admin-header.component';
import { AdminSidebarComponent } from './admin-sidebar/admin-sidebar.component';

/** Menu latéral sur grand écran : largeur libre, icônes seules, ou masqué. */
export type EtatSidebar = 'etendue' | 'reduite' | 'fermee';

export const LARGEUR_SIDEBAR = { defaut: 250, min: 200, max: 420, reduite: 70 } as const;
/** En glissant la poignée : sous ce seuil le menu passe en icônes seules, sous le second il se ferme. */
const SEUIL_REDUCTION = 150;
const SEUIL_FERMETURE = 40;
const PAS_CLAVIER = 16;
const CLE_STOCKAGE_SIDEBAR = 'admin-sidebar-affichage';

/** Coquille de l'administration : grille, affichage mobile, fonds semi-transparents et
 * <router-outlet>. En-tête, menu et cloche sont des composants enfants ; les entrées du menu
 * sont dans admin-nav.config.ts (DOCUMENTATION.md, § 6.4). Sur grand écran, le menu se
 * redimensionne par sa poignée, se réduit aux icônes ou se masque ; préférence locale. */
@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [RouterOutlet, AdminHeaderComponent, AdminSidebarComponent],
  templateUrl: './admin-layout.component.html',
  styleUrls: ['./admin-layout.component.scss']
})
export class AdminLayoutComponent implements OnInit {
  @ViewChild(AdminHeaderComponent) private header?: AdminHeaderComponent;

  readonly largeurs = LARGEUR_SIDEBAR;

  currentUser: User | null = null;
  etatSidebar: EtatSidebar = 'etendue';
  /** Largeur choisie en mode étendu, gardée quand on réduit ou ferme le menu. */
  largeurSidebar: number = LARGEUR_SIDEBAR.defaut;
  /** Glissement de la poignée en cours : pas d'animation, le contenu suit le pointeur. */
  redimensionnement = false;
  sidebarOpen = false; // mobile
  isMobile = false;
  /** Une liste déroulante de l'en-tête est ouverte : affiche le fond qui la ferme. */
  menusOuverts = false;

  /** État à retrouver quand on rouvre un menu fermé. */
  private etatAvantFermeture: Exclude<EtatSidebar, 'fermee'> = 'etendue';
  /** Largeur au début du glissement : gardée si le geste finit en icônes seules ou fermé. */
  private largeurAvantGlissement: number = LARGEUR_SIDEBAR.defaut;

  constructor(
    private authService: AuthService,
    private router: Router,
  ) {
    this.lirePreference();
  }

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.checkScreenSize();
    // Rafraîchit le profil : getCurrentUser() ne relit que le cache, un droit accordé après la
    // connexion resterait sinon invisible.
    this.authService.fetchMe().subscribe({
      next: (user) => this.currentUser = user,
      error: () => {},
    });
  }

  get sidebarCollapsed(): boolean {
    return this.etatSidebar === 'reduite';
  }

  get sidebarFermee(): boolean {
    return this.etatSidebar === 'fermee';
  }

  /** Largeur de la colonne du menu dans la grille (variable CSS --sidebar-largeur). */
  get largeurAffichee(): number {
    switch (this.etatSidebar) {
      case 'fermee': return 0;
      case 'reduite': return LARGEUR_SIDEBAR.reduite;
      case 'etendue': return this.largeurSidebar;
    }
  }

  @HostListener('window:resize')
  onResize(): void {
    this.checkScreenSize();
  }

  private checkScreenSize(): void {
    this.isMobile = window.innerWidth <= 768;
    this.sidebarOpen = false;
  }

  /** Bouton de l'en-tête. Desktop : masque/réaffiche le menu. Mobile : l'ouvre/le ferme. */
  toggleSidebar(): void {
    if (this.isMobile) {
      this.sidebarOpen = !this.sidebarOpen;
    } else {
      this.definirEtat(this.sidebarFermee ? this.etatAvantFermeture : 'fermee');
    }
  }

  /** Bouton du bas du menu : icônes seules / libellés. */
  basculerReduction(): void {
    this.definirEtat(this.sidebarCollapsed ? 'etendue' : 'reduite');
  }

  // ==================== POIGNÉE ====================

  debutRedimensionnement(event: PointerEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    // Le pointeur reste capté par la poignée même s'il sort de la fenêtre ou passe sur une iframe.
    try {
      (event.target as HTMLElement).setPointerCapture(event.pointerId);
    } catch {
      // Pointeur déjà relâché : le glissement marche quand même tant qu'il reste sur la poignée.
    }
    this.redimensionnement = true;
    this.largeurAvantGlissement = this.largeurSidebar;
  }

  redimensionner(event: PointerEvent): void {
    if (!this.redimensionnement) return;
    // Le menu part du bord gauche de la fenêtre : sa largeur est la position du pointeur.
    const x = event.clientX;
    if (x < SEUIL_FERMETURE) {
      this.etatSidebar = 'fermee';
    } else if (x < SEUIL_REDUCTION) {
      this.etatSidebar = 'reduite';
    } else {
      this.etatSidebar = 'etendue';
      this.largeurSidebar = this.borner(x);
    }
  }

  finRedimensionnement(event: PointerEvent): void {
    if (!this.redimensionnement) return;
    try {
      (event.target as HTMLElement).releasePointerCapture(event.pointerId);
    } catch {
    }
    this.redimensionnement = false;
    // En passant sous la largeur minimale, la largeur a été bornée : on rend celle d'avant.
    if (this.etatSidebar !== 'etendue') this.largeurSidebar = this.largeurAvantGlissement;
    this.definirEtat(this.etatSidebar);
  }

  /** Double-clic sur la poignée : largeur par défaut. */
  reinitialiserLargeur(): void {
    this.largeurSidebar = LARGEUR_SIDEBAR.defaut;
    this.definirEtat('etendue');
  }

  /** Poignée au clavier (rôle separator) : flèches pour la largeur, Entrée pour réduire. */
  clavierPoignee(event: KeyboardEvent): void {
    switch (event.key) {
      case 'ArrowLeft':
        if (this.etatSidebar === 'etendue' && this.largeurSidebar > LARGEUR_SIDEBAR.min) {
          this.largeurSidebar = this.borner(this.largeurSidebar - PAS_CLAVIER);
        } else {
          this.definirEtat(this.etatSidebar === 'etendue' ? 'reduite' : 'fermee');
        }
        break;
      case 'ArrowRight':
        if (this.etatSidebar === 'etendue') {
          this.largeurSidebar = this.borner(this.largeurSidebar + PAS_CLAVIER);
        } else {
          this.definirEtat(this.etatSidebar === 'fermee' ? 'reduite' : 'etendue');
        }
        break;
      case 'Enter':
        this.basculerReduction();
        break;
      default:
        return;
    }
    event.preventDefault();
    this.sauvegarderPreference();
  }

  private definirEtat(etat: EtatSidebar): void {
    this.etatSidebar = etat;
    if (etat !== 'fermee') this.etatAvantFermeture = etat;
    this.sauvegarderPreference();
  }

  private borner(largeur: number): number {
    return Math.round(Math.min(LARGEUR_SIDEBAR.max, Math.max(LARGEUR_SIDEBAR.min, largeur)));
  }

  private lirePreference(): void {
    try {
      const sauvegarde = JSON.parse(localStorage.getItem(CLE_STOCKAGE_SIDEBAR) ?? 'null');
      if (['etendue', 'reduite', 'fermee'].includes(sauvegarde?.etat)) this.etatSidebar = sauvegarde.etat;
      if (['etendue', 'reduite'].includes(sauvegarde?.avantFermeture)) this.etatAvantFermeture = sauvegarde.avantFermeture;
      if (typeof sauvegarde?.largeur === 'number') this.largeurSidebar = this.borner(sauvegarde.largeur);
    } catch {
      // localStorage indisponible ou valeur illisible : affichage par défaut.
    }
  }

  private sauvegarderPreference(): void {
    try {
      localStorage.setItem(CLE_STOCKAGE_SIDEBAR, JSON.stringify({
        etat: this.etatSidebar, avantFermeture: this.etatAvantFermeture, largeur: this.largeurSidebar,
      }));
    } catch {
    }
  }

  // ==================== MOBILE ET LISTES DÉROULANTES ====================

  closeSidebar(): void {
    if (this.isMobile) {
      this.sidebarOpen = false;
    }
  }

  /** Sur mobile, toute action sur les listes de l'en-tête ferme le menu latéral. */
  onMenusOuverts(ouverts: boolean): void {
    this.menusOuverts = ouverts;
    this.closeSidebar();
  }

  closeAllMenus(): void {
    this.header?.fermerMenus();
    this.closeSidebar();
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
    this.closeAllMenus();
  }

  onNavItemClick(): void {
    this.closeSidebar();
  }
}
