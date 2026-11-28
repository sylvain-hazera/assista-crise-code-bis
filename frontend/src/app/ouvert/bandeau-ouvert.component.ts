import { Component, Input } from '@angular/core';
import { RouterLink } from '@angular/router';

/** Le bandeau commun des pages ouvertes : retour à l'accueil `/ouvert`, et le titre. */
@Component({
  selector: 'app-bandeau-ouvert',
  standalone: true,
  imports: [RouterLink],
  template: `
    <header class="bandeau">
      <a routerLink="/ouvert" class="retour"><span class="material-icons" aria-hidden="true">chevron_left</span>Tout ce qu'on partage</a>
      <span class="titre">{{ titre }}</span>
    </header>
  `,
  styles: [`
    .bandeau { display: flex; align-items: center; gap: 1rem; min-height: 44px; padding: 0 16px;
      background: var(--ac-surface, #ffffff); border-bottom: 1px solid var(--ac-border, #e2e5ea); color: var(--ac-text, #1f2933); }
    .retour { display: inline-flex; align-items: center; gap: .1rem; color: var(--ac-blue-text, #1d4ed8); text-decoration: none; font-size: .9rem; white-space: nowrap; }
    .retour:hover, .retour:focus-visible { text-decoration: underline; }
    .titre { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  `],
})
export class BandeauOuvertComponent {
  @Input() titre = '';
}
