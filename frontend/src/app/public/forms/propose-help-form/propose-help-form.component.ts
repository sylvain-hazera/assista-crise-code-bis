import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray, AbstractControl, ValidationErrors } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { forkJoin, Observable } from 'rxjs';
import { CommonModule } from '@angular/common';
import { OfferService } from '../../../services/offer.service';
import { DisponibiliteOffreService } from '../../../services/disponibilite-offre.service';
import { CrisisService } from '../../../services/crisis.service';
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

interface JourDispo {
  date: string;       // YYYY-MM-DD
  label: string;       // ex: "lun. 25/08"
  creneaux: { creneau: Creneau; label: string; checked: boolean }[];
}

// Labels exacts des OfferType côté backend (backend/entrypoint.sh) — utilisés pour savoir
// quels champs complémentaires afficher pour une ligne donnée.
const TYPE_HEBERGEMENT = 'Hébergement';
const TYPE_SOINS = 'Soins médicaux et paramédicaux';
const TYPE_TRANSPORT = 'Transport';
const TYPE_MATERIEL = 'Matériel';
const TYPE_SOUTIEN = 'Soutien psychologique';
const TYPE_AUTRE = 'Autre';
const TYPE_NOURRITURE = 'Nourriture et eau';

// Valeur de materielType déclenchant la rubrique "Engins agricoles / chantiers / spéciaux"
// (liste à cocher, voir engineLines) — un "pseudo-type" : cette ligne du formulaire ne devient
// jamais elle-même une offre, seuls les engins cochés en dessous en deviennent une chacun (voir
// isEnginesGatewayRow()/onSubmit()).
const ENGINS_AGRICOLES_VALUE = 'ENGINS_AGRICOLES';

// Présence physique de l'offreur avec ce qu'il propose : certains types l'excluent ou
// l'impliquent toujours par nature, d'autres sont ambigus (un camion, des vivres... peuvent
// être déposés seuls ou apportés par l'offreur en personne) et demandent une réponse
// explicite — voir addOffer()/presencePhysiqueValidator. Un hébergement prêté n'implique
// jamais que l'offreur y réside ; à l'inverse, Soins/Soutien/Autre (bénévolat) SONT la
// personne elle-même, la présence est toujours vraie.
const TYPES_PRESENCE_FORCEE_FAUSSE = [TYPE_HEBERGEMENT];
const TYPES_PRESENCE_FORCEE_VRAIE = [TYPE_SOINS, TYPE_SOUTIEN, TYPE_AUTRE];
const TYPES_PRESENCE_A_PRECISER = [TYPE_TRANSPORT, TYPE_MATERIEL, TYPE_NOURRITURE];

// Types où l'offreur s'engage en personne mais n'a pas déjà de champ de qualification dédié
// (Soins → numero_adeli_rpps, Soutien → soutien_type couvrent déjà ce besoin) : c'est là qu'une
// case à cocher générique "diplôme de secourisme" apporte une information nouvelle.
const TYPES_SECOURISME_GENERIQUE = [TYPE_HEBERGEMENT, TYPE_TRANSPORT, TYPE_AUTRE];

/** La case de conformité (permis/CACES, assurance, CT, sobriété, plaque) n'est obligatoire que
 * sur les lignes où un véhicule/engin est en jeu (voir showConformiteVehicule) — sa validité
 * dépend donc du contrôle voisin `type`, pas d'elle-même. Angular ne réévalue pas
 * automatiquement un validateur quand un AUTRE contrôle change : addOffer() force la
 * réévaluation sur chaque changement de `type` (voir son abonnement à valueChanges). */
function confirmationReglementaireValidator(control: AbstractControl): ValidationErrors | null {
  const parent = control.parent;
  if (!parent) return null;
  const type = parent.get('type')?.value;
  // La ligne "passerelle" vers la rubrique Engins ne devient jamais elle-même une offre (voir
  // ENGINS_AGRICOLES_VALUE) : sa propre confirmation réglementaire n'a pas de sens, celle du lot
  // d'engins cochés (engineConfirmationReglementaire) la remplace.
  if (type === TYPE_MATERIEL && parent.get('materielType')?.value === ENGINS_AGRICOLES_VALUE) return null;
  const requiert = type === TYPE_TRANSPORT || type === TYPE_MATERIEL;
  return (requiert && !control.value) ? { required: true } : null;
}

