import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { MissionService } from '../../services/mission.service';
import { TeamService } from '../../services/team.service';
import { CrisisService } from '../../services/crisis.service';
import { DossierService } from '../../services/dossier.service';

import { Mission } from '../../shared/models/mission.model';
import { Team } from '../../shared/models/team.model';
import { Crisis } from '../../shared/models/crisis.model';
import { Dossier } from '../../shared/models/dossier.model';

type ModalView = 'none' | 'create' | 'edit' | 'delete' | 'detail';
type FilterCrisis = string | 'ALL';
type FilterStatut = Mission['statut'] | 'ALL';

@Component({
  selector: 'app-missions',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule],
  templateUrl: './missions.component.html',
  styleUrls: ['./missions.component.scss'],
})
export class MissionsComponent implements OnInit {

  missions: Mission[] = [];
  teams: Team[] = [];
  crises: Crisis[] = [];
  dossiers: Dossier[] = [];

  isLoading = true;
  isSaving = false;
  errorMessage = '';
  successMessage = '';

  filterCrisis: FilterCrisis = 'ALL';
  filterStatut: FilterStatut = 'ALL';
  searchQuery = '';

  teamSearchQuery = '';

  modal: ModalView = 'none';
  selectedMission: Mission | null = null;
  missionForm!: FormGroup;

  readonly statutOptions: { label: string; value: Mission['statut'] }[] = [
    { label: 'En préparation', value: 'EN_PREPARATION' },
    { label: 'En cours', value: 'EN_COURS' },
    { label: 'Terminée', value: 'TERMINEE' },
  ];

  constructor(
    private fb: FormBuilder,
    private missionService: MissionService,
    private teamService: TeamService,
    private crisisService: CrisisService,
    private dossierService: DossierService,
  ) {}

  ngOnInit(): void {
    this.buildForm();
    this.loadAll();
  }

  private buildForm(): void {
    this.missionForm = this.fb.group({
      titre: ['', Validators.required],
      description: [''],
      crise: [null, Validators.required],
      equipe_ids: [[]],
      statut: ['EN_PREPARATION'],
    });
  }

  loadAll(): void {
    this.isLoading = true;
    forkJoin({
      missions: this.missionService.getAll(),
      teams: this.teamService.getAll(),
      crises: this.crisisService.getAll(),
      dossiers: this.dossierService.getAll(),
    }).subscribe({
      next: ({ missions, teams, crises, dossiers }) => {
        this.missions = missions;
        this.teams = teams;
        this.crises = crises;
        this.dossiers = dossiers;
        this.isLoading = false;
      },
      error: () => {
        this.showError('Impossible de charger les missions.');
        this.isLoading = false;
      },
    });
  }

  // ── Filtrage / affichage liste ──────────────────────────────

  get filteredMissions(): Mission[] {
    let list = [...this.missions];
    if (this.filterCrisis !== 'ALL') list = list.filter(m => m.crise === this.filterCrisis);
    if (this.filterStatut !== 'ALL') list = list.filter(m => m.statut === this.filterStatut);
    const q = this.searchQuery.trim().toLowerCase();
    if (q) list = list.filter(m => m.titre.toLowerCase().includes(q));
    return list;
  }

  crisisName(id: string): string {
    return this.crises.find(c => c.id === id)?.name ?? id.slice(0, 8);
  }

  teamName(id: string): string {
    return this.teams.find(t => t.id === id)?.name ?? id.slice(0, 8);
  }

  dossiersForMission(missionId: string): Dossier[] {
    return this.dossiers.filter(d => d.mission === missionId);
  }

  statutLabel(s: Mission['statut']): string {
    return this.statutOptions.find(o => o.value === s)?.label ?? s;
  }

  statutClass(s: Mission['statut']): string {
    return ({ EN_PREPARATION: 'stat-prep', EN_COURS: 'stat-cours', TERMINEE: 'stat-terminee' } as Record<string, string>)[s] ?? '';
  }

