// import { CanActivateFn } from '@angular/router';

// export const adminGuard: CanActivateFn = (route, state) => {
//   return true;
// };

import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from './auth.service'; // Votre service qui gère l'état

export const adminGuard = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.isConnected && authService.isAdmin) {
    return true; // Accès autorisé
  }

  // Redirection si l'utilisateur n'est pas admin
  return router.parseUrl('/accueil'); 
};