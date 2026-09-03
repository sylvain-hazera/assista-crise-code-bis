import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { PlanService } from '../../../services/plan.service';
import { ZoneService } from '../../../services/zone.service';
import { TeamService } from '../../../services/team.service';
import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { AuthService } from '../../../auth/services/auth.service';
import { Plan } from '../../../shared/models/plan.model';
import { Zone } from '../../../shared/models/zone.model';
import { Team } from '../../../shared/models/team.model';
import { PointOperationnel } from '../../../shared/models/point-operationnel.model';

/**
 * Créer/éditer un plan (dispositif pré-enregistré, voir Plan) : sélection par chip-toggle des
 * zones/équipes/points déjà existants de mon institution — même patron d'accumulation locale
 * puis submit unique que ZoneModalComponent (un plan en création n'a pas encore d'id).
 */
@Component({
  selector: 'app-plan-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
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

  selectedZoneIds: string[] = [];
  selectedTeamIds: string[] = [];
  selectedPointIds: string[] = [];

  saving = false;
  errorMessage = '';

  private myInstitutionId: string | null = null;

  constructor(
    private fb: FormBuilder,
    private planService: PlanService,
    private zoneService: ZoneService,
    private teamService: TeamService,
    private pointService: PointOperationnelService,
    private authService: AuthService,
  ) {
    this.buildForm();
    this.myInstitutionId = this.authService.getCurrentUser()?.institution_id ?? null;
    this.zoneService.getAll().subscribe(zones => this.zones = zones);
    this.teamService.getAll().subscribe(teams => {
      this.teams = this.myInstitutionId ? teams.filter(t => t.institution === this.myInstitutionId) : teams;
    });
    this.pointService.getMine().subscribe(points => this.points = points);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['plan']) {
      this.buildForm();
    }
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
