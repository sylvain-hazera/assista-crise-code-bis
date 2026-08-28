import { inject } from '@angular/core';
import { Router, CanActivateFn } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { AuthService } from '../../auth/services/auth.service';

/** Rafraîchit le profil depuis l'API avant de statuer : `canEnterAdminArea()`/`isSysAdmin()`
 * lisent le cache local posé à la connexion (voir `getCurrentUser()`), qui reste périmé tant
 * que l'utilisateur ne se reconnecte pas manuellement. Sans ce rafraîchissement, un accès démo
 * (ou toute autre élévation de rôle) accordé après la connexion ne serait jamais atteignable :
 * le garde bloquerait l'entrée dans /admin avant même que la mise en page (qui rafraîchit elle
 * aussi le profil dans son ngOnInit) n'ait la moindre chance de s'exécuter.*/
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




