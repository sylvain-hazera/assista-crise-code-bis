import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray, AbstractControl, ValidationErrors } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { forkJoin, Observable } from 'rxjs';
import { CommonModule } from '@angular/common';
import { OfferService } from '../../../services/offer.service';
import { DisponibiliteOffreService } from '../../../services/disponibilite-offre.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { Offer } from '../../../shared/models/offer.model';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole, User } from '../../../shared/models/user.model';
import { Creneau } from '../../../shared/models/disponibilite-offre.model';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { AddressResult } from '../../../shared/models/address-result.model';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { CompetenceService } from '../../../services/competence.service';
import { Competence } from '../../../shared/models/competence.model';
import { MaterielCatalogueService } from '../../../services/materiel-catalogue.service';
import { MaterielCatalogue } from '../../../shared/models/materiel-catalogue.model';
import { RgpdNoticeComponent } from '../../../shared/components/public/rgpd-notice/rgpd-notice.component';
import { ValidationSummaryComponent } from '../../../shared/components/public/validation-summary/validation-summary.component';
import { PhotoGalleryPickerComponent } from '../../../shared/components/public/photo-gallery-picker/photo-gallery-picker.component';
import { CriseLieuThemeComponent } from '../../../shared/components/public/crise-lieu-theme/crise-lieu-theme.component';

interface JourDispo {
  date: string;       // YYYY-MM-DD
  label: string;       // ex: "lun. 25/08"
  creneaux: { creneau: Creneau; label: string; checked: boolean }[];
}

// Libellés exacts des OfferType (backend/entrypoint.sh).
const TYPE_HEBERGEMENT = 'Hébergement';
const TYPE_SOINS = 'Soins médicaux et paramédicaux';
const TYPE_TRANSPORT = 'Transport';
const TYPE_MATERIEL = 'Matériel';
const TYPE_SOUTIEN = 'Soutien psychologique';
const TYPE_AUTRE = 'Autre';
const TYPE_NOURRITURE = 'Nourriture et eau';
const TYPE_BENEVOLAT = 'Bénévolat';

// Pseudo-type : la ligne ne devient pas une offre, chaque engin coché devient la sienne
// (voir DOCUMENTATION.md, § 6.2).
const ENGINS_AGRICOLES_VALUE = 'ENGINS_AGRICOLES';

// Présence physique de l'offreur : imposée par certains types, à préciser pour les types
// ambigus (voir DOCUMENTATION.md, § 6.2).
const TYPES_PRESENCE_FORCEE_FAUSSE = [TYPE_HEBERGEMENT];
const TYPES_PRESENCE_FORCEE_VRAIE = [TYPE_SOINS, TYPE_SOUTIEN, TYPE_AUTRE, TYPE_BENEVOLAT];
const TYPES_PRESENCE_A_PRECISER = [TYPE_TRANSPORT, TYPE_MATERIEL, TYPE_NOURRITURE];

/** Case de conformité véhicule, obligatoire selon le contrôle voisin `type` : addOffer()
 * force la réévaluation à chaque changement de type. */
function confirmationReglementaireValidator(control: AbstractControl): ValidationErrors | null {
  const parent = control.parent;
  if (!parent) return null;
  const type = parent.get('type')?.value;
  // La ligne passerelle Engins utilise engineConfirmationReglementaire à la place.
  if (type === TYPE_MATERIEL && parent.get('materielType')?.value === ENGINS_AGRICOLES_VALUE) return null;
  const requiert = type === TYPE_TRANSPORT || type === TYPE_MATERIEL;
  return (requiert && !control.value) ? { required: true } : null;
}

/** presencePhysique doit être true/false (jamais null) sur les types ambigus. */
function presencePhysiqueValidator(control: AbstractControl): ValidationErrors | null {
  const parent = control.parent;
  if (!parent) return null;
  const type = parent.get('type')?.value;
  if (type === TYPE_MATERIEL && parent.get('materielType')?.value === ENGINS_AGRICOLES_VALUE) return null;
  const requiert = TYPES_PRESENCE_A_PRECISER.includes(type);
  return (requiert && control.value === null) ? { required: true } : null;
}

/** Type d'animal exigé si transportType === ANIMAUX (réévalué dans addOffer()). */
function transportAnimauxPrecisionValidator(control: AbstractControl): ValidationErrors | null {
  const parent = control.parent;
  if (!parent) return null;
  const transportType = parent.get('transportType')?.value;
  return (transportType === 'ANIMAUX' && !control.value) ? { required: true } : null;
}

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent, TagSearchInputComponent, RgpdNoticeComponent, ValidationSummaryComponent, PhotoGalleryPickerComponent, CriseLieuThemeComponent],
  templateUrl: './propose-help-form.component.html',
  styleUrl: './propose-help-form.component.scss'
})
export class ProposeHelpFormComponent implements OnInit {
  currentUser : User | null = null;
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  state: number = 1;

