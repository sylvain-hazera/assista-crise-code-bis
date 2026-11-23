import { Component, inject } from '@angular/core';
import { AuthService } from '../../../../auth/services/auth.service';

/**
 * « Formation » : passer de la production à la zone de démonstration, et revenir (demande du
 * 20/11/2026, pour les applications installées Terrain et Pilotage).
 *
 * Même mécanisme que la bascule Prod/Démo des en-têtes du site (AuthService.setEnvironment :
 * la zone part avec chaque requête dans X-Environment, la page se recharge). Proposé seulement
 * aux comptes à qui un administrateur a ouvert la démonstration (`demo_role`). On demande
 * confirmation : en pleine crise, un doigt qui glisse ne doit pas faire travailler sur des
 * données fictives.
 */
@Component({
  selector: 'app-bouton-formation',
  template: `
    @if (auth.canAccessDemo()) {
      <button type="button" class="formation" [class.active]="enFormation()" (click)="basculer()"
              [attr.aria-pressed]="enFormation()"
              [title]="enFormation() ? 'Revenir aux données réelles' : 'Passer en formation (données fictives de démonstration)'">
        <span class="material-icons" aria-hidden="true">{{ enFormation() ? 'school' : 'model_training' }}</span>
        <span class="libelle-formation">Formation</span>
      </button>
    }
  `,
  styles: [`
    .formation {
      display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 999px;
      font: inherit; font-size: .78rem; font-weight: 600; cursor: pointer;
      border: 1px solid var(--ac-border, #d1d5db); background: var(--ac-surface, #fff); color: var(--ac-text, #1f2937);
    }
    .formation .material-icons { font-size: 1rem; }
    .formation.active { background: #f97316; border-color: #ea580c; color: #fff; }
    /* Barre du pilotage sur écran étroit : l'icône seule, le titre reste au survol. */
    @media (max-width: 1100px) {
      :host-context(.entete-compacte) .libelle-formation { display: none; }
      :host-context(.entete-compacte) .formation { padding: 6px; }
    }
    .formation:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: 2px; }
  `],
})
export class BoutonFormationComponent {
  readonly auth = inject(AuthService);

  enFormation(): boolean { return this.auth.getEnvironment() === 'DEMO'; }

  basculer(): void {
    const question = this.enFormation()
      ? 'Revenir aux données réelles ?\n\nVous quittez la formation : ce que vous ferez ensuite compte pour de vrai.'
      : 'Passer en formation ?\n\nVous travaillerez sur les données fictives de démonstration. Rien de ce que vous y ferez n\'atteint les données réelles.';
    if (!window.confirm(question)) return;
    this.auth.setEnvironment(this.enFormation() ? 'PROD' : 'DEMO');
  }
}
