import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { environment } from '../../../../../environments/environment';

/** Où en est la personne, et où elle peut partir (voir core/engagements_personnels.py). */
export interface MonEngagement {
  en_cours: { crise: string; crise_nom: string; equipe_nom: string | null; parti_le: string;
              depart_de?: string; hebergement?: string } | null;
  /** `hebergement` : le logement de la personne sur cette crise, si elle y est en déplacement
   * sur site — elle part alors de là, et y rentre. */
  crises: { id: string; nom: string; hebergement?: string }[];
  equipes: { id: string; nom: string }[];
}

/**
 * « Je pars », « je rentre » : les deux gestes par lesquels un agent ou un bénévole déclare
 * le temps qu'il passe sur une crise (17/11/2026).
 *
 * Deux boutons et rien à saisir. L'heure est celle du serveur au moment du geste. Le bloc ne
 * s'affiche que s'il y a quelque chose à déclarer : une crise en cours qui concerne
 * l'institution ou les équipes de la personne, ou un départ pas encore refermé.
 */
@Component({
  selector: 'app-depart-retour',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    @if (etat && (etat.en_cours || etat.crises.length)) {
      <section class="depart-retour" [class.parti]="etat.en_cours">
        @if (etat.en_cours; as e) {
          <p>
            <span class="material-icons">directions_run</span>
            Vous êtes parti sur <strong>{{ e.crise_nom }}</strong>@if (e.equipe_nom) { avec {{ e.equipe_nom }} }
            depuis le {{ e.parti_le | date:'dd/MM à HH:mm' }}.
          </p>
          <label>Je rentre
            <select [(ngModel)]="lieu">
              <option value="DOMICILE">à mon domicile</option>
              <option value="HEBERGEMENT">à mon hébergement sur site</option>
            </select></label>
          <button type="button" class="btn-primary" [disabled]="envoi" (click)="geste('rentrer')">Je rentre</button>
        } @else {
          <p><span class="material-icons">schedule</span> Déclarez votre départ : c'est ce qui compte le temps que vous passez sur la crise.</p>
          @if (etat.crises.length > 1) {
            <label>Crise
              <select [(ngModel)]="crise">
                @for (c of etat.crises; track c.id) { <option [value]="c.id">{{ c.nom }}</option> }
              </select></label>
          }
          @if (etat.equipes.length > 1) {
            <label>Avec
              <select [(ngModel)]="equipe">
                <option value="">— sans équipe —</option>
                @for (q of etat.equipes; track q.id) { <option [value]="q.id">{{ q.nom }}</option> }
              </select></label>
          }
          <label>Je pars
            <select [(ngModel)]="lieu">
              <option value="DOMICILE">de mon domicile</option>
              <option value="HEBERGEMENT">de mon hébergement sur site{{ hebergement ? ' (' + hebergement + ')' : '' }}</option>
            </select></label>
          <button type="button" class="btn-primary" [disabled]="envoi" (click)="geste('partir')">Je pars</button>
        }
        @if (lienReleve) { <a routerLink="/mon-releve" class="releve">Mon relevé d'heures</a> }
        @if (erreur) { <p class="erreur" role="alert">{{ erreur }}</p> }
      </section>
    }
  `,
  styles: [`
    .depart-retour { display: flex; flex-wrap: wrap; gap: .6rem 1rem; align-items: center; padding: .7rem 1rem; margin: 0 0 1rem;
      border: 1px solid var(--ac-border, #e5e7eb); border-left: 4px solid #1d4ed8; border-radius: 8px; background: var(--ac-surface, #fff); }
    .depart-retour.parti { border-left-color: #b45309; }
    p { margin: 0; flex: 1 1 16rem; display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
    .erreur { flex-basis: 100%; color: #b91c1c; }
    .releve { font-size: .9rem; }
    .material-icons { font-size: 1.2rem; }
  `],
})
export class DepartRetourComponent implements OnInit {
  /** Lien vers le relevé complet ; inutile quand le bloc est posé sur cette page-là. */
  @Input() lienReleve = true;

  etat: MonEngagement | null = null;
  /** D'où l'on part, puis où l'on rentre : domicile, ou hébergement si l'on est logé sur site. */
  lieu = 'DOMICILE';
  crise = '';
  equipe = '';
  envoi = false;
  erreur = '';

  private readonly url = `${environment.apiUrl}/mon-engagement/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    // Un échec de lecture ne casse pas la page qui héberge le bloc : il ne s'affiche pas.
    this.http.get<MonEngagement>(this.url).subscribe({ next: (etat) => this.recevoir(etat), error: () => {} });
  }

  private recevoir(etat: MonEngagement): void {
    this.etat = etat;
    if (!etat.crises.some(c => c.id === this.crise)) this.crise = etat.crises[0]?.id ?? '';
    // Une seule équipe : on part avec elle sans le demander.
    if (etat.equipes.length === 1) this.equipe = etat.equipes[0].id;
    // Logé sur site, on part de son logement ; parti, on rentre par défaut d'où l'on vient.
    this.lieu = etat.en_cours ? (etat.en_cours.depart_de || 'DOMICILE') : (this.hebergement ? 'HEBERGEMENT' : 'DOMICILE');
  }

  get hebergement(): string {
    return this.etat?.crises.find(c => c.id === this.crise)?.hebergement ?? '';
  }

  geste(geste: 'partir' | 'rentrer'): void {
    this.envoi = true;
    this.erreur = '';
    const corps = geste === 'partir'
      ? { geste, crise: this.crise, equipe: this.equipe || null, depart_de: this.lieu }
      : { geste, retour_a: this.lieu };
    this.http.post<MonEngagement>(this.url, corps).subscribe({
      next: (etat) => { this.envoi = false; this.recevoir(etat); },
      error: (err) => { this.envoi = false; this.erreur = err?.error?.detail || "La déclaration n'a pas pu être enregistrée."; },
    });
  }
}
