import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TableTriFiltre } from '../../../utils/table-tri-filtre';

/** En-tête de colonne triable.
 *
 * Sélecteur d'ATTRIBUT sur `th` et non élément propre : un `<app-...>` placé dans un `<tr>` est
 * sorti du tableau par le navigateur (seuls `th`/`td` y sont valides) et la mise en page est
 * détruite. En attribut, le composant s'applique au `th` lui-même.
 *
 * `tabindex`/`role`/`aria-sort` sont portés ici, une fois, plutôt que recopiés sur chaque
 * colonne : trente en-têtes cliquables à la souris et inaccessibles au clavier, c'est trente
 * fois le même oubli. */
@Component({
  selector: 'th[appThTri]',
  standalone: true,
  imports: [CommonModule],
  template: `{{ libelle }}<span class="tri-indicateur">{{ table.indicateur(cle) }}</span>`,
  host: {
    'class': 'th-triable',
    'role': 'columnheader',
    'tabindex': '0',
    '[attr.aria-sort]': 'table.ariaSort(cle)',
    '[attr.title]': '"Trier par " + libelle',
    '(click)': 'table.basculer(cle)',
    '(keydown.enter)': 'table.basculer(cle)',
    '(keydown.space)': 'basculerAuClavier($event)',
  },
  styles: [`
    :host { cursor: pointer; user-select: none; white-space: nowrap; }
    .tri-indicateur { margin-left: 0.25rem; font-size: 0.7rem; opacity: 0.8; }
  `],
})
export class ThTriComponent {
  @Input({ required: true }) table!: TableTriFiltre<any>;
  @Input({ required: true }) cle!: string;
  @Input() libelle = '';

  basculerAuClavier(evenement: Event): void {
    // Sans ça, la barre d'espace fait défiler la page au lieu de trier.
    evenement.preventDefault();
    this.table.basculer(this.cle);
  }
}

/** Cellule de filtre d'une colonne, posée dans une seconde ligne d'en-tête.
 *
 * Un filtre par colonne plutôt qu'une seule recherche globale : chercher « 1 » dans tout le
 * tableau ramène tout, alors que « 1 » dans la colonne node_num a un sens. Les deux cumulent. */
@Component({
  selector: 'th[appThFiltre]',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <input type="search" class="filtre-colonne" [attr.aria-label]="'Filtrer sur ' + (libelle || cle)"
           [placeholder]="placeholder" [ngModel]="table.filtres[cle] || ''"
           (ngModelChange)="table.filtres[cle] = $event">
  `,
  styles: [`
    :host { padding: 0.15rem 0.3rem !important; font-weight: 400; }
    .filtre-colonne {
      width: 100%; min-width: 4rem; box-sizing: border-box;
      padding: 0.2rem 0.35rem; font-size: 0.75rem;
      border: 1px solid var(--ac-border, #cbd5e1); border-radius: 3px;
      background: var(--ac-surface, #fff); color: var(--ac-text, #0f172a);
    }
  `],
})
export class ThFiltreComponent {
  @Input({ required: true }) table!: TableTriFiltre<any>;
  @Input({ required: true }) cle!: string;
  @Input() libelle = '';
  @Input() placeholder = 'filtrer';
}
