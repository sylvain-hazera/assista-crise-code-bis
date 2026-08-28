import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { DeclarationSecuriteService } from '../../services/declaration-securite.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { DeclarationSecurite, SituationDeclarant } from '../../shared/models/declaration-securite.model';
import { CentreAccueilPublic } from '../../shared/models/point-operationnel.model';

interface SituationOption {
  value: SituationDeclarant;
  label: string;
}

const SITUATION_OPTIONS: SituationOption[] = [
  { value: 'RELOGE', label: "Je suis en sécurité / relogé" },
  { value: 'EN_CENTRE', label: "Je suis en centre d'accueil" },
  { value: 'BESOIN_CENTRE', label: "Je suis en sécurité mais j'ai besoin d'un point de chute" },
  { value: 'HORS_ZONE', label: "Je suis en sécurité, hors zone (voyage, chez des proches…)" },
];

@Component({
  selector: 'app-mes-declarations-securite',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './mes-declarations-securite.component.html',
  styleUrl: './mes-declarations-securite.component.scss',
})
export class MesDeclarationsSecuriteComponent implements OnInit {
  declarations: DeclarationSecurite[] = [];
  isLoading = true;
  errorMessage = '';

  readonly situationOptions = SITUATION_OPTIONS;

  editingId: string | null = null;
  editSituation: SituationDeclarant = 'RELOGE';
  editCentreId: string | null = null;
  editCentres: CentreAccueilPublic[] = [];
  editLoadingCentres = false;
  editSaving = false;
  editError = '';

  constructor(
    private declarationSecuriteService: DeclarationSecuriteService,
    private pointOperationnelService: PointOperationnelService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.chargerDeclarations();
  }

  private chargerDeclarations(): void {
    this.declarationSecuriteService.mesDeclarations().subscribe({
      next: (declarations) => {
        this.declarations = declarations;
        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = "Impossible de charger vos déclarations. Vous devez être connecté.";
        this.isLoading = false;
      },
    });
  }

  headcount(d: DeclarationSecurite): number {
    return d.nombre_adultes + d.nombre_enfants;
  }

  fmtDate(d: string | null | undefined): string {
    if (!d) return '—';
    return new Date(d).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  goToDeclare(): void {
    this.router.navigate(['/other-declaration']);
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }

  isEditing(d: DeclarationSecurite): boolean {
    return this.editingId === d.id;
  }

  startEdit(d: DeclarationSecurite): void {
    this.editingId = d.id ?? null;
    this.editSituation = d.situation ?? 'RELOGE';
    this.editCentreId = d.centre_accueil ?? null;
    this.editCentres = [];
    this.editError = '';

    if (this.editSituation === 'EN_CENTRE') {
      this.loadCentres(d);
    }
  }

  cancelEdit(): void {
    this.editingId = null;
    this.editCentres = [];
    this.editError = '';
  }

  onEditSituationChange(d: DeclarationSecurite): void {
    if (this.editSituation === 'EN_CENTRE') {
      this.loadCentres(d);
    } else {
      this.editCentreId = null;
    }
  }

  private loadCentres(d: DeclarationSecurite): void {
    if (!d.crise) {
      this.editCentres = [];
      return;
    }
    this.editLoadingCentres = true;
    this.pointOperationnelService.getCentresAccueilPublics(d.crise).subscribe({
      next: (centres) => {
        this.editCentres = centres;
        this.editLoadingCentres = false;
      },
      error: () => {
        this.editCentres = [];
        this.editLoadingCentres = false;
      },
    });
  }

  saveEdit(d: DeclarationSecurite): void {
    if (!d.id) return;
    if (this.editSituation === 'EN_CENTRE' && !this.editCentreId) {
      this.editError = 'Merci de choisir un centre d\'accueil.';
      return;
    }

    this.editSaving = true;
    this.editError = '';
    const payload: Partial<DeclarationSecurite> = {
      situation: this.editSituation,
      centre_accueil: this.editSituation === 'EN_CENTRE' ? this.editCentreId : null,
    };

    this.declarationSecuriteService.update(d.id, payload).subscribe({
      next: (updated) => {
        const index = this.declarations.findIndex((decl) => decl.id === updated.id);
        if (index !== -1) {
          this.declarations[index] = updated;
        }
        this.editSaving = false;
        this.editingId = null;
      },
      error: () => {
        this.editError = "La mise à jour a échoué. Réessayez.";
        this.editSaving = false;
      },
    });
  }
}
