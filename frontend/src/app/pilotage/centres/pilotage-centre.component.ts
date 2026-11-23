import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { DetailCentre, PilotageService } from '../pilotage.service';
import { PointSecretariatModalComponent } from '../../admin/crises/point-secretariat-modal/point-secretariat-modal.component';
import { PointOperationnel } from '../../shared/models/point-operationnel.model';

type Onglet = 'registre' | 'stock' | 'equipe' | 'fiche';

/**
 * Un centre, en détail (23/11/2026) : le registre des présents (sortie en un geste, arrivée),
 * le stock (manques d'abord ; recevoir, distribuer, compter), l'équipe et son planning du jour,
 * la fiche (capacité, ouverture, fermeture). Les noms des personnes accueillies ne sont montrés
 * qu'à qui gère le centre — le serveur ne les envoie pas aux autres.
 */
@Component({
  selector: 'app-pilotage-centre',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, PointSecretariatModalComponent],
  template: `
    <a routerLink=".." class="retour"><span class="material-icons" aria-hidden="true">arrow_back</span> Centres</a>
    @if (!centre()) {
      <p class="vide">{{ erreur() ?? 'Chargement…' }}</p>
    } @else {
      @if (centre(); as c) {
        <h1>{{ c.nom }}</h1>
        <p class="discret">{{ c.type_libelle }} · {{ c.etat === 'OUVERT' ? 'ouvert' : c.etat === 'FERME' ? 'fermé' : 'prévu' }}
          · <strong>{{ c.occupation.presents }}</strong>@if (c.occupation.capacite !== null) { / {{ c.occupation.capacite }} } présent(s)</p>
        <nav class="sous-onglets" aria-label="Rubriques du centre">
          @for (o of onglets; track o.id) {
            <button type="button" [class.actif]="onglet() === o.id" (click)="onglet.set(o.id)">{{ o.libelle }}</button>
          }
        </nav>

        @switch (onglet()) {
          @case ('registre') {
            @if (c.peut_gerer && c.etat === 'OUVERT') {
              <div class="gestes"><button type="button" (click)="secretariat.set(pointDe(c))">+ Admission</button></div>
            }
            @if (!c.registre.length) { <p class="vide">Personne n'est enregistré comme présent.</p> }
            <ul class="liste">
              @for (l of c.registre; track l.id) {
                <li>
                  <div class="texte">
                    <strong>{{ l.nombre }} · {{ l.libelle }}</strong>@if (l.nom) { — {{ l.nom }} }
                    <span class="discret">arrivé(s) {{ l.arrivee | date:'dd/MM HH:mm' }}@if (l.commentaire) { · {{ l.commentaire }} }</span>
                  </div>
                  @if (c.peut_gerer) { <button type="button" class="secondaire" [disabled]="enCours()" (click)="sortie(l.id)">Sortie</button> }
                </li>
              }
            </ul>
            @if (c.mouvements.length) {
              <h2>Mouvements (48 h)</h2>
              <ul class="liste discret">
                @for (m of c.mouvements; track $index) {
                  <li>{{ m.nombre }} {{ m.libelle.toLowerCase() }} : arrivée {{ m.arrivee | date:'dd/MM HH:mm' }}@if (m.depart) { · départ {{ m.depart | date:'dd/MM HH:mm' }} }</li>
                }
              </ul>
            }
          }
          @case ('stock') {
            @if (!c.stock.length) { <p class="vide">Aucun stock suivi pour ce centre.</p> }
            <ul class="liste">
              @for (s of c.stock; track s.item) {
                <li>
                  <div class="texte"><strong>{{ s.article }}</strong>
                    <span class="discret">{{ s.quantite }} {{ s.unite }}@if (s.niveau === 'NUL') { · <span class="alerte">vide</span> } @else if (s.niveau === 'FAIBLE') { · <span class="alerte">faible</span> }</span>
                  </div>
                  @if (c.peut_gerer) {
                    <div class="gestes-stock">
                      <input type="number" min="0" [attr.aria-label]="'Quantité — ' + s.article" #q value="1"/>
                      <button type="button" class="secondaire" [disabled]="enCours()" (click)="stock('recevoir', s.item, +q.value)">Reçu</button>
                      <button type="button" class="secondaire" [disabled]="enCours()" (click)="stock('distribuer', s.item, +q.value)">Distribué</button>
                      <button type="button" class="secondaire" [disabled]="enCours()" (click)="stock('compter', s.item, +q.value)">Compté</button>
                    </div>
                  }
                </li>
              }
            </ul>
          }
          @case ('equipe') {
            <h2>Responsables</h2>
            @for (r of c.responsables; track r.nom) { <p>{{ r.nom }}@if (r.telephone) { · <a [href]="'tel:' + r.telephone">{{ r.telephone }}</a> }</p> }
            @if (!c.responsables.length) { <p class="vide">Aucun responsable désigné.</p> }
            <h2>Équipes</h2>
            @for (e of c.equipes; track e.id) { <p>{{ e.nom }} · {{ e.effectif }} membre(s)</p> }
            @if (!c.equipes.length) { <p class="vide">Aucune équipe ne tient ce centre.</p> }
            <h2>Planning d'aujourd'hui</h2>
            @for (p of c.planning; track $index) { <p>{{ creneau(p.creneau) }} : {{ p.membre }}</p> }
            @if (!c.planning.length) { <p class="vide">Personne au planning aujourd'hui.</p> }
          }
          @case ('fiche') {
            @if (c.adresse) { <p>{{ c.adresse }}</p> }
            <p class="discret">@if (c.ouvert_le) { Ouvert le {{ c.ouvert_le | date:'dd/MM HH:mm' }} }@if (c.ferme_le) { · fermé le {{ c.ferme_le | date:'dd/MM HH:mm' }} }</p>
            @if (c.peut_gerer) {
              <form class="ligne-form" (ngSubmit)="capacite()">
                <label>Capacité <input type="number" name="capacite" min="0" [(ngModel)]="nouvelleCapacite"/></label>
                <button type="submit" class="secondaire" [disabled]="enCours()">Enregistrer</button>
              </form>
              <div class="gestes">
                @if (c.etat === 'OUVERT') { <button type="button" class="secondaire" [disabled]="enCours()" (click)="etat('fermer')">Fermer le centre</button> }
                @else { <button type="button" [disabled]="enCours()" (click)="etat('ouvrir')">{{ c.etat === 'FERME' ? 'Rouvrir' : 'Ouvrir' }} le centre</button> }
              </div>
            }
            <p class="discret">La fiche complète (adresse, équipes, matériel) se modifie sur le site.</p>
          }
        }
        @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
      }
    }
    @if (secretariat(); as p) {
      <app-point-secretariat-modal [point]="p" (closed)="secretariat.set(null); charger()"></app-point-secretariat-modal>
    }
  `,
  styles: [`
    .retour { display: inline-flex; align-items: center; gap: 4px; text-decoration: none; color: var(--brand-primary, #2563eb); min-height: 40px; }
    h1 { margin: 4px 0; font-size: 1.4rem; overflow-wrap: anywhere; }
    h2 { margin: 14px 0 6px; font-size: 1rem; }
    .vide, .discret { color: var(--ac-text-muted, #6b7280); }
    .discret { font-size: .82rem; }
    .sous-onglets { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
    .sous-onglets button { border: 1px solid var(--ac-border, #d1d5db); background: transparent; border-radius: 999px; padding: 6px 12px;
      min-height: 36px; font: inherit; cursor: pointer; &.actif { background: var(--brand-primary, #2563eb); color: #fff; border-color: transparent; } }
    .liste { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
    .liste li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--ac-border, #f3f4f6); }
    .texte { display: flex; flex-direction: column; min-width: 0; flex: 1 1 200px; overflow-wrap: anywhere; }
    .ligne-form { display: flex; flex-wrap: wrap; gap: 6px; align-items: flex-end; margin-bottom: 10px;
      input, select { min-height: 40px; font: inherit; max-width: 100%; } input[type=number] { width: 6em; }
      label { display: flex; flex-direction: column; font-size: .82rem; } }
    .gestes, .gestes-stock { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 6px;
      input { width: 5em; min-height: 40px; font: inherit; } }
    button { border: none; border-radius: 8px; padding: 8px 12px; min-height: 40px; font: inherit; font-weight: 600; cursor: pointer;
      background: var(--brand-primary, #2563eb); color: #fff; &:disabled { opacity: .5; }
      &.secondaire { background: transparent; color: inherit; border: 1px solid var(--ac-border, #d1d5db); } }
    .alerte { color: #b45309; font-weight: 600; }
    .erreur { color: #b91c1c; }
  `],
})
export class PilotageCentreComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  readonly pilotage = inject(PilotageService);
  readonly centre = signal<DetailCentre | null>(null);
  readonly onglet = signal<Onglet>('registre');
  readonly enCours = signal(false);
  readonly erreur = signal<string | null>(null);
  /** L'admission complète : le secrétariat du site, à l'identique. */
  readonly secretariat = signal<PointOperationnel | null>(null);
  readonly onglets: { id: Onglet; libelle: string }[] = [
    { id: 'registre', libelle: 'Registre' }, { id: 'stock', libelle: 'Stock' },
    { id: 'equipe', libelle: 'Équipe' }, { id: 'fiche', libelle: 'Fiche' },
  ];
  nouvelleCapacite: number | null = null;
  private id = '';
  private minuterie?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    this.id = this.route.snapshot.paramMap.get('id') ?? '';
    const o = this.route.snapshot.queryParamMap.get('onglet') as Onglet | null;
    if (o && this.onglets.some(x => x.id === o)) this.onglet.set(o);
    this.charger();
    this.minuterie = setInterval(() => this.charger(), 30_000);
  }

  ngOnDestroy(): void { clearInterval(this.minuterie); }

  async charger(): Promise<void> {
    try {
      const c = await this.pilotage.centre(this.id);
      if (this.nouvelleCapacite === null) this.nouvelleCapacite = c.occupation.capacite;
      this.centre.set(c);
    } catch (e: any) {
      this.erreur.set(e?.error?.error ?? e?.error?.detail ?? 'Centre indisponible.');
    }
  }

  pointDe(c: DetailCentre): PointOperationnel {
    return { id: c.id, nom: c.nom } as PointOperationnel;
  }

  creneau(c: string): string {
    return ({ MATIN: 'Matin', MIDI: 'Après-midi', SOIR: 'Soir', NUIT: 'Nuit' } as Record<string, string>)[c] ?? c;
  }

  private async geste(action: () => Promise<unknown>): Promise<void> {
    this.enCours.set(true);
    this.erreur.set(null);
    try { await action(); await this.charger(); }
    catch (e: any) { this.erreur.set(e?.error?.detail ?? e?.error?.error ?? 'Geste refusé.'); }
    finally { this.enCours.set(false); }
  }

  sortie(ligne: string): Promise<void> { return this.geste(() => this.pilotage.sortie(ligne)); }

  stock(geste: 'recevoir' | 'distribuer' | 'compter', item: string, quantite: number): Promise<void> {
    if (!(quantite >= 0)) return Promise.resolve();
    return this.geste(() => this.pilotage.gesteStock(this.id, geste, item, quantite));
  }

  capacite(): Promise<void> {
    return this.geste(() => this.pilotage.etatCentre(this.id, null, this.nouvelleCapacite));
  }

  etat(geste: 'ouvrir' | 'fermer'): Promise<void> {
    const c = this.centre();
    if (geste === 'fermer' && c && c.occupation.presents > 0
        && !confirm(`${c.occupation.presents} personne(s) encore présente(s). Fermer quand même ?`)) return Promise.resolve();
    return this.geste(() => this.pilotage.etatCentre(this.id, geste));
  }
}
