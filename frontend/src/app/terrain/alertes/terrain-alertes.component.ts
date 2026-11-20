import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { NotificationTerrain, TerrainService } from '../terrain.service';

/**
 * Mes notifications (mobilisations, consignes), comme dans l'application Android. Les accusés
 * suivent la même règle : « remise » quand la liste est affichée, « lue » quand on ouvre.
 */
@Component({
  selector: 'app-terrain-alertes',
  imports: [DatePipe],
  template: `
    <h1>Alertes</h1>
    @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
    @if (!chargement() && !notifications().length) {
      <p class="discret">Aucune notification ces derniers jours.</p>
    }
    @for (n of notifications(); track n.id) {
      <article class="notification" [class.urgent]="n.urgent" [class.non-lue]="!n.date_lue" (click)="ouvrir(n)"
               (keydown.enter)="ouvrir(n)" tabindex="0" role="button" [attr.aria-expanded]="ouverte() === n.id">
        <div class="ligne">
          <span class="genre">{{ n.genre_libelle }}</span>
          <span class="date">{{ n.date_creation | date:'d MMM, HH:mm' }}</span>
        </div>
        <h2>{{ n.titre }}</h2>
        @if (ouverte() === n.id && n.corps) { <p class="corps">{{ n.corps }}</p> }
        @if (n.institution_nom) { <p class="discret">{{ n.institution_nom }}</p> }
      </article>
    }
  `,
  styles: [`
    h1 { font-size: 1.25rem; margin: 4px 0 12px; }
    .notification {
      background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
      border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; cursor: pointer;
    }
    .notification.non-lue h2 { font-weight: 700; }
    .notification.urgent { border-left: 4px solid var(--ac-red-border, #fca5a5); }
    .notification:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); }
    .ligne { display: flex; justify-content: space-between; font-size: .75rem; color: var(--ac-text-muted, #6b7280); }
    h2 { font-size: 1rem; font-weight: 500; margin: 4px 0 0; }
    .corps { white-space: pre-line; margin: 8px 0 0; }
    .discret { color: var(--ac-text-muted, #6b7280); font-size: .85rem; margin: 4px 0 0; }
    .erreur { color: var(--ac-red-text, #b91c1c); }
  `],
})
export class TerrainAlertesComponent implements OnInit {
  private terrain = inject(TerrainService);
  readonly notifications = signal<NotificationTerrain[]>([]);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  readonly ouverte = signal<string | null>(null);

  ngOnInit(): void {
    this.terrain.notifications().subscribe({
      next: (liste) => {
        this.notifications.set(liste);
        this.chargement.set(false);
        const nouvelles = liste.filter(n => !n.date_vue).map(n => n.id);
        if (nouvelles.length) this.terrain.accuser(nouvelles, 'VUE').subscribe({ error: () => {} });
      },
      error: () => {
        this.chargement.set(false);
        this.erreur.set('Impossible de charger les notifications. Vérifiez le réseau.');
      },
    });
  }

  ouvrir(n: NotificationTerrain): void {
    this.ouverte.set(this.ouverte() === n.id ? null : n.id);
    if (!n.date_lue) {
      this.terrain.accuser([n.id], 'LUE').subscribe({ error: () => {} });
      this.notifications.update(l => l.map(x => (x.id === n.id ? { ...x, date_lue: new Date().toISOString() } : x)));
    }
  }
}
