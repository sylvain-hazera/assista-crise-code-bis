import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';

export const enableGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);

  const router = inject(Router);

  if (authService.isEnable()) {
    return true; // Accès autorisé
  }

  alert(
    'Votre compte est en attente de validation par un administrateur.\n\n'
  );

  return router.parseUrl('/accueil'); 
};
