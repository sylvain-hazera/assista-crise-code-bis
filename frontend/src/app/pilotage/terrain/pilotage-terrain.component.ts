import { Component, computed, inject } from '@angular/core';
import { DatePipe } from '@angular/common';

import { MessageTerrainPilotage, PilotageService } from '../pilotage.service';

/**
 * Le terrain en direct (23/11/2026) : en tête, les alertes Danger et Demande de premiers secours
 * que le poste de commandement n'a pas encore prises en compte ; puis chaque intervenant, par
 * équipe, avec son dernier statut (« sur place », « en route », « disponible »…) et depuis
 * quand ; enfin les derniers messages. Relu toutes les 30 s par le service du pilotage.
 */
@Component({
  selector: 'app-pilotage-terrain',
  standalone: true,
  imports: [DatePipe],
  template: `
    <h1>Terrain</h1>
    @if (!pilotage.criseId()) {
      <p class="vide">Choisissez une crise dans la barre du haut.</p>
    } @else if (!pilotage.terrain()) {
      <p class="vide">Chargement…</p>
    } @else {
      @if (pilotage.terrain()!.alertes.length) {
        <section class="alertes" aria-label="Alertes à prendre en compte">
          @for (a of pilotage.terrain()!.alertes; track a.id) {
            <article class="alerte">
              <span class="material-icons" aria-hidden="true">{{ a.type === 'DANGER' ? 'warning' : 'medical_services' }}</span>
              <div class="corps-alerte">
                <strong>{{ a.type_libelle }}</strong> — {{ a.auteur_nom }}@if (a.equipe_nom) { · {{ a.equipe_nom }} }
                <span class="quand">{{ a.emis_le | date:'HH:mm' }} · {{ canal(a.canal) }}@if (a.dossier_numero) { · dossier {{ a.dossier_numero }} }</span>
                @if (a.texte) { <p>{{ a.texte }}</p> }
              </div>
              <button type="button" [disabled]="enCours === a.id" (click)="prendre(a)">Pris en compte</button>
            </article>
          }
        </section>
      } @else {
        <p class="calme"><span class="material-icons" aria-hidden="true">check_circle</span> Aucune alerte en attente.</p>
      }

      <section class="bloc">
        <h2>Intervenants ({{ pilotage.terrain()!.statuts.length }})</h2>
        @if (!pilotage.terrain()!.statuts.length) { <p class="vide">Aucun message de terrain pour cette crise.</p> }
        @for (g of groupes(); track g.equipe) {
          <h3>{{ g.equipe }}</h3>
          <ul class="statuts">
            @for (s of g.membres; track s.id) {
              <li [class.prioritaire]="s.prioritaire">
                <span class="nom">{{ s.auteur_nom }}</span>
                <span class="statut">{{ s.statut }}</span>
                <span class="quand">depuis {{ s.emis_le | date:'HH:mm' }} · {{ canal(s.canal) }}@if (s.dossier_numero) { · {{ s.dossier_numero }} }</span>
              </li>
            }
          </ul>
        }
      </section>

      <section class="bloc">
        <h2>Derniers messages</h2>
        <ul class="fil">
          @for (m of pilotage.terrain()!.derniers; track m.id) {
            <li>
              <span class="quand">{{ m.emis_le | date:'dd/MM HH:mm' }}</span>
              <span>{{ m.auteur_nom }} — {{ m.type_libelle }}@if (m.nombre) { ({{ m.nombre }}) }@if (m.texte) { : {{ m.texte }} }</span>
              @if (m.pris_en_compte_par_nom) { <span class="pris">pris en compte par {{ m.pris_en_compte_par_nom }}</span> }
            </li>
          }
        </ul>
      </section>
    }
  `,
  styles: [`
    h1 { margin: 0 0 12px; font-size: 1.4rem; }
    h2 { margin: 0 0 8px; font-size: 1.05rem; }
    h3 { margin: 10px 0 4px; font-size: .9rem; color: var(--ac-text-muted, #6b7280); }
    .vide { color: var(--ac-text-muted, #6b7280); }
    .alertes { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
    .alerte { display: flex; gap: 10px; align-items: flex-start; padding: 12px; border-radius: 10px;
      background: #fef2f2; border: 1px solid #fecaca; color: #7f1d1d;
      .material-icons { color: #b91c1c; } p { margin: 4px 0 0; } }
    .corps-alerte { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .alerte button { flex: none; border: none; border-radius: 8px; padding: 8px 12px; min-height: 40px;
      background: #b91c1c; color: #fff; font: inherit; font-weight: 600; cursor: pointer; &:disabled { opacity: .6; } }
    .calme { display: flex; align-items: center; gap: 6px; color: #15803d; margin: 0 0 16px; }
    .bloc { padding: 12px; border-radius: 10px; background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb); margin-bottom: 12px; }
    .statuts, .fil { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .statuts li { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; padding: 6px 0; border-bottom: 1px solid var(--ac-border, #f3f4f6);
      &.prioritaire .statut { color: #b91c1c; } }
    .nom { font-weight: 600; }
    .statut { font-weight: 600; color: var(--brand-primary, #2563eb); }
    .quand { font-size: .78rem; color: var(--ac-text-muted, #6b7280); }
    .fil li { display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: .88rem; padding: 4px 0; }
    .pris { font-size: .75rem; color: #15803d; }
  `],
})
export class PilotageTerrainComponent {
  readonly pilotage = inject(PilotageService);
  enCours: string | null = null;

  /** Les intervenants rangés par équipe. */
  readonly groupes = computed(() => {
    const parEquipe = new Map<string, MessageTerrainPilotage[]>();
    for (const s of this.pilotage.terrain()?.statuts ?? []) {
      const e = s.equipe_nom || 'Sans équipe';
      parEquipe.set(e, [...(parEquipe.get(e) ?? []), s]);
    }
    return [...parEquipe.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([equipe, membres]) => ({ equipe, membres }));
  });

  canal(c: string): string {
    return c === 'MESHTASTIC' ? 'Meshtastic' : c === 'MESHCORE' ? 'MeshCore' : 'données';
  }

  async prendre(a: MessageTerrainPilotage): Promise<void> {
    this.enCours = a.id;
    try { await this.pilotage.prendreEnCompte(a.id); } finally { this.enCours = null; }
  }
}
