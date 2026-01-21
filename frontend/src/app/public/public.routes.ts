import { Routes } from '@angular/router';
import { HomeComponent } from './home/home.component';
import { GuideComponent } from './guide/guide.component';
import { AboutComponent } from './about/about.component';
import { GlobalMapComponent } from './global-map/global-map.component';
import { CrisisComponent } from './crisis/crisis.component';


export const PUBLIC_ROUTES: Routes = [
  { path: '', redirectTo: 'accueil', pathMatch: 'full' },
      { path: 'accueil', component: HomeComponent },
      {path: 'guide', component: GuideComponent},
      {path: 'carte', component: GlobalMapComponent},
      {path: 'crises', component: CrisisComponent},
      {path: 'info', component: AboutComponent},
      {
        path: 'login',
        loadComponent: () => import('../auth/component/login/login.component')
          .then(m => m.LoginComponent)
      },
      {
        path: 'register',
        loadComponent: () => import('../auth/component/register/register.component')
          .then(m => m.RegisterComponent)
      },
      {
        path: 'help-proposal',
        loadComponent: () => import('./forms/propose-help-form/propose-help-form.component')
          .then(m => m.ProposeHelpFormComponent)
      },
      {
        path: 'help-request',
        loadComponent: () => import('./forms/request-help-form/request-help-form.component')
          .then(m => m.RequestHelpFormComponent)
      },
      {
        path: 'safe-declaration',
        loadComponent: () => import('./forms/declare-safe-form/declare-safe-form.component')
          .then(m => m.DeclareSafeFormComponent)
      },
      {
        path: 'crisis-declaration',
        loadComponent: () => import('./forms/declare-crisis-form/declare-crisis-form.component')
          .then(m => m.DeclareCrisisFormComponent)
      },
      {
        path: 'mentions-legales',
        loadComponent: () => import('./legal/mentions-legales/mentions-legales.component')
          .then(m => m.MentionsLegalesComponent)
      },
      {
        path: 'cgu',
        loadComponent: () => import('./legal/cgu/cgu.component')
          .then(m => m.CguComponent)
      },
      {
        path: 'rgpd',
        loadComponent: () => import('./legal/rgpd/rgpd.component')
          .then(m => m.RgpdComponent)
      },
      {
        path: 'credits',
        loadComponent: () => import('./legal/credits/credits.component')
          .then(m => m.CreditsComponent)
      }
];