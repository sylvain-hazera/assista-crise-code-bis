import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { AuthService } from '../auth/services/auth.service';

/** Le poste de pilotage est réservé aux rôles institutionnels (dans la zone affichée, réelle ou
 * de formation). Le compte est relu d'abord, comme pour l'administration ; les autres sont menés
 * vers leur espace, Terrain. Sans réseau, on se fie au compte déjà connu. */
export const pilotageGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const decider = () => auth.isInstitutionalEffective() || router.parseUrl('/terrain');
  return auth.fetchMe().pipe(map(decider), catchError(() => of(decider())));
};
