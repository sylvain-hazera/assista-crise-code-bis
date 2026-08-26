import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AffectationCompetenceService } from '../../services/affectation-competence.service';
import { CrisisService } from '../../services/crisis.service';
import { CompetenceService } from '../../services/competence.service';
import { TeamService } from '../../services/team.service';

import { AffectationCompetence } from '../../shared/models/affectation-competence.model';
import { Crisis } from '../../shared/models/crisis.model';
import { Competence } from '../../shared/models/competence.model';
import { Team } from '../../shared/models/team.model';

@Component({
  selector: 'app-affectations',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './affectations.component.html',
  styleUrls: ['./affectations.component.scss'],
})
export class AffectationsComponent implements OnInit {

  affectations: AffectationCompetence[] = [];
  crises: Crisis[] = [];
  competences: Competence[] = [];
  teams: Team[] = [];

  showForm = false;
  form!: FormGroup;
  isLoading = true;
  errorMessage = '';
  successMessage = '';

  constructor(
    private fb: FormBuilder,
    private affectationService: AffectationCompetenceService,
    private crisisService: CrisisService,
    private competenceService: CompetenceService,
    private teamService: TeamService,
  ) {
    this.form = this.fb.group({
      crise: [null, Validators.required],
      competence: [null, Validators.required],
      equipe: [null, Validators.required],
      active: [true],
      commentaire: [''],
    });
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading = true;
    forkJoin({
      affectations: this.affectationService.getAll(),
      crises: this.crisisService.getAll(),
      competences: this.competenceService.getAll(),
      teams: this.teamService.getAll(),
    }).subscribe({
      next: ({ affectations, crises, competences, teams }) => {
        this.affectations = affectations;
        this.crises = crises;
        this.competences = competences;
        this.teams = teams;
        this.isLoading = false;
      },
      error: () => {
        this.showError('Impossible de charger les affectations.');
        this.isLoading = false;
      },
    });
  }

  reload(): void {
    this.affectationService.getAll().subscribe(data => this.affectations = data);
  }

  submit(): void {
    if (this.form.invalid) { this.form.markAllAsTouched(); return; }
    this.affectationService.create(this.form.value).subscribe({
      next: () => {
        this.reload();
        this.showSuccess('Affectation créée.');
        this.form.reset({ active: true, commentaire: '' });
        this.showForm = false;
      },
      error: () => this.showError("Erreur lors de la création de l'affectation."),
    });
  }

  toggleActive(affectation: AffectationCompetence): void {
    this.affectationService.update(affectation.id, { ...affectation, active: !affectation.active }).subscribe({
      next: () => this.reload(),
      error: () => this.showError('Erreur lors de la mise à jour.'),
    });
  }

  delete(affectation: AffectationCompetence): void {
    this.affectationService.delete(affectation.id).subscribe({
      next: () => { this.reload(); this.showSuccess('Affectation supprimée.'); },
      error: () => this.showError('Erreur lors de la suppression.'),
    });
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
