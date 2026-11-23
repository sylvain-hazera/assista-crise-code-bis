import { Component, OnDestroy, OnInit, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subscription, catchError, forkJoin, of } from 'rxjs';
import { CelluleCriseService } from '../../services/cellule-crise.service';
import { DossierService } from '../../services/dossier.service';
import { TeamService } from '../../services/team.service';
import { JournalCollectiviteService } from '../../services/journal-collectivite.service';
import { CelluleCrise } from '../../shared/models/cellule-crise.model';
import { Dossier } from '../../shared/models/dossier.model';
import { Team } from '../../shared/models/team.model';
import { JournalCollectivite } from '../../shared/models/journal-collectivite.model';
import { pollWhileVisible } from '../../shared/utils/polling.util';
import { dureeDepuis } from '../../shared/utils/duree.util';
import { PilotageService, TableauxSituation } from '../pilotage.service';

const CLOS = ['RESOLU', 'CLOTURE'];
const RAFRAICHISSEMENT_MS = 60_000;

interface VerrouEcran { release(): Promise<void>; addEventListener(type: 'release', f: () => void): void; }
type NavigateurAvecVerrou = Navigator & { wakeLock?: { request(type: 'screen'): Promise<VerrouEcran> } };

/** Ce que la situation doit faire remonter en premier : un dossier urgent ou signalé important. */
export function dossiersPrioritaires(dossiers: Dossier[], criseId: string): Dossier[] {
  const rang = (d: Dossier) => (d.priorite === 'URGENTE' ? 0 : 2) + (d.important ? 0 : 1);
  return dossiers
    .filter(d => d.crise === criseId && !CLOS.includes(d.statut) && (d.priorite === 'URGENTE' || d.important))
    .sort((a, b) => rang(a) - rang(b) || (a.date_creation ?? '').localeCompare(b.date_creation ?? ''));
}

/**
 * La situation de la crise, d'un coup d'œil : l'écran d'accueil du poste de pilotage
 * (directeur des opérations, sur iPad). Ce qui attend une décision, ce qui est urgent, qui est
 * engagé, et la main courante, où il écrit sans changer d'écran. Relu chaque minute tant que
 * l'écran est visible. Le détail reste dans la cellule de crise et l'administration.
 */
@Component({
  selector: 'app-pilotage-situation',
  imports: [DatePipe, FormsModule, RouterLink],
  templateUrl: './pilotage-situation.component.html',
  styleUrl: './pilotage-situation.component.scss',
})
export class PilotageSituationComponent implements OnInit, OnDestroy {
  readonly pilotage = inject(PilotageService);
  private cellules = inject(CelluleCriseService);
  private dossiersService = inject(DossierService);
  private equipesService = inject(TeamService);
  private journalService = inject(JournalCollectiviteService);

  readonly cellule = signal<CelluleCrise | null>(null);
  readonly dossiers = signal<Dossier[]>([]);
  readonly equipes = signal<Team[]>([]);
  readonly journal = signal<JournalCollectivite[]>([]);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  readonly misAJourLe = signal<Date | null>(null);
  readonly ecranAllume = signal(false);
  nouvelleEntree = '';
  readonly ecriture = signal(false);
  readonly dureeDepuis = dureeDepuis;

  readonly prioritaires = computed(() => {
    const id = this.pilotage.criseId();
    return id ? dossiersPrioritaires(this.dossiers(), id) : [];
  });
  readonly ouverts = computed(() => this.dossiers().filter(d => d.crise === this.pilotage.criseId() && !CLOS.includes(d.statut)));
  readonly sansEquipe = computed(() => this.ouverts().filter(d => !d.equipe).length);
  readonly engagees = computed(() => this.equipes().filter(e => !!e.engagement_debut)
    .sort((a, b) => (a.engagement_debut ?? '').localeCompare(b.engagement_debut ?? '')));
  readonly aAffecter = computed(() => {
    const c = this.cellule()?.compteurs;
    return c ? c.dossiers_ressource_en_attente + c.dossiers_moyen_en_attente + c.dossiers_non_qualifies_en_attente : null;
  });

  sousTitre(e: Team): string {
    return [e.mission_active_titre, e.leader_nom ? `chef : ${e.leader_nom}` : null].filter(Boolean).join(' · ');
  }

