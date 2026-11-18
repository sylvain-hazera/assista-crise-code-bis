import { Component } from '@angular/core';
import { AuthService } from '../../../../auth/services/auth.service';

/**
 * En production, pour les comptes qui ont accès à la zone de démonstration : un bandeau qui
 * les y invite, bien plus visible que l'interrupteur « Prod » de l'en-tête (demande de Sylvain
 * du 19/11/2026, après le déplacement des crises d'exercice en démonstration).
 *
 * Masquable pour la session seulement : il revient à la connexion suivante, mais ne gêne pas
 * une cellule qui travaille sur une vraie crise.
 */
@Component({
  selector: 'app-invitation-demo',
  standalone: true,
  template: `
    @if (visible) {
      <div class="invitation" role="region" aria-label="Zone de démonstration">
        <span class="material-icons icone" aria-hidden="true">science</span>
        <div class="texte">
          <strong>Vos exercices sont dans la zone de démonstration.</strong>
          Les crises d'essai, leurs équipes et leurs dossiers y ont été déplacés : passez-y pour les retrouver
          et vous entraîner sans toucher aux données réelles.
        </div>
        <button type="button" class="aller" (click)="allerEnDemo()">
          <span class="material-icons" aria-hidden="true">arrow_forward</span> Aller en démonstration
        </button>
        <button type="button" class="masquer" (click)="masquer()" title="Masquer jusqu'à la prochaine connexion"
                aria-label="Masquer jusqu'à la prochaine connexion">
          <span class="material-icons" aria-hidden="true">close</span>
        </button>
      </div>
    }
  `,
  styles: [`
    .invitation {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: .6rem 1rem;
      padding: .8rem 1rem;
      background: #fb923c;            /* theme: fixe, la couleur du mode démo, sur les deux thèmes */
      color: #431407;
      border-bottom: 3px solid #ea580c;
      font-size: .95rem;
      line-height: 1.4;
    }
    .icone { font-size: 1.8rem; }
    .texte { flex: 1 1 18rem; }
    .aller {
      display: inline-flex; align-items: center; gap: .35rem;
      padding: .5rem 1rem;
      border: 0; border-radius: 8px;
      background: #431407; color: #fff7ed;
      font-weight: 700; font-size: .95rem;
      cursor: pointer;
    }
    .aller:hover { background: #7c2d12; }
    .masquer {
      background: none; border: 0; padding: .25rem; color: inherit; cursor: pointer; border-radius: 50%;
    }
    .aller:focus-visible, .masquer:focus-visible { outline: 3px solid #431407; outline-offset: 2px; }
  `],
})
export class InvitationDemoComponent {
  private static readonly CLE = 'invitation_demo_masquee';
  private masquee = false;

  constructor(private authService: AuthService) {
    try {
      this.masquee = sessionStorage.getItem(InvitationDemoComponent.CLE) === '1';
    } catch {
      this.masquee = false;
    }
  }

  get visible(): boolean {
    return !this.masquee && this.authService.canAccessDemo() && this.authService.getEnvironment() === 'PROD';
  }

  allerEnDemo(): void {
    this.authService.setEnvironment('DEMO');
  }

  masquer(): void {
    this.masquee = true;
    try {
      sessionStorage.setItem(InvitationDemoComponent.CLE, '1');
    } catch {
      /* navigation privée : masqué pour cette page seulement */
    }
  }
}
