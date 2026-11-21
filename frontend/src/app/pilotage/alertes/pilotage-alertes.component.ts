import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { NotificationService } from '../../services/notification.service';
import { AppNotification } from '../../shared/models/notification.model';
import { pollWhileVisible } from '../../shared/utils/polling.util';
import { NotificationsPousseesService } from '../../terrain/notifications-poussees.service';

/**
 * Les alertes du poste de pilotage : les notifications du site (nouvelle demande, dossier,
 * vigilance…), en grand, avec leur fiche. Et, sur l'iPad installé, « Me prévenir sur cet iPad »
 * pour les recevoir même application fermée (titre et page seulement : rien de sensible ne passe
 * par le service de notification d'Apple).
 */
@Component({
  selector: 'app-pilotage-alertes',
  imports: [DatePipe],
  template: `
    <h1>Alertes</h1>
    @switch (poussees.etat()) {
      @case ('inactives') {
        <section class="poussees">
          <p>Être prévenu sur cet appareil, même application fermée.</p>
          <button type="button" (click)="poussees.activer()">Me prévenir sur cet appareil</button>
        </section>
      }
      @case ('a-installer') {
        <section class="poussees">
          <p>Pour être prévenu application fermée, installez d'abord Pilotage : dans Safari, Partager, puis
             « Sur l'écran d'accueil ». Ouvrez-la ensuite depuis son icône.</p>
        </section>
      }
      @case ('refusees') {
        <section class="poussees refusees">
          <p>Les notifications sont refusées pour cette application. Rétablissez-les dans les Réglages de l'iPad
             (Notifications, puis Pilotage).</p>
        </section>
      }
      @case ('actives') {
        <p class="actives"><span class="material-icons" aria-hidden="true">notifications_active</span> Cet appareil est prévenu, même application fermée.</p>
      }
    }
    @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
    @if (!notifications().length && !chargement()) { <p class="discret">Aucune alerte.</p> }
    <ul class="alertes">
      @for (n of notifications(); track n.id) {
        <li [class.non-lue]="!n.lu">
          <button type="button" class="tete" (click)="ouvrir(n)" [attr.aria-expanded]="ouverte() === n.id">
            <span class="texte">
              <strong>{{ n.titre }}</strong>
              <small>{{ n.date_creation | date:'d MMM HH:mm' }}@if (n.dossier_numero) { · dossier {{ n.dossier_numero }} }</small>
            </span>
            @if (!n.lu) { <span class="point" aria-label="Non lue"></span> }
          </button>
          @if (ouverte() === n.id) {
            <div class="fiche">
              <p>{{ n.message }}</p>
              @if (n.details?.length) {
                <dl>
                  @for (d of n.details; track d.libelle) { <div><dt>{{ d.libelle }}</dt><dd>{{ d.valeur }}</dd></div> }
                </dl>
              }
              @if (n.lien) {
                <button type="button" class="lien" (click)="suivre(n)">{{ n.lien_libelle || 'Ouvrir' }}
                  <span class="material-icons" aria-hidden="true">arrow_forward</span></button>
              }
            </div>
          }
        </li>
      }
    </ul>
  `,
  styles: [`
    h1 { font-size: 1.4rem; margin: 0 0 12px; }
    p { margin: 0; }
    .poussees { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 16px; border-radius: 12px;
                margin-bottom: 14px; background: var(--ac-blue-bg, #dbeafe); color: var(--ac-blue-text, #1e40af); }
    .poussees p { flex: 1; min-width: 220px; }
    .poussees.refusees { background: var(--ac-amber-bg, #fef3c7); color: var(--ac-amber-text, #92400e); }
    .poussees button { min-height: 44px; padding: 0 16px; border: 0; border-radius: 10px; font: inherit; font-weight: 600;
                       cursor: pointer; background: var(--brand-primary, #2563eb); color: #fff; }
    .actives { display: flex; align-items: center; gap: 6px; margin-bottom: 14px; color: var(--ac-green-text, #166534); font-size: .9rem; }
    .alertes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .alertes li { background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb); border-radius: 12px; }
    .alertes li.non-lue { border-color: var(--brand-primary, #2563eb); }
    .tete { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 56px; padding: 10px 16px; border: 0;
            background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
    .texte { flex: 1; display: flex; flex-direction: column; }
    .texte small { color: var(--ac-text-muted, #6b7280); }
    .point { width: 10px; height: 10px; border-radius: 50%; background: var(--brand-primary, #2563eb); }
    .fiche { padding: 0 16px 14px; display: flex; flex-direction: column; gap: 10px; }
    dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; font-size: .9rem; }
    dl div { display: contents; }
    dt { color: var(--ac-text-muted, #6b7280); }
    dd { margin: 0; }
    .lien { align-self: flex-start; display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 14px;
            border-radius: 10px; border: 1px solid var(--ac-border, #d1d5db); background: var(--ac-surface, #fff);
            color: var(--brand-primary, #2563eb); font: inherit; font-weight: 600; cursor: pointer; }
    .discret { color: var(--ac-text-muted, #6b7280); }
    .erreur { color: var(--ac-red-text, #b91c1c); }
  `],
})
export class PilotageAlertesComponent implements OnInit, OnDestroy {
  private service = inject(NotificationService);
  private router = inject(Router);
  readonly poussees = inject(NotificationsPousseesService);
  readonly notifications = signal<AppNotification[]>([]);
  readonly ouverte = signal<string | null>(null);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  private abonnement?: Subscription;

  ngOnInit(): void {
    // `true` : ce poste ne se déclare joignable qu'une fois abonné (voir NotificationsPousseesService).
    this.poussees.actualiser(true).catch(() => {});
    this.abonnement = pollWhileVisible(() => this.service.getAll(), 30_000).subscribe({
      next: (liste) => { this.notifications.set(liste); this.chargement.set(false); this.erreur.set(null); },
      error: () => { this.chargement.set(false); this.erreur.set('Les alertes n\'ont pas pu être chargées. Vérifiez le réseau.'); },
    });
  }

  ngOnDestroy(): void { this.abonnement?.unsubscribe(); }

  ouvrir(n: AppNotification): void {
    this.ouverte.set(this.ouverte() === n.id ? null : n.id);
    if (!n.lu) {
      this.service.markAsRead(n.id).subscribe({
        next: () => this.notifications.update(l => l.map(x => (x.id === n.id ? { ...x, lu: true } : x))),
        error: () => {},
      });
    }
  }

  suivre(n: AppNotification): void {
    if (n.lien?.startsWith('/') && !n.lien.startsWith('//')) this.router.navigateByUrl(n.lien);
  }
}
