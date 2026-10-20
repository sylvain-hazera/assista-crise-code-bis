import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';
import { definirConfigInstance } from './app/shared/utils/config-instance';

// Sur un satellite, /config-instance.json décrit l'instance (fond de carte local) ; sur le
// central il n'existe pas (la page HTML renvoyée n'est pas du JSON) : configuration vide.
fetch('/config-instance.json', { cache: 'no-store' })
  .then(r => (r.ok ? r.json() : {}))
  .catch(() => ({}))
  .then(config => {
    definirConfigInstance(config);
    return bootstrapApplication(AppComponent, appConfig);
  })
  .catch((err) => console.error(err));
