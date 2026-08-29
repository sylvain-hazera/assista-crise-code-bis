import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { TeamService } from '../../services/team.service';
import { DossierService } from '../../services/dossier.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

import { Team } from '../../shared/models/team.model';
import { Dossier } from '../../shared/models/dossier.model';

const STATUT_LABELS: Record<string, string> = {
  EN_ATTENTE_DISTRIBUTION: 'En attente de distribution',
  NOUVEAU: 'Nouveau',
  EN_ATTENTE_AFFECTATION: "En attente d'affectation",
  AFFECTE: 'Affecté à une équipe',
  EN_COURS: 'En cours de traitement',
  RESOLU: 'Résolu',
  CLOTURE: 'Clôturé',
};

const PRIORITE_OPTIONS: { value: Dossier['priorite']; label: string }[] = [
  { value: 'URGENTE', label: 'Urgente' },
  { value: 'NORMALE', label: 'Normale' },
  { value: 'BASSE', label: 'Basse' },
];

@Component({
  selector: 'app-mes-interventions',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './mes-interventions.component.html',
  styleUrl: './mes-interventions.component.scss',
})
export class MesInterventionsComponent implements OnInit, OnDestroy {
  isLoading = true;
  errorMessage = '';

  teams: Team[] = [];
  allDossiers: Dossier[] = [];
  selectedTeamId: string | 'ALL' = 'ALL';
  statutFilter: string | 'ALL' = 'ALL';

  photoUrls: Record<string, string> = {};
  savingDossierId: string | null = null;

  readonly priorites = PRIORITE_OPTIONS;
  readonly statutOptions = Object.entries(STATUT_LABELS).map(([value, label]) => ({ value, label }));

  constructor(
    private teamService: TeamService,
    private dossierService: DossierService,
    private requestService: RequestService,
    private informationService: InformationService,
  ) {}

  ngOnInit(): void {
    this.teamService.mesEquipes().subscribe({
      next: (teams) => {
        this.teams = teams;
        if (!teams.length) {
          this.isLoading = false;
          return;
        }
        this.loadDossiers();
      },
      error: () => {
        this.errorMessage = 'Impossible de charger vos équipes.';
        this.isLoading = false;
      },
    });
  }

  private loadDossiers(): void {
    const teamIds = new Set(this.teams.map(t => t.id));
    this.dossierService.getAll().subscribe({
      next: (dossiers) => {
        this.allDossiers = dossiers.filter(d => d.equipe && teamIds.has(d.equipe));
        this.isLoading = false;
        this.allDossiers.filter(d => d.demande || d.information).forEach(d => this.loadDossierPhoto(d));
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les dossiers de vos équipes.';
        this.isLoading = false;
      },
    });
  }

  private loadDossierPhoto(dossier: Dossier): void {
    const service = dossier.demande ? this.requestService : this.informationService;
    const id = dossier.demande || dossier.information;
    if (!id) return;
    service.preview(id).subscribe({
      next: (blob) => { this.photoUrls[dossier.id] = URL.createObjectURL(blob); },
      error: () => {},
    });
  }

  statutLabel(statut: string): string {
    return STATUT_LABELS[statut] || statut;
  }

  teamName(teamId: string | undefined): string {
    return this.teams.find(t => t.id === teamId)?.name || '—';
  }

  get filteredDossiers(): Dossier[] {
    let list = this.allDossiers;
    if (this.selectedTeamId !== 'ALL') {
      list = list.filter(d => d.equipe === this.selectedTeamId);
    }
    if (this.statutFilter !== 'ALL') {
      list = list.filter(d => d.statut === this.statutFilter);
    }
    return [...list].sort((a, b) => a.ordre - b.ordre);
  }

  /** Le réordonnancement manuel n'a de sens qu'au sein d'une même équipe (chaque équipe gère
   * sa propre tournée) : les flèches haut/bas ne sont donc affichées que si une équipe précise
   * est sélectionnée, jamais sur la vue "toutes mes équipes" mélangeant plusieurs tournées. */
  get canReorder(): boolean {
    return this.selectedTeamId !== 'ALL';
  }

  moveUp(dossier: Dossier): void {
    const list = this.filteredDossiers;
    const index = list.findIndex(d => d.id === dossier.id);
    if (index <= 0) return;
    this.swapOrdre(dossier, list[index - 1]);
  }

  moveDown(dossier: Dossier): void {
    const list = this.filteredDossiers;
    const index = list.findIndex(d => d.id === dossier.id);
    if (index === -1 || index >= list.length - 1) return;
    this.swapOrdre(dossier, list[index + 1]);
  }

  private swapOrdre(a: Dossier, b: Dossier): void {
    const ordreA = a.ordre;
    const ordreB = b.ordre;
    this.savingDossierId = a.id;
    this.dossierService.definirPriorite(a.id, { ordre: ordreB }).subscribe({
      next: (updated) => { a.ordre = updated.ordre; },
      error: () => {},
      complete: () => { this.savingDossierId = null; },
    });
    this.dossierService.definirPriorite(b.id, { ordre: ordreA }).subscribe({
      next: (updated) => { b.ordre = updated.ordre; },
      error: () => {},
    });
  }

  onPrioriteChange(dossier: Dossier, priorite: Dossier['priorite']): void {
    this.savingDossierId = dossier.id;
    this.dossierService.definirPriorite(dossier.id, { priorite }).subscribe({
      next: (updated) => { dossier.priorite = updated.priorite; },
      error: () => {},
      complete: () => { this.savingDossierId = null; },
    });
  }

  ngOnDestroy(): void {
    Object.values(this.photoUrls).forEach(url => URL.revokeObjectURL(url));
  }
}
