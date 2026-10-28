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

