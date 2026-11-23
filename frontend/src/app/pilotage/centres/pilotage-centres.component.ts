import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { CentrePilotage, PilotageService } from '../pilotage.service';
import { PointSecretariatModalComponent } from '../../admin/crises/point-secretariat-modal/point-secretariat-modal.component';
import { PointOperationnel } from '../../shared/models/point-operationnel.model';

/** La jauge d'un centre : vert, orange à 90 %, rouge plein. */
export function niveauJauge(c: CentrePilotage): 'ok' | 'presque' | 'plein' | 'inconnu' {
  if (c.occupation.capacite === null) return 'inconnu';
  return c.occupation.plein ? 'plein' : c.occupation.presque_plein ? 'presque' : 'ok';
}

/**
 * Les centres de la crise (23/11/2026) : accueil (CARE), transit, regroupement des moyens. En
 * tête, l'orientation (qui cherche un centre, qui est à reloger) ; puis une carte par centre —
 * jauge, répartition, arrivées et départs du jour, manques, équipe — et les gestes courants :
 * enregistrer une arrivée, ouvrir ou fermer. Le détail (registre, stock, planning) s'ouvre d'un
 * toucher. Relu toutes les 30 s par le service du pilotage.
 */
@Component({
  selector: 'app-pilotage-centres',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, PointSecretariatModalComponent],
  template: `
    <h1>Centres</h1>
    @if (!pilotage.criseId()) {
      <p class="vide">Choisissez une crise dans la barre du haut.</p>
    } @else if (!pilotage.centres()) {
      <p class="vide">Chargement…</p>
    } @else {
      @if (pilotage.centres()!.orientation; as o) {
        <p class="orientation">
          <span class="material-icons" aria-hidden="true">directions</span>
          <span><strong>{{ o.cherchent_un_centre.personnes }}</strong> personne(s) en sécurité cherchent un centre
            ({{ o.cherchent_un_centre.declarations }} déclaration(s)) · <strong>{{ o.relogement.en_recherche }}</strong> famille(s) à reloger
            · {{ o.relogement.heberges }} hébergée(s)</span>
        </p>
      }
      @if (!pilotage.centres()!.centres.length) {
        <p class="vide">Aucun centre d'accueil, de transit ou de regroupement pour cette crise. Créez-en un depuis la fiche de la crise sur le site.</p>
      }
      <div class="grille">
        @for (c of pilotage.centres()!.centres; track c.id) {
          <article class="centre" [attr.data-etat]="c.etat">
            <header>
              <a [routerLink]="[c.id]" class="nom">{{ c.nom }}</a>
              <span class="etat">{{ etatLibelle(c) }}</span>
            </header>
            <p class="type">{{ c.type_libelle }}@if (c.accepte_animaux) { · animaux acceptés }</p>
            <div class="jauge" [attr.data-niveau]="niveau(c)" role="img"
                 [attr.aria-label]="c.occupation.presents + ' présent(s)' + (c.occupation.capacite !== null ? ' sur ' + c.occupation.capacite : '')">
              <span class="barre" [style.width.%]="largeur(c)"></span>
            </div>
            <p class="chiffres"><strong>{{ c.occupation.presents }}</strong>@if (c.occupation.capacite !== null) { / {{ c.occupation.capacite }} } présent(s)
              <span class="discret">· +{{ c.occupation.arrivees_24h }} / −{{ c.occupation.departs_24h }} sur 24 h</span></p>
            @if (c.occupation.par_type.length) {
              <p class="discret">@for (t of c.occupation.par_type; track t.type; let d = $last) { {{ t.nombre }} {{ t.libelle.toLowerCase() }}@if (!d) { · } }</p>
            }
            @if (c.manques.length) {
              <p class="manques"><span class="material-icons" aria-hidden="true">inventory_2</span>
                Manque : @for (m of c.manques; track m.article; let d = $last) { {{ m.article }}@if (m.niveau === 'NUL') { (vide) }@if (!d) { , } }</p>
            }
            <p class="discret">
              @for (r of c.responsables; track r.nom; let d = $last) { {{ r.nom }}@if (r.telephone) { · <a [href]="'tel:' + r.telephone">{{ r.telephone }}</a> }@if (!d) { ; } }
              @if (!c.responsables.length) { Aucun responsable désigné }
              @for (e of c.equipes; track e.id) { · {{ e.nom }} ({{ e.effectif }}) }
              @if (c.sur_place_creneau) { · {{ c.sur_place_creneau }} au planning maintenant }
            </p>
            @if (c.peut_gerer) {
              <div class="gestes">
                @if (c.etat === 'OUVERT') {
                  <button type="button" (click)="ouvrirArrivee(c)">+ Admission</button>
                  <a class="secondaire" [routerLink]="[c.id]" [queryParams]="{ onglet: 'registre' }">Sortie…</a>
                  <button type="button" class="secondaire" [disabled]="enCours() === c.id" (click)="etat(c, 'fermer')">Fermer</button>
                } @else {
                  <button type="button" [disabled]="enCours() === c.id" (click)="etat(c, 'ouvrir')">{{ c.etat === 'FERME' ? 'Rouvrir' : 'Ouvrir' }}</button>
                }
              </div>
            }
          </article>
        }
      </div>
      @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
    }
    <!-- L'admission complète : le même secrétariat que sur le site (personne seule, famille ou
         groupe, adultes, enfants et leurs âges, référent, régime alimentaire, commentaire). -->
    @if (secretariat(); as p) {
      <app-point-secretariat-modal [point]="p" (closed)="fermerSecretariat()"></app-point-secretariat-modal>
    }
  `,
  styles: [`
    h1 { margin: 0 0 12px; font-size: 1.4rem; }
    .vide, .discret { color: var(--ac-text-muted, #6b7280); }
    .discret { font-size: .8rem; margin: 2px 0; }
    .orientation { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border-radius: 10px; margin: 0 0 12px;
      background: var(--ac-blue-bg, #dbeafe); color: var(--ac-text, #1e3a8a); }
    .grille { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap: 12px; }
    .centre { padding: 12px; border-radius: 10px; background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
      min-width: 0; overflow-wrap: anywhere; &[data-etat='FERME'] { opacity: .7; } }
    header { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
    .nom { font-weight: 700; font-size: 1.05rem; color: inherit; text-decoration: none; &:hover { text-decoration: underline; } }
    .etat { flex: none; font-size: .75rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--ac-border, #e5e7eb); }
    [data-etat='OUVERT'] .etat { background: #dcfce7; color: #166534; }
    .type { margin: 2px 0 8px; font-size: .82rem; color: var(--ac-text-muted, #6b7280); }
    .jauge { height: 10px; border-radius: 5px; background: var(--ac-border, #e5e7eb); overflow: hidden;
      .barre { display: block; height: 100%; background: #16a34a; }
      &[data-niveau='presque'] .barre { background: #d97706; } &[data-niveau='plein'] .barre { background: #b91c1c; }
      &[data-niveau='inconnu'] .barre { background: #6b7280; } }
    .chiffres { margin: 6px 0 2px; }
    .manques { display: flex; gap: 4px; align-items: flex-start; color: #b45309; font-size: .85rem; margin: 4px 0;
      .material-icons { font-size: 18px; } }
    .gestes { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .gestes button, .gestes a { border: none; border-radius: 8px; padding: 8px 12px; min-height: 40px; font: inherit; font-weight: 600;
      cursor: pointer; background: var(--brand-primary, #2563eb); color: #fff; text-decoration: none; display: inline-flex; align-items: center;
      &:disabled { opacity: .5; } &.secondaire { background: transparent; color: inherit; border: 1px solid var(--ac-border, #d1d5db); } }
    .arrivee { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--ac-border, #e5e7eb);
      label { display: flex; flex-direction: column; font-size: .82rem; gap: 2px; }
      input, select { min-height: 40px; font: inherit; max-width: 100%; } }
    .erreur { color: #b91c1c; }
  `],
})
export class PilotageCentresComponent implements OnInit {
  readonly pilotage = inject(PilotageService);
  readonly enCours = signal<string | null>(null);
  /** Le centre dont le secrétariat (admission complète) est ouvert. */
  readonly secretariat = signal<PointOperationnel | null>(null);
  readonly erreur = signal<string | null>(null);

