import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { environment } from '../../../environments/environment';

export interface DemandeAdhesionAdmin {
  id: string; nom: string; activite: string; commune_nom: string; echelon_libelle: string; territoire: string;
  agrement: string; statut: string; statut_libelle: string; motif_refus: string; date_demande: string;
  demandeur: string; demandeur_email: string; fonction: string; telephone: string;
  doublons: { id: string; nom: string; commune_nom: string }[];
}

/**
 * Les associations existantes qui demandent à rejoindre le réseau (26/11/2026) : l'administrateur
 * vérifie qu'il ne s'agit pas d'un doublon, puis accepte (l'association est créée, le demandeur en
 * devient le bureau) ou refuse avec un motif.
 */
@Component({
  selector: 'app-adhesions-associations',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page">
      <h1><span class="material-icons">group_add</span> Adhésions d'associations</h1>
      <p class="chapeau">Des associations qui existent déjà demandent à rejoindre le réseau. Vérifiez surtout qu'il ne s'agit
        pas d'un doublon : à l'acceptation, l'association est créée et le demandeur en devient le bureau.</p>
      <nav class="onglets">
        @for (s of statuts; track s.code) {
          <button type="button" [class.actif]="statut === s.code" (click)="statut = s.code; charger()">{{ s.libelle }}</button>
        }
      </nav>
      @if (erreur) { <p class="message erreur" role="alert">{{ erreur }}</p> }
      @if (message) { <p class="message" role="status">{{ message }}</p> }
      @for (d of demandes; track d.id) {
        <article class="demande">
          <header>
            <h2>{{ d.nom }}</h2>
            <span class="note">{{ d.date_demande | date:'dd/MM/yyyy' }}</span>
          </header>
          <p>{{ d.activite }}</p>
          <dl>
            <dt>Siège</dt><dd>{{ d.commune_nom }}</dd>
            <dt>Intervient jusqu'à</dt><dd>{{ d.echelon_libelle }}@if (d.territoire && d.echelon_libelle !== d.territoire) { ({{ d.territoire }}) }</dd>
            <dt>Agrément</dt><dd>{{ d.agrement || 'non agréée' }}</dd>
            <dt>Demandeur</dt><dd>{{ d.demandeur }}@if (d.fonction) { , {{ d.fonction }} } — {{ d.demandeur_email }}@if (d.telephone) { · {{ d.telephone }} }</dd>
          </dl>
          @if (d.doublons.length) {
            <p class="alerte">Nom proche d'une association déjà inscrite :
              @for (x of d.doublons; track x.id) { <strong>{{ x.nom }}</strong>@if (x.commune_nom) { ({{ x.commune_nom }}) } }</p>
          }
          @if (d.statut === 'EN_ATTENTE') {
            <div class="actions">
              <button type="button" class="btn-primary" (click)="traiter(d, 'accepter')">Accepter</button>
              @if (aRefuser === d.id) {
                <input type="text" maxlength="300" [(ngModel)]="motif" placeholder="Motif envoyé au demandeur" aria-label="Motif du refus">
                <button type="button" class="btn-secondary" (click)="traiter(d, 'refuser')">Refuser</button>
              } @else {
                <button type="button" class="lien" (click)="aRefuser = d.id; motif = ''">Refuser…</button>
              }
            </div>
          } @else {
            <p><span class="pastille" [class.ok]="d.statut === 'ACCEPTEE'">{{ d.statut_libelle }}</span>
              @if (d.motif_refus) { <span class="note">{{ d.motif_refus }}</span> }</p>
          }
        </article>
      } @empty {
        <p class="note">Aucune demande.</p>
      }
    </div>
  `,
  styles: [`
    .page { max-width: 60rem; margin: 0 auto; padding: 1rem 16px 3rem; }
    h1 { display: flex; align-items: center; gap: .5rem; margin: 0 0 .3rem; }
    h2 { margin: 0; font-size: 1.1rem; }
    .chapeau, .note { color: var(--ac-text-muted, #6b7280); }
    .note { font-size: .85rem; }
    .message { padding: .6rem .8rem; border-left: 4px solid #1d4ed8; background: var(--ac-blue-bg, #eff6ff); margin: .5rem 0; }
    .message.erreur { border-left-color: #b91c1c; background: var(--ac-red-bg, #fef2f2); }
    .onglets { display: flex; gap: .25rem; border-bottom: 1px solid var(--ac-border, #e5e7eb); margin: .8rem 0;
      button { font: inherit; padding: .45rem .9rem; border: 0; border-bottom: 3px solid transparent; background: none; cursor: pointer; color: inherit; }
      button.actif { border-bottom-color: #1d4ed8; font-weight: 600; } }
    .demande { padding: .9rem 1rem; border: 1px solid var(--ac-border, #e5e7eb); border-radius: 8px; background: var(--ac-surface, #fff); margin: 0 0 .8rem;
      header { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
      p { margin: .4rem 0; } }
    dl { display: grid; grid-template-columns: max-content 1fr; gap: .2rem .8rem; margin: .4rem 0; dt { font-weight: 600; } dd { margin: 0; } }
    .alerte { padding: .45rem .7rem; border-left: 4px solid #b45309; background: var(--ac-orange-bg, #fffbeb); }
    .actions { display: flex; flex-wrap: wrap; gap: .5rem .75rem; align-items: center; margin-top: .5rem;
      input { flex: 1 1 16rem; font: inherit; padding: .4rem .5rem; border: 1px solid var(--ac-border-strong, #d1d5db); border-radius: 6px; } }
    .pastille { display: inline-block; padding: .05rem .5rem; border-radius: 999px; font-size: .75rem; color: #fff; background: #b91c1c; }
    .pastille.ok { background: #15803d; }
    .lien { font: inherit; background: none; border: 0; padding: 0; color: #1d4ed8; cursor: pointer; text-decoration: underline; }
    .btn-primary, .btn-secondary { padding: .45rem 1rem; border-radius: 6px; cursor: pointer; font: inherit; font-size: .9rem; }
    .btn-primary { border: 1px solid #2563eb; background: #2563eb; color: #fff; }
    .btn-secondary { border: 1px solid var(--ac-border-strong, #d1d5db); background: var(--ac-surface-2, #f9fafb); color: var(--ac-text, #374151); }
  `],
})
export class AdhesionsAssociationsComponent implements OnInit {
  demandes: DemandeAdhesionAdmin[] = [];
  statut = 'EN_ATTENTE';
  readonly statuts = [{ code: 'EN_ATTENTE', libelle: 'En attente' }, { code: 'ACCEPTEE', libelle: 'Acceptées' }, { code: 'REFUSEE', libelle: 'Refusées' }];
  erreur = '';
  message = '';
  aRefuser: string | null = null;
  motif = '';

  private readonly url = `${environment.apiUrl}/associations/demandes/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.http.get<{ demandes: DemandeAdhesionAdmin[] }>(this.url, { params: { toutes: '1', statut: this.statut } }).subscribe({
      next: (r) => this.demandes = r.demandes,
      error: (err) => this.erreur = err?.error?.detail || 'Les demandes n\'ont pas pu être chargées.',
    });
  }

  traiter(d: DemandeAdhesionAdmin, geste: 'accepter' | 'refuser'): void {
    if (geste === 'refuser' && !this.motif.trim()) { this.erreur = 'Dites pourquoi vous refusez : le demandeur le lira.'; return; }
    if (geste === 'accepter' && d.doublons.length && !confirm(`Un nom proche existe déjà. Créer quand même « ${d.nom} » ?`)) return;
    this.erreur = '';
    this.http.post(`${this.url}${d.id}/`, { geste, motif: this.motif.trim() }).subscribe({
      next: () => { this.aRefuser = null; this.message = geste === 'accepter' ? `${d.nom} a rejoint le réseau ; le demandeur est prévenu.` : 'Demande refusée.'; this.charger(); },
      error: (err) => this.erreur = err?.error?.detail || 'La demande n\'a pas pu être traitée.',
    });
  }
}
