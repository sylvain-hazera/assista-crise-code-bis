import { Component, EventEmitter, HostBinding, Input, Output } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import { GROUPES_NAV, GroupeNav, GroupeNavId, NAV_ITEMS, NavItem } from '../admin-nav.config';

const CLE_STOCKAGE_GROUPES = 'admin-sidebar-groupes-ouverts';

/** Menu latéral de l'administration. Placement et affichage mobile : admin-layout.
 * Entrées et droits d'affichage : admin-nav.config.ts. */
@Component({
  selector: 'app-admin-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './admin-sidebar.component.html',
  styleUrl: './admin-sidebar.component.scss',
})
export class AdminSidebarComponent {
  /** Mode réduit (icônes seules), desktop uniquement. */
  @HostBinding('class.collapsed')
  @Input() collapsed = false;

  /** Clic sur une entrée : le layout ferme le menu sur mobile. */
  @Output() navigation = new EventEmitter<void>();
  @Output() deconnexion = new EventEmitter<void>();

  readonly groupesNav: GroupeNav[] = GROUPES_NAV;

  /** État replié/déplié par cadre, préférence locale (localStorage). « Crise en cours » déplié par défaut. */
  groupesOuverts: Partial<Record<GroupeNavId, boolean>> = { crise: true };

  constructor(private authService: AuthService) {
    try {
      const sauvegarde = localStorage.getItem(CLE_STOCKAGE_GROUPES);
      if (sauvegarde) this.groupesOuverts = JSON.parse(sauvegarde);
    } catch {
      // localStorage indisponible : repli silencieux sur le défaut.
    }
  }

  itemsDuGroupe(id: GroupeNavId): NavItem[] {
    return NAV_ITEMS.filter(item => item.groupe === id && this.isNavItemVisible(item));
  }

  get itemsPermanents(): NavItem[] {
    return this.itemsDuGroupe('permanent');
  }

  estGroupeOuvert(id: GroupeNavId): boolean {
    return !!this.groupesOuverts[id];
  }

  toggleGroupe(id: GroupeNavId): void {
    this.groupesOuverts = { ...this.groupesOuverts, [id]: !this.groupesOuverts[id] };
    try {
      localStorage.setItem(CLE_STOCKAGE_GROUPES, JSON.stringify(this.groupesOuverts));
    } catch {
    }
  }

  /** Rôle effectif (AuthService.getEffectiveRole) : masque ce qui ne pourrait pas charger.
   * Les gardes de route protègent aussi les URL. */
  isNavItemVisible(item: NavItem): boolean {
    switch (item.visibilite ?? 'institutionnel') {
      case 'tous':
        return true;
      case 'sysadmin':
        return this.authService.isSysAdmin();
      case 'validation-comptes': {
        const role = this.authService.getEffectiveRole();
        return role === UserRole.ADMIN || role === UserRole.LOCAL_AUTH;
      }
      case 'autorite-locale':
        return this.authService.isAutoriteLocaleCommunale();
      case 'registre-vulnerables':
        // Champ calculé côté serveur, jamais recalculé ici.
        return !!this.authService.getCurrentUser()?.acces_registre_vulnerables;
      case 'membres-association':
        return !!this.authService.getCurrentUser()?.acces_membres_association;
      case 'institutionnel':
        return this.authService.isInstitutionalEffective();
    }
  }
}
