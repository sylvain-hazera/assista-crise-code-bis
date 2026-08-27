import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { PointOperationnel, PointType } from '../../../shared/models/point-operationnel.model';
import { Institution } from '../../../shared/models/institution.model';
import { AddressResult } from '../../../shared/models/address-result.model';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { PointPickerComponent } from '../../../shared/components/common/point-picker/point-picker.component';

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
  imports: [CommonModule, ReactiveFormsModule, AddressPickerComponent, PointPickerComponent],
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

  form!: FormGroup;
  latitude: number | null = null;
  longitude: number | null = null;
  saving = false;
  errorMessage = '';

  constructor(private fb: FormBuilder, private pointService: PointOperationnelService) {
    this.buildForm();
  }

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
      date_ouverture: [this.toDatetimeLocal(this.point?.date_ouverture)],
      date_fermeture: [this.toDatetimeLocal(this.point?.date_fermeture)],
    });
    this.latitude = this.point?.latitude ?? null;
    this.longitude = this.point?.longitude ?? null;
  }

  get isEdit(): boolean {
    return !!this.point;
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

    const { institution, type, nom, description, date_ouverture, date_fermeture } = this.form.value;
    const payload: any = {
      type, nom,
      description: description || undefined,
      date_ouverture: date_ouverture || null,
      date_fermeture: date_fermeture || null,
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
