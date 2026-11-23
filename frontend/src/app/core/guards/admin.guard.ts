import { inject } from '@angular/core';
import { Router, CanActivateFn } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { AuthService } from '../../auth/services/auth.service';
import { UserRole } from '../../shared/models/user.model';

/** Rafraîchit le profil avant de statuer : le cache local de la connexion ne reflète pas un
 * droit accordé depuis (ex: accès démo). */
function withFreshProfile(authService: AuthService, router: Router, check: () => boolean) {
  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => check() ? true : router.parseUrl('/accueil')),
    catchError(() => of(router.parseUrl('/accueil'))),
  );
}

export const adminGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return withFreshProfile(authService, router, () => authService.canEnterAdminArea());
};

export const sysAdminGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return withFreshProfile(authService, router, () => authService.isSysAdmin());
};

/** Réservé à l'administrateur de la plateforme : supervision technique, comptes MQTT. */
export const adminPlateformeGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.isAdminPlateforme() ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/accueil'))),
  );
};

/** Redirige vers une page « droits insuffisants » dans l'admin quand le rôle effectif n'est
 * pas institutionnel (au lieu d'erreurs dans chaque page). */
export const institutionalEffectiveGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.isInstitutionalEffective() ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};

/** Validation des comptes en attente (Secours organisés) : admin ou mairie (son code postal). */
export const accountValidationGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => {
      const role = authService.getEffectiveRole();
      return (role === UserRole.ADMIN || role === UserRole.LOCAL_AUTH)
        ? true
        : router.parseUrl('/admin/acces-refuse');
    }),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};

/** Collectivités territoriales (isAutoriteLocaleCommunale), sinon 403 à l'usage.
 *
 * S'appelait `zonesGuard` : le nom venait de sa premiere page, mais le critere n'a jamais eu
 * de rapport avec les zones, et il garde aujourd'hui plusieurs ecrans qui n'en ont pas non
 * plus. Renomme le 28/10/2026 en ajoutant les habilitations au registre, pour ne pas ecrire
 * un troisieme garde au corps identique faute d'un nom juste. C'est le garde attendu par le
 * menu pour la visibilite `autorite-locale` (voir admin-sidebar.component.spec.ts). */
export const autoriteLocaleGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.isAutoriteLocaleCommunale() ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};

/** Membres association : champ serveur `acces_membres_association`.
 *
 * Les trois critères (administrateur, compte rattaché à une AASC, membre du bureau d'une AASC
 * même rattaché ailleurs) sont invérifiables côté navigateur — le dernier surtout, qui est un
 * attribut du rattachement et non du compte. Avant le 28/10/2026 la page était ouverte à tout
 * rôle institutionnel et se fermait d'elle-même : elle paraissait cassée à une mairie plutôt
 * qu'absente. */
/** « Revue des droits » (23/11/2026) : champ serveur `acces_revue_droits` — administrateur, ou
 * bureau, contact principal ou responsable d'une institution (backend/core/revue_droits.py). */
export const revueDroitsGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.getCurrentUser()?.acces_revue_droits ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};

export const membresAssociationGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.getCurrentUser()?.acces_membres_association ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};

/** Campagnes de disponibilité : champ serveur `acces_campagnes`, vrai pour qui peut en mener
 * une — bureau d'une association, agent ou élu d'une collectivité, encadrant d'une équipe.
 * Distinct de `membresAssociationGuard` depuis le 14/11/2026 : les campagnes servent aussi
 * aux mairies. */
export const campagnesGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.getCurrentUser()?.acces_campagnes ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};

/** Registre des personnes vulnérables : champ serveur `acces_registre_vulnerables`, qui reflète
 * depuis le 28/10/2026 la DÉSIGNATION nominative (HabilitationRegistreVulnerables) et non plus
 * l'appartenance à la RCSC. Volontairement vrai avant que l'engagement au secret ne soit signé,
 * puisque c'est la page elle-même qui le fait signer — les fiches restent fermées jusque-là
 * (core/vulnerabilites.py). Non recalculable côté client. */
export const vulnerabilitesGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.getCurrentUser()?.acces_registre_vulnerables ? true : router.parseUrl('/admin/acces-refuse')),
    catchError(() => of(router.parseUrl('/admin/acces-refuse'))),
  );
};


/** Domaine radio : champ serveur `acces_radio` (nœud personnel actif, passerelle de
 * l'institution, ou droit accordé — voir backend/core/acces_radio.py).
 *
 * Seul garde du projet à ne PAS renvoyer vers `/admin/acces-refuse` : il renvoie vers
 * `/admin/radio`, qui dit ce qu'il faut (un nœud, ou une passerelle) et permet de demander le
 * droit. « Accès refusé » serait exact et inutile — la personne a besoin de savoir ce qui lui
 * manque, pas qu'il lui manque quelque chose. */
export const radioGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.getToken()) {
    return router.parseUrl('/accueil');
  }
  return authService.fetchMe().pipe(
    map(() => authService.getCurrentUser()?.acces_radio ? true : router.parseUrl('/admin/radio')),
    catchError(() => of(router.parseUrl('/admin/radio'))),
  );
};
