import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AuthService } from '../../auth/services/auth.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { OfferService } from '../../services/offer.service';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { Offer } from '../../shared/models/offer.model';
import { Institution } from '../../shared/models/institution.model';
import { PointModalComponent } from '../crises/point-modal/point-modal.component';

/** Logement des intervenants : points de type Hébergement et offres de particuliers cochées
 * « accueil_intervenants » (distinct d'accueil_sinistres). Une offre de particulier reste en
 * attente tant qu'un institutionnel ne l'a pas validée (valider_accueil_intervenants). */
@Component({
  selector: 'app-logement-intervenants',
  standalone: true,
  imports: [CommonModule, FormsModule, PointModalComponent],
  templateUrl: './logement-intervenants.component.html',
  styleUrl: './logement-intervenants.component.scss',
})
export class LogementIntervenantsComponent implements OnInit {
  points: PointOperationnel[] = [];
  pointTypes: PointType[] = [];
  offresEnAttente: Offer[] = [];
  offresValidees: Offer[] = [];

  isLoading = true;
  errorMessage = '';
  validationEnCours: string | null = null;

  pointModalOpen = false;
  editingPoint: PointOperationnel | null = null;

  readonly selectableInstitutions: Institution[] = [];

  constructor(
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private offerService: OfferService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  get isAdmin(): boolean {
    return this.authService.isAdmin();
  }

  /** Seul un point de ce type est proposable à la création ici -- on ne force pas le champ
   * dans PointModalComponent (pas prévu pour), on restreint juste son sélecteur de type à
   * cette unique option, ce qui revient au même pour l'utilisateur. */
  get pointTypesHebergement(): PointType[] {
    return this.pointTypes.filter(t => t.code === 'HEBERGEMENT');
  }

  private load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    forkJoin({
      points: this.pointService.getAll(),
      pointTypes: this.pointTypeService.getAll(),
      offresEnAttente: this.offerService.getAll({ accueil_intervenants: 'true', accueil_intervenants_valide: 'false' }),
      offresValidees: this.offerService.getAll({ accueil_intervenants: 'true', accueil_intervenants_valide: 'true' }),
    }).subscribe({
      next: ({ points, pointTypes, offresEnAttente, offresValidees }) => {
        this.points = points.filter(p => p.type_code === 'HEBERGEMENT');
        this.pointTypes = pointTypes;
        this.offresEnAttente = offresEnAttente;
        this.offresValidees = offresValidees;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les logements intervenants.';
        this.isLoading = false;
      },
    });
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

  valider(offre: Offer): void {
    if (!offre.id) return;
    this.validationEnCours = offre.id;
    this.offerService.validerAccueilIntervenants(offre.id).subscribe({
      next: () => {
        this.validationEnCours = null;
        this.load();
      },
      error: () => {
        this.validationEnCours = null;
        this.errorMessage = "Échec de la validation de l'offre.";
      },
    });
  }
}
