import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';

import { PlanService } from '../../../services/plan.service';
import { PlanMissionModeleService } from '../../../services/plan-mission-modele.service';
import { ZoneService } from '../../../services/zone.service';
import { TeamService } from '../../../services/team.service';
import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { UserService } from '../../../services/user.service';
import { AuthService } from '../../../auth/services/auth.service';
import { Plan, PlanMissionModele } from '../../../shared/models/plan.model';
import { Zone } from '../../../shared/models/zone.model';
import { Team } from '../../../shared/models/team.model';
import { PointOperationnel } from '../../../shared/models/point-operationnel.model';
import { User } from '../../../shared/models/user.model';

/**
 * Créer/éditer un plan (dispositif pré-enregistré, voir Plan) : sélection par chip-toggle des
 * zones/équipes/points déjà existants de mon institution — même patron d'accumulation locale
 * puis submit unique que ZoneModalComponent (un plan en création n'a pas encore d'id).
 */
@Component({
  selector: 'app-plan-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, FormsModule],
  templateUrl: './plan-modal.component.html',
  styleUrl: './plan-modal.component.scss',
})
export class PlanModalComponent implements OnChanges {
  @Input() plan: Plan | null = null; // null = création

  @Output() saved = new EventEmitter<Plan>();
  @Output() closed = new EventEmitter<void>();

  form!: FormGroup;
  zones: Zone[] = [];
  teams: Team[] = [];
  points: PointOperationnel[] = [];
  users: User[] = [];

  selectedZoneIds: string[] = [];
  selectedTeamIds: string[] = [];
  selectedPointIds: string[] = [];

  saving = false;
  errorMessage = '';

  // Missions modèles (uniquement en édition — un plan sans id ne peut pas encore en porter, voir
  // PlanMissionModele.plan) : équipe/mission/référent instanciés en Mission+Dossier réels à
  // l'activation de cette équipe (PlanViewSet.activer).
  missionsModeles: PlanMissionModele[] = [];
  missionForm!: FormGroup;
  showMissionForm = false;
  missionReferentQuery = '';
  showMissionReferentResults = false;
  missionSaving = false;
  missionError = '';

  private myInstitutionId: string | null = null;

  constructor(
    private fb: FormBuilder,
    private planService: PlanService,
    private missionModeleService: PlanMissionModeleService,
    private zoneService: ZoneService,
    private teamService: TeamService,
    private pointService: PointOperationnelService,
    private userService: UserService,
    private authService: AuthService,
  ) {
    this.buildForm();
    this.buildMissionForm();
    this.myInstitutionId = this.authService.getCurrentUser()?.institution_id ?? null;
    this.zoneService.getAll().subscribe(zones => this.zones = zones);
    this.teamService.getAll().subscribe(teams => {
      this.teams = this.myInstitutionId ? teams.filter(t => t.institution === this.myInstitutionId) : teams;
    });
    this.pointService.getMine().subscribe(points => this.points = points);
    this.userService.getAll().subscribe(users => this.users = users);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['plan']) {
      this.buildForm();
      this.loadMissionsModeles();
    }
  }

  private buildMissionForm(): void {
    this.missionForm = this.fb.group({
      equipe: [null, Validators.required],
      titre: ['', Validators.required],
      description: [''],
      referent: [null],
    });
  }

  private loadMissionsModeles(): void {
    this.missionsModeles = [];
    if (!this.plan?.id) return;
    this.missionModeleService.getByPlan(this.plan.id).subscribe(modeles => this.missionsModeles = modeles);
  }

  // Équipes sélectionnées pour ce plan (le formulaire n'a de sens que pour l'une d'elles) —
  // recalculé à chaque affichage plutôt que mémorisé, `selectedTeamIds` change librement.
  get selectableTeamsForMission(): Team[] {
    return this.teams.filter(t => !!t.id && this.selectedTeamIds.includes(t.id));
  }

  get missionReferentResults(): User[] {
    const q = this.missionReferentQuery.trim().toLowerCase();
    if (!q) return [];
    return this.users.filter(u =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) || u.username.toLowerCase().includes(q)
    );
  }

  selectMissionReferent(user: User): void {
    this.missionForm.get('referent')?.setValue(user.id);
    this.missionReferentQuery = `${user.first_name} ${user.last_name}`.trim() || user.username;
    this.showMissionReferentResults = false;
  }

  onMissionReferentQueryChange(): void {
    this.missionForm.get('referent')?.setValue(null);
    this.showMissionReferentResults = true;
  }

  hideMissionReferentResultsDelayed(): void {
    setTimeout(() => this.showMissionReferentResults = false, 150);
  }

  submitMission(): void {
    if (!this.plan?.id || this.missionForm.invalid) { this.missionForm.markAllAsTouched(); return; }

    const { equipe, titre, description, referent } = this.missionForm.value;
    this.missionSaving = true;
    this.missionError = '';
    this.missionModeleService.create({
      plan: this.plan.id, equipe, titre, description: description || undefined, referent: referent || undefined,
    }).subscribe({
      next: () => {
        this.missionSaving = false;
        this.loadMissionsModeles();
        this.missionForm.reset();
        this.missionReferentQuery = '';
        this.showMissionForm = false;
      },
      error: (err) => {
        this.missionSaving = false;
        this.missionError = err.error?.detail || err.error?.equipe?.[0] || "Impossible d'enregistrer cette mission.";
      },
    });
  }

  deleteMission(modele: PlanMissionModele): void {
    this.missionModeleService.delete(modele.id).subscribe({
      next: () => this.loadMissionsModeles(),
      error: () => this.missionError = 'Impossible de retirer cette mission.',
    });
  }

  private buildForm(): void {
    this.form = this.fb.group({
      nom: [this.plan?.nom ?? '', Validators.required],
      description: [this.plan?.description ?? ''],
    });
    this.selectedZoneIds = [...(this.plan?.zones_ids ?? [])];
    this.selectedTeamIds = [...(this.plan?.equipes_ids ?? [])];
    this.selectedPointIds = [...(this.plan?.points_ids ?? [])];
  }

  get isEdit(): boolean {
    return !!this.plan;
  }

  toggleZone(id: string): void {
    this.selectedZoneIds = this.selectedZoneIds.includes(id)
      ? this.selectedZoneIds.filter(i => i !== id)
      : [...this.selectedZoneIds, id];
  }

  toggleTeam(id: string): void {
    this.selectedTeamIds = this.selectedTeamIds.includes(id)
      ? this.selectedTeamIds.filter(i => i !== id)
      : [...this.selectedTeamIds, id];
  }

  togglePoint(id: string): void {
    this.selectedPointIds = this.selectedPointIds.includes(id)
      ? this.selectedPointIds.filter(i => i !== id)
      : [...this.selectedPointIds, id];
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { nom, description } = this.form.getRawValue();
    const payload = {
      nom,
      description: description || undefined,
      zones_ids: this.selectedZoneIds,
      equipes_ids: this.selectedTeamIds,
      points_ids: this.selectedPointIds,
    };

    this.saving = true;
    this.errorMessage = '';

    const request$ = this.isEdit
      ? this.planService.update(this.plan!.id, payload)
      : this.planService.create(payload);

    request$.subscribe({
      next: (result) => {
        this.saving = false;
        this.saved.emit(result);
      },
      error: (err) => {
        this.saving = false;
        this.errorMessage = err.error?.detail || "Impossible d'enregistrer ce plan.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }
}
