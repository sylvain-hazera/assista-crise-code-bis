import { HttpErrorResponse, HttpEvent, HttpHandlerFn, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from '../../auth/services/auth.service';
import { BehaviorSubject, Observable, catchError, filter, switchMap, take, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';

let isRefreshing = false;
const refreshedTokenSubject = new BehaviorSubject<string | null>(null);

function withAuth(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
  return req.clone({ headers: req.headers.set('Authorization', `Bearer ${token}`) });
}

function withEnvironment(req: HttpRequest<unknown>, authService: AuthService): HttpRequest<unknown> {
  return req.clone({ headers: req.headers.set('X-Environment', authService.getEnvironment()) });
}

function isAuthEndpoint(url: string): boolean {
  // /token/, /token/refresh/, /token/blacklist/ : jamais de retry dessus (boucle infinie
  // sinon, ou tentative de rafraîchissement absurde sur un login qui a juste échoué).
  return url.includes('/token/');
}

// Ces en-têtes ne doivent JAMAIS partir vers un service tiers (ex: Base Adresse Nationale
// pour l'autocomplétion d'adresse) : un serveur externe qui ne les déclare pas dans son
// Access-Control-Allow-Headers fait échouer le préflight CORS entier, cassant la requête
// même pour un usage anonyme sans token (observé avec X-Environment sur l'API BAN).
function isOwnApiRequest(url: string): boolean {
  return url.startsWith(environment.apiUrl);
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isOwnApiRequest(req.url)) {
    return next(req);
  }

  const authService = inject(AuthService);
  const token = authService.getToken();
  let cloned = token ? withAuth(req, token) : req;
  cloned = withEnvironment(cloned, authService);

  return next(cloned).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status !== 401 || isAuthEndpoint(req.url)) {
        return throwError(() => error);
      }
      return handleUnauthorized(req, next, authService);
    })
  );
};

function handleUnauthorized(
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
  authService: AuthService
): Observable<HttpEvent<unknown>> {
  if (!isRefreshing) {
    isRefreshing = true;
    refreshedTokenSubject.next(null);

    return authService.refreshToken().pipe(
      switchMap(res => {
        isRefreshing = false;
        refreshedTokenSubject.next(res.access);
        return next(withEnvironment(withAuth(req, res.access), authService));
      }),
      catchError(err => {
        isRefreshing = false;
        authService.logout();
        return throwError(() => err);
      })
    );
  }

  // Un rafraîchissement est déjà en cours (déclenché par une autre requête en parallèle) :
  // on attend le nouveau token plutôt que de déclencher un second rafraîchissement, qui
  // échouerait puisque le refresh token en cours de rotation devient à usage unique.
  return refreshedTokenSubject.pipe(
    filter((newToken): newToken is string => newToken !== null),
    take(1),
    switchMap(newToken => next(withEnvironment(withAuth(req, newToken), authService)))
  );
}
