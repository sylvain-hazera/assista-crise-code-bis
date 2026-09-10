import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter, withInMemoryScrolling } from '@angular/router';

import { routes } from './app.routes';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { authInterceptor } from './auth/interceptor/auth';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    // Sans ça, Angular garde la position de scroll de la page précédente lors d'une navigation
    // (ex: admin/dossiers, tout en bas) — arriver sur une page plus courte (ex: admin/carte)
    // laisse alors l'écran vide (le scroll dépasse le contenu réel), donnant l'impression d'un
    // bug tant qu'on ne remonte pas manuellement. anchorScrolling: conserve le comportement des
    // ancres (#fragment) si jamais utilisées, seul le scroll "au changement de route" change.
    provideRouter(routes, withInMemoryScrolling({ scrollPositionRestoration: 'top', anchorScrolling: 'enabled' })),
    // provideHttpClient(),
    provideHttpClient(withInterceptors([authInterceptor]))

  ]
};
