import { HttpErrorResponse, HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';

import { environment } from '../../environments/environment';
import { BasculeSatelliteService } from '../services/bascule-satellite.service';

/** Compte les échecs RÉSEAU de notre API (statut 0 : rien n'a répondu) pour proposer la bascule
 * vers le satellite ; toute réponse du serveur, même une erreur, prouve qu'il répond. */
export const basculeSatelliteInterceptor: HttpInterceptorFn = (req, next) => {
  const notre = req.url.startsWith(environment.apiUrl) || req.url.startsWith('/api');
  if (!notre) return next(req);
  const bascule = inject(BasculeSatelliteService);
  return next(req).pipe(tap({
    next: (e) => { if (e instanceof HttpResponse) bascule.noterReponse(true); },
    error: (e) => {
      if (e instanceof HttpErrorResponse) bascule.noterReponse(e.status !== 0);
    },
  }));
};