  latitude: number | null = null;
  longitude: number | null = null;

  typesOffreMap: Map<string, string> = new Map(); // offerType (label) -> UUID

  readonly TYPE_HEBERGEMENT = TYPE_HEBERGEMENT;
  readonly TYPE_SOINS = TYPE_SOINS;
  readonly TYPE_TRANSPORT = TYPE_TRANSPORT;
  readonly TYPE_MATERIEL = TYPE_MATERIEL;
  readonly TYPE_SOUTIEN = TYPE_SOUTIEN;
  readonly TYPE_AUTRE = TYPE_AUTRE;
  readonly ENGINS_AGRICOLES_VALUE = ENGINS_AGRICOLES_VALUE;

  readonly materielLivraisonOptions: { value: string; label: string }[] = [
    { value: 'A_RECUPERER', label: 'À récupérer sur place' },
    { value: 'LIVRAISON_POSSIBLE', label: 'Je peux le déposer dans un centre de regroupement' },
  ];

  readonly materielTypeOptions: { value: string; label: string }[] = [
    { value: '', label: '— Choisir —' },
    { value: 'CUVE', label: 'Cuve / citerne mobile' },
    { value: 'POMPE', label: 'Pompe' },
    { value: 'ETUVE', label: 'Étuve' },
    { value: 'CHAMBRE_FROIDE', label: 'Chambre froide' },
    { value: 'REMORQUE', label: 'Remorque' },
    { value: ENGINS_AGRICOLES_VALUE, label: 'Engins agricoles / chantiers / spécialisés' },
    { value: 'AUTRE', label: 'Autre' },
  ];

  readonly cuveContenuOptions: { value: string; label: string }[] = [
    { value: 'EAU', label: 'Eau' },
    { value: 'CARBURANT', label: 'Carburant' },
  ];

  // ── Hébergement : critères détaillés du logement (offre) ───────────────────────
  readonly typeLoyerOptions: { value: string; label: string }[] = [
    { value: 'GRATUIT', label: 'Gratuit' },
    { value: 'NEGOCIE', label: 'Loyer négocié (du fait de la situation)' },
    { value: 'MARCHE', label: 'Loyer au prix du marché' },
  ];

  readonly typeLogementOptions: { value: string; label: string }[] = [
    { value: '', label: '— Choisir —' },
    { value: 'MAISON', label: 'Maison' },
    { value: 'APPARTEMENT', label: 'Appartement' },
    { value: 'STUDIO', label: 'Studio' },
    { value: 'COLOCATION', label: 'Colocation' },
    { value: 'CHAMBRE', label: 'Chambre' },
  ];

  /** Adresse propre au logement ; à défaut, l'adresse partagée est utilisée à la soumission. */
  onHebergementAddressSelected(row: AbstractControl, addr: AddressResult | null): void {
    this.rowGroup(row).patchValue({
      hebergementLatitude: addr?.latitude ?? null,
      hebergementLongitude: addr?.longitude ?? null,
    });
  }

  // ── Rubrique "Engins agricoles / chantiers / spéciaux" ─────────────────────────
  // Chaque engin coché devient une offre (Matériel/Autre + catalogue), avec quantité et photo
  // propres. Catalogue MaterielCatalogue (categorie=ENGIN), extensible via « Autre ».
  engineLines: { item: MaterielCatalogue; checked: boolean; quantite: number | null; photo: File | null }[] = [];
  newEngineNom = '';
  addingCustomEngine = false;
  // Une seule confirmation réglementaire pour tout le lot d'engins.
  engineConfirmationReglementaire = false;
  engineImmatriculation = '';

  get hasCheckedEngines(): boolean {
    return this.engineLines.some(l => l.checked);
  }

  private loadEngineCatalogue(): void {
    this.materielCatalogueService.getAll('ENGIN').subscribe({
      next: (list) => {
        this.engineLines = list.map(item => ({ item, checked: false, quantite: null, photo: null }));
      },
      error: () => {},
    });
  }

  onEnginePhotoSelected(line: { photo: File | null }, event: Event): void {
    const input = event.target as HTMLInputElement;
    line.photo = input.files?.[0] ?? null;
  }

  addCustomEngine(): void {
    const nom = this.newEngineNom.trim();
    if (!nom) return;
    this.addingCustomEngine = true;
    this.materielCatalogueService.create({ nom, categorie: 'ENGIN' }).subscribe({
      next: (item) => {
        // Réutilise l'entrée existante (nom insensible à la casse), comme TagLikeViewSetMixin.
        const existing = this.engineLines.find(l => l.item.id === item.id);
        if (existing) {
          existing.checked = true;
        } else {
          this.engineLines = [...this.engineLines, { item, checked: true, quantite: null, photo: null }];
        }
        this.newEngineNom = '';
        this.addingCustomEngine = false;
      },
      error: () => { this.addingCustomEngine = false; },
    });
  }

  selectedAddress: AddressResult | null = null;

