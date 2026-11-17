import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { PersonneVulnerableService, TypeVulnerabiliteService } from '../../../services/vulnerabilite.service';
import { ZoneService } from '../../../services/zone.service';
import { AdresseDeLaCommune, PersonneVulnerable, TypeVulnerabilite } from '../../../shared/models/vulnerabilite.model';
import { ZoneLibellee, libellerZones } from '../../../shared/models/zone.model';
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
  zones: ZoneLibellee[] = [];
  categories: TypeVulnerabilite[] = [];
  saving = false;
  errorMessage = '';

  /** Adresses de la commune proposées pour ce qui est tapé (relevé local, voir le service). */
  propositions: AdresseDeLaCommune[] = [];
  /** Identifiant de l'adresse choisie ; vide tant que l'adresse est un texte libre. */
  adresseBanId = '';
  /** Faux : la commune n'a pas encore de relevé d'adresses, le rattachement n'est pas possible. */
  releveDisponible = true;
  private rechercheEnAttente: ReturnType<typeof setTimeout> | null = null;

  /** À chaque frappe : le texte ne correspond plus à l'adresse choisie, donc le lien tombe, et
   * l'on repropose. Un court délai évite une requête par lettre. */
  surSaisieAdresse(): void {
    this.adresseBanId = '';
    if (this.rechercheEnAttente) clearTimeout(this.rechercheEnAttente);
    const texte = (this.form.get('adresse')?.value || '').trim();
    if (texte.length < 3) { this.propositions = []; return; }
    this.rechercheEnAttente = setTimeout(() => this.chercherAdresses(texte), 250);
  }

  chercherAdresses(texte: string): void {
    this.personneVulnerableService.chercherAdresses(texte, this.personne?.commune_code).subscribe({
      next: (reponse) => { this.releveDisponible = reponse.releve_disponible; this.propositions = reponse.adresses; },
      error: () => { this.propositions = []; },
    });
  }

  choisirAdresse(adresse: AdresseDeLaCommune): void {
    this.form.patchValue({ adresse: adresse.adresse });
    this.adresseBanId = adresse.ban_id;
    this.propositions = [];
  }

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
    this.zoneService.getAll().subscribe(zones => this.zones = libellerZones(zones));
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
    this.adresseBanId = this.personne?.adresse_ban_id ?? '';
    this.propositions = [];
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
      adresse_ban_id: this.adresseBanId || null,
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
