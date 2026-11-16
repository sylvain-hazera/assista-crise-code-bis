import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';

import { DossierPcsService, ManquePcs } from '../../../../services/dossier-pcs.service';

/**
 * Rappel discret, pendant la crise, que le plan de sauvegarde est incomplet.
 *
 * **Il ne bloque rien, et c'est tout son objet.** Une crise s'ouvre et se conduit même si la
 * commune n'a pas découpé ses quartiers ou pas fini son annuaire : dans l'urgence, on fait avec
 * ce qu'on a. Ce rappel dit seulement ce qui manque et où y revenir — replié par défaut, pour ne
 * pas encombrer l'écran de quelqu'un qui a autre chose à faire. Les liens s'ouvrent dans un
 * nouvel onglet : on ne quitte pas l'écran de crise pour aller compléter un paragraphe.
 *
 * Silencieux s'il n'y a rien à dire (plan complet, ou compte sans collectivité).
 */
@Component({
  selector: 'app-rappel-plan-incomplet',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (manques.length) {
      <div class="rappel" role="note">
        <button type="button" class="entete" (click)="ouvert = !ouvert" [attr.aria-expanded]="ouvert">
          <span class="material-icons">info</span>
          <span>Votre plan de sauvegarde est incomplet sur {{ manques.length }} point{{ manques.length > 1 ? 's' : '' }}.
            <strong>Cela n'empêche rien :</strong> vous pourrez y revenir.</span>
          <span class="material-icons chevron">{{ ouvert ? 'expand_less' : 'expand_more' }}</span>
        </button>
        @if (ouvert) {
          <ul>
            @for (manque of manques; track manque.partie + manque.message) {
              <li><strong>{{ manque.partie }}</strong> — {{ manque.message }}
                @if (manque.route) { <a [href]="manque.route" target="_blank" rel="noopener">Compléter dans « {{ manque.ou }} »</a> }
              </li>
            }
          </ul>
        }
      </div>
    }
  `,
  styles: [`
    .rappel { margin: 0 0 1rem; border: 1px solid var(--ac-border, #d1d5db); border-radius: 8px; background: var(--ac-surface, #fff); font-size: .86rem; }
    .entete { display: flex; align-items: center; gap: .5rem; width: 100%; padding: .5rem .8rem; border: none; background: none;
              color: var(--ac-text-muted, #6b7280); font: inherit; text-align: left; cursor: pointer; }
    .entete .material-icons { font-size: 1.1rem; }
    .chevron { margin-left: auto; }
    ul { margin: 0; padding: 0 .9rem .7rem 2.2rem; color: var(--ac-text, #1f2937); }
    li { margin-bottom: .3rem; }
    a { margin-left: .3rem; font-size: .82rem; }
  `],
})
export class RappelPlanIncompletComponent implements OnInit {
  manques: ManquePcs[] = [];
  ouvert = false;

  constructor(private dossier: DossierPcsService) {}

  ngOnInit(): void {
    // Toute erreur est tue : ce rappel n'est jamais une raison d'afficher une alerte en crise.
    this.dossier.lire().subscribe({ next: (d) => { this.manques = d.manques; }, error: () => {} });
  }
}
