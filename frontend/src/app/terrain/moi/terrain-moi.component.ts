import { Component, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { ApplicationInstallableService } from '../../services/application-installable.service';
import { TerrainService } from '../terrain.service';
import { NotificationsPousseesService } from '../notifications-poussees.service';
import { HorsLigneService } from '../hors-ligne.service';

/** Mon compte, côté terrain : ma fiche, mes réglages, l'installation, la déconnexion. */
@Component({
  selector: 'app-terrain-moi',
  imports: [RouterLink],
  template: `
    <h1>{{ prenom() }}</h1>
    <nav class="liste">
      <a routerLink="/ma-fiche-benevole"><span class="material-icons" aria-hidden="true">badge</span>Ma fiche bénévole et mes disponibilités</a>
      <a routerLink="/mon-releve"><span class="material-icons" aria-hidden="true">schedule</span>Mon relevé d'heures</a>
      <a routerLink="/settings"><span class="material-icons" aria-hidden="true">settings</span>Mes réglages</a>
      <a routerLink="/securite-du-compte"><span class="material-icons" aria-hidden="true">lock</span>Sécurité du compte</a>
    </nav>
    @if (!installable.estInstallee()) {
      <section class="installer">
        <h2>Installer l'application</h2>
        <p>Sur iPhone : dans Safari, touchez <strong>Partager</strong> puis <strong>« Sur l'écran d'accueil »</strong>.
           Sur Android : menu du navigateur, puis <strong>« Installer l'application »</strong>.</p>
      </section>
    }
    <button type="button" class="deconnexion" (click)="deconnecter()">Se déconnecter</button>
  `,
  styles: [`
    h1 { font-size: 1.25rem; margin: 4px 0 12px; }
    .liste { display: flex; flex-direction: column; background: var(--ac-surface, #fff);
             border: 1px solid var(--ac-border, #e5e7eb); border-radius: 12px; overflow: hidden; }
    .liste a { display: flex; align-items: center; gap: 12px; padding: 14px; color: inherit; text-decoration: none;
               border-bottom: 1px solid var(--ac-border, #e5e7eb); }
    .liste a:last-child { border-bottom: 0; }
    .liste a:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: -2px; }
    .installer { margin-top: 16px; padding: 12px 14px; border-radius: 12px; background: var(--ac-blue-bg, #dbeafe);
                 color: var(--ac-blue-text, #1e40af); }
    .installer h2 { font-size: 1rem; margin: 0 0 4px; }
    .installer p { margin: 0; font-size: .9rem; }
    .deconnexion { margin-top: 20px; width: 100%; padding: 12px; border-radius: 10px; font: inherit; cursor: pointer;
                   border: 1px solid var(--ac-border, #d1d5db); background: var(--ac-surface, #fff); color: var(--ac-red-text, #b91c1c); }
  `],
})
export class TerrainMoiComponent {
  private auth = inject(AuthService);
  private terrain = inject(TerrainService);
  private router = inject(Router);
  private notifications = inject(NotificationsPousseesService);
  private horsLigne = inject(HorsLigneService);
  readonly installable = inject(ApplicationInstallableService);

  prenom(): string { return this.auth.getCurrentUser()?.first_name || 'Mon compte'; }

  deconnecter(): void {
    // Ce téléphone ne joint plus cette personne : comme à la déconnexion sur Android.
    this.notifications.desactiver().finally(() => this.terrain.oublierLAppareil().subscribe({
      complete: () => this.fin(), error: () => this.fin(),
    }));
  }

  private fin(): void {
    // Rien de la personne ne reste sur le téléphone : copies et file effacées, clés comprises.
    this.horsLigne.effacer().catch(() => {});
    this.auth.logout();
    this.router.navigate(['/login'], { queryParams: { returnUrl: '/terrain' } });
  }
}
