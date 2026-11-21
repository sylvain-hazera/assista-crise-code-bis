import { Component, EventEmitter, OnInit, Output } from '@angular/core';

import { InstitutionActive, RattachementService } from '../../../../services/rattachement.service';
import { DelegationGestionService } from '../../../../services/delegation-gestion.service';

/**
 * Délégation de gestion (21/11/2026), en tête de l'administration :
 * - quand on agit pour une collectivité par délégation, un bandeau permanent le dit — on ne
 *   doit jamais se tromper de casquette ;
 * - quand la convention est rompue avec l'AASC qui fournissait l'accès, la collectivité n'a
 *   plus que l'export de ses données : ce composant prend toute la page (`exportSeul`).
 */
@Component({
  selector: 'app-bandeau-delegation',
  standalone: true,
  template: `
    @if (etat?.export_seul) {
      <section class="export-seul" role="alert">
        <h1>Accès à la plateforme suspendu</h1>
        <p>La convention avec l'association qui exploitait la plateforme pour votre collectivité a pris fin.
           Vos données restent les vôtres : vous pouvez les exporter à tout moment.</p>
        <button type="button" class="btn-primary" (click)="exporter()" [disabled]="enCours">
          {{ enCours ? 'Préparation…' : 'Exporter toutes nos données' }}
        </button>
        @if (erreur) { <p class="erreur">{{ erreur }}</p> }
      </section>
    } @else if (etat?.delegation_en_cours; as d) {
      <p class="bandeau" role="status">
        <span class="material-icons" aria-hidden="true">handshake</span>
        Vous agissez pour <strong>{{ d.collectivite }}</strong>, par délégation à {{ d.aasc }}.
      </p>
    }
  `,
  styles: [`
    .bandeau { display: flex; align-items: center; gap: .5rem; margin: 0 0 1rem; padding: .6rem 1rem;
      border-radius: 8px; background: #fef3c7; color: #78350f; border: 1px solid #fcd34d; }
    .export-seul { max-width: 40rem; margin: 3rem auto; text-align: center; display: flex; flex-direction: column; gap: 1rem; }
    .erreur { color: #b91c1c; }
  `],
})
export class BandeauDelegationComponent implements OnInit {
  @Output() exportSeul = new EventEmitter<boolean>();
  etat: InstitutionActive | null = null;
  enCours = false;
  erreur = '';

  constructor(private rattachement: RattachementService, private delegations: DelegationGestionService) {}

  ngOnInit(): void {
    this.rattachement.institutionActive().subscribe({
      next: etat => { this.etat = etat; this.exportSeul.emit(!!etat.export_seul); },
      error: () => {},
    });
  }

  exporter(): void {
    const id = this.etat?.active;
    if (!id) return;
    this.enCours = true;
    this.erreur = '';
    this.delegations.exporter(id).subscribe({
      next: blob => {
        this.enCours = false;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'donnees-collectivite.zip';
        a.click();
        URL.revokeObjectURL(a.href);
      },
      error: () => { this.enCours = false; this.erreur = "L'export a échoué. Réessayez, ou contactez-nous."; },
    });
  }
}
