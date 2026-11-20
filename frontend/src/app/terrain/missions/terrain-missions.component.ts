import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Mission } from '../../shared/models/mission.model';
import { TerrainService } from '../terrain.service';

const LIBELLES: Record<Mission['statut'], string> = {
  EN_PREPARATION: 'En préparation', EN_COURS: 'En cours', TERMINEE: 'Terminée',
};

/** Les missions de mes équipes, en cours d'abord ; je dis où j'en suis (comme sur Android). */
@Component({
  selector: 'app-terrain-missions',
  imports: [DatePipe],
  template: `
    <h1>Mes missions</h1>
    @if (erreur()) {
      <p class="erreur" role="alert">{{ erreur() }}</p>
    }
    @if (chargement()) {
      <p class="discret">Chargement…</p>
    } @else if (!missions().length) {
      <p class="discret">Aucune mission pour vos équipes en ce moment.</p>
    }
    @for (m of missions(); track m.id) {
      <article class="mission" [class.en-cours]="m.statut === 'EN_COURS'">
        <div class="ligne">
          <h2>{{ m.titre }}</h2>
          <span class="statut" [attr.data-statut]="m.statut">{{ libelle(m.statut) }}</span>
        </div>
        @if (m.crise_nom) { <p class="crise">{{ m.crise_nom }}</p> }
        @if (m.description) { <p class="description">{{ m.description }}</p> }
        <p class="discret">
          {{ (m.equipes_noms ?? []).join(', ') }}
          @if (m.date_creation) { · créée le {{ m.date_creation | date:'d MMM, HH:mm' }} }
        </p>
        <div class="actions">
          @if (m.statut === 'EN_PREPARATION') {
            <button type="button" class="principal" [disabled]="enCours() === m.id" (click)="changer(m, 'EN_COURS')">Je commence</button>
          }
          @if (m.statut === 'EN_COURS') {
            <button type="button" class="principal" [disabled]="enCours() === m.id" (click)="changer(m, 'TERMINEE')">Terminé</button>
          }
        </div>
      </article>
    }
  `,
  styles: [`
    h1 { font-size: 1.25rem; margin: 4px 0 12px; }
    .mission {
      background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
      border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;
    }
    .mission.en-cours { border-left: 4px solid var(--brand-primary, #2563eb); }
    .ligne { display: flex; align-items: flex-start; gap: 8px; }
    h2 { font-size: 1.02rem; margin: 0; flex: 1; }
    .statut {
      font-size: .72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap;
      background: var(--ac-surface-2, #f3f4f6); color: var(--ac-text, #1f2937);
    }
    .statut[data-statut="EN_COURS"] { background: var(--ac-blue-bg, #dbeafe); color: var(--ac-blue-text, #1e40af); }
    .statut[data-statut="TERMINEE"] { background: var(--ac-green-bg, #dcfce7); color: var(--ac-green-text, #166534); }
    .crise { margin: 4px 0 0; font-weight: 600; font-size: .9rem; }
    .description { margin: 6px 0; white-space: pre-line; }
    .discret { color: var(--ac-text-muted, #6b7280); font-size: .85rem; margin: 4px 0; }
    .erreur { color: var(--ac-red-text, #b91c1c); }
    .actions { display: flex; gap: 8px; margin-top: 8px; }
    .principal {
      flex: 1; border: 0; border-radius: 10px; padding: 12px; font: inherit; font-weight: 600; cursor: pointer;
      background: var(--brand-primary, #2563eb); color: #fff;
    }
    .principal:disabled { opacity: .6; }
  `],
})
export class TerrainMissionsComponent implements OnInit {
  private terrain = inject(TerrainService);
  readonly missions = signal<Mission[]>([]);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  readonly enCours = signal<string | null>(null);

  libelle(statut: Mission['statut']): string { return LIBELLES[statut] ?? statut; }

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.terrain.missions().subscribe({
      next: (missions) => {
        const ordre = { EN_COURS: 0, EN_PREPARATION: 1, TERMINEE: 2 } as const;
        this.missions.set([...missions].sort((a, b) => ordre[a.statut] - ordre[b.statut]));
        this.chargement.set(false);
        this.erreur.set(null);
      },
      error: () => {
        this.chargement.set(false);
        this.erreur.set('Impossible de charger les missions. Vérifiez le réseau, puis réessayez.');
      },
    });
  }

  changer(mission: Mission, statut: Mission['statut']): void {
    if (!mission.id) return;
    this.enCours.set(mission.id);
    this.terrain.changerStatut(mission.id, statut).subscribe({
      next: (a_jour) => {
        this.missions.update(liste => liste.map(m => (m.id === mission.id ? { ...m, ...a_jour, statut } : m)));
        this.enCours.set(null);
      },
      error: () => {
        this.enCours.set(null);
        this.erreur.set('Le changement n\'a pas été enregistré : réessayez quand le réseau revient.');
      },
    });
  }
}
