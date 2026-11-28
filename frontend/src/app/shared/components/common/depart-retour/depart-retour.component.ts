import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { environment } from '../../../../../environments/environment';

/** Où en est la personne, et où elle peut partir (voir core/engagements_personnels.py). */
export interface MonEngagement {
  en_cours: { crise: string; crise_nom: string; equipe_nom: string | null; parti_le: string;
              depart_de?: string; hebergement?: string;
              /** Relevé kilométrique (28/11/2026). */
              vehicule_personnel?: string | null; compteur_depart?: string } | null;
  /** Mes véhicules déclarés : on choisit au départ celui avec lequel on part. */
  vehicules?: { id: string; designation: string }[];
  /** `hebergement` : le logement de la personne sur cette crise, si elle y est en déplacement
   * sur site — elle part alors de là, et y rentre. */
  crises: { id: string; nom: string; hebergement?: string }[];
  equipes: { id: string; nom: string }[];
  /** Les manifestations du jour où je suis inscrit (26/11/2026) : on part aussi pour elles. */
  manifestations?: { id: string; nom: string; debut: string; fin: string }[];
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
    @if (etat && (etat.en_cours || etat.crises.length || manifestations.length)) {
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
          <span class="deplacement">
            @if (e.compteur_depart) {
              <label>Compteur à l'arrivée <input type="text" inputmode="numeric" maxlength="9" [(ngModel)]="compteurArrivee" [placeholder]="'départ : ' + e.compteur_depart"></label>
            } @else {
              <label>Km aller-retour <input type="text" inputmode="decimal" maxlength="7" [(ngModel)]="kilometres" placeholder="facultatif"></label>
            }
            <label>Péage <input type="text" inputmode="decimal" maxlength="7" [(ngModel)]="peage" placeholder="€"></label>
            <label>Stationnement <input type="text" inputmode="decimal" maxlength="7" [(ngModel)]="stationnement" placeholder="€"></label>
          </span>
          <button type="button" class="btn-primary" [disabled]="envoi" (click)="geste('rentrer')">Je rentre</button>
        } @else {
          <p><span class="material-icons">schedule</span> Déclarez votre départ : c'est ce qui compte le temps que vous passez sur
            {{ etat.crises.length ? 'la crise' : 'la manifestation' }}.</p>
          @if (etat.crises.length + manifestations.length > 1) {
            <label>Pour
              <select [(ngModel)]="cible" (ngModelChange)="choisir($event)">
                @for (c of etat.crises; track c.id) { <option [value]="'c:' + c.id">{{ c.nom }}</option> }
                @for (m of manifestations; track m.id) { <option [value]="'m:' + m.id">{{ m.nom }} ({{ m.debut | date:'HH:mm' }})</option> }
              </select></label>
          }
          @if (etat.equipes.length > 1 && !cible.startsWith('m:')) {
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
          @if (vehicules.length) {
            <span class="deplacement">
              <label>Avec
                <select [(ngModel)]="vehicule">
                  <option value="">— sans mon véhicule —</option>
                  @for (v of vehicules; track v.id) { <option [value]="v.id">{{ v.designation }}</option> }
                </select></label>
              @if (vehicule) {
                <label>Compteur au départ <input type="text" inputmode="numeric" maxlength="9" [(ngModel)]="compteurDepart" placeholder="facultatif"></label>
              }
            </span>
          }
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
    .deplacement { display: inline-flex; flex-wrap: wrap; gap: .4rem .8rem; align-items: center; }
    .deplacement input { width: 6.5rem; }
  `],
})
export class DepartRetourComponent implements OnInit {
  /** Lien vers le relevé complet ; inutile quand le bloc est posé sur cette page-là. */
  @Input() lienReleve = true;

  etat: MonEngagement | null = null;
  /** D'où l'on part, puis où l'on rentre : domicile, ou hébergement si l'on est logé sur site. */
  lieu = 'DOMICILE';
  crise = '';
  /** « c:<crise> » ou « m:<manifestation> » : ce pour quoi on part. */
  cible = '';
  equipe = '';
  envoi = false;
  erreur = '';
  // Relevé kilométrique (28/11/2026) : tout est facultatif, et se complète ensuite dans Mon relevé.
  vehicule = '';
  compteurDepart = '';
  compteurArrivee = '';
  kilometres = '';
  peage = '';
  stationnement = '';

  private readonly url = `${environment.apiUrl}/mon-engagement/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    // Un échec de lecture ne casse pas la page qui héberge le bloc : il ne s'affiche pas.
    this.http.get<MonEngagement>(this.url).subscribe({ next: (etat) => this.recevoir(etat), error: () => {} });
  }

  private recevoir(etat: MonEngagement): void {
    this.etat = etat;
    if (!etat.crises.some(c => c.id === this.crise)) this.crise = etat.crises[0]?.id ?? '';
    const cibles = [...etat.crises.map(c => `c:${c.id}`), ...(etat.manifestations ?? []).map(m => `m:${m.id}`)];
    if (!cibles.includes(this.cible)) this.cible = cibles[0] ?? '';
    // Une seule équipe : on part avec elle sans le demander.
    if (etat.equipes.length === 1) this.equipe = etat.equipes[0].id;
    // Logé sur site, on part de son logement ; parti, on rentre par défaut d'où l'on vient.
    this.lieu = etat.en_cours ? (etat.en_cours.depart_de || 'DOMICILE') : (this.hebergement ? 'HEBERGEMENT' : 'DOMICILE');
    if (etat.vehicules?.length === 1 && !this.vehicule) this.vehicule = etat.vehicules[0].id;
    this.compteurDepart = this.compteurArrivee = this.kilometres = this.peage = this.stationnement = '';
  }

  get vehicules(): NonNullable<MonEngagement['vehicules']> { return this.etat?.vehicules ?? []; }

  get manifestations(): NonNullable<MonEngagement['manifestations']> { return this.etat?.manifestations ?? []; }

  choisir(cible: string): void {
    this.cible = cible;
    if (cible.startsWith('c:')) this.crise = cible.slice(2);
  }

  get hebergement(): string {
    return this.etat?.crises.find(c => c.id === this.crise)?.hebergement ?? '';
  }

  geste(geste: 'partir' | 'rentrer'): void {
    this.envoi = true;
    this.erreur = '';
    const depart = this.vehicule ? { vehicule_personnel: this.vehicule, compteur_depart: this.compteurDepart } : {};
    // Seul ce qui est saisi part : rentrer sans rien dire reste le geste d'avant.
    const retour: Record<string, string> = {};
    for (const [cle, valeur] of [['compteur_arrivee', this.compteurArrivee], ['kilometres', this.kilometres],
                                 ['peage', this.peage], ['stationnement', this.stationnement]]) {
      if (valeur.trim()) retour[cle] = valeur.trim();
    }
    const corps = geste !== 'partir' ? { geste, retour_a: this.lieu, ...retour }
      : this.cible.startsWith('m:') ? { geste, manifestation: this.cible.slice(2), depart_de: this.lieu, ...depart }
      : { geste, crise: this.crise, equipe: this.equipe || null, depart_de: this.lieu, ...depart };
    this.http.post<MonEngagement>(this.url, corps).subscribe({
      next: (etat) => { this.envoi = false; this.recevoir(etat); },
      error: (err) => { this.envoi = false; this.erreur = err?.error?.detail || "La déclaration n'a pas pu être enregistrée."; },
    });
  }
}
