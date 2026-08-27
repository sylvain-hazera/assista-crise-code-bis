import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { MaterielPointService } from '../../../services/materiel-point.service';
import { PointOperationnel } from '../../../shared/models/point-operationnel.model';
import { MaterielPoint, TypeMateriel, StatutMateriel } from '../../../shared/models/materiel-point.model';

const TYPES: { value: TypeMateriel; label: string }[] = [
  { value: 'CUVE', label: 'Cuve' },
  { value: 'POMPE', label: 'Pompe' },
  { value: 'ETUVE', label: 'Étuve' },
  { value: 'CHAMBRE_FROIDE', label: 'Chambre froide' },
  { value: 'REMORQUE', label: 'Remorque' },
  { value: 'AUTRE', label: 'Autre' },
];

const STATUTS: { value: StatutMateriel; label: string }[] = [
  { value: 'EN_TRANSIT', label: 'En transit' },
  { value: 'SUR_PLACE', label: 'Sur place' },
  { value: 'RETIRE', label: 'Retiré' },
];

/** "Sous-menu - fenêtre" inventaire d'un point : liste du matériel en transit ou présent,
 * avec ajout/édition inline — même esprit que le tableau "Institutions impliquées" déjà
 * présent sur l'écran crise. */
@Component({
  selector: 'app-point-inventaire-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './point-inventaire-modal.component.html',
  styleUrl: './point-inventaire-modal.component.scss'
})
export class PointInventaireModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Output() closed = new EventEmitter<void>();

  types = TYPES;
  statuts = STATUTS;
  materiels: MaterielPoint[] = [];
  loading = true;
  form: FormGroup;
  editingId: string | null = null;

  constructor(private fb: FormBuilder, private materielService: MaterielPointService) {
    this.form = this.fb.group({
      type: ['AUTRE', Validators.required],
      nom: ['', Validators.required],
      quantite: [1, [Validators.required, Validators.min(1)]],
      unite: ['unité'],
      statut: ['SUR_PLACE'],
      commentaire: [''],
    });
  }

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.materielService.getByPoint(this.point.id).subscribe(data => {
      this.materiels = data;
      this.loading = false;
    });
  }

  statutLabel(statut: StatutMateriel): string {
    return this.statuts.find(s => s.value === statut)?.label ?? statut;
  }

  edit(materiel: MaterielPoint): void {
    this.editingId = materiel.id;
    this.form.setValue({
      type: materiel.type, nom: materiel.nom, quantite: materiel.quantite,
      unite: materiel.unite, statut: materiel.statut, commentaire: materiel.commentaire ?? '',
    });
  }

  cancelEdit(): void {
    this.editingId = null;
    this.form.reset({ type: 'AUTRE', nom: '', quantite: 1, unite: 'unité', statut: 'SUR_PLACE', commentaire: '' });
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const payload = { ...this.form.value, point: this.point.id };
    const request$ = this.editingId
      ? this.materielService.update(this.editingId, payload)
      : this.materielService.create(payload);

    request$.subscribe(() => {
      this.load();
      this.cancelEdit();
    });
  }

  remove(materiel: MaterielPoint): void {
    if (!confirm(`Retirer « ${materiel.nom} » de l'inventaire ?`)) return;
    this.materielService.delete(materiel.id).subscribe(() => this.load());
  }

  close(): void {
    this.closed.emit();
  }
}
