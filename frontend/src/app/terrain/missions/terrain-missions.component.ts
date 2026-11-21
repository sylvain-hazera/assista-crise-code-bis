import { Component, OnInit, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { SuiviTerrainService } from '../position/suivi-terrain.service';
import { evalueLesDegats } from '../droits';
import { Mission } from '../../shared/models/mission.model';
import { TerrainService } from '../terrain.service';
import { HorsLigneService } from '../hors-ligne.service';

const LIBELLES: Record<Mission['statut'], string> = {
  EN_PREPARATION: 'En préparation', EN_COURS: 'En cours', TERMINEE: 'Terminée',
};

/** Les missions de mes équipes, en cours d'abord ; je dis où j'en suis (comme sur Android). */
@Component({
  selector: 'app-terrain-missions',
  imports: [DatePipe, RouterLink],
  template: `
    <nav class="outils" aria-label="Outils de terrain">
      <a routerLink="/terrain/dossiers"><span class="material-icons" aria-hidden="true">folder_open</span>Dossiers</a>
      <a routerLink="/terrain/qr"><span class="material-icons" aria-hidden="true">qr_code_2</span>QR codes</a>
      @if (evalueLesDegats) {
        <a routerLink="/terrain/degats"><span class="material-icons" aria-hidden="true">home_repair_service</span>Dégâts</a>
      }
    </nav>
    @if (suivi.engagementEnCours() && !suivi.actif()) {
      <section class="partage">
        @if (!suivi.etat().consentement) {
          <p><strong>Votre équipe est engagée.</strong> Partager votre position avec vos équipes pendant l'engagement ?
             Sur iPhone, elle ne part que l'application ouverte : l'écran restera allumé.</p>
          <button type="button" class="principal" (click)="suivi.consentir()">Partager ma position</button>
        } @else if (suivi.arreteALaMain()) {
          <p>Partage de position arrêté pour cet engagement.</p>
          <button type="button" class="principal" (click)="suivi.reprendre()">Reprendre le partage</button>
        }
      </section>
    }
    <h1>Mes missions</h1>
    @if (erreur()) {
      <p class="erreur" role="alert">{{ erreur() }}</p>
    }
    @if (copieDu()) {
      <p class="copie" role="status">Hors ligne : missions telles qu'elles étaient le {{ copieDu() | date:'d MMM à HH:mm' }}.</p>
    }
    @if (chargement()) {
      <p class="discret">Chargement…</p>
    } @else if (!missions().length) {
      <p class="discret">Aucune mission pour vos équipes en ce moment.</p>
    }
    @for (m of missions(); track m.id) {
      <article class="mission" [class.en-cours]="m.statut === 'EN_COURS'">
        <div class="ligne">
          <h2>{{ m.titre }}</h2>
          <span class="statut" [attr.data-statut]="m.statut">{{ libelle(m.statut) }}</span>
        </div>
        @if (enAttente().has(m.id!)) {
          <p class="attente">Enregistré sur ce téléphone : partira au retour du réseau.</p>
        }
        @if (m.crise_nom) { <p class="crise">{{ m.crise_nom }}</p> }
        @if (m.description) { <p class="description">{{ m.description }}</p> }
        <p class="discret">
          {{ (m.equipes_noms ?? []).join(', ') }}
          @if (m.date_creation) { · créée le {{ m.date_creation | date:'d MMM, HH:mm' }} }
        </p>
        <div class="actions">
          @if (m.statut === 'EN_PREPARATION') {
            <button type="button" class="principal" [disabled]="enCours() === m.id" (click)="changer(m, 'EN_COURS')">Je commence</button>
          }
          @if (m.statut === 'EN_COURS') {
            <button type="button" class="principal" [disabled]="enCours() === m.id" (click)="changer(m, 'TERMINEE')">Terminé</button>
          }
        </div>
      </article>
    }
  `,
  styles: [`
    h1 { font-size: 1.25rem; margin: 4px 0 12px; }
    .outils { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 8px; margin-bottom: 12px; }
    .outils a { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 10px 6px; min-height: 44px;
                border-radius: 12px; background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
                color: inherit; text-decoration: none; font-size: .82rem; font-weight: 600; }
    .outils a .material-icons { color: var(--brand-primary, #2563eb); }
    .outils a:focus-visible { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: 2px; }
    .partage { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; padding: 12px 14px; border-radius: 12px;
               background: var(--ac-blue-bg, #dbeafe); color: var(--ac-blue-text, #1e40af); font-size: .9rem; }
    .partage p { margin: 0; }
    .mission {
      background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb);
      border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;
    }
    .mission.en-cours { border-left: 4px solid var(--brand-primary, #2563eb); }
    .ligne { display: flex; align-items: flex-start; gap: 8px; }
    h2 { font-size: 1.02rem; margin: 0; flex: 1; }
    .statut {
      font-size: .72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap;
      background: var(--ac-surface-2, #f3f4f6); color: var(--ac-text, #1f2937);
    }
    .statut[data-statut="EN_COURS"] { background: var(--ac-blue-bg, #dbeafe); color: var(--ac-blue-text, #1e40af); }
    .statut[data-statut="TERMINEE"] { background: var(--ac-green-bg, #dcfce7); color: var(--ac-green-text, #166534); }
    .crise { margin: 4px 0 0; font-weight: 600; font-size: .9rem; }
    .description { margin: 6px 0; white-space: pre-line; }
    .discret { color: var(--ac-text-muted, #6b7280); font-size: .85rem; margin: 4px 0; }
    .erreur { color: var(--ac-red-text, #b91c1c); }
    .copie { background: var(--ac-amber-bg, #fef3c7); color: var(--ac-amber-text, #92400e); border-radius: 8px;
             padding: 8px 10px; font-size: .85rem; }
    .attente { color: var(--ac-amber-text, #92400e); font-size: .82rem; margin: 4px 0 0; font-weight: 600; }
    .actions { display: flex; gap: 8px; margin-top: 8px; }
    .principal {
      flex: 1; border: 0; border-radius: 10px; padding: 12px; font: inherit; font-weight: 600; cursor: pointer;
      background: var(--brand-primary, #2563eb); color: #fff;
    }
    .principal:disabled { opacity: .6; }
  `],
})
export class TerrainMissionsComponent implements OnInit {
  private terrain = inject(TerrainService);
  private horsLigne = inject(HorsLigneService);
  readonly suivi = inject(SuiviTerrainService);
  readonly evalueLesDegats = evalueLesDegats(inject(AuthService));
  readonly missions = signal<Mission[]>([]);
  /** Sans réseau : la date de la copie affichée. */
  readonly copieDu = signal<string | null>(null);
  /** Missions dont un changement attend d'être envoyé. */
  readonly enAttente = signal<Set<string>>(new Set());

  constructor() {
    // La file s'est vidée (réseau revenu) : on relit le serveur, qui a maintenant tout.
    effect(() => {
      if (this.horsLigne.enAttente() === 0 && this.enAttente().size) setTimeout(() => this.charger());
    });
  }
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  readonly enCours = signal<string | null>(null);

  libelle(statut: Mission['statut']): string { return LIBELLES[statut] ?? statut; }

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.terrain.missions().subscribe({
      next: (missions) => {
        this.horsLigne.garder('missions', missions).catch(() => {});
        this.copieDu.set(null);
        this.afficher(missions);
      },
      error: async (e) => {
        const copie = HorsLigneService.estHorsLigne(e) ? await this.horsLigne.relire<Mission[]>('missions') : null;
        if (copie) {
          this.copieDu.set(copie.enregistree_le);
          await this.afficher(copie.valeur);
        } else {
          this.chargement.set(false);
          this.erreur.set('Impossible de charger les missions. Vérifiez le réseau, puis réessayez.');
        }
      },
    });
  }

  /** Les missions, corrigées de ce qui a été fait ici et attend d'être envoyé. */
  private async afficher(missions: Mission[]): Promise<void> {
    const actions = await this.horsLigne.enFile().catch(() => []);
    const statuts = new Map<string, Mission['statut']>();
    for (const { valeur } of actions) if (valeur.genre === 'statut_mission') statuts.set(valeur.mission, valeur.statut as Mission['statut']);
    const ordre = { EN_COURS: 0, EN_PREPARATION: 1, TERMINEE: 2 } as const;
    this.missions.set(missions.map(m => (m.id && statuts.has(m.id) ? { ...m, statut: statuts.get(m.id)! } : m))
      .sort((a, b) => ordre[a.statut] - ordre[b.statut]));
    this.enAttente.set(new Set(statuts.keys()));
    this.chargement.set(false);
    this.erreur.set(null);
  }

  changer(mission: Mission, statut: Mission['statut']): void {
    if (!mission.id) return;
    this.enCours.set(mission.id);
    this.terrain.changerStatut(mission.id, statut).subscribe({
      next: (a_jour) => {
        this.missions.update(liste => liste.map(m => (m.id === mission.id ? { ...m, ...a_jour, statut } : m)));
        this.enCours.set(null);
      },
      error: async (e) => {
        this.enCours.set(null);
        if (!HorsLigneService.estHorsLigne(e)) {
          this.erreur.set('Le changement n\'a pas été accepté par le serveur.');
          return;
        }
        // Sans réseau : gardé sur le téléphone, envoyé au retour du réseau.
        await this.horsLigne.differer({ genre: 'statut_mission', mission: mission.id!, statut, faite_le: new Date().toISOString() });
        this.missions.update(liste => liste.map(m => (m.id === mission.id ? { ...m, statut } : m)));
        this.enAttente.update(s => new Set(s).add(mission.id!));
      },
    });
  }
}
