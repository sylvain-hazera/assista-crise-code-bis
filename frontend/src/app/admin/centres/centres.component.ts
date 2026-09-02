import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AuthService } from '../../auth/services/auth.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { Institution } from '../../shared/models/institution.model';
import { UserRole } from '../../shared/models/user.model';
import { PointModalComponent } from '../crises/point-modal/point-modal.component';

/**
 * Accès direct à "mes" centres (points d'accueil / de regroupement dont je suis responsable,
 * leader ou membre de l'équipe), toutes crises confondues — évite d'avoir à repasser par la
 * fiche de chaque crise pour gérer un centre déjà créé. Bascule "Tous les centres" pour un
 * profil qui supervise plus large que ses propres affectations.
 */
@Component({
  selector: 'app-centres',
  standalone: true,
  imports: [CommonModule, FormsModule, PointModalComponent],
  templateUrl: './centres.component.html',
  styleUrl: './centres.component.scss'
})
export class CentresComponent implements OnInit {
  points: PointOperationnel[] = [];
  pointTypes: PointType[] = [];
  scope: 'mine' | 'all' = 'mine';
  searchQuery = '';
  isLoading = true;
  errorMessage = '';

  pointModalOpen = false;
  editingPoint: PointOperationnel | null = null;

  readonly selectableInstitutions: Institution[] = [];

  constructor(
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  get isAdmin(): boolean {
    return this.authService.getCurrentUser()?.type === UserRole.ADMIN;
  }

  setScope(scope: 'mine' | 'all'): void {
    if (this.scope === scope) return;
    this.scope = scope;
    this.load();
  }

  private load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    const points$ = this.scope === 'mine' ? this.pointService.getMine() : this.pointService.getAll();

    forkJoin({ points: points$, pointTypes: this.pointTypeService.getAll() }).subscribe({
      next: ({ points, pointTypes }) => {
        this.points = points;
        this.pointTypes = pointTypes;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les centres.';
        this.isLoading = false;
      },
    });
  }

  get filteredPoints(): PointOperationnel[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.points;
    return this.points.filter(p =>
      p.nom.toLowerCase().includes(q) || (p.crise_nom ?? '').toLowerCase().includes(q)
    );
  }

  openPointModal(point: PointOperationnel): void {
    this.editingPoint = point;
    this.pointModalOpen = true;
  }

  openCreateModal(): void {
    this.editingPoint = null;
    this.pointModalOpen = true;
  }

  closePointModal(): void {
    this.pointModalOpen = false;
    this.editingPoint = null;
  }

  onPointSaved(): void {
    this.closePointModal();
    this.load();
  }

  onPointUpdated(updated: PointOperationnel): void {
    const idx = this.points.findIndex(p => p.id === updated.id);
    if (idx !== -1) this.points[idx] = updated;
    this.editingPoint = updated;
  }
}
