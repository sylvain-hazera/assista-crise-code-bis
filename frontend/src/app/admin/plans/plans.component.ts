import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { PlanService } from '../../services/plan.service';
import { DossierPcsComponent } from './dossier-pcs/dossier-pcs.component';
import { Plan, PlanActivationResult } from '../../shared/models/plan.model';
import { PlanModalComponent } from './plan-modal/plan-modal.component';
import { PlanActivationModalComponent } from './plan-activation-modal/plan-activation-modal.component';

/**
 * Dispositifs pré-enregistrés de mon institution (voir Plan) : équipes/points/zones préparés à
 * l'avance, activables en un geste sur une crise réelle le jour J.
 */
@Component({
  selector: 'app-plans',
  standalone: true,
  imports: [CommonModule, FormsModule, PlanModalComponent, PlanActivationModalComponent, DossierPcsComponent],
  templateUrl: './plans.component.html',
  styleUrl: './plans.component.scss',
})
export class PlansComponent implements OnInit {
  plans: Plan[] = [];
  searchQuery = '';
  isLoading = true;
  errorMessage = '';
  successMessage = '';

  modalOpen = false;
  editingPlan: Plan | null = null;

  activationModalOpen = false;
  activatingPlan: Plan | null = null;

  constructor(private planService: PlanService, private router: Router) {}

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.planService.getAll().subscribe({
      next: (plans) => {
        this.plans = plans;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les plans.';
        this.isLoading = false;
      },
    });
  }

  get filteredPlans(): Plan[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.plans;
    return this.plans.filter(p => p.nom.toLowerCase().includes(q));
  }

  openCreateModal(): void {
    this.editingPlan = null;
    this.modalOpen = true;
  }

  openEditModal(plan: Plan): void {
    this.editingPlan = plan;
    this.modalOpen = true;
  }

  closeModal(): void {
    this.modalOpen = false;
    this.editingPlan = null;
  }

  onSaved(): void {
    this.closeModal();
    this.load();
  }

  deletePlan(plan: Plan, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Retirer le plan « ${plan.nom} » ?`)) return;
    this.planService.delete(plan.id).subscribe({
      next: () => this.load(),
      error: () => this.errorMessage = 'Impossible de retirer ce plan.',
    });
  }

  openActivationModal(plan: Plan, event: Event): void {
    event.stopPropagation();
    this.activatingPlan = plan;
    this.activationModalOpen = true;
  }

  closeActivationModal(): void {
    this.activationModalOpen = false;
    this.activatingPlan = null;
  }

  onActivated(result: PlanActivationResult): void {
    this.closeActivationModal();
    const dossiersPart = result.dossiers_crees.length > 0
      ? `, ${result.dossiers_crees.length} mission(s) instanciée(s)`
      : '';
    this.successMessage = `Plan activé sur la crise « ${result.crise.name} » (${result.equipes_activees.length} équipe(s), ${result.points_actives.length} point(s)${dossiersPart}).`;
    this.criseActivee = result.crise.id;
  }

  /** Crise sur laquelle un dispositif vient d'être activé : c'est là qu'on va ensuite. */
  criseActivee = '';

  /** La suite d'une activation est la conduite de la crise, pas la liste des crises : on ouvre
   * la cellule de crise de celle qu'on vient d'armer. */
  ouvrirCellule(): void {
    this.router.navigate(['/admin/cellule-crise'], { queryParams: this.criseActivee ? { crise: this.criseActivee } : {} });
  }

  goToCrises(): void {
    this.router.navigate(['/admin/crises']);
  }
}
