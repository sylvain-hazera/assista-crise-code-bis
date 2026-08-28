import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { RegistrePresenceService } from '../../../services/registre-presence.service';
import { DeclarationSecuriteService } from '../../../services/declaration-securite.service';
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

  constructor(
    private fb: FormBuilder,
    private registreService: RegistrePresenceService,
    private declarationSecuriteService: DeclarationSecuriteService,
  ) {
    this.form = this.fb.group({
      type_personne: ['EVACUE', Validators.required],
      nom: [''],
      nombre: [1, [Validators.required, Validators.min(1)]],
      commentaire: [''],
      // Recensement enrichi ("je suis ok"), utilisé seulement quand type_personne === 'EVACUE'
      // — crée une DeclarationSecurite (qui génère elle-même la ligne RegistrePresence
      // correspondante), au lieu d'un simple RegistrePresence direct pour les autres types.
      type_declarant: ['PERSONNE_SEULE'],
      nom_referent: [''],
      prenom_referent: [''],
      contact_referent: [''],
      nombre_adultes: [1, [Validators.min(1)]],
      nombre_enfants: [0, [Validators.min(0)]],
      regime_alimentaire_specifique: [false],
    });
  }

  get isEvacue(): boolean {
    return this.form.get('type_personne')?.value === 'EVACUE';
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

  private resetForm(): void {
    this.form.reset({
      type_personne: 'EVACUE', nom: '', nombre: 1, commentaire: '',
      type_declarant: 'PERSONNE_SEULE', nom_referent: '', prenom_referent: '', contact_referent: '',
      nombre_adultes: 1, nombre_enfants: 0, regime_alimentaire_specifique: false,
    });
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    if (this.isEvacue) {
      const v = this.form.value;
      if (!v.nom_referent || !v.prenom_referent || !v.contact_referent) {
        this.form.markAllAsTouched();
        return;
      }
      const payload = {
        type_declarant: v.type_declarant,
        nom_referent: v.nom_referent,
        prenom_referent: v.prenom_referent,
        contact_referent: v.contact_referent,
        nombre_adultes: v.type_declarant === 'PERSONNE_SEULE' ? 1 : v.nombre_adultes,
        nombre_enfants: v.type_declarant === 'PERSONNE_SEULE' ? 0 : v.nombre_enfants,
        regime_alimentaire_specifique: v.regime_alimentaire_specifique,
        commentaire: v.commentaire,
        centre_accueil: this.point.id,
      };
      this.declarationSecuriteService.create(payload).subscribe(() => {
        this.load();
        this.resetForm();
      });
      return;
    }

    const payload = {
      type_personne: this.form.value.type_personne,
      nom: this.form.value.nom,
      nombre: this.form.value.nombre,
      commentaire: this.form.value.commentaire,
      point: this.point.id,
    };
    this.registreService.create(payload).subscribe(() => {
      this.load();
      this.resetForm();
    });
  }

  marquerSortie(entree: RegistrePresence): void {
    this.registreService.sortie(entree.id).subscribe(() => this.load());
  }

  close(): void {
    this.closed.emit();
  }
}