  teamZoneSummary(team: Team): string {
    if (team.zone_precise) return 'zone dessinée';
    if (team.communes?.length) return `${team.communes.length} commune${team.communes.length > 1 ? 's' : ''}`;
    if (team.departements?.length) return `${team.departements.length} département${team.departements.length > 1 ? 's' : ''}`;
    return 'aucune zone déclarée';
  }

  // ── Création / édition ──────────────────────────────────────

  openCreate(): void {
    this.missionForm.reset({ titre: '', description: '', crise: null, equipe_ids: [], statut: 'EN_PREPARATION' });
    this.teamSearchQuery = '';
    this.modal = 'create';
  }

  openEdit(mission: Mission, e?: Event): void {
    e?.stopPropagation();
    this.selectedMission = mission;
    this.missionForm.patchValue({
      titre: mission.titre,
      description: mission.description,
      crise: mission.crise,
      equipe_ids: [...mission.equipe_ids],
      statut: mission.statut,
    });
    this.teamSearchQuery = '';
    this.modal = 'edit';
  }

  get filteredTeamsForForm(): Team[] {
    const q = this.teamSearchQuery.trim().toLowerCase();
    if (!q) return [];
    const selected = new Set(this.missionForm.value.equipe_ids as string[]);
    return this.teams.filter(t => !selected.has(t.id!) && t.name.toLowerCase().includes(q));
  }

  addTeamToForm(team: Team): void {
    const ids: string[] = this.missionForm.value.equipe_ids;
    if (!ids.includes(team.id!)) this.missionForm.get('equipe_ids')?.setValue([...ids, team.id]);
    this.teamSearchQuery = '';
  }

  removeTeamFromForm(teamId: string): void {
    const ids: string[] = this.missionForm.value.equipe_ids;
    this.missionForm.get('equipe_ids')?.setValue(ids.filter(id => id !== teamId));
  }

  submitCreate(): void {
    if (this.missionForm.invalid) { this.missionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.missionService.create(this.missionForm.value).subscribe({
      next: () => { this.loadAll(); this.showSuccess('Mission créée.'); this.closeModal(); this.isSaving = false; },
      error: (err) => { this.showError(err?.error?.detail || 'Erreur lors de la création.'); this.isSaving = false; },
    });
  }

  submitEdit(): void {
    if (!this.selectedMission?.id || this.missionForm.invalid) { this.missionForm.markAllAsTouched(); return; }
    this.isSaving = true;
    this.missionService.patch(this.selectedMission.id, this.missionForm.value).subscribe({
      next: () => { this.loadAll(); this.showSuccess('Mission modifiée.'); this.closeModal(); this.isSaving = false; },
      error: () => { this.showError('Erreur lors de la modification.'); this.isSaving = false; },
    });
  }

  cloturerMission(mission: Mission, e?: Event): void {
    e?.stopPropagation();
    this.missionService.patch(mission.id!, { statut: 'TERMINEE', date_cloture: new Date().toISOString() }).subscribe({
      next: () => { this.loadAll(); this.showSuccess('Mission clôturée.'); },
      error: () => this.showError('Erreur lors de la clôture.'),
    });
  }

  openDelete(mission: Mission, e?: Event): void {
    e?.stopPropagation();
    this.selectedMission = mission;
    this.modal = 'delete';
  }

  confirmDelete(): void {
    if (!this.selectedMission?.id) return;
    this.missionService.delete(this.selectedMission.id).subscribe({
      next: () => { this.loadAll(); this.showSuccess('Mission supprimée.'); this.closeModal(); },
      error: () => this.showError('Erreur lors de la suppression.'),
    });
  }

  // ── Détail ───────────────────────────────────────────────────

  openDetail(mission: Mission): void {
    this.selectedMission = mission;
    this.modal = 'detail';
  }

  closeModal(): void {
    this.modal = 'none';
    this.selectedMission = null;
  }

  private showSuccess(msg: string): void {
    this.successMessage = msg;
    setTimeout(() => this.successMessage = '', 3000);
  }

  private showError(msg: string): void {
    this.errorMessage = msg;
    setTimeout(() => this.errorMessage = '', 5000);
  }
}