  libelleStatut(statut: string): string {
    const texte = (statut || '').toLowerCase().replace(/_/g, ' ');
    return texte.charAt(0).toUpperCase() + texte.slice(1);
  }

  private abonnement?: Subscription;
  /** Veille de la zone, accueil, dégâts, moyens, radio (23/11/2026). */
  readonly tableaux = signal<TableauxSituation | null>(null);
  private verrou: VerrouEcran | null = null;

  constructor() {
    // Une autre crise choisie dans l'en-tête : tout est relu pour elle.
    effect(() => {
      const id = this.pilotage.criseId();
      this.abonnement?.unsubscribe();
      if (id) this.suivre(id);
    });
  }

  ngOnInit(): void {
    document.addEventListener('visibilitychange', this.reprendreLEcran);
  }

  ngOnDestroy(): void {
    this.abonnement?.unsubscribe();
    document.removeEventListener('visibilitychange', this.reprendreLEcran);
    this.verrou?.release().catch(() => {});
  }

  private suivre(criseId: string): void {
    this.chargement.set(true);
    this.abonnement = pollWhileVisible(() => forkJoin({
      cellule: this.cellules.get(criseId).pipe(catchError(() => of(null))),
      dossiers: this.dossiersService.getAll(),
      equipes: this.equipesService.getAll(),
      journal: this.journalService.getAll(criseId).pipe(catchError(() => of([] as JournalCollectivite[]))),
      tableaux: this.pilotage.situation(criseId).pipe(catchError(() => of(null))),
    }), RAFRAICHISSEMENT_MS).subscribe({
      next: ({ cellule, dossiers, equipes, journal, tableaux }) => {
        this.tableaux.set(tableaux);
        this.cellule.set(cellule);
        this.dossiers.set(dossiers);
        this.equipes.set(equipes.filter(e => e.actif !== false && e.assigned_crisis_ids?.includes(criseId)));
        this.journal.set([...journal].sort((a, b) => b.date_creation.localeCompare(a.date_creation)).slice(0, 8));
        this.misAJourLe.set(new Date());
        this.erreur.set(null);
        this.chargement.set(false);
      },
      error: () => {
        this.chargement.set(false);
        this.erreur.set('La situation n\'a pas pu être chargée. Vérifiez le réseau ; elle sera relue à la prochaine ouverture.');
      },
    });
  }

  ecrire(): void {
    const texte = this.nouvelleEntree.trim();
    const criseId = this.pilotage.criseId();
    if (!texte || !criseId || this.ecriture()) return;
    this.ecriture.set(true);
    this.journalService.create(texte, criseId).subscribe({
      next: (entree) => {
        this.journal.update(j => [entree, ...j].slice(0, 8));
        this.nouvelleEntree = '';
        this.ecriture.set(false);
      },
      error: () => {
        this.ecriture.set(false);
        this.erreur.set('L\'entrée n\'a pas été enregistrée dans la main courante. Réessayez.');
      },
    });
  }

  /** « Garder l'écran allumé » : un iPad posé sur la table du PC de crise ne doit pas s'éteindre. */
  async basculerEcran(): Promise<void> {
    if (this.verrou) {
      await this.verrou.release().catch(() => {});
      this.verrou = null;
      this.ecranAllume.set(false);
      return;
    }
    await this.allumer();
  }

  private async allumer(): Promise<void> {
    try {
      const verrou = await (navigator as NavigateurAvecVerrou).wakeLock?.request('screen');
      if (!verrou) { this.erreur.set('Ce navigateur ne sait pas garder l\'écran allumé.'); return; }
      this.verrou = verrou;
      this.ecranAllume.set(true);
      verrou.addEventListener('release', () => { if (document.visibilityState === 'visible') { this.verrou = null; this.ecranAllume.set(false); } });
    } catch {
      this.ecranAllume.set(false);
    }
  }

  /** Safari relâche l'écran allumé quand l'application passe derrière : on le reprend au retour. */
  private reprendreLEcran = () => {
    if (document.visibilityState === 'visible' && this.ecranAllume() && !this.verrou) this.allumer();
    if (document.visibilityState === 'hidden') this.verrou = null;
  };
}
