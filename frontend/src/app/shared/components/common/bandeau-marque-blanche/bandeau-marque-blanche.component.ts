import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Observable, map } from 'rxjs';

import { BrandingService } from '../../../../services/branding.service';

/** Bandeau affiché en tête des pages légales, uniquement en marque blanche.
 *
 * Les textes juridiques (CGU, confidentialité, mentions légales, convention de
 * sous-traitance) nomment la plateforme et son éditeur, et doivent continuer à le faire : c'est
 * l'identité du responsable et du sous-traitant qui est en jeu. Mais une personne qui arrive
 * par le domaine d'un partenaire connaît le service sous UN AUTRE NOM, et lire soudain celui de
 * la plateforme donne l'impression de s'être trompée de site.
 *
 * Ce bandeau fait le lien en une phrase, sans toucher au corps des textes — donc sans risque
 * d'en affaiblir la portée juridique. Il disparaît hors marque blanche, où il n'apprendrait
 * rien.
 */
@Component({
  selector: 'app-bandeau-marque-blanche',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (nomPartenaire$ | async; as nom) {
      <aside class="bandeau-marque">
        <span class="material-icons">info</span>
        <p>
          Vous consultez ce service sous le nom <strong>{{ nom }}</strong>. Il s'appuie sur la
          plateforme Assista&nbsp;Crise, dont l'éditeur est identifié ci-dessous : les mentions
          qui suivent désignent cette plateforme.
        </p>
      </aside>
    }
  `,
  styles: [`
    .bandeau-marque {
      display: flex;
      gap: .6rem;
      align-items: flex-start;
      margin: 0 0 1.5rem;
      padding: .85rem 1rem;
      border-radius: 8px;
      border-left: 3px solid var(--ac-accent, #2563eb);
      background: var(--ac-surface-2, #eff6ff);
    }
    .bandeau-marque .material-icons { color: var(--ac-accent, #2563eb); font-size: 1.15rem; }
    .bandeau-marque p { margin: 0; font-size: .88rem; line-height: 1.5; }
  `],
})
export class BandeauMarqueBlancheComponent {
  /** Le nom du partenaire, ou `null` hors marque blanche — auquel cas rien ne s'affiche. */
  readonly nomPartenaire$: Observable<string | null>;

  constructor(private brandingService: BrandingService) {
    this.nomPartenaire$ = this.brandingService.branding$.pipe(
      map(b => (b.nom_affichage && b.nom_affichage !== 'Assista-Crise')
        ? b.nom_affichage : null),
    );
  }
}