  ngOnInit(): void { this.pilotage.rafraichirCentres(); }

  niveau = niveauJauge;

  largeur(c: CentrePilotage): number {
    if (!c.occupation.capacite) return c.occupation.presents ? 100 : 0;
    return Math.min(100, Math.round(100 * c.occupation.presents / c.occupation.capacite));
  }

  etatLibelle(c: CentrePilotage): string {
    return { OUVERT: 'Ouvert', PREVU: 'Prévu', FERME: 'Fermé' }[c.etat];
  }

  /** L'admission complète, par le secrétariat du site (23/11/2026 : « il faut faire la même entrée »). */
  ouvrirArrivee(c: CentrePilotage): void {
    this.secretariat.set({ id: c.id, nom: c.nom } as PointOperationnel);
  }

  fermerSecretariat(): void {
    this.secretariat.set(null);
    this.pilotage.rafraichirCentres();
  }

  async etat(c: CentrePilotage, geste: 'ouvrir' | 'fermer'): Promise<void> {
    if (geste === 'fermer' && c.occupation.presents > 0
        && !confirm(`${c.occupation.presents} personne(s) encore présente(s) à « ${c.nom} ». Fermer quand même ?`)) return;
    this.enCours.set(c.id);
    this.erreur.set(null);
    try { await this.pilotage.etatCentre(c.id, geste); }
    catch (e: any) { this.erreur.set(e?.error?.detail ?? e?.error?.error ?? 'Geste refusé.'); }
    finally { this.enCours.set(null); }
  }
}
