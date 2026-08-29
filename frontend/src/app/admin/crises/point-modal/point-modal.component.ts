import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { CompetenceService } from '../../../services/competence.service';
import { TeamService } from '../../../services/team.service';
import { PointOperationnel, PointType } from '../../../shared/models/point-operationnel.model';
import { Institution } from '../../../shared/models/institution.model';
import { Competence } from '../../../shared/models/competence.model';
import { Team } from '../../../shared/models/team.model';
import { AddressResult } from '../../../shared/models/address-result.model';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { PointPickerComponent } from '../../../shared/components/common/point-picker/point-picker.component';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { PointEquipeModalComponent } from '../point-equipe-modal/point-equipe-modal.component';
import { PointInventaireModalComponent } from '../point-inventaire-modal/point-inventaire-modal.component';
import { StocksComparaisonModalComponent } from '../stocks-comparaison-modal/stocks-comparaison-modal.component';
import { PointSecretariatModalComponent } from '../point-secretariat-modal/point-secretariat-modal.component';

/**
 * Modale "Créer/éditer un point opérationnel" — remplace l'ancien formulaire inline de
 * crises.component (création seule). Volontairement séparée en composant dédié : les volets
 * suivants du même chantier (compétences requises, équipe responsable, inventaire matériel)
 * y ajoutent chacun une section, ce qui aurait rendu crises.component ingérable si tout était
 * resté inline.
 */
@Component({
  selector: 'app-point-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, AddressPickerComponent, PointPickerComponent, TagSearchInputComponent, PointEquipeModalComponent, PointInventaireModalComponent, StocksComparaisonModalComponent, PointSecretariatModalComponent],
  templateUrl: './point-modal.component.html',
  styleUrl: './point-modal.component.scss'
})
export class PointModalComponent implements OnChanges {
  @Input({ required: true }) crisisId!: string;
  @Input({ required: true }) pointTypes: PointType[] = [];
  @Input({ required: true }) selectableInstitutions: Institution[] = [];
  @Input() isAdmin = false;
  @Input() point: PointOperationnel | null = null; // null = création

  @Output() saved = new EventEmitter<PointOperationnel>();
  @Output() closed = new EventEmitter<void>();
  /** Mise à jour "silencieuse" (compétences, futures sections équipe/matériel) : le parent
   * doit rafraîchir sa liste, mais la modale reste ouverte (contrairement à `saved`, qui
   * suit la soumission du formulaire principal et ferme la modale). */
  @Output() pointUpdated = new EventEmitter<PointOperationnel>();

  form!: FormGroup;
  latitude: number | null = null;
  longitude: number | null = null;
  saving = false;
  errorMessage = '';
  selectedCompetences: { id: string; nom: string }[] = [];
  teams: Team[] = [];
  equipeModalOpen = false;
  inventaireModalOpen = false;
  comparaisonModalOpen = false;
  secretariatModalOpen = false;

  constructor(
    private fb: FormBuilder,
    private pointService: PointOperationnelService,
    private competenceService: CompetenceService,
    private teamService: TeamService,
    private router: Router,
  ) {
    this.buildForm();
    this.teamService.getAll().subscribe(teams => this.teams = teams);
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['point']) {
      this.buildForm();
    }
  }

  private buildForm(): void {
    this.form = this.fb.group({
      institution: [null],
      type: [this.point?.type ?? null, Validators.required],
      nom: [this.point?.nom ?? '', Validators.required],
      description: [this.point?.description ?? ''],
      capacite_accueil: [this.point?.capacite_accueil ?? null],
      date_ouverture: [this.toDatetimeLocal(this.point?.date_ouverture)],
      date_fermeture: [this.toDatetimeLocal(this.point?.date_fermeture)],
      equipe: [this.point?.equipe ?? null],
    });
    this.latitude = this.point?.latitude ?? null;
    this.longitude = this.point?.longitude ?? null;

    const ids = this.point?.competences_requises ?? [];
    const libelles = this.point?.competences_requises_libelles ?? [];
    this.selectedCompetences = ids.map((id, i) => ({ id, nom: libelles[i] ?? id }));
  }

  onCompetenceSelected(item: Competence): void {
    if (!this.point || this.selectedCompetences.some(c => c.id === item.id)) return;
    const ids = [...this.selectedCompetences.map(c => c.id), item.id];
    this.pointService.update(this.point.id, { competences_requises: ids }).subscribe(updated => {
      this.selectedCompetences = [...this.selectedCompetences, { id: item.id, nom: item.nom }];
      this.pointUpdated.emit(updated);
    });
  }

  removeCompetence(id: string): void {
    if (!this.point) return;
    const ids = this.selectedCompetences.filter(c => c.id !== id).map(c => c.id);
    this.pointService.update(this.point.id, { competences_requises: ids }).subscribe(updated => {
      this.selectedCompetences = this.selectedCompetences.filter(c => c.id !== id);
      this.pointUpdated.emit(updated);
    });
  }

  get isEdit(): boolean {
    return !!this.point;
  }

  openEquipeModal(): void {
    this.equipeModalOpen = true;
  }

  closeEquipeModal(): void {
    this.equipeModalOpen = false;
  }

  openInventaireModal(): void {
    this.inventaireModalOpen = true;
  }

  closeInventaireModal(): void {
    this.inventaireModalOpen = false;
  }

  /** Ouvre le tableau Signalements en mode sélection pour y piocher des offres de matériel à
   * ajouter au stock de ce point (voir ReportingComponent ?pickForPoint=). */
  ouvrirTableauOffres(): void {
    if (!this.point?.id) return;
    this.router.navigate(['/admin/signalements'], { queryParams: { pickForPoint: this.point.id } });
  }

  openComparaisonModal(): void {
    this.comparaisonModalOpen = true;
  }

  closeComparaisonModal(): void {
    this.comparaisonModalOpen = false;
  }

  openSecretariatModal(): void {
    this.secretariatModalOpen = true;
  }

  closeSecretariatModal(): void {
    this.secretariatModalOpen = false;
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

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { institution, type, nom, description, capacite_accueil, date_ouverture, date_fermeture, equipe } = this.form.value;
    const payload: any = {
      type, nom,
      description: description || undefined,
      capacite_accueil: capacite_accueil || null,
      date_ouverture: date_ouverture || null,
      date_fermeture: date_fermeture || null,
      equipe: equipe || null,
    };

    if (this.latitude != null && this.longitude != null) {
      payload.location = JSON.stringify({ type: 'Point', coordinates: [this.longitude, this.latitude] });
    }

    this.saving = true;
    this.errorMessage = '';

    const request$ = this.isEdit
      ? this.pointService.update(this.point!.id, payload)
      : this.pointService.create({ ...payload, crise: this.crisisId, institution: institution || undefined });

    request$.subscribe({
      next: (result) => {
        this.saving = false;
        this.saved.emit(result);
      },
      error: (err) => {
        this.saving = false;
        this.errorMessage = err.error?.crise?.[0] || err.error?.detail || "Impossible d'enregistrer ce point.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }

  private toDatetimeLocal(iso?: string | null): string {
    if (!iso) return '';
    // <input type="datetime-local"> attend "YYYY-MM-DDTHH:mm", sans le suffixe timezone ISO.
    return iso.slice(0, 16);
  }
}