/** presencePhysique doit être explicitement true/false (jamais null) sur les types ambigus —
 * voir TYPES_PRESENCE_A_PRECISER. Même mécanique que confirmationReglementaireValidator. */
function presencePhysiqueValidator(control: AbstractControl): ValidationErrors | null {
  const parent = control.parent;
  if (!parent) return null;
  const type = parent.get('type')?.value;
  if (type === TYPE_MATERIEL && parent.get('materielType')?.value === ENGINS_AGRICOLES_VALUE) return null;
  const requiert = TYPES_PRESENCE_A_PRECISER.includes(type);
  return (requiert && control.value === null) ? { required: true } : null;
}

/** Le type d'animal transporté change radicalement les moyens requis (cage, bétaillère...) :
 * exigé dès que transportType === ANIMAUX. Dépend de transportType, pas de type — voir
 * l'abonnement dédié dans addOffer(). */
function transportAnimauxPrecisionValidator(control: AbstractControl): ValidationErrors | null {
  const parent = control.parent;
  if (!parent) return null;
  const transportType = parent.get('transportType')?.value;
  return (transportType === 'ANIMAUX' && !control.value) ? { required: true } : null;
}

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent, TagSearchInputComponent, RgpdNoticeComponent, ValidationSummaryComponent, PhotoGalleryPickerComponent],
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

  // ── Rubrique "Engins agricoles / chantiers / spéciaux" ─────────────────────────
  // Liste à cocher dédiée, indépendante du menu déroulant "Type de matériel" ci-dessus (qui ne
  // sert plus qu'aux quelques types structurels fixes) : chaque engin coché devient, à la
  // soumission, sa propre offre (type Matériel/Autre + ce catalogue précis), avec sa propre
  // quantité et sa propre photo — voir buildEngineCreations(). Adossée à MaterielCatalogue
  // (categorie=ENGIN), donc extensible en direct via la ligne "Autre" ci-dessous.
  engineLines: { item: MaterielCatalogue; checked: boolean; quantite: number | null; photo: File | null }[] = [];
  newEngineNom = '';
  addingCustomEngine = false;
  // Une seule confirmation réglementaire pour tout le lot d'engins cochés (pas une par ligne) —
  // même rappel légal que showConformiteVehicule pour une ligne Transport/Matériel standard.
  engineConfirmationReglementaire = false;

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
        // Réutilise la ligne existante si ce nom (insensible à la casse) est déjà dans le
        // catalogue — même dédoublonnage que TagLikeViewSetMixin côté back.
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

  crisisOptions: { value: string; label: string }[] = [];
  filteredCrisisOptions: { value: string; label: string }[] = [];
  crisisSearch: string = 'Aucune crise en rapport';
  showCrisisDropdown: boolean = false;

  offerTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

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

  // Catalogue partagé (façon hashtag) : un matériel "Autre" tapé une fois devient proposable à
  // tout le monde ensuite — même mécanisme que pour l'inventaire des points. Chargé en entier
  // (pas seulement via recherche) pour apparaître directement dans le menu déroulant "Type de
  // matériel", avant "Autre" — qui ne doit plus servir que pour un matériel pas encore listé.
  allMateriels: MaterielCatalogue[] = [];
  materielCatalogueSearchFn = (q: string) => this.materielCatalogueService.search(q);
  materielCatalogueCreateFn = (nom: string) => this.materielCatalogueService.create({ nom });
  materielCatalogueCreateLabelFn = (value: string) => `Ajouter « ${value} » comme nouveau matériel`;

  readonly CATALOGUE_PREFIX = 'CATALOGUE:';

  /** Le menu "Type de matériel" mélange les types structurels fixes (CUVE, POMPE...) et le
   * catalogue partagé, distingués par un préfixe sur la valeur — choisir une entrée du
   * catalogue revient à choisir "Autre" + ce matériel précis, sans repasser par la recherche. */
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
    private crisisService: CrisisService,
    private authService: AuthService,
    private competenceService: CompetenceService,
    private materielCatalogueService: MaterielCatalogueService,
  ) {}

  onMaterielCatalogueSelected(row: AbstractControl, item: MaterielCatalogue): void {
    this.rowGroup(row).patchValue({ materielCatalogue: item.id, materielCatalogueNom: item.nom });
    // Apparaît désormais directement dans le menu déroulant, avant "Autre" — pour ce
    // formulaire (pas besoin de recharger la page) et pour tous les suivants (déjà en base).
    if (!this.allMateriels.some(m => m.id === item.id)) {
      this.allMateriels = [...this.allMateriels, item];
    }
  }

  onCompetenceSelected(item: Competence): void {
    if (this.selectedCompetences.some(c => c.id === item.id)) return;
    this.selectedCompetences = [...this.selectedCompetences, item];
  }

  removeCompetence(id: string): void {
    this.selectedCompetences = this.selectedCompetences.filter(c => c.id !== id);
  }

  // Liste déroulante des compétences déjà existantes (navigable sans avoir à taper), avec une
  // option "Autre" qui révèle le champ de recherche/création libre ci-dessous — même patron
  // que materielTypeOptions pour le matériel.
  allCompetences: Competence[] = [];
  competenceDropdownValue = '';
  showCompetenceAutre = false;

  onCompetenceDropdownChange(): void {
    if (this.competenceDropdownValue === 'AUTRE') {
      this.showCompetenceAutre = true;
    } else if (this.competenceDropdownValue) {
      const comp = this.allCompetences.find(c => c.id === this.competenceDropdownValue);
      if (comp) this.onCompetenceSelected(comp);
    }
    this.competenceDropdownValue = '';
  }

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesOffre();
    this.loadActiveCrises();
    this.buildJoursDispo();
    this.competenceService.getAll().subscribe({
      next: (list) => this.allCompetences = list,
      error: () => {},
    });
    this.materielCatalogueService.getAll().subscribe({
      // Les engins (categorie=ENGIN) ont leur propre rubrique dédiée (voir loadEngineCatalogue)
      // — exclus d'ici pour ne pas apparaître une seconde fois dans "Type de matériel" > Autre.
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

  /** Coche ou décoche tous les créneaux d'un coup — si au moins un créneau reste décoché,
   * l'action est "tout cocher" ; sinon "tout décocher" (cf. allDisposChecked). */
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

  loadActiveCrises(): void {
    this.crisisService.getAll().subscribe({
      next: (crises: Crisis[]) => {
        const activeCrises = crises.filter(c => c.is_open !== false);
        this.crisisOptions = [
          { value: '', label: 'Aucune crise en rapport' },
          ...activeCrises.map(c => ({
            value: c.id,
            label: `${c.name} - ${c.type_display || c.type}`
          }))
        ];
        this.filteredCrisisOptions = [...this.crisisOptions];
      },
      error: (err) => console.error('Erreur chargement crises:', err)
    });
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      crisisId: [''],
      offerRows: new FormArray([]),
      addressVisible: [false],
      image: [null],
    });

    this.addOffer(); // Ajouter une ligne d'offre initiale

    this.informationForm = this.formBuilder.group({
      lastName: [this.currentUser?.last_name, Validators.required],
      firstName: [this.currentUser?.first_name, Validators.required],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phoneNumber: [this.currentUser?.phone_number, [Validators.required, Validators.pattern(/^\+?[\d\s.-]{10,20}$/)]],
      organisationNom: [''],
    });
  }

  /** Galerie (jusqu'à 10 photos) — la première du tableau émis est toujours la principale
   * désignée (voir PhotoGalleryPickerComponent), envoyée dans le champ `photo` existant de
   * l'offre ; les suivantes sont postées séparément vers la galerie après création (voir
   * onSubmit). */
  selectedPhotos: File[] = [];

  onPhotosSelected(files: File[]): void {
    this.selectedPhotos = files;
  }

  // Encadré rouge de résumé, un par étape (formulaire en 2 temps) — remplace les alert()
  // génériques qui ne disaient jamais lesquels des champs posaient problème.
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
    const crisisLabel = this.crisisOptions.find(c => c.value === crisisId)?.label || 'non liée à une crise';
    const addressVisible = this.requestForm.get('addressVisible')?.value;
    const hasLocation = !!(addressVisible && this.latitude != null && this.longitude != null);

    // Dépôt groupé (entreprise/association déposant plusieurs personnes/véhicules en une
    // seule visite) : un seul groupe_id partagé par toutes les lignes de cette soumission, posé
    // uniquement si un nom d'organisation est renseigné — sinon comportement inchangé.
    const organisationNom = (this.informationForm.get('organisationNom')?.value || '').trim();
    const groupeId = organisationNom ? crypto.randomUUID() : null;

    // La ligne "passerelle" vers Engins agricoles (voir ENGINS_AGRICOLES_VALUE) ne devient
    // jamais elle-même une offre : seuls les engins cochés en dessous (checkedEngineLines) en
    // deviennent une chacun. `realRows` remplace offerRows.controls comme base d'index pour le
    // reste de la méthode (déclaration de disponibilités, photos de galerie).
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

      if (hasLocation) {
        formData.append('location', JSON.stringify({
          type: 'Point', coordinates: [this.longitude, this.latitude],
        }));
      }

      formData.append('description', this.buildDescription(v));
      formData.append('renouvelable', String(!!v.renouvelable));
      if (v.presencePhysique !== null) formData.append('presence_physique', String(v.presencePhysique));
      if (v.type === TYPE_HEBERGEMENT && v.hebergementDuree) formData.append('hebergement_duree', v.hebergementDuree);
      if (v.type === TYPE_SOINS && v.numeroAdeliRpps) formData.append('numero_adeli_rpps', v.numeroAdeliRpps);
      if (v.type === TYPE_TRANSPORT && v.transportType) formData.append('transport_type', v.transportType);
      if (v.type === TYPE_TRANSPORT && v.transportType === 'ANIMAUX' && v.transportAnimauxPrecision) {
        formData.append('transport_animaux_precision', v.transportAnimauxPrecision);
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
      if (v.type === TYPE_SOUTIEN && v.soutienType) formData.append('soutien_type', v.soutienType);
      if (this.showSecourisme(v.type)) formData.append('diplome_secourisme', String(!!v.diplomeSecourisme));
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
      // Compétences déclarées côté personne : n'ont de sens que si l'offreur est
      // effectivement présent avec ce qu'il propose (voir presencePhysique).
      if (v.presencePhysique === true) {
        this.selectedCompetences.forEach(c => formData.append('competences', c.id));
      }

      return this.offerService.create(formData);
    });

    // Rubrique "Engins agricoles / chantiers / spéciaux" : chaque ligne cochée devient sa
    // propre offre (Matériel/Autre + ce catalogue précis), avec sa propre photo — indépendante
    // de la galerie globale ci-dessus, qui ne s'applique qu'aux lignes du formulaire standard.
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
      // Pas de choix "présent moi-même" dans cette liste rapide (contrairement à une ligne
      // standard) : un engin coché ici est mis à disposition seul, par défaut.
      formData.append('presence_physique', 'false');
      formData.append('materiel_type', 'AUTRE');
      formData.append('materiel_catalogue', line.item.id);
      formData.append('quantite', String(line.quantite || 1));
      formData.append('confirmation_reglementaire', String(!!this.engineConfirmationReglementaire));

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
        // Des disponibilités n'ont de sens que pour une offre où l'offreur est présent en
        // personne (voir presencePhysique) — seules les offres issues des lignes standard sont
        // concernées, elles restent en tête de `offers` puisque `creations` les place en premier.
        const rowOffers = offers.slice(0, rowCreations.length);
        rowOffers.forEach((o, i) => {
          if (realRows[i].value.presencePhysique === true) this.declareDisponibilites(o.id);
        });
        // Photos additionnelles de la galerie (au-delà de la principale déjà envoyée avec
        // chaque offre) — postées séparément vers chaque offre créée, une fois qu'elle existe.
        // Ne s'applique qu'aux lignes standard : les engins ont chacun leur propre photo dédiée.
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

  onCrisisSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.crisisSearch = input.value;
    this.filteredCrisisOptions = this.crisisOptions.filter(crisis =>
      crisis.label.toLowerCase().includes(this.crisisSearch.toLowerCase())
    );
    this.showCrisisDropdown = true;
  }

  selectCrisis(crisis: { value: string; label: string }): void {
    this.crisisSearch = crisis.label;
    this.requestForm.patchValue({ crisisId: crisis.value });
    this.showCrisisDropdown = false;
  }

  /** La commune est obligatoire même pour un offreur d'aide (matching géographique avec les
   * besoins à proximité) : l'adresse précise reste néanmoins masquable au public via la case
   * "adresse visible" plus bas — seule la sélection elle-même (qui résout une commune) est
   * requise ici. */
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

  /** Envoie les créneaux de disponibilité cochés, liés à l'offre qui vient d'être créée. Un
   * échec ici n'annule pas la création de l'offre (déjà faite). */
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
      numeroAdeliRpps: [''],
      transportType: [''],
      transportAnimauxPrecision: ['', transportAnimauxPrecisionValidator],
      materielType: [''],
      cuveContenu: [''],
      materielCatalogue: [null],
      materielCatalogueNom: [''],
      quantite: [null],
      unite: [''],
      soutienType: [''],
      diplomeSecourisme: [false],
      materielLivraison: [''],
      confirmationReglementaire: [false, confirmationReglementaireValidator],
      immatriculation: [''],
      renouvelable: [false],
      presencePhysique: [null as boolean | null, presencePhysiqueValidator],
    });
    // Le type conditionne l'exigibilité de confirmationReglementaire (voir le validateur) :
    // sans cet abonnement, choisir Transport/Matériel APRÈS coup ne rendrait jamais la case
    // obligatoire tant qu'on ne retouche pas la case elle-même. Pilote aussi presencePhysique :
    // forcée vrai/faux sur les types non-ambigus, remise à null (à préciser) sur les autres —
    // change de type après avoir répondu ne doit pas garder une réponse qui ne correspond plus.
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
    // Même mécanique que confirmationReglementaireValidator ci-dessus, mais pilotée par
    // transportType (sous-catégorie), pas type : choisir "Transport d'animaux" APRÈS coup doit
    // rendre transportAnimauxPrecision obligatoire sans retoucher le champ lui-même.
    row.get('transportType')?.valueChanges.subscribe(() => {
      row.get('transportAnimauxPrecision')?.updateValueAndValidity();
    });
    // Choisir "Engins agricoles..." (ligne passerelle, voir ENGINS_AGRICOLES_VALUE) dispense
    // cette ligne de presencePhysique/confirmationReglementaire, remplacées par les leurs
    // (engineConfirmationReglementaire) — sans cet abonnement, les valider une fois avant de
    // changer d'avis laisserait l'ancienne réponse geler l'état invalide/valide du contrôle.
    row.get('materielType')?.valueChanges.subscribe((materielType: string | null) => {
      row.get('confirmationReglementaire')?.updateValueAndValidity();
      row.get('presencePhysique')?.updateValueAndValidity();
      if (materielType === ENGINS_AGRICOLES_VALUE) {
        row.get('presencePhysique')?.setValue(null);
      }
    });
    this.offerRows.push(row);
  }

  /** Cette ligne demande-t-elle explicitement si l'offreur est présent (types ambigus) ? Pas
   * pour la ligne "passerelle" Engins agricoles — voir ENGINS_AGRICOLES_VALUE. */
  showPresencePhysiqueChoice(type: string | null | undefined, materielType?: string | null): boolean {
    if (type === TYPE_MATERIEL && materielType === ENGINS_AGRICOLES_VALUE) return false;
    return !!type && TYPES_PRESENCE_A_PRECISER.includes(type);
  }

  removeOffer(index: number): void {
    this.offerRows.removeAt(index);
  }

  /** Cette ligne d'offre implique-t-elle une présence en personne sans déjà avoir son propre
   * champ de qualification (Soins/Soutien) ? Voir TYPES_SECOURISME_GENERIQUE. */
  showSecourisme(type: string | null | undefined): boolean {
    return !!type && TYPES_SECOURISME_GENERIQUE.includes(type);
  }

  /** Transport (toujours un véhicule, conduit par l'offreur) et Matériel (peut être un engin
   * ou un véhicule remorquable, prêté seul ou avec l'offreur) sont les deux types où un
   * véhicule/engin est potentiellement en jeu — le rappel s'affiche sur les deux, la conduite
   * conditionnelle précise du texte ("que vous le conduisiez ou non") le rend juste même quand
   * le matériel proposé n'est en réalité pas motorisé (ex: une cuve). */
  showConformiteVehicule(type: string | null | undefined, materielType?: string | null): boolean {
    if (type === TYPE_MATERIEL && materielType === ENGINS_AGRICOLES_VALUE) return false;
    return type === TYPE_TRANSPORT || type === TYPE_MATERIEL;
  }

  /** Une personne qui ne propose QUE du matériel (ex: une cuve à prêter, un hébergement vide)
   * n'a ni compétence ni disponibilité personnelle à déclarer : lui montrer ces deux sections
   * (pensées pour un engagement en personne) n'a pas de sens et ajoute du bruit/des clics
   * inutiles. S'appuie désormais sur presencePhysique, déclaré explicitement par ligne
   * (remplace l'ancienne règle "tout type ≠ Matériel", fausse pour l'Hébergement et incapable
   * de distinguer un Transport/Matériel avec ou sans l'offreur). */
  get proposeAideEnPersonne(): boolean {
    return this.offerRows.controls.some(row => row.value.presencePhysique === true);
  }
}
