import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { RegistrePresenceService } from '../../../services/registre-presence.service';
import { PointOperationnel } from '../../../shared/models/point-operationnel.model';
import { RegistrePresence, TypePersonneAccueillie } from '../../../shared/models/registre-presence.model';

const TYPES: { value: TypePersonneAccueillie; label: string }[] = [
  { value: 'EVACUE', label: 'Personne évacuée' },
  { value: 'POMPIER', label: 'Pompier' },
  { value: 'BENEVOLE_AUTRE_EQUIPE', label: "Bénévole d'une autre équipe" },
  { value: 'AUTRE', label: 'Autre' },
];

/** "Secrétariat" du point : registre de qui est accueilli en ce moment (évacués, pompiers,
 * bénévoles d'autres équipes...) — même moule que PointInventaireModalComponent (liste +
 * formulaire d'ajout inline dans une seule modale). */
@Component({
  selector: 'app-point-secretariat-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './point-secretariat-modal.component.html',
  styleUrl: './point-secretariat-modal.component.scss'
})
export class PointSecretariatModalComponent implements OnInit {
  @Input({ required: true }) point!: PointOperationnel;
  @Output() closed = new EventEmitter<void>();

  types = TYPES;
  registre: RegistrePresence[] = [];
  loading = true;
  form: FormGroup;

  constructor(private fb: FormBuilder, private registreService: RegistrePresenceService) {
    this.form = this.fb.group({
      type_personne: ['EVACUE', Validators.required],
      nom: [''],
      nombre: [1, [Validators.required, Validators.min(1)]],
      commentaire: [''],
    });
  }

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.loading = true;
    this.registreService.getByPoint(this.point.id).subscribe(data => {
      this.registre = data;
      this.loading = false;
    });
  }

  get presents(): RegistrePresence[] {
    return this.registre.filter(r => !r.date_depart);
  }

  get sortis(): RegistrePresence[] {
    return this.registre.filter(r => !!r.date_depart);
  }

  get totalPresents(): number {
    return this.presents.reduce((sum, r) => sum + r.nombre, 0);
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const payload = { ...this.form.value, point: this.point.id };
    this.registreService.create(payload).subscribe(() => {
      this.load();
      this.form.reset({ type_personne: 'EVACUE', nom: '', nombre: 1, commentaire: '' });
    });
  }

  marquerSortie(entree: RegistrePresence): void {
    this.registreService.sortie(entree.id).subscribe(() => this.load());
  }

  close(): void {
    this.closed.emit();
  }
}
