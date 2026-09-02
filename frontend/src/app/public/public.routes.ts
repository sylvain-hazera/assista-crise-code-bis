import { Routes } from '@angular/router';
import { HomeComponent } from './home/home.component';
import { GuideComponent } from './guide/guide.component';
import { AboutComponent } from './about/about.component';
import { GlobalMapComponent } from './global-map/global-map.component';
import { CrisisComponent } from './crisis/crisis.component';
import { authGuard } from '../core/guards/auth.guard';
import { adminGuard } from '../core/guards/admin.guard';
import { RecherchesPersonnesComponent } from '../pages/recherches-personnes/recherches-personnes.component';
import { RecherchePersonneCreateComponent } from '../pages/recherche-personne-create/recherche-personne-create.component';
import { RecherchePersonneDetailComponent } from '../pages/recherche-personne-detail/recherche-personne-detail.component';

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
        path: 'activate-account/:uidb64/:token',
        loadComponent: () => import('../auth/component/activate-account/activate-account.component')
          .then(m => m.ActivateAccountComponent)
      },
      {
        path: 'completer-inscription',
        canActivate: [authGuard],
        loadComponent: () => import('../auth/component/completer-inscription/completer-inscription.component')
          .then(m => m.CompleterInscriptionComponent)
      },
      {
        path: 'connexion-magique/:uidb64/:token',
        loadComponent: () => import('../auth/component/magic-login/magic-login.component')
          .then(m => m.MagicLoginComponent)
      },
      {
        path: 'reinitialiser-mot-de-passe/:uidb64/:token',
        loadComponent: () => import('../auth/component/reset-password/reset-password.component')
          .then(m => m.ResetPasswordComponent)
      },
      {
        path: 'dossier-suivi/:id',
        canActivate: [authGuard],
        loadComponent: () => import('./dossier-suivi/dossier-suivi.component')
          .then(m => m.DossierSuiviComponent)
      },
      {
        path: 'confirmation-ressource/:token',
        loadComponent: () => import('./engagement-ressource/engagement-ressource.component')
          .then(m => m.EngagementRessourceComponent)
      },
      {
        path: 'repondre-offre/:token',
        loadComponent: () => import('./offer-reponse/offer-reponse.component')
          .then(m => m.OfferReponseComponent)
      },
      {
        path: 'settings',
        canActivate: [authGuard],
        loadComponent: () => import('./settings/settings.component')
          .then(m => m.SettingsComponent)
      },
      {
        path: 'mon-equipe/:id',
        canActivate: [authGuard],
        loadComponent: () => import('../pages/mon-equipe/mon-equipe.component')
          .then(m => m.MonEquipeComponent)
      },
      {
        path: 'mon-equipe/:id/hebergement',
        canActivate: [authGuard],
        loadComponent: () => import('../pages/hebergement-matching/hebergement-matching.component')
          .then(m => m.HebergementMatchingComponent)
      },
      {
        path: 'mes-interventions',
        canActivate: [authGuard],
        loadComponent: () => import('../pages/mes-interventions/mes-interventions.component')
          .then(m => m.MesInterventionsComponent)
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
        path: 'other-declaration',
        loadComponent: () => import('./forms/other-declaration-form/other-declaration-form.component')
          .then(m => m.OtherDeclarationFormComponent)
      },
      {
        path: 'crisis-declaration',
        canActivate: [adminGuard],
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
      },
      {
        path: 'recherches-personnes',
        canActivate: [authGuard],
        component: RecherchesPersonnesComponent
      },
      {
        path: 'recherches-personnes/new',
        canActivate: [authGuard],
        component: RecherchePersonneCreateComponent
      },
      {
        path: 'recherches-personnes/:id',
        canActivate: [authGuard],
        component: RecherchePersonneDetailComponent
      },
];
