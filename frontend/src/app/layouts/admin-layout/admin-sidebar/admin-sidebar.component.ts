import { Component, EventEmitter, HostBinding, Input, Output } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import {
  GROUPES_NAV, GroupeNav, GroupeNavId, NAV_ITEMS, NavItem,
  SOUS_GROUPES_NAV, SousGroupeNav, SousGroupeNavId,
} from '../admin-nav.config';

const CLE_STOCKAGE_GROUPES = 'admin-sidebar-groupes-ouverts';
const CLE_STOCKAGE_SOUS_GROUPES = 'admin-sidebar-sous-groupes-ouverts';

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

  /** Grand écran : affiche le bouton icônes seules / libellés (le layout gère l'état). */
  @Input() reductible = false;

  @Output() basculerReduction = new EventEmitter<void>();

  /** Clic sur une entrée : le layout ferme le menu sur mobile. */
  @Output() navigation = new EventEmitter<void>();
  @Output() deconnexion = new EventEmitter<void>();

  readonly groupesNav: GroupeNav[] = GROUPES_NAV;
  readonly sousGroupesNav: SousGroupeNav[] = SOUS_GROUPES_NAV;

  /** État replié/déplié par cadre, préférence locale (localStorage). « Crise en cours » déplié par défaut. */
  groupesOuverts: Partial<Record<GroupeNavId, boolean>> = { crise: true };

  /** Idem pour les sous-cadres, dans une clé séparée : un sous-cadre et son cadre portent des
   * identifiants de types différents, les mélanger dans le même objet rendrait le typage
   * faux dès qu'un futur sous-cadre porterait le nom d'un cadre. */
  sousGroupesOuverts: Partial<Record<SousGroupeNavId, boolean>> = {};

  constructor(private authService: AuthService) {
    try {
      const sauvegarde = localStorage.getItem(CLE_STOCKAGE_GROUPES);
      if (sauvegarde) this.groupesOuverts = JSON.parse(sauvegarde);
      const sauvegardeSous = localStorage.getItem(CLE_STOCKAGE_SOUS_GROUPES);
      if (sauvegardeSous) this.sousGroupesOuverts = JSON.parse(sauvegardeSous);
    } catch {
      // localStorage indisponible : repli silencieux sur le défaut.
    }
  }

  /** TOUTES les entrées visibles du cadre, sous-cadres compris. Sert au mode réduit (qui
   * affiche tout à plat, faute de pouvoir replier sans libellé) et à savoir si le cadre a
   * quelque chose à montrer. */
  itemsDuGroupe(id: GroupeNavId): NavItem[] {
    return NAV_ITEMS.filter(item => item.groupe === id && this.isNavItemVisible(item));
  }

  /** Entrées affichées directement dans le cadre, avant les sous-cadres. */
  itemsDirectsDuGroupe(id: GroupeNavId): NavItem[] {
    return this.itemsDuGroupe(id).filter(item => !item.sousGroupe);
  }

  itemsDuSousGroupe(id: SousGroupeNavId): NavItem[] {
    return NAV_ITEMS.filter(item => item.sousGroupe === id && this.isNavItemVisible(item));
  }

  /** Sous-cadres du cadre qui ont au moins une entrée visible : un sous-cadre vide ne doit pas
   * laisser un repli qui ne contient rien. */
  sousGroupesDuGroupe(id: GroupeNavId): SousGroupeNav[] {
    return SOUS_GROUPES_NAV.filter(
      sous => sous.groupe === id && this.itemsDuSousGroupe(sous.id).length > 0,
    );
  }

  estSousGroupeOuvert(id: SousGroupeNavId): boolean {
    return !!this.sousGroupesOuverts[id];
  }

  toggleSousGroupe(id: SousGroupeNavId): void {
    this.sousGroupesOuverts = { ...this.sousGroupesOuverts, [id]: !this.sousGroupesOuverts[id] };
    try {
      localStorage.setItem(CLE_STOCKAGE_SOUS_GROUPES, JSON.stringify(this.sousGroupesOuverts));
    } catch {
      // localStorage indisponible : l'état reste en mémoire pour la session.
    }
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
      case 'radio':
        // Champ serveur : il dépend du matériel enregistré et des droits accordés, aucun des
        // deux n'étant connu du navigateur (backend/core/acces_radio.py).
        return !!this.authService.getCurrentUser()?.acces_radio;
      case 'institutionnel':
        return this.authService.isInstitutionalEffective();
    }
  }
}
