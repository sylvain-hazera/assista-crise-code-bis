import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { MissionService } from '../../services/mission.service';
import { TeamService } from '../../services/team.service';
import { CrisisService } from '../../services/crisis.service';
import { DossierService } from '../../services/dossier.service';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';

import { Mission } from '../../shared/models/mission.model';
import { Team } from '../../shared/models/team.model';
import { Crisis } from '../../shared/models/crisis.model';
import { Dossier } from '../../shared/models/dossier.model';
import { PositionNoeudMission } from '../../shared/models/position-noeud-mission.model';
import { MinimapComponent, MinimapPointInteret } from '../../shared/components/common/minimap/minimap.component';

type ModalView = 'none' | 'create' | 'edit' | 'delete' | 'detail';
type FilterCrisis = string | 'ALL';
type FilterStatut = Mission['statut'] | 'ALL';

@Component({
  selector: 'app-missions',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, MinimapComponent],
  templateUrl: './missions.component.html',
  styleUrls: ['./missions.component.scss'],
})
export class MissionsComponent implements OnInit {

  missions: Mission[] = [];
  teams: Team[] = [];
  crises: Crisis[] = [];
  dossiers: Dossier[] = [];
  /** Positions des nœuds MeshCore personnels des équipes en mission EN_COURS — voir
   * NoeudMeshUtilisateurViewSet.positions_en_mission, jamais renvoyé hors mission active. */
  positionsMesh: PositionNoeudMission[] = [];

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
    private noeudMeshService: NoeudMeshUtilisateurService,
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

    // Séparé du forkJoin principal : purement additif (carte de suivi terrain), ne doit
    // jamais faire échouer le chargement des missions si MeshCore n'est pas configuré ou
    // que l'appelant n'a pas les droits dessus.
    this.noeudMeshService.positionsEnMission().subscribe({
      next: (positions) => { this.positionsMesh = positions; },
      error: () => { this.positionsMesh = []; },
    });
  }

  // ── Suivi de position MeshCore (missions EN_COURS uniquement) ───────

  positionsPourMission(missionId: string): PositionNoeudMission[] {
    return this.positionsMesh.filter(p => p.mission_id === missionId);
  }

  /** Premier nœud suivi = point principal de la mini-carte, les autres en points
   * d'intérêt — MinimapComponent ajuste alors le cadrage pour tous les englober (voir
   * MinimapComponent.fitToPoints). */
  pointPrincipalPourMission(missionId: string): PositionNoeudMission | null {
    return this.positionsPourMission(missionId)[0] ?? null;
  }

  pointsInteretPourMission(missionId: string): MinimapPointInteret[] {
    return this.positionsPourMission(missionId).slice(1).map(p => ({
      latitude: p.latitude, longitude: p.longitude,
      label: p.nom_noeud || p.utilisateur_nom,
    }));
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

  demarrerMission(mission: Mission, e?: Event): void {
    e?.stopPropagation();
    this.missionService.patch(mission.id!, { statut: 'EN_COURS' }).subscribe({
      next: () => { this.loadAll(); this.showSuccess('Mission passée en cours.'); },
      error: () => this.showError('Erreur lors du changement de statut.'),
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
