import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';

export const enableGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);

  const router = inject(Router);

  if (authService.isEnable()) {
    return true; // Accès autorisé
  }

  return router.parseUrl('/accueil'); 
};