  onAddressSelected(addr: AddressResult | null): void {
    this.selectedAddress = addr;
    this.latitude = addr?.latitude ?? null;
    this.longitude = addr?.longitude ?? null;
  }

  // Étape « crise + lieu + thèmes à l'écoute » (app-crise-lieu-theme) : l'adresse n'est
  // demandée qu'une fois.
  criseSelectionnee: Crisis | null = null;
  typesOffreAutorises: string[] = [];

  onCriseSelectionnee(crise: Crisis | null): void {
    this.criseSelectionnee = crise;
    this.requestForm.patchValue({ crisisId: crise?.id || '' });
  }

  onTypesAutorises(typeIds: string[]): void {
    this.typesOffreAutorises = typeIds;
  }

  offerTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  /** Types limités aux thèmes à l'écoute ; options par nom, typesOffreMap fait la correspondance. */
  get offerTypeOptionsFiltrees(): { value: string; label: string }[] {
    return this.offerTypeOptions.slice(1).filter(opt => {
      const id = this.typesOffreMap.get(opt.value);
      return id && this.typesOffreAutorises.includes(id);
    });
  }

  personTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: UserRole.SIMPLE_USER, label: 'Particulier' },
    { value: UserRole.LOCAL_AUTH , label: 'Organisation' },
    { value: UserRole.RESCUE , label: 'Secours organisés' },
  ];

  // ── Disponibilités (8 jours x matin/midi/soir/nuit) ────────────
  joursDispo: JourDispo[] = [];

  // ── Compétences que le bénévole peut apporter (filtre côté recrutement) ─
  selectedCompetences: Competence[] = [];
  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  // Catalogue partagé : un matériel « Autre » saisi une fois est proposé à tous ensuite.
  allMateriels: MaterielCatalogue[] = [];
  materielCatalogueSearchFn = (q: string) => this.materielCatalogueService.search(q);
  materielCatalogueCreateFn = (nom: string) => this.materielCatalogueService.create({ nom });
  materielCatalogueCreateLabelFn = (value: string) => `Ajouter « ${value} » comme nouveau matériel`;

  readonly CATALOGUE_PREFIX = 'CATALOGUE:';

  /** Valeurs préfixées : une entrée du catalogue équivaut à « Autre » + ce matériel. */
  onMaterielTypeDropdownChange(row: AbstractControl, value: string): void {
    const rg = this.rowGroup(row);
    if (value.startsWith(this.CATALOGUE_PREFIX)) {
      const id = value.slice(this.CATALOGUE_PREFIX.length);
      const item = this.allMateriels.find(m => m.id === id);
      rg.patchValue({ materielType: 'AUTRE', materielCatalogue: id, materielCatalogueNom: item?.nom ?? '' });
    } else {
      rg.patchValue({ materielType: value, materielCatalogue: null, materielCatalogueNom: '' });
    }
  }

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private offerService: OfferService,
    private disponibiliteOffreService: DisponibiliteOffreService,
    private authService: AuthService,
    private competenceService: CompetenceService,
    private materielCatalogueService: MaterielCatalogueService,
  ) {}

  onMaterielCatalogueSelected(row: AbstractControl, item: MaterielCatalogue): void {
    this.rowGroup(row).patchValue({ materielCatalogue: item.id, materielCatalogueNom: item.nom });
    if (!this.allMateriels.some(m => m.id === item.id)) {
      this.allMateriels = [...this.allMateriels, item];
    }
  }

  // ── Type de matériel : menu catégorie/sous-catégorie pliable (choix unique) ──
  // État déplié tenu par ligne, indexé par l'instance du FormGroup.
  private materielDropdownOpenRows = new Set<AbstractControl>();
  private expandedMaterielGroupsByRow = new Map<AbstractControl, Set<string>>();

  isMaterielDropdownOpen(row: AbstractControl): boolean {
    return this.materielDropdownOpenRows.has(row);
  }

  toggleMaterielDropdown(row: AbstractControl): void {
    if (this.materielDropdownOpenRows.has(row)) this.materielDropdownOpenRows.delete(row);
    else this.materielDropdownOpenRows.add(row);
  }

  private materielExpandedSet(row: AbstractControl): Set<string> {
    let set = this.expandedMaterielGroupsByRow.get(row);
    if (!set) {
      set = new Set<string>();
      this.expandedMaterielGroupsByRow.set(row, set);
    }
    return set;
  }

  isMaterielGroupExpanded(row: AbstractControl, parentId: string): boolean {
    return this.materielExpandedSet(row).has(parentId);
  }

  toggleMaterielGroupExpand(row: AbstractControl, parentId: string): void {
    const set = this.materielExpandedSet(row);
    if (set.has(parentId)) set.delete(parentId);
    else set.add(parentId);
  }

  /** Catalogue par parent (MaterielCatalogue.parent) ; les entrées inactives sont masquées ici. */
  get materielGroups(): { parent: MaterielCatalogue; children: MaterielCatalogue[] }[] {
    const actifs = this.allMateriels.filter(m => m.actif !== false);
    const topLevel = actifs.filter(m => !m.parent);
    return topLevel.map(parent => ({
      parent,
      children: actifs.filter(m => m.parent === parent.id),
    }));
  }

  materielDisplayLabel(row: AbstractControl): string {
    const v = this.rowGroup(row).value;
    if (v.materielCatalogue && v.materielCatalogueNom) return v.materielCatalogueNom;
    const opt = this.materielTypeOptions.find(o => o.value === v.materielType);
    return opt && opt.value ? opt.label : '— Choisir —';
  }

  selectMaterielType(row: AbstractControl, value: string): void {
    this.onMaterielTypeDropdownChange(row, value);
    this.materielDropdownOpenRows.delete(row);
  }

  selectMaterielCatalogueItemFromTree(row: AbstractControl, item: MaterielCatalogue): void {
    // materielType doit valoir 'AUTRE' : onSubmit n'envoie materiel_catalogue que dans ce cas.
    this.rowGroup(row).patchValue({ materielType: 'AUTRE' });
    this.onMaterielCatalogueSelected(row, item);
    this.materielDropdownOpenRows.delete(row);
  }

  onCompetenceSelected(item: Competence): void {
    if (this.selectedCompetences.some(c => c.id === item.id)) return;
    this.selectedCompetences = [...this.selectedCompetences, item];
  }

  removeCompetence(id: string): void {
    this.selectedCompetences = this.selectedCompetences.filter(c => c.id !== id);
  }

  allCompetences: Competence[] = [];
  // « Autre (préciser) » ouvre la recherche/création libre, pour une compétence non listée.
  showCompetenceAutre = false;

  // ── Menu catégorie/sous-catégorie pliable (Competence.parent), sélection multiple ──
  competencesDropdownOpen = false;
  expandedCompetenceGroups = new Set<string>();

  get competenceGroups(): { parent: Competence; children: Competence[] }[] {
    const topLevel = this.allCompetences.filter(c => !c.parent);
    return topLevel.map(parent => ({
      parent,
      children: this.allCompetences.filter(c => c.parent === parent.id),
    }));
  }

  toggleCompetenceGroupExpand(parentId: string): void {
    if (this.expandedCompetenceGroups.has(parentId)) this.expandedCompetenceGroups.delete(parentId);
    else this.expandedCompetenceGroups.add(parentId);
  }

  isCompetenceGroupExpanded(parentId: string): boolean {
    return this.expandedCompetenceGroups.has(parentId);
  }

  isCompetenceChecked(id: string): boolean {
    return this.selectedCompetences.some(c => c.id === id);
  }

  toggleCompetenceChecked(item: Competence): void {
    if (this.isCompetenceChecked(item.id)) this.removeCompetence(item.id);
    else this.onCompetenceSelected(item);
  }

  competenceGroupState(group: { parent: Competence; children: Competence[] }): 'all' | 'some' | 'none' {
    const ids = [group.parent.id, ...group.children.map(c => c.id)];
    const selected = ids.filter(id => this.isCompetenceChecked(id)).length;
    if (selected === 0) return 'none';
    return selected === ids.length ? 'all' : 'some';
  }

  /** Coche ou décoche le thème parent et tous ses sous-thèmes. */
  toggleCompetenceGroupChecked(group: { parent: Competence; children: Competence[] }): void {
    const groupItems = [group.parent, ...group.children];
    const tout = groupItems.every(c => this.isCompetenceChecked(c.id));
    for (const item of groupItems) {
      const checked = this.isCompetenceChecked(item.id);
      if (tout && checked) this.removeCompetence(item.id);
      else if (!tout && !checked) this.onCompetenceSelected(item);
    }
  }

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesOffre();
    this.buildJoursDispo();
    this.competenceService.getAll().subscribe({
      next: (list) => this.allCompetences = list,
      error: () => {},
    });
    this.materielCatalogueService.getAll().subscribe({
      // Les engins ont leur propre rubrique (loadEngineCatalogue).
      next: (list) => this.allMateriels = list.filter(m => m.categorie !== 'ENGIN'),
      error: () => {},
    });
    this.loadEngineCatalogue();
  }

  private buildJoursDispo(): void {
    const CRENEAUX: { creneau: Creneau; label: string }[] = [
      { creneau: 'MATIN', label: 'Matin' },
      { creneau: 'MIDI', label: 'Midi' },
      { creneau: 'SOIR', label: 'Soir' },
      { creneau: 'NUIT', label: 'Nuit' },
    ];
    const jours: JourDispo[] = [];
    for (let i = 0; i < 8; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      jours.push({
        date: d.toISOString().slice(0, 10),
        label: d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' }),
        creneaux: CRENEAUX.map(c => ({ ...c, checked: false })),
      });
    }
    this.joursDispo = jours;
  }

  toggleDispo(jour: JourDispo, slot: { checked: boolean }): void {
    slot.checked = !slot.checked;
  }

  get allDisposChecked(): boolean {
    return this.joursDispo.every(jour => jour.creneaux.every(slot => slot.checked));
  }

  /** Tout cocher si un créneau reste décoché, sinon tout décocher. */
  toggleAllDispos(): void {
    const nouvelEtat = !this.allDisposChecked;
    this.joursDispo.forEach(jour => jour.creneaux.forEach(slot => slot.checked = nouvelEtat));
  }

  loadTypesOffre(): void {
    this.offerService.getTypes().subscribe({
      next: (types: any[]) => {
        types.forEach(type => {
          this.typesOffreMap.set(type.type, type.id);
        });
        this.offerTypeOptions = [
          { value: '', label: 'Dropdown' },
          ...types.map(t => ({ value: t.type, label: t.type }))
        ];
      },
      error: (err: any) => console.error('Erreur chargement types offre:', err)
    });
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      crisisId: [''],
      offerRows: new FormArray([]),
      addressVisible: [false],
      image: [null],
    });

    this.addOffer();

    this.informationForm = this.formBuilder.group({
      lastName: [this.currentUser?.last_name, Validators.required],
      firstName: [this.currentUser?.first_name, Validators.required],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phoneNumber: [this.currentUser?.phone_number, [Validators.required, Validators.pattern(/^\+?[\d\s.-]{10,20}$/)]],
      organisationNom: [''],
      // Qualifications déclarées une fois pour la personne, reportées sur chaque offre où elle est
      // présente (voir onSubmit).
      diplomeSecourisme: [false],
      ancienSapeurPompier: [false],
      acceptCgu: [false, Validators.requiredTrue],
    });
  }

  /** Galerie (10 photos max) : la première part dans `photo` de l'offre, les autres sont postées
   * après création. */
  selectedPhotos: File[] = [];

  onPhotosSelected(files: File[]): void {
    this.selectedPhotos = files;
  }

  // Résumé des erreurs, un par étape.
  formErrorsStep1: string[] = [];
  formErrorsStep2: string[] = [];

  private step1ValidationErrors(): string[] {
    const errors: string[] = [];
    if (!this.selectedAddress) errors.push('Sélectionnez une adresse dans la liste proposée.');
    return errors;
  }

  private step2ValidationErrors(): string[] {
    const errors: string[] = [];
    const f = this.informationForm;
    if (f.get('lastName')?.invalid) errors.push('Le nom est obligatoire.');
    if (f.get('firstName')?.invalid) errors.push('Le prénom est obligatoire.');
    if (f.get('email')?.invalid) errors.push('L\'email est obligatoire et doit être valide.');
    if (f.get('phoneNumber')?.invalid) errors.push('Le téléphone est obligatoire et doit être valide.');
    if (f.get('acceptCgu')?.invalid) errors.push('Vous devez accepter les conditions générales d\'utilisation.');
    if (this.offerRows.invalid) errors.push('Complétez les informations sur votre offre (un ou plusieurs champs manquants ou invalides).');
    if (this.hasCheckedEngines && !this.engineConfirmationReglementaire) {
      errors.push('Confirmez être en règle (vous et les engins cochés) pour valider la rubrique Engins agricoles / chantiers / spéciaux.');
    }
    return errors;
  }

  onSubmit(): void {
    this.informationForm.markAllAsTouched();
    this.offerRows.markAllAsTouched();
    this.formErrorsStep2 = this.step2ValidationErrors();
    if (this.formErrorsStep2.length > 0) return;

    const crisisId = this.requestForm.get('crisisId')?.value;
    const crisisLabel = this.criseSelectionnee ? `${this.criseSelectionnee.name} - ${this.criseSelectionnee.type_display || this.criseSelectionnee.type}` : 'non liée à une crise';
    const addressVisible = this.requestForm.get('addressVisible')?.value;
    const hasLocation = !!(addressVisible && this.latitude != null && this.longitude != null);

    // Dépôt groupé (organisation) : un groupe_id commun, seulement si un nom d'organisation est saisi.
    const organisationNom = (this.informationForm.get('organisationNom')?.value || '').trim();
    const groupeId = organisationNom ? crypto.randomUUID() : null;

    // La ligne passerelle Engins est exclue ; `realRows` sert de base d'index pour la suite.
    const realRows = this.offerRows.controls.filter(row => {
      const v = row.value;
      return !(v.type === TYPE_MATERIEL && v.materielType === ENGINS_AGRICOLES_VALUE);
    });

    const rowCreations: Observable<Offer>[] = realRows.map(row => {
      const v = row.value;
      const formData = new FormData();

      formData.append('title', `Offre d'aide - ${crisisLabel} - ${v.type}`);
      formData.append('first_name_offer', this.informationForm.get('firstName')?.value);
      formData.append('last_name_offer', this.informationForm.get('lastName')?.value);
      formData.append('email_offer', this.informationForm.get('email')?.value);
      formData.append('phone_offer', this.informationForm.get('phoneNumber')?.value);

      const typeId = this.typesOffreMap.get(v.type);
      if (typeId) formData.append('offer_type', typeId);
      if (crisisId) formData.append('crisis', crisisId);

      // L'adresse du logement prime sur « Votre adresse ».
      const hebergementHasOwnLocation = v.type === TYPE_HEBERGEMENT && v.hebergementLatitude != null && v.hebergementLongitude != null;
      if (hebergementHasOwnLocation) {
        formData.append('location', JSON.stringify({
          type: 'Point', coordinates: [v.hebergementLongitude, v.hebergementLatitude],
        }));
      } else if (hasLocation) {
        formData.append('location', JSON.stringify({
          type: 'Point', coordinates: [this.longitude, this.latitude],
        }));
      }

      formData.append('description', this.buildDescription(v));
      formData.append('renouvelable', String(!!v.renouvelable));
      if (v.presencePhysique !== null) formData.append('presence_physique', String(v.presencePhysique));
      if (v.type === TYPE_HEBERGEMENT && v.hebergementDuree) formData.append('hebergement_duree', v.hebergementDuree);
      if (v.type === TYPE_HEBERGEMENT && v.typeLoyer) formData.append('type_loyer', v.typeLoyer);
      if (v.type === TYPE_HEBERGEMENT && v.typeLoyer && v.typeLoyer !== 'GRATUIT') {
        if (v.loyerMontantMin) formData.append('loyer_montant_min', v.loyerMontantMin);
        if (v.loyerMontantMax) formData.append('loyer_montant_max', v.loyerMontantMax);
      }
      if (v.type === TYPE_HEBERGEMENT && v.typeLogement) formData.append('type_logement', v.typeLogement);
      if (v.type === TYPE_HEBERGEMENT && v.niveauLogement) formData.append('niveau_logement', v.niveauLogement);
      if (v.type === TYPE_HEBERGEMENT && v.niveauLogement === 'ETAGE' && v.accesEtage) {
        formData.append('acces_etage', v.accesEtage);
      }
      if (v.type === TYPE_HEBERGEMENT && v.nombrePieces) formData.append('nombre_pieces', v.nombrePieces);
      if (v.type === TYPE_HEBERGEMENT && v.nombreChambres) formData.append('nombre_chambres', v.nombreChambres);
      if (v.type === TYPE_HEBERGEMENT && v.capaciteAdultes) formData.append('capacite_adultes', v.capaciteAdultes);
      if (v.type === TYPE_HEBERGEMENT && v.capaciteEnfants) formData.append('capacite_enfants', v.capaciteEnfants);
      if (v.type === TYPE_HEBERGEMENT) {
        formData.append('animaux_acceptes', String(!!v.animauxAcceptes));
        formData.append('jardin', String(!!v.jardin));
        formData.append('pmr_compatible', String(!!v.pmrCompatible));
        formData.append('accueil_sinistres', String(!!v.accueilSinistres));
        formData.append('accueil_intervenants', String(!!v.accueilIntervenants));
      }
      if (v.type === TYPE_SOINS && v.numeroAdeliRpps) formData.append('numero_adeli_rpps', v.numeroAdeliRpps);
      if (v.type === TYPE_TRANSPORT && v.transportType) formData.append('transport_type', v.transportType);
      if (v.type === TYPE_TRANSPORT && v.transportType === 'ANIMAUX' && v.transportAnimauxPrecision) {
        formData.append('transport_animaux_precision', v.transportAnimauxPrecision);
      }
      if (v.type === TYPE_TRANSPORT && v.transportType === 'PERSONNES' && v.nombrePlacesAssises != null) {
        formData.append('nombre_places_assises', String(v.nombrePlacesAssises));
      }
      if (v.type === TYPE_MATERIEL && v.materielType) formData.append('materiel_type', v.materielType);
      if (v.type === TYPE_MATERIEL && v.materielType === 'CUVE' && v.cuveContenu) {
        formData.append('cuve_contenu', v.cuveContenu);
      }
      if (v.type === TYPE_MATERIEL && v.materielType === 'AUTRE' && v.materielCatalogue) {
        formData.append('materiel_catalogue', v.materielCatalogue);
      }
      if (v.type === TYPE_MATERIEL && v.quantite) formData.append('quantite', v.quantite);
      if (v.type === TYPE_MATERIEL && v.unite) formData.append('unite', v.unite);
      if (v.type === TYPE_MATERIEL && v.materielLivraison) formData.append('materiel_livraison', v.materielLivraison);
      if (v.type === TYPE_MATERIEL && v.presencePhysique === true && v.accompagne !== null) {
        formData.append('accompagne', String(!!v.accompagne));
        if (v.accompagne && v.nombreAccompagnants) formData.append('nombre_accompagnants', String(v.nombreAccompagnants));
      }
      if (v.type === TYPE_SOUTIEN && v.soutienType) formData.append('soutien_type', v.soutienType);
      // Qualifications reportées sur chaque offre où la personne est présente.
      if (v.presencePhysique === true) {
        formData.append('diplome_secourisme', String(!!this.informationForm.get('diplomeSecourisme')?.value));
        formData.append('ancien_sapeur_pompier', String(!!this.informationForm.get('ancienSapeurPompier')?.value));
      }
      if (this.showConformiteVehicule(v.type, v.materielType)) {
        formData.append('confirmation_reglementaire', String(!!v.confirmationReglementaire));
        if (v.immatriculation) formData.append('immatriculation', v.immatriculation);
      }

      formData.append('status', 'DISPONIBLE');
      if (organisationNom) {
        formData.append('organisation_nom', organisationNom);
        formData.append('groupe_id', groupeId!);
      }
      if (this.currentUser?.id) formData.append('author', this.currentUser.id);
      if (this.selectedPhotos[0]) formData.append('photo', this.selectedPhotos[0]);
      // Compétences reportées seulement si l'offreur est présent.
      if (v.presencePhysique === true) {
        this.selectedCompetences.forEach(c => formData.append('competences', c.id));
      }

      return this.offerService.create(formData);
    });

    // Chaque engin coché devient une offre, avec sa propre photo.
    const checkedEngineLines = this.engineLines.filter(l => l.checked);
    const engineCreations: Observable<Offer>[] = checkedEngineLines.map(line => {
      const formData = new FormData();
      formData.append('title', `Offre d'aide - ${crisisLabel} - Engin : ${line.item.nom}`);
      formData.append('first_name_offer', this.informationForm.get('firstName')?.value);
      formData.append('last_name_offer', this.informationForm.get('lastName')?.value);
      formData.append('email_offer', this.informationForm.get('email')?.value);
      formData.append('phone_offer', this.informationForm.get('phoneNumber')?.value);

      const typeId = this.typesOffreMap.get(TYPE_MATERIEL);
      if (typeId) formData.append('offer_type', typeId);
      if (crisisId) formData.append('crisis', crisisId);
      if (hasLocation) {
        formData.append('location', JSON.stringify({
          type: 'Point', coordinates: [this.longitude, this.latitude],
        }));
      }

      formData.append('description', `Engin proposé : ${line.item.nom}`);
      formData.append('renouvelable', 'false');
      // Un engin coché est mis à disposition seul par défaut.
      formData.append('presence_physique', 'false');
      formData.append('materiel_type', 'AUTRE');
      formData.append('materiel_catalogue', line.item.id);
      formData.append('quantite', String(line.quantite || 1));
      formData.append('confirmation_reglementaire', String(!!this.engineConfirmationReglementaire));
      if (this.engineImmatriculation.trim()) formData.append('immatriculation', this.engineImmatriculation.trim());

      formData.append('status', 'DISPONIBLE');
      if (organisationNom) {
        formData.append('organisation_nom', organisationNom);
        formData.append('groupe_id', groupeId!);
      }
      if (this.currentUser?.id) formData.append('author', this.currentUser.id);
      if (line.photo) formData.append('photo', line.photo);

      return this.offerService.create(formData);
    });

    const creations = [...rowCreations, ...engineCreations];

    forkJoin(creations).subscribe({
      next: (offers) => {
        // Disponibilités seulement pour les offres avec présence ; les lignes standard sont en tête
        // de `offers`.
        const rowOffers = offers.slice(0, rowCreations.length);
        rowOffers.forEach((o, i) => {
          if (realRows[i].value.presencePhysique === true) this.declareDisponibilites(o.id);
        });
        // Photos supplémentaires postées après création (lignes standard seulement).
        const photosSupplementaires = this.selectedPhotos.slice(1);
        rowOffers.forEach(o => {
          photosSupplementaires.forEach((file, i) => {
            this.offerService.addPhoto(o.id, file, i).subscribe({
              error: (err) => console.error('Erreur ajout photo galerie:', err),
            });
          });
        });
        alert('Votre offre a été enregistrée avec succès !');
        this.router.navigate(['/accueil']);
      },
      error: (err) => {
        console.error('Erreur création offre:', err);
        if (err.status === 400 && err.error) {
          const errors = Object.entries(err.error).map(([key, value]) => `${key}: ${value}`).join('\n');
          alert(`Erreur de validation:\n${errors}`);
        } else {
          alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
        }
      }
    });
  }

  private buildDescription(rowValue: any): string {
    if (rowValue.type === TYPE_AUTRE) {
      return `[Bénévolat] ${rowValue.description || ''}`.trim();
    }
    return rowValue.description || '';
  }

  /** Commune obligatoire (rapprochement géographique) ; l'adresse peut rester masquée au public. */
  onContinue(): void {
    this.formErrorsStep1 = this.step1ValidationErrors();
    if (this.formErrorsStep1.length > 0) return;
    this.state = 2;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  goBack(): void {
    if(this.state == 1) {
      this.router.navigate(['/accueil']);
    } else {
      this.state = 1;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  /** Envoie les créneaux cochés ; un échec n'annule pas l'offre déjà créée. */
  private declareDisponibilites(offerId: string): void {
    for (const jour of this.joursDispo) {
      for (const slot of jour.creneaux) {
        if (slot.checked) {
          this.disponibiliteOffreService.create({
            offer: offerId, date: jour.date, creneau: slot.creneau,
          }).subscribe({
            error: (err) => console.error('Erreur enregistrement disponibilité:', err),
          });
        }
      }
    }
  }

  // ── Lignes "Quelle aide proposez-vous" ─────────────────────────
  get offerRows(): FormArray {
    return this.requestForm.get('offerRows') as FormArray;
  }

  rowGroup(control: AbstractControl): FormGroup {
    return control as FormGroup;
  }

  addOffer(): void {
    const row = this.formBuilder.group({
      type: ['', Validators.required],
      description: ['', [Validators.minLength(10)]],
      hebergementDuree: [''],
      // Adresse du logement (à défaut, « Votre adresse ») ; Offer n'a pas de commune_code.
      hebergementLatitude: [null as number | null],
      hebergementLongitude: [null as number | null],
      typeLoyer: [''],
      loyerMontantMin: [null],
      loyerMontantMax: [null],
      typeLogement: [''],
      niveauLogement: [''],
      accesEtage: [''],
      nombrePieces: [null],
      nombreChambres: [null],
      capaciteAdultes: [null],
      capaciteEnfants: [null],
      animauxAcceptes: [false],
      jardin: [false],
      pmrCompatible: [false],
      accueilSinistres: [true],
      accueilIntervenants: [false],
      numeroAdeliRpps: [''],
      transportType: [''],
      transportAnimauxPrecision: ['', transportAnimauxPrecisionValidator],
      nombrePlacesAssises: [null as number | null],
      materielType: [''],
      cuveContenu: [''],
      materielCatalogue: [null],
      materielCatalogueNom: [''],
      quantite: [null],
      unite: [''],
      soutienType: [''],
      materielLivraison: [''],
      confirmationReglementaire: [false, confirmationReglementaireValidator],
      immatriculation: [''],
      renouvelable: [false],
      presencePhysique: [null as boolean | null, presencePhysiqueValidator],
      accompagne: [null as boolean | null],
      nombreAccompagnants: [null as number | null],
    });
    // Le type rend confirmationReglementaire obligatoire ou non : réévaluation à chaque changement.
    // Il fixe aussi presencePhysique (vrai/faux selon le type, null à préciser sinon).
    row.get('type')?.valueChanges.subscribe((type: string | null) => {
      row.get('confirmationReglementaire')?.updateValueAndValidity();
      if (TYPES_PRESENCE_FORCEE_VRAIE.includes(type ?? '')) {
        row.get('presencePhysique')?.setValue(true);
      } else if (TYPES_PRESENCE_FORCEE_FAUSSE.includes(type ?? '')) {
        row.get('presencePhysique')?.setValue(false);
      } else {
        row.get('presencePhysique')?.setValue(null);
      }
    });
    // Idem pour transportAnimauxPrecision, piloté par transportType.
    row.get('transportType')?.valueChanges.subscribe(() => {
      row.get('transportAnimauxPrecision')?.updateValueAndValidity();
    });
    // La ligne passerelle Engins est dispensée de presencePhysique/confirmationReglementaire.
    row.get('materielType')?.valueChanges.subscribe((materielType: string | null) => {
      row.get('confirmationReglementaire')?.updateValueAndValidity();
      row.get('presencePhysique')?.updateValueAndValidity();
      if (materielType === ENGINS_AGRICOLES_VALUE) {
        row.get('presencePhysique')?.setValue(null);
      }
    });
    this.offerRows.push(row);
  }

  /** Faut-il demander la présence de l'offreur ? (types ambigus, hors ligne passerelle) */
  showPresencePhysiqueChoice(type: string | null | undefined, materielType?: string | null): boolean {
    if (type === TYPE_MATERIEL && materielType === ENGINS_AGRICOLES_VALUE) return false;
    return !!type && TYPES_PRESENCE_A_PRECISER.includes(type);
  }

  removeOffer(index: number): void {
    this.offerRows.removeAt(index);
  }

  /** Transport et Matériel peuvent impliquer un véhicule ou un engin : le rappel s'affiche sur les deux. */
  showConformiteVehicule(type: string | null | undefined, materielType?: string | null): boolean {
    if (type === TYPE_MATERIEL && materielType === ENGINS_AGRICOLES_VALUE) return false;
    return type === TYPE_TRANSPORT || type === TYPE_MATERIEL;
  }

  /** Compétences et disponibilités ne s'affichent que si l'offreur est présent sur au moins une ligne. */
  get proposeAideEnPersonne(): boolean {
    return this.offerRows.controls.some(row => row.value.presencePhysique === true);
  }
}
