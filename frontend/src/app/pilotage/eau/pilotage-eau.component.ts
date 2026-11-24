import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ActivationPointEau, PilotageService } from '../pilotage.service';
import { MiniCartePointsEauComponent } from './mini-carte-points-eau.component';

/**
 * Le circuit réflexe des points d'eau en feu de forêt (24/11/2026) : la cellule choisit à chaud
 * les points autour du feu et l'équipe envoyée sur chacun, puis suit les binômes (en route,
 * pompe en place, fermé) et la prévenance du CODIS (email, accusé, tâche d'appel, carte en
 * direct sans compte). Relu toutes les 30 s par le service du pilotage.
 */
@Component({
  selector: 'app-pilotage-eau',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, MiniCartePointsEauComponent],
  template: `
    <h1>Points d'eau</h1>
    @if (!pilotage.criseId()) {
      <p class="vide">Choisissez une crise dans la barre du haut.</p>
    } @else if (!pilotage.circuitEau()) {
      <p class="vide">Chargement…</p>
    } @else {
      @let c = pilotage.circuitEau()!;
      @if (c.propose) {
        <p class="proposition"><span class="material-icons" aria-hidden="true">local_fire_department</span>
          Feu en cours : choisissez les points d'eau à ouvrir et l'équipe envoyée sur chacun, puis activez.</p>
      }
      @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }

      @if (c.activations.length || c.candidats?.length) {
        <app-mini-carte-points-eau [candidats]="c.peut_piloter ? (c.candidats || []) : []" [activations]="c.activations"
                                   [choix]="choix" (basculer)="basculer($event)" />
      }

      @if (c.activations.length) {
        <section>
          <h2>Points ouverts <span class="discret">({{ c.actifs }} actif(s), remplissage possible)</span></h2>
          <div class="tableau-defilant"><table>
            <thead><tr><th>Point d'eau</th><th>Équipe</th><th>État</th><th>Depuis</th>@if (c.peut_piloter) { <th></th> }</tr></thead>
            <tbody>
              @for (a of c.activations; track a.id) {
                <tr [attr.data-statut]="a.statut">
                  <td><a [href]="lienCarte(a)" target="_blank" rel="noopener">{{ a.nom }}</a>
                    @if (a.debit) { <span class="discret"> · {{ a.debit | number:'1.0-0' }} m³/h</span> }
                    @if (a.gps) {
                      <span class="coordonnees">GPS {{ a.gps }}@if (a.lambert93) { · Lambert 93 X {{ a.lambert93.x }} Y {{ a.lambert93.y }} }</span>
                    }</td>
                  <td>{{ a.indicatif || a.equipe || '—' }}</td>
                  <td><span class="etat">{{ a.statut_libelle }}</span></td>
                  <td>{{ depuis(a) | date:'HH:mm' }}</td>
                  @if (c.peut_piloter) {
                    <td class="gestes">
                      @if (a.statut === 'DEMANDE' || a.statut === 'EN_ROUTE' || a.statut === 'FERME') {
                        <button type="button" class="petit" [disabled]="occupe()" (click)="etat(a, 'ACTIF')">Actif</button>
                      }
                      @if (a.statut === 'ACTIF') {
                        <button type="button" class="petit" [disabled]="occupe()" (click)="etat(a, 'FERME')">Fermer</button>
                      }
                      @if (a.statut === 'DEMANDE' || a.statut === 'EN_ROUTE') {
                        <button type="button" class="petit discret" [disabled]="occupe()" (click)="etat(a, 'ANNULE')">Annuler</button>
                      }
                    </td>
                  }
                </tr>
              }
            </tbody>
          </table></div>
        </section>
      }

      <section class="codis">
        <h2>CODIS</h2>
        @if (!c.interlocuteurs_codis) {
          <p class="alerte">Aucun contact SDIS (CODIS) dans l'annuaire de crise de votre institution : ajoutez-le dans
            « Annuaire de crise » pour qu'il soit prévenu par email à chaque point ouvert.</p>
        }
        @if (c.codis_sans_accuse) {
          <p class="alerte">{{ c.codis_sans_accuse }} prévenance(s) sans accusé de réception : appelez le CODIS (tâche dans la cellule).</p>
        }
        @for (p of c.prevenances_codis.slice(0, 6); track p.id) {
          <p class="discret">{{ p.point }} — {{ p.organisme || 'CODIS' }} : {{ p.statut_libelle }}
            @if (p.envoye_le) { ({{ p.envoye_le | date:'HH:mm' }}) }@if (p.accuse_le) { · accusé à {{ p.accuse_le | date:'HH:mm' }} }</p>
        }
        @if (c.peut_piloter) {
          <div class="lien">
            @if (c.lien_codis) {
              <input type="text" readonly [value]="c.lien_codis" aria-label="Lien de la carte du CODIS">
              <button type="button" class="petit" (click)="copier(c.lien_codis)">{{ copie() ? 'Copié' : 'Copier' }}</button>
              <button type="button" class="petit discret" (click)="lien('renouveler')">Renouveler</button>
              <button type="button" class="petit discret" (click)="lien('revoquer')">Révoquer</button>
            } @else {
              <button type="button" class="petit" (click)="lien('creer')">Créer le lien de la carte CODIS</button>
            }
          </div>
          <p class="discret">Le lien ouvre, sans compte, la carte des points d'eau de la crise (aucun nom de personne). Il est
            joint à chaque email au CODIS.</p>
        }
      </section>

      @if (c.peut_piloter) {
        <section>
          <h2>Ouvrir des points d'eau</h2>
          @if (!c.candidats?.length) {
            <p class="vide">Aucun point d'eau connu autour de la crise. Les points se signalent depuis l'application
              (« Point d'eau » sur la carte) ou s'importent depuis la base du SDIS.</p>
          } @else {
            <div class="candidats">
              @for (p of c.candidats; track p.id) {
                <label class="candidat" [class.choisi]="choix[p.id]">
                  <input type="checkbox" [(ngModel)]="choix[p.id]">
                  <span class="libelle">
                    <strong>{{ p.nom || p.type_libelle + (p.ref_terrain ? ' ' + p.ref_terrain : '') }}</strong>
                    @if (p.adresse) { <span class="adresse">{{ p.adresse }}</span> }
                    @if (p.gps) {
                      <span class="coordonnees">GPS {{ p.gps }}@if (p.lambert93) { · Lambert 93 X {{ p.lambert93.x }} Y {{ p.lambert93.y }} }</span>
                    }
                    <span class="discret">{{ p.distance_km | number:'1.1-1' }} km
                      @if (p.debit) { · {{ p.debit | number:'1.0-0' }} m³/h }@if (p.volume) { · {{ p.volume | number:'1.0-0' }} m³ }
                      · {{ p.source === 'OSM' ? 'OSM, indicatif' : p.source === 'SDIS' ? 'SDIS' : 'validé commune' }}
                      @if (p.etat === 'INDISPONIBLE') { · <span class="rouge">indisponible</span> }</span>
                  </span>
                  @if (choix[p.id]) {
                    <select [(ngModel)]="equipes[p.id]" [attr.aria-label]="'Équipe pour ' + p.type_libelle">
                      <option [ngValue]="undefined" disabled>Équipe envoyée…</option>
                      @for (e of c.equipes || []; track e.id) { <option [ngValue]="e.id">{{ e.indicatif || e.nom }} ({{ e.effectif }})</option> }
                    </select>
                  }
                </label>
              }
            </div>
            <button type="button" class="activer" [disabled]="occupe() || !nbChoisis()" (click)="activer()">
              Activer {{ nbChoisis() || '' }} point(s) d'eau
            </button>
          }
        </section>
      }
    }
  `,
  styles: [`
    :host { display: block; padding: 1rem; max-width: 60rem; }
    h1 { margin: 0 0 .75rem; font-size: 1.4rem; }
    h2 { font-size: 1.05rem; margin: 1.25rem 0 .5rem; }
    section { display: flex; flex-direction: column; gap: .4rem; }
    .vide, .discret { color: var(--ac-text-muted, #6b7280); }
    .discret { font-size: .85rem; margin: 0; }
    .proposition, .alerte, .erreur { display: flex; gap: .5rem; align-items: center; padding: .6rem .8rem; border-radius: 8px; margin: 0; }
    .proposition { background: var(--ac-amber-bg, #fffbeb); color: var(--ac-orange-text, #92400e); font-weight: 600; }
    .alerte, .erreur { background: var(--ac-red-bg, #fef2f2); color: var(--ac-red-text, #b91c1c); }
    .tableau-defilant { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
    th, td { text-align: left; padding: .45rem .5rem; border-bottom: 1px solid var(--ac-border, #e5e7eb); }
    tr[data-statut='ACTIF'] .etat { color: #15803d; font-weight: 700; }
    tr[data-statut='FERME'], tr[data-statut='ANNULE'] { opacity: .6; }
    .gestes { display: flex; gap: .3rem; flex-wrap: wrap; }
    .petit { padding: .35rem .7rem; border-radius: 6px; border: 1px solid var(--ac-border, #d1d5db); background: var(--ac-surface, #fff); cursor: pointer; }
    .petit.discret { color: var(--ac-text-muted, #6b7280); }
    .lien { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; }
    .lien input { flex: 1 1 16rem; min-width: 0; padding: .4rem .6rem; border: 1px solid var(--ac-border, #d1d5db); border-radius: 6px; }
    .candidats { display: flex; flex-direction: column; gap: .35rem; }
    .adresse, .coordonnees { display: block; font-size: .82rem; color: var(--ac-text-muted, #9ca3af); }
    .coordonnees { font-variant-numeric: tabular-nums; }
    .candidat { display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; padding: .55rem .7rem; border: 1px solid var(--ac-border, #e5e7eb); border-radius: 8px; cursor: pointer; }
    .candidat.choisi { border-color: #1d4ed8; background: var(--ac-blue-bg, #eff6ff); }
    .candidat .libelle { display: flex; flex-direction: column; flex: 1 1 14rem; min-width: 0; }
    .candidat select { flex: 0 1 14rem; min-width: 0; padding: .35rem; }
    .rouge { color: var(--ac-red-text, #b91c1c); }
    .activer { align-self: flex-start; margin-top: .5rem; padding: .7rem 1.2rem; border: none; border-radius: 8px; background: #b91c1c; color: #fff; font-weight: 700; font-size: 1rem; cursor: pointer; }
    .activer:disabled { opacity: .5; cursor: default; }
  `],
})
export class PilotageEauComponent implements OnInit {
  readonly pilotage = inject(PilotageService);
  readonly occupe = signal(false);
  readonly erreur = signal<string | null>(null);
  readonly copie = signal(false);
  choix: Record<number, boolean> = {};
  equipes: Record<number, string | undefined> = {};

