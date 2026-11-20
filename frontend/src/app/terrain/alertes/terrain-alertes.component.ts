import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { NotificationTerrain, TerrainService } from '../terrain.service';
import { NotificationsPousseesService } from '../notifications-poussees.service';
import { EtapeNotification } from '../terrain.service';
import { HorsLigneService } from '../hors-ligne.service';

/**
 * Mes notifications (mobilisations, consignes), comme dans l'application Android. Les accusés
 * suivent la même règle : « remise » quand la liste est affichée, « lue » quand on ouvre.
 */
@Component({
  selector: 'app-terrain-alertes',
  imports: [DatePipe],
  template: `
    <h1>Alertes</h1>
    @switch (poussees.etat()) {
      @case ('inactives') {
        <section class="encart">
          <p>Recevez les mobilisations et les consignes sur ce téléphone, même application fermée.</p>
          <button type="button" class="principal" (click)="activer()">Activer les notifications</button>
        </section>
      }
      @case ('a-installer') {
        <section class="encart">
          <p>Sur iPhone, les notifications ne sont possibles qu'une fois l'application installée :
             dans Safari, touchez <strong>Partager</strong> puis <strong>« Sur l'écran d'accueil »</strong>,
             puis ouvrez-la depuis son icône.</p>
        </section>
      }
      @case ('refusees') {
        <section class="encart">
          <p>Les notifications sont refusées pour cette application. Pour les rétablir : Réglages du téléphone,
             Notifications, puis le nom de l'application.</p>
        </section>
      }
    }
    @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
    @if (copieDu()) {
      <p class="copie" role="status">Hors ligne : alertes telles qu'elles étaient le {{ copieDu() | date:'d MMM à HH:mm' }}.</p>
    }
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
    .copie { background: var(--ac-amber-bg, #fef3c7); color: var(--ac-amber-text, #92400e); border-radius: 8px;
             padding: 8px 10px; font-size: .85rem; }
    .encart { background: var(--ac-blue-bg, #dbeafe); color: var(--ac-blue-text, #1e40af);
              border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
    .encart p { margin: 0 0 8px; font-size: .9rem; }
    .encart p:last-child { margin-bottom: 0; }
    .principal { width: 100%; border: 0; border-radius: 10px; padding: 12px; font: inherit; font-weight: 600;
                 cursor: pointer; background: var(--brand-primary, #2563eb); color: #fff; }
  `],
})
export class TerrainAlertesComponent implements OnInit {
  private terrain = inject(TerrainService);
  readonly poussees = inject(NotificationsPousseesService);
  private horsLigne = inject(HorsLigneService);
  readonly copieDu = signal<string | null>(null);
  readonly notifications = signal<NotificationTerrain[]>([]);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  readonly ouverte = signal<string | null>(null);

  ngOnInit(): void {
    this.terrain.notifications().subscribe({
      next: (liste) => {
        this.horsLigne.garder('alertes', liste).catch(() => {});
        this.copieDu.set(null);
        this.notifications.set(liste);
        this.chargement.set(false);
        const nouvelles = liste.filter(n => !n.date_vue).map(n => n.id);
        if (nouvelles.length) this.accuser(nouvelles, 'VUE');
      },
      error: async (e) => {
        const copie = HorsLigneService.estHorsLigne(e) ? await this.horsLigne.relire<NotificationTerrain[]>('alertes') : null;
        this.chargement.set(false);
        if (copie) {
          this.copieDu.set(copie.enregistree_le);
          this.notifications.set(copie.valeur);
        } else {
          this.erreur.set('Impossible de charger les notifications. Vérifiez le réseau.');
        }
      },
    });
  }

  activer(): void { this.poussees.activer().catch(() => {}); }

  /** Un accusé qui ne part pas faute de réseau attend dans la file : « lu » doit arriver. */
  private accuser(ids: string[], etape: EtapeNotification): void {
    this.terrain.accuser(ids, etape).subscribe({
      error: (e) => {
        if (HorsLigneService.estHorsLigne(e)) {
          this.horsLigne.differer({ genre: 'accuse', ids, etape, faite_le: new Date().toISOString() }).catch(() => {});
        }
      },
    });
  }

  ouvrir(n: NotificationTerrain): void {
    this.ouverte.set(this.ouverte() === n.id ? null : n.id);
    if (!n.date_lue) {
      this.accuser([n.id], 'LUE');
      this.notifications.update(l => l.map(x => (x.id === n.id ? { ...x, date_lue: new Date().toISOString() } : x)));
    }
  }
}
