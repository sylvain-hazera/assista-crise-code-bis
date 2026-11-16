import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AbonnementAlertes, AlerteHabitantsService } from '../../../../services/alerte-habitants.service';

/**
 * « Recevoir les alertes de ma commune » : l'habitant s'abonne, pour lui-même, aux alertes des
 * collectivités de son choix, et s'en désabonne quand il veut.
 *
 * C'est un consentement, et c'est ce qui fait la liste des destinataires d'une alerte : la
 * commune n'écrit pas à quelqu'un parce qu'il habite là, mais parce qu'il l'a demandé. Ce n'est
 * pas FR-Alert, que l'on reçoit sans rien demander et qui relève du préfet.
 */
@Component({
  selector: 'app-abonnement-alertes',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="abonnement-alertes">
      <h3><span class="material-icons">notifications_active</span> Recevoir les alertes de ma commune</h3>
      <p class="tab-hint">
        Abonnez-vous aux alertes de votre commune : en cas de crise, elle pourra vous prévenir par la messagerie,
        l'application ou, si elle le choisit, par courriel ou SMS. Vous vous désabonnez quand vous voulez.
        Ce n'est pas FR-Alert, que vous recevez sans rien demander.
      </p>
      @if (erreur) { <p class="error-message" role="alert">{{ erreur }}</p> }

      @for (abonnement of abonnements; track abonnement.institution) {
        <p class="ligne">
          <span><span class="material-icons ok">check_circle</span> {{ abonnement.institution_nom }}</span>
          <button type="button" class="lien" (click)="desabonner(abonnement)">Me désabonner</button>
        </p>
      } @empty {
        <p class="tab-hint">Vous n'êtes abonné aux alertes d'aucune commune.</p>
      }

      <div class="recherche">
        <input type="search" [(ngModel)]="recherche" (ngModelChange)="chercher()" name="recherche-commune"
               placeholder="Nom de votre commune" aria-label="Chercher une commune">
        @for (collectivite of resultats; track collectivite.id) {
          <p class="ligne">
            <span>{{ collectivite.nom }}</span>
            <button type="button" class="lien" (click)="abonner(collectivite.id)">M'abonner</button>
          </p>
        }
        @if (recherche.trim().length >= 2 && cherche && !resultats.length) {
          <p class="tab-hint">Aucune commune de ce nom n'utilise encore ce service.</p>
        }
      </div>
    </div>
  `,
  styles: [`
    .abonnement-alertes { margin: 1.5rem 0; }
    h3 { display: flex; align-items: center; gap: .4rem; }
    .ligne { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin: .35rem 0;
             padding: .45rem .7rem; border: 1px solid var(--ac-border, #d1d5db); border-radius: 6px; }
    .ligne span { display: inline-flex; align-items: center; gap: .35rem; }
    .ok { font-size: 1.1rem; color: var(--ac-green-text, #166534); }
    .lien { border: none; background: none; padding: 0; color: var(--ac-primary, #1d4ed8); font: inherit; font-weight: 600;
            text-decoration: underline; cursor: pointer; white-space: nowrap; }
    .recherche { margin-top: .8rem; }
    input { width: 100%; max-width: 420px; padding: .5rem .6rem; border-radius: 6px; border: 1px solid var(--ac-border, #d1d5db);
            background: var(--ac-surface, #fff); color: var(--ac-text, #1f2937); font: inherit; }
  `],
})
export class AbonnementAlertesComponent implements OnInit {
  abonnements: AbonnementAlertes[] = [];
  recherche = '';
  resultats: { id: string; nom: string }[] = [];
  /** Vrai une fois qu'une recherche a répondu : sinon « aucune commune » s'afficherait pendant la frappe. */
  cherche = false;
  erreur = '';

  constructor(private service: AlerteHabitantsService) {}

  ngOnInit(): void {
    this.charger();
  }

  private charger(): void {
    this.service.mesAbonnements().subscribe({ next: (a) => { this.abonnements = a; }, error: () => {} });
  }

  chercher(): void {
    const q = this.recherche.trim();
    this.cherche = false;
    if (q.length < 2) { this.resultats = []; return; }
    this.service.chercherCollectivites(q).subscribe({
      next: (resultats) => {
        // Une réponse arrivée après une frappe plus récente ne doit pas l'écraser.
        if (q !== this.recherche.trim()) return;
        const deja = new Set(this.abonnements.map(a => a.institution));
        this.resultats = resultats.filter(r => !deja.has(r.id));
        this.cherche = true;
      },
      error: () => { this.erreur = 'La recherche a échoué.'; },
    });
  }

  abonner(institution: string): void {
    this.erreur = '';
    this.service.sAbonner(institution).subscribe({
      next: () => { this.recherche = ''; this.resultats = []; this.cherche = false; this.charger(); },
      error: () => { this.erreur = "L'abonnement n'a pas pu être enregistré."; },
    });
  }

  desabonner(abonnement: AbonnementAlertes): void {
    if (!confirm(`Ne plus recevoir les alertes de « ${abonnement.institution_nom} » ?`)) return;
    this.erreur = '';
    this.service.seDesabonner(abonnement.institution).subscribe({
      next: () => this.charger(), error: () => { this.erreur = "Le désabonnement n'a pas pu être enregistré."; },
    });
  }
}
