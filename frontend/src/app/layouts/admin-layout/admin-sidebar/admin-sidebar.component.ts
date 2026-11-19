import { Component, DestroyRef, EventEmitter, HostBinding, Input, Output, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient } from '@angular/common/http';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { catchError, filter, of } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { pollWhileVisible } from '../../../shared/utils/polling.util';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import {
  CompteurNav, GROUPES_NAV, GroupeNav, GroupeNavId, NAV_ITEMS, NavItem,
  SOUS_GROUPES_NAV, SousGroupeNav, SousGroupeNavId,
} from '../admin-nav.config';

/** Réponse de GET /api/compteurs-menu/ (backend/core/views_menu.py). */
interface CompteursMenu {
  signalements: number | null;
  messages_a_relire: number | null;
  demandes_mobilisation: number | null;
  crise_ouverte: boolean;
}

/** Fréquence de rafraîchissement des compteurs, onglet visible seulement. */
const RAFRAICHISSEMENT_COMPTEURS_MS = 120_000;

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

  readonly sousGroupesNav: SousGroupeNav[] = SOUS_GROUPES_NAV;

  /** Une crise est-elle ouverte pour mon institution ? Tant qu'on ne le sait pas, on fait
   * comme si : mieux vaut « Crise en cours » devant par erreur que derrière. */
  criseOuverte = true;
  compteurs: Partial<Record<CompteurNav, number>> = {};

  /** Ordre des cadres selon la situation : hors crise, « Préparer » passe devant
   * « Crise en cours » et « Après la crise » (revue du menu, 19/11/2026). */
  get groupesNav(): GroupeNav[] {
    if (this.criseOuverte) return GROUPES_NAV;
    const preparer = GROUPES_NAV.filter(g => g.id === 'preparation');
    const reste = GROUPES_NAV.filter(g => g.id !== 'preparation');
    const avant = reste.findIndex(g => g.id === 'crise');
    return [...reste.slice(0, avant), ...preparer, ...reste.slice(avant)];
  }

  /** État replié/déplié par cadre, préférence locale (localStorage). Par défaut : « Mon
   * activité », et « Crise en cours » (ou « Préparer » hors crise, voir appliquerSituation). */
  groupesOuverts: Partial<Record<GroupeNavId, boolean>> = { 'mon-activite': true, crise: true };
  /** Vrai si l'utilisateur a déjà choisi ce qui est ouvert : la situation ne le change plus. */
  private preferenceEnregistree = false;

  /** Idem pour les sous-cadres, dans une clé séparée : un sous-cadre et son cadre portent des
   * identifiants de types différents, les mélanger dans le même objet rendrait le typage
   * faux dès qu'un futur sous-cadre porterait le nom d'un cadre. */
  sousGroupesOuverts: Partial<Record<SousGroupeNavId, boolean>> = Object.fromEntries(
    SOUS_GROUPES_NAV.filter(sous => sous.ouvertParDefaut).map(sous => [sous.id, true]),
  );

  constructor(private authService: AuthService) {
    try {
      const sauvegarde = localStorage.getItem(CLE_STOCKAGE_GROUPES);
      if (sauvegarde) {
        this.groupesOuverts = JSON.parse(sauvegarde);
        this.preferenceEnregistree = true;
      }
      // Fusionnée avec les défauts : un sous-cadre apparu depuis (les étapes de la crise)
      // s'ouvre comme prévu au lieu de rester fermé faute d'avoir été enregistré.
      const sauvegardeSous = localStorage.getItem(CLE_STOCKAGE_SOUS_GROUPES);
      if (sauvegardeSous) this.sousGroupesOuverts = { ...this.sousGroupesOuverts, ...JSON.parse(sauvegardeSous) };
    } catch {
      // localStorage indisponible : repli silencieux sur le défaut.
    }
    // Le cadre de la page affichée s'ouvre de lui-même : arrivé par un lien (un renvoi depuis
    // une autre page, une notification), on ne doit pas chercher où l'on est (19/11/2026).
    const router = inject(Router, { optional: true });
    if (router) {
      this.ouvrirLeCadreDe(router.url);
      router.events.pipe(filter((e) => e instanceof NavigationEnd), takeUntilDestroyed(inject(DestroyRef)))
        .subscribe((e) => this.ouvrirLeCadreDe((e as NavigationEnd).urlAfterRedirects));
    }
    // Compteurs et situation. Facultatif : sans HttpClient (essais), le menu reste statique.
    const http = inject(HttpClient, { optional: true });
    if (http) {
      pollWhileVisible(
        () => http.get<CompteursMenu>(`${environment.apiUrl}/compteurs-menu/`).pipe(catchError(() => of(null))),
        RAFRAICHISSEMENT_COMPTEURS_MS,
      ).pipe(takeUntilDestroyed(inject(DestroyRef))).subscribe((reponse) => {
        if (reponse) this.appliquerSituation(reponse);
      });
    }
  }

  appliquerSituation(reponse: CompteursMenu): void {
    this.compteurs = {
      signalements: reponse.signalements ?? 0,
      messages_a_relire: reponse.messages_a_relire ?? 0,
      demandes_mobilisation: reponse.demandes_mobilisation ?? 0,
    };
    this.criseOuverte = !!reponse.crise_ouverte;
    if (!this.preferenceEnregistree) {
      // Rien de choisi par l'utilisateur : on ouvre ce dont la situation a besoin.
      this.groupesOuverts = { 'mon-activite': true, crise: this.criseOuverte, preparation: !this.criseOuverte };
      this.ouvrirLeCadreDe(this.urlCourante);
    }
  }

  private urlCourante = '';

  /** Le nombre à afficher en pastille (0 : pas de pastille). */
  compteurDe(item: NavItem): number {
    return item.compteur ? (this.compteurs[item.compteur] ?? 0) : 0;
  }

  /** Ouvre le cadre (et le sous-cadre) de l'entrée la plus précise qui correspond à l'adresse,
   * sans rien refermer ni enregistrer : la préférence de l'utilisateur reste la sienne. */
  ouvrirLeCadreDe(url: string): void {
    this.urlCourante = url || '';
    const chemin = (url || '').split(/[?#]/)[0];
    const entree = NAV_ITEMS
      .filter((i) => chemin === i.route || chemin.startsWith(i.route + '/'))
      .sort((a, b) => b.route.length - a.route.length)[0];
    if (!entree || entree.groupe === 'permanent') return;
    this.groupesOuverts = { ...this.groupesOuverts, [entree.groupe]: true };
    if (entree.sousGroupe) this.sousGroupesOuverts = { ...this.sousGroupesOuverts, [entree.sousGroupe]: true };
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
    this.preferenceEnregistree = true;
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
      case 'admin-plateforme':
        return this.authService.isAdminPlateforme();
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
      case 'campagnes':
        return !!this.authService.getCurrentUser()?.acces_campagnes;
      case 'radio':
        // Champ serveur : il dépend du matériel enregistré et des droits accordés, aucun des
        // deux n'étant connu du navigateur (backend/core/acces_radio.py).
        return !!this.authService.getCurrentUser()?.acces_radio;
      case 'institutionnel':
        return this.authService.isInstitutionalEffective();
    }
  }
}
