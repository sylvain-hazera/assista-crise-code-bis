import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { StockService } from '../../../../services/stock.service';
import { DisponibiliteStock } from '../../../models/stock.model';

/**
 * Face à une demande de matériel : « on l'a en stock ? », et si oui, « réserver pour cette
 * demande ». Deux boutons, pour que celui qui traite la demande n'ait pas à ouvrir la page
 * Stocks et à chercher : on part de ce que la demande réclame, et on dit où c'est.
 *
 * Réserver met de côté sans sortir : l'objet reste au dépôt, mais plus personne d'autre ne peut
 * le prendre. Il sortira quand la personne viendra (page Stocks, « Remettre »).
 */
@Component({
  selector: 'app-stock-pour-demande',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="stock-demande">
      @if (!resultat) {
        <button type="button" class="btn-secondary" [disabled]="cherche" (click)="chercher()">
          <span class="material-icons">inventory_2</span> {{ cherche ? 'Recherche…' : 'On l’a en stock ?' }}</button>
      } @else {
        <form class="recherche" (ngSubmit)="chercher()">
          <label>Chercher dans le stock
            <input type="search" name="mot" [(ngModel)]="mot" placeholder="couverture, pompe, lit de camp…"></label>
          <button type="submit" class="btn-secondary" [disabled]="cherche">Chercher</button>
          <button type="button" class="lien" (click)="resultat = null">fermer</button>
        </form>
        @if (!resultat.articles.length) {
          <p class="note">@if (resultat.cherche) { Rien dans votre stock ne correspond à « {{ resultat.cherche }} ». } @else { Dites ce que vous cherchez. }</p>
        }
        @for (a of resultat.articles; track a.article) {
          <div class="article">
            <strong>{{ a.designation }}</strong> — {{ nombre(a.libre) }} {{ a.unite }} de libre
            @for (l of a.lieux; track l.depot) {
              <div class="lieu">
                <span>{{ l.depot_nom }}@if (l.au_point) { (point d'accueil) } : {{ nombre(l.libre) }} libre(s)@if (+l.reserve > 0) { — {{ nombre(l.reserve) }} déjà réservé(s) }</span>
                @if (+l.libre > 0) {
                  <input type="number" min="1" [max]="+l.libre" step="any" [name]="'q' + l.depot" [(ngModel)]="quantites[a.article + l.depot]"
                         [attr.aria-label]="'Quantité à réserver dans ' + l.depot_nom">
                  <button type="button" class="btn-primary" [disabled]="envoi || !quantites[a.article + l.depot]" (click)="reserver(a.article, l.depot, l.depot_nom)">
                    Réserver pour cette demande</button>
                }
              </div>
            } @empty { <div class="note">Aucun en stock en ce moment.</div> }
          </div>
        }
      }
      @if (message) { <p class="message" role="status">{{ message }}</p> }
      @if (erreur) { <p class="message erreur" role="alert">{{ erreur }}</p> }
    </div>`,
  styles: [`.stock-demande { display: grid; gap: .5rem; font-size: .9rem; }
    .recherche, .lieu { display: flex; flex-wrap: wrap; gap: .5rem; align-items: end; }
    .lieu { align-items: center; padding: .25rem 0 .25rem .8rem; }
    label { display: grid; gap: .2rem; font-weight: 600; font-size: .85rem; }
    input { font: inherit; font-weight: 400; padding: .35rem .5rem; } input[type=number] { width: 5.5rem; }
    .article { padding: .5rem .6rem; border: 1px solid var(--ac-border, #e5e7eb); border-radius: 6px; }
    .note { margin: 0; color: var(--ac-text-muted, #6b7280); }
    .lien { font: inherit; background: none; border: 0; padding: 0; color: #1d4ed8; cursor: pointer; text-decoration: underline; }
    .message { margin: 0; padding: .45rem .6rem; border-left: 4px solid #1d4ed8; background: var(--ac-blue-bg, #eff6ff); }
    .message.erreur { border-left-color: #b91c1c; background: var(--ac-red-bg, #fef2f2); }`],
})
export class StockPourDemandeComponent implements OnChanges {
  /** La demande d'aide traitée : la réservation lui sera rattachée. */
  @Input() demande: string | null = null;
  /** Ce qu'on cherche si la demande ne désigne pas un matériel du catalogue (le titre du dossier). */
  @Input() indice = '';

  resultat: DisponibiliteStock | null = null;
  mot = '';
  quantites: Record<string, number | null> = {};
  cherche = false;
  envoi = false;
  message = '';
  erreur = '';

  constructor(private stocks: StockService) {}

  ngOnChanges(): void { this.resultat = null; this.mot = ''; this.quantites = {}; this.message = this.erreur = ''; }

  /** Première recherche : d'après le matériel que la demande réclame ; ensuite, d'après le mot saisi. */
  chercher(): void {
    const critere = this.resultat || !this.demande ? { recherche: (this.mot || this.indice).trim() } : { demande: this.demande };
    this.cherche = true;
    this.erreur = this.message = '';
    this.stocks.disponibilite(critere).subscribe({
      next: (d) => { this.cherche = false; this.resultat = d; this.mot = this.mot || d.cherche || this.indice; },
      error: (e) => { this.cherche = false; this.erreur = e?.error?.detail || 'Votre stock n’a pas pu être consulté.'; },
    });
  }

  reserver(article: string, depot: string, depotNom: string): void {
    const quantite = this.quantites[article + depot];
    if (!quantite || quantite <= 0) return;
    this.envoi = true;
    this.erreur = this.message = '';
    this.stocks.reserver({ article, depot, quantite, ...(this.demande ? { demande: this.demande } : {}) }).subscribe({
      next: (r) => {
        this.envoi = false;
        this.quantites[article + depot] = null;
        this.message = `Réservé pour cette demande : ${this.nombre(r.quantite)} ${r.unite} de ${r.article_designation}, dans ${depotNom}. `
          + 'Il sortira du stock quand vous le remettrez (page Stocks, « Remettre »).';
        this.resultat = null;
      },
      error: (e) => { this.envoi = false; this.erreur = e?.error?.detail || 'Cette réservation n’a pas pu être faite.'; },
    });
  }

  nombre(valeur: string | number): string { return (+valeur).toLocaleString('fr-FR', { maximumFractionDigits: 3 }); }
}
