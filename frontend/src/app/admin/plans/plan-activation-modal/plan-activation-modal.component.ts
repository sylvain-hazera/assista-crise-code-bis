import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { PlanService } from '../../../services/plan.service';
import { CrisisService } from '../../../services/crisis.service';
import { TeamService } from '../../../services/team.service';
import { BesoinService } from '../../../services/besoin.service';
import { Plan, PlanActivationResult } from '../../../shared/models/plan.model';
import { Crisis } from '../../../shared/models/crisis.model';
import { Team } from '../../../shared/models/team.model';
import { Besoin } from '../../../shared/models/besoin.model';
import { AddressResult } from '../../../shared/models/address-result.model';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { PointPickerComponent } from '../../../shared/components/common/point-picker/point-picker.component';

/**
 * Active un plan sur une crise réelle (existante ou créée à la volée) : checklist des
 * équipes/points du plan, pré-cochés (tous par défaut — c'est le levier "varier les équipes
 * activées"), avec un éditeur de thèmes par équipe pré-rempli depuis ses thèmes actuels et
 * librement ajustable avant validation (le levier "varier les thèmes à l'équipe").
 */
@Component({
  selector: 'app-plan-activation-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, AddressPickerComponent, PointPickerComponent],
  templateUrl: './plan-activation-modal.component.html',
  styleUrl: './plan-activation-modal.component.scss',
})
export class PlanActivationModalComponent implements OnInit {
  @Input({ required: true }) plan!: Plan;

  @Output() activated = new EventEmitter<PlanActivationResult>();
  @Output() closed = new EventEmitter<void>();

  crisisTypeOptions = [
    { value: 'INCENDIE', label: 'Incendie' },
    { value: 'INONDATION', label: 'Inondation' },
    { value: 'ACCIDENT', label: 'Accident' },
    { value: 'CATASTROPHE_NATURELLE', label: 'Catastrophe naturelle' },
    { value: 'AUTRE', label: 'Autre' },
  ];

  mode: 'existing' | 'new' = 'existing';
  crises: Crisis[] = [];
  selectedCrisisId: string | null = null;

  nouvelleCriseName = '';
  nouvelleCriseType = 'AUTRE';
  latitude: number | null = null;
  longitude: number | null = null;

  planTeams: Team[] = [];
  allThemes: Besoin[] = [];
  selectedTeamIds: string[] = [];
  selectedPointIds: string[] = [];
  teamThemeSelections: Record<string, string[]> = {};

  loading = true;
  activating = false;
  errorMessage = '';

  constructor(
    private planService: PlanService,
    private crisisService: CrisisService,
    private teamService: TeamService,
    private besoinService: BesoinService,
  ) {}

  ngOnInit(): void {
    this.selectedTeamIds = [...this.plan.equipes_ids];
    this.selectedPointIds = [...this.plan.points_ids];

    forkJoin({
      crises: this.crisisService.getAll(),
      teams: this.teamService.getAll(),
      themes: this.besoinService.getAll(),
    }).subscribe({
      next: ({ crises, teams, themes }) => {
        this.crises = crises.filter(c => c.is_open !== false);
        this.planTeams = teams.filter(t => this.plan.equipes_ids.includes(t.id!));
        this.allThemes = themes;
        this.planTeams.forEach(t => {
          this.teamThemeSelections[t.id!] = [...(t.theme_ids ?? [])];
        });
        this.loading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les données nécessaires à l’activation.';
        this.loading = false;
      },
    });
  }

  get planPoints(): { id: string; nom: string }[] {
    return this.plan.points_ids.map((id, i) => ({ id, nom: this.plan.points_noms[i] || id }));
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

  toggleTheme(teamId: string, themeId: string): void {
    const current = this.teamThemeSelections[teamId] ?? [];
    this.teamThemeSelections[teamId] = current.includes(themeId)
      ? current.filter(i => i !== themeId)
      : [...current, themeId];
  }

  onAddressSelected(addr: AddressResult | null): void {
    if (!addr) return;
    this.latitude = addr.latitude;
    this.longitude = addr.longitude;
  }

  onPositionChange(pos: { latitude: number; longitude: number }): void {
    this.latitude = pos.latitude;
    this.longitude = pos.longitude;
  }

  get canSubmit(): boolean {
    if (this.mode === 'existing') return !!this.selectedCrisisId;
    return !!this.nouvelleCriseName.trim() && this.latitude != null && this.longitude != null;
  }

  submit(): void {
    if (!this.canSubmit) return;

    const equipes = this.selectedTeamIds.map(team_id => ({
      team_id,
      themes_ids: this.teamThemeSelections[team_id] ?? [],
    }));

    const payload: any = {
      equipes,
      points: this.selectedPointIds,
    };

    if (this.mode === 'existing') {
      payload.crise_id = this.selectedCrisisId;
    } else {
      payload.nouvelle_crise = {
        name: this.nouvelleCriseName.trim(),
        type: this.nouvelleCriseType,
        location: JSON.stringify({ type: 'Point', coordinates: [this.longitude, this.latitude] }),
      };
    }

    this.activating = true;
    this.errorMessage = '';

    this.planService.activer(this.plan.id, payload).subscribe({
      next: (result) => {
        this.activating = false;
        this.activated.emit(result);
      },
      error: (err) => {
        this.activating = false;
        this.errorMessage = err.error?.error || err.error?.detail || "Impossible d'activer ce plan.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }
}
