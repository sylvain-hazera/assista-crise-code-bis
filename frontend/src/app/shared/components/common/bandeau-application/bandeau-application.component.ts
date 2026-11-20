import { Component, inject } from '@angular/core';
import { ApplicationInstallableService } from '../../../../services/application-installable.service';

/**
 * Deux annonces discrètes, en bas de l'écran (DOSSIER-PWA-INTERVENANTS.md) :
 * - « Une nouvelle version est disponible » — l'équivalent, pour le site installé, de la boîte
 *   de mise à jour de l'application Android ;
 * - sur iPhone et iPad, comment installer l'application (Safari ne le propose pas lui-même).
 */
@Component({
  selector: 'app-bandeau-application',
  template: `
    @if (service.nouvelleVersion()) {
      <div class="bandeau" role="status">
        <span class="material-icons" aria-hidden="true">system_update</span>
        <span class="texte">Une nouvelle version est disponible.</span>
        <button type="button" class="principal" (click)="service.recharger()">Recharger</button>
      </div>
    } @else if (service.installationProposee()) {
      <div class="bandeau" role="note">
        <span class="material-icons" aria-hidden="true">add_to_home_screen</span>
        <span class="texte">
          Installez l'application {{ service.espace() === 'pilotage' ? 'Pilotage' : 'Terrain' }} :
          touchez <strong>Partager</strong> <span class="material-icons partager" aria-label="(icône Partager)">ios_share</span>
          puis <strong>« Sur l'écran d'accueil »</strong>.
        </span>
        <button type="button" class="fermer" (click)="service.ecarterLInstallation()" aria-label="Ne plus proposer">
          <span class="material-icons" aria-hidden="true">close</span>
        </button>
      </div>
    }
  `,
  styles: [`
    .bandeau {
      position: fixed; left: 50%; transform: translateX(-50%); z-index: 1000;
      bottom: calc(12px + env(safe-area-inset-bottom, 0px));
      width: min(520px, calc(100% - 24px));
      display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 12px;
      background: var(--ac-surface, #fff); color: var(--ac-text, #1f2937);
      border: 1px solid var(--ac-border, #d1d5db); box-shadow: 0 4px 16px rgba(0, 0, 0, .2);
      font-size: .9rem;
    }
    .texte { flex: 1; min-width: 0; }
    .partager { font-size: 1rem; vertical-align: -3px; }
    .principal {
      border: 0; border-radius: 8px; padding: 8px 14px; cursor: pointer; font: inherit; font-weight: 600;
      background: var(--brand-primary, #2563eb); color: #fff;
    }
    .fermer { border: 0; background: transparent; color: inherit; cursor: pointer; padding: 4px; }
    button:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: 2px; }
  `],
})
export class BandeauApplicationComponent {
  readonly service = inject(ApplicationInstallableService);
}
