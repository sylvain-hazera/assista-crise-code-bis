import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { PersonneVulnerableService, TypeVulnerabiliteService } from '../../../services/vulnerabilite.service';
import { ZoneService } from '../../../services/zone.service';
import { PersonneVulnerable, TypeVulnerabilite } from '../../../shared/models/vulnerabilite.model';
import { Zone } from '../../../shared/models/zone.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { QuiAConsulteComponent } from '../../../shared/components/qui-a-consulte/qui-a-consulte.component';

/**
 * Créer/éditer une fiche du registre des personnes vulnérables (voir PersonneVulnerable côté
 * backend) -- même patron que zone-modal (création/édition en un seul submit). Catégories de
 * vulnérabilité via le catalogue partagé TypeVulnerabilite (tag-search-input, même gabarit que
 * zone-modal pour les communes) : "ajouter un item libre" crée une entrée catalogue réutilisable,
 * jamais un champ de notes libres -- discipline "fonctionnel, jamais diagnostic".
 */
@Component({
  selector: 'app-personne-vulnerable-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, TagSearchInputComponent, QuiAConsulteComponent],
  templateUrl: './personne-vulnerable-modal.component.html',
  styleUrl: './personne-vulnerable-modal.component.scss',
})
export class PersonneVulnerableModalComponent implements OnInit, OnChanges {
  @Input() personne: PersonneVulnerable | null = null; // null = création

  @Output() saved = new EventEmitter<PersonneVulnerable>();
  @Output() closed = new EventEmitter<void>();

  form!: FormGroup;
  zones: Zone[] = [];
  categories: TypeVulnerabilite[] = [];
  saving = false;
  errorMessage = '';

  categorieSearchFn = (q: string) => this.typeVulnerabiliteService.search(q);
  categorieCreateFn = (nom: string) => this.typeVulnerabiliteService.create({ nom });
  categorieCreateLabelFn = (value: string) => `Créer « ${value} » comme nouvelle catégorie`;

  constructor(
    private fb: FormBuilder,
    private personneVulnerableService: PersonneVulnerableService,
    private typeVulnerabiliteService: TypeVulnerabiliteService,
    private zoneService: ZoneService,
  ) {
    this.buildForm();
  }

  ngOnInit(): void {
    this.zoneService.getAll().subscribe(zones => this.zones = zones);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['personne']) {
      this.buildForm();
    }
  }

  private buildForm(): void {
    this.form = this.fb.group({
      nom: [this.personne?.nom ?? '', Validators.required],
      prenom: [this.personne?.prenom ?? '', Validators.required],
      adresse: [this.personne?.adresse ?? '', Validators.required],
      telephone: [this.personne?.telephone ?? ''],
      zone: [this.personne?.zone ?? ''],
      contact_aidant_nom: [this.personne?.contact_aidant_nom ?? ''],
      contact_aidant_telephone: [this.personne?.contact_aidant_telephone ?? ''],
      mode_consentement: [this.personne?.mode_consentement ?? 'VOLONTAIRE', Validators.required],
      demandeur_consentement: [this.personne?.demandeur_consentement ?? ''],
      date_consentement: [this.personne?.date_consentement ?? ''],
    });
    this.categories = [...(this.personne?.categories_detail ?? [])];
  }

  get isEdit(): boolean {
    return !!this.personne;
  }

  addCategorie(categorie: TypeVulnerabilite): void {
    if (this.categories.some(c => c.id === categorie.id)) return;
    this.categories = [...this.categories, categorie];
  }

  removeCategorie(id: string): void {
    this.categories = this.categories.filter(c => c.id !== id);
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const raw = this.form.getRawValue();
    const payload: Partial<PersonneVulnerable> = {
      ...raw,
      zone: raw.zone || null,
      telephone: raw.telephone || null,
      contact_aidant_nom: raw.contact_aidant_nom || null,
      contact_aidant_telephone: raw.contact_aidant_telephone || null,
      date_consentement: raw.date_consentement || null,
      categorie_ids: this.categories.map(c => c.id),
    };

    this.saving = true;
    this.errorMessage = '';

    const request$ = this.isEdit
      ? this.personneVulnerableService.update(this.personne!.id, payload)
      : this.personneVulnerableService.create(payload);

    request$.subscribe({
      next: (result) => {
        this.saving = false;
        this.saved.emit(result);
      },
      error: (err) => {
        this.saving = false;
        this.errorMessage = err.error?.detail || "Impossible d'enregistrer cette fiche.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }
}
