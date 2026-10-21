import { Component, Input, OnChanges, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subject, takeUntil } from 'rxjs';
import { AuditLogAdminEntry, AuditLogService } from '../../../services/audit-log.service';

/** « Qui a consulté cette fiche ? » -- les dernières fois où une fiche a été ouverte, vue dans
 *  une liste ou exportée, avec un lien vers son historique complet dans la main courante
 *  (demande du 21/10/2026 : retrouver quelqu'un qui aurait consulté une fiche pour en récupérer
 *  les coordonnées). Chargé seulement à la demande : la consultation de l'historique est
 *  elle-même tracée. Même périmètre que la main courante côté serveur : tout pour le
 *  super-admin, les actes de sa propre institution sinon. */
@Component({
  selector: 'app-qui-a-consulte',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <section class="qac">
      @if (!ouvert) {
        <button type="button" class="qac-ouvrir" (click)="ouvrir()">
          <span class="material-icons">manage_search</span> Qui a consulté cette fiche ?
        </button>
      } @else {
        <h4><span class="material-icons">manage_search</span> Qui a consulté cette fiche ?</h4>
        @if (chargement) {
          <p class="qac-muted">Chargement…</p>
        } @else if (erreur) {
          <p class="qac-muted">{{ erreur }}</p>
        } @else if (!lignes.length) {
          <p class="qac-muted">Aucune consultation enregistrée (comptes système masqués).</p>
        } @else {
          <ul>
            @for (l of lignes; track l.id) {
              <li>
                <span class="qac-date">{{ l.date_action | date:'dd/MM/yyyy HH:mm' }}</span>
                <span class="qac-qui">{{ l.utilisateur_nom }}@if (l.institution_nom) { · {{ l.institution_nom }} }</span>
                <span class="qac-ip">{{ l.adresse_ip || '—' }}</span>
                <span class="qac-comment">{{ comment(l) }}</span>
              </li>
            }
          </ul>
        }
        <a class="qac-tout" [routerLink]="['/admin/main-courante']" [queryParams]="{ objet: objetId }">
          Historique complet dans la main courante
        </a>
      }
    </section>
  `,
  styles: [`
    .qac { margin-top: 1rem; padding-top: .9rem; border-top: 1px solid #e5e7eb; font-size: .85rem; }
    .qac-ouvrir {
      display: inline-flex; align-items: center; gap: .35rem; background: none; border: 1px solid #d1d5db;
      border-radius: 8px; padding: .4rem .75rem; cursor: pointer; color: #374151; font-size: .85rem;
      .material-icons { font-size: 18px; }
      &:hover { background: #f9fafb; }
    }
    h4 { display: flex; align-items: center; gap: .35rem; margin: 0 0 .5rem; font-size: .9rem; .material-icons { font-size: 18px; } }
    ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .3rem; }
    li { display: grid; grid-template-columns: 7.5rem minmax(0, 1fr) 7rem 9.5rem; gap: .5rem; align-items: baseline; }
    .qac-date, .qac-ip { font-variant-numeric: tabular-nums; color: #6b7280; }
    .qac-qui { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .qac-comment { font-size: .78rem; color: #92400e; }
    .qac-muted { color: #6b7280; margin: 0; }
    .qac-tout { display: inline-block; margin-top: .6rem; font-size: .82rem; }
    @media (max-width: 640px) { li { grid-template-columns: 1fr; gap: 0; padding-bottom: .3rem; border-bottom: 1px solid #f3f4f6; } }
  `],
})
export class QuiAConsulteComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) objetId!: string;

  ouvert = false;
  chargement = false;
  erreur = '';
  lignes: AuditLogAdminEntry[] = [];
  private destroy$ = new Subject<void>();

  constructor(private auditLogService: AuditLogService) {}

  ngOnChanges(): void {
    // Autre fiche affichée dans la même modale : on referme, rien n'est chargé d'avance.
    this.ouvert = false;
    this.lignes = [];
  }

  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  ouvrir(): void {
    this.ouvert = true;
    this.chargement = true;
    this.erreur = '';
    this.auditLogService.browse(
      { masquer_systeme: true, criteres: [{ cle: 'objet', valeur: this.objetId, libelle: '', exclu: false }] }, 1, 10,
    ).pipe(takeUntil(this.destroy$)).subscribe({
      next: (page) => { this.lignes = page.results; this.chargement = false; },
      error: () => { this.erreur = 'Historique indisponible pour votre compte.'; this.chargement = false; },
    });
  }

  comment(l: AuditLogAdminEntry): string {
    switch (l.exposition) {
      case 'FICHE': return 'fiche ouverte';
      case 'LISTE': return 'liste avec coordonnées';
      case 'LISTE_SANS_COORDONNEES': return 'liste sans coordonnées';
      case 'EXPORT': return 'export';
      default: return (l.action_libelle ?? '').toLowerCase();
    }
  }
}