  ngOnInit(): void { this.pilotage.rafraichirCircuitEau(true); }

  /** Un point touché sur la mini-carte : coché ou décoché, comme dans la liste. */
  basculer(id: number): void { this.choix = { ...this.choix, [id]: !this.choix[id] }; }

  nbChoisis(): number { return Object.values(this.choix).filter(Boolean).length; }

  depuis(a: ActivationPointEau): string {
    return ({ ACTIF: a.actif_le, EN_ROUTE: a.en_route_le, FERME: a.ferme_le } as Record<string, string | null>)[a.statut] || a.demande_le;
  }

  lienCarte(a: ActivationPointEau): string {
    return `https://www.openstreetmap.org/?mlat=${a.latitude}&mlon=${a.longitude}#map=17/${a.latitude}/${a.longitude}`;
  }

  async activer(): Promise<void> {
    const choisis = Object.entries(this.choix).filter(([, v]) => v).map(([k]) => Number(k));
    const sansEquipe = choisis.filter(id => !this.equipes[id]);
    if (sansEquipe.length) { this.erreur.set('Choisissez l\'équipe envoyée sur chaque point coché.'); return; }
    this.erreur.set(null);
    this.occupe.set(true);
    try {
      await this.pilotage.activerPointsEau(choisis.map(id => ({ pei: id, equipe: this.equipes[id]! })));
      this.choix = {};
      this.equipes = {};
    } catch (e: any) {
      this.erreur.set(e?.error?.detail || 'L\'activation a échoué. Réessayez.');
    } finally {
      this.occupe.set(false);
    }
  }

  async etat(a: ActivationPointEau, etat: 'ACTIF' | 'FERME' | 'ANNULE'): Promise<void> {
    this.occupe.set(true);
    try { await this.pilotage.etatPointEau(a.id, etat); }
    catch (e: any) { this.erreur.set(e?.error?.detail || 'Le changement d\'état a échoué.'); }
    finally { this.occupe.set(false); }
  }

  async lien(geste: 'creer' | 'renouveler' | 'revoquer'): Promise<void> {
    try { await this.pilotage.lienCodis(geste); } catch { this.erreur.set('Le lien du CODIS n\'a pas pu être modifié.'); }
  }

  copier(texte: string): void {
    navigator.clipboard?.writeText(texte).then(() => { this.copie.set(true); setTimeout(() => this.copie.set(false), 2000); });
  }
}
