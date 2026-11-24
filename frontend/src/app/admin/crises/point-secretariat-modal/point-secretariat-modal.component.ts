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
  // Le regroupement des moyens accueille des intervenants (23/11/2026).
  { value: 'INTERVENANT', label: 'Intervenant mobilisé' },
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
  // Ce qui empêche l'enregistrement, affiché au-dessus du bouton (24/11/2026 : le clic
  // refusait sans rien dire quand le contact manquait).
  erreur: string | null = null;
  tente = false;

  // Âge de chaque enfant déclaré (index = même ordre que les lignes affichées) — jamais de
  // nom, juste l'âge (voir DeclarationSecurite.ages_enfants) ; redimensionné à chaque
  // changement de nombre_enfants, valeurs déjà saisies conservées.
  agesEnfants: (number | null)[] = [];

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
      // « Aucun email communiqué à l'entrée » : l'admission passe, le contact se complète
      // ensuite depuis la liste des présents (24/11/2026).
      contact_non_communique: [false],
      nombre_adultes: [1, [Validators.min(1)]],
      nombre_enfants: [0, [Validators.min(0)]],
      regime_alimentaire_specifique: [false],
    });
    this.form.get('nombre_enfants')?.valueChanges.subscribe((n: number) => this.resizeAgesEnfants(n));
  }

  private resizeAgesEnfants(nombreEnfants: number): void {
    const n = Math.max(0, nombreEnfants || 0);
    if (n === this.agesEnfants.length) return;
    if (n < this.agesEnfants.length) {
      this.agesEnfants = this.agesEnfants.slice(0, n);
    } else {
      this.agesEnfants = [...this.agesEnfants, ...Array(n - this.agesEnfants.length).fill(null)];
    }
  }

  setAgeEnfant(index: number, value: string): void {
    const age = value === '' ? null : Number(value);
    this.agesEnfants[index] = age != null && !Number.isNaN(age) ? age : null;
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
      contact_non_communique: false,
      nombre_adultes: 1, nombre_enfants: 0, regime_alimentaire_specifique: false,
    });
    this.agesEnfants = [];
    this.tente = false;
    this.erreur = null;
  }

  /** Champs obligatoires restés vides pour une personne évacuée. */
  get manquants(): string[] {
    if (!this.isEvacue) return [];
    const v = this.form.value;
    const vide = (x: unknown) => !String(x ?? '').trim();
    return [
      vide(v.prenom_referent) ? 'le prénom' : '',
      vide(v.nom_referent) ? 'le nom' : '',
      vide(v.contact_referent) && !v.contact_non_communique
        ? "un contact (email ou téléphone), ou cocher « Aucun email communiqué à l'entrée »" : '',
    ].filter(Boolean);
  }

  manque(champ: 'prenom_referent' | 'nom_referent' | 'contact_referent'): boolean {
    if (champ === 'contact_referent' && this.form.value.contact_non_communique) return false;
    return this.tente && this.isEvacue && !String(this.form.value[champ] ?? '').trim();
  }

  private echec(err: any): void {
    const corps = err?.error;
    let detail = '';
    if (corps && typeof corps === 'object') {
      detail = Object.values(corps).flat().filter(x => typeof x === 'string').join(' ');
    }
    this.erreur = detail || "L'arrivée n'a pas pu être enregistrée. Vérifiez la connexion et réessayez.";
  }

  submit(): void {
    this.tente = true;
    this.erreur = null;
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.erreur = 'Le nombre de personnes doit être au moins 1.';
      return;
    }

    if (this.isEvacue) {
      const v = this.form.value;
      const manquants = this.manquants;
      if (manquants.length) {
        this.form.markAllAsTouched();
        this.erreur = `À compléter avant d'enregistrer : ${manquants.join(', ')}.`;
        return;
      }
      const payload = {
        type_declarant: v.type_declarant,
        nom_referent: v.nom_referent,
        prenom_referent: v.prenom_referent,
        contact_referent: (v.contact_referent || '').trim(),
        contact_non_communique: !!v.contact_non_communique && !(v.contact_referent || '').trim(),
        nombre_adultes: v.type_declarant === 'PERSONNE_SEULE' ? 1 : v.nombre_adultes,
        nombre_enfants: v.type_declarant === 'PERSONNE_SEULE' ? 0 : v.nombre_enfants,
        ages_enfants: v.type_declarant === 'PERSONNE_SEULE'
          ? [] : this.agesEnfants.filter((a): a is number => a != null),
        regime_alimentaire_specifique: v.regime_alimentaire_specifique,
        commentaire: v.commentaire,
        centre_accueil: this.point.id,
      };
      this.declarationSecuriteService.create(payload).subscribe({
        next: () => { this.load(); this.resetForm(); },
        error: err => this.echec(err),
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
    this.registreService.create(payload).subscribe({
      next: () => { this.load(); this.resetForm(); },
      error: err => this.echec(err),
    });
  }

  // Complément du contact d'une admission enregistrée sans (une ligne à la fois).
  contactEnCours: string | null = null;
  contactSaisi = '';
  erreurContact: string | null = null;

  ouvrirContact(entree: RegistrePresence): void {
    this.contactEnCours = entree.id;
    this.contactSaisi = '';
    this.erreurContact = null;
  }

  enregistrerContact(entree: RegistrePresence): void {
    const contact = this.contactSaisi.trim();
    if (!contact) {
      this.erreurContact = 'Indiquez un email ou un téléphone.';
      return;
    }
    if (!entree.declaration) return;
    this.declarationSecuriteService.completerContact(entree.declaration, contact).subscribe({
      next: () => { this.contactEnCours = null; this.load(); },
      error: err => {
        const corps = err?.error;
        this.erreurContact = (corps && (corps.contact_referent || corps.detail)) || "Le contact n'a pas pu être enregistré.";
      },
    });
  }

  marquerSortie(entree: RegistrePresence): void {
    this.registreService.sortie(entree.id).subscribe(() => this.load());
  }

  close(): void {
    this.closed.emit();
  }
}
