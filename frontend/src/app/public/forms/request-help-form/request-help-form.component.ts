import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { forkJoin, Observable } from 'rxjs';
import { RequestService } from '../../../services/request.service';
import { CrisisService } from '../../../services/crisis.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { Request } from '../../../shared/models/request.model';
import { User } from '../../../shared/models/user.model';
import { AuthService } from '../../../auth/services/auth.service';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { AddressResult } from '../../../shared/models/address-result.model';
import { RgpdNoticeComponent } from '../../../shared/components/public/rgpd-notice/rgpd-notice.component';
import { ValidationSummaryComponent } from '../../../shared/components/public/validation-summary/validation-summary.component';
import { PhotoGalleryPickerComponent } from '../../../shared/components/public/photo-gallery-picker/photo-gallery-picker.component';

const TYPE_HEBERGEMENT = 'Hébergement';

/** Critères détaillés du logement recherché, par index de besoin — même patron que
 * subCategorySelections (tableau parallèle à needsType/descriptions, pas un FormGroup :
 * needsType reste un FormArray de simples contrôles string, voir addNeed()/removeNeed()). */
interface HebergementDetails {
  hebergementDuree: string;
  latitude: number | null;
  longitude: number | null;
  communeCode: string | null;
  typeLoyer: string;
  loyerMontantMin: number | null;
  loyerMontantMax: number | null;
  typeLogement: string;
  niveauLogement: string;
  accesEtage: string;
  nombrePieces: number | null;
  nombreChambres: number | null;
  capaciteAdultes: number | null;
  capaciteEnfants: number | null;
  animauxAcceptes: boolean;
  jardin: boolean;
  pmrCompatible: boolean;
}

function emptyHebergementDetails(): HebergementDetails {
  return {
    hebergementDuree: '', latitude: null, longitude: null, communeCode: null,
    typeLoyer: '', loyerMontantMin: null, loyerMontantMax: null,
    typeLogement: '', niveauLogement: '', accesEtage: '',
    nombrePieces: null, nombreChambres: null, capaciteAdultes: null, capaciteEnfants: null,
    animauxAcceptes: false, jardin: false, pmrCompatible: false,
  };
}

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent, RgpdNoticeComponent, ValidationSummaryComponent, PhotoGalleryPickerComponent],
  templateUrl: './request-help-form.component.html',
  styleUrl: './request-help-form.component.scss'
})
export class RequestHelpFormComponent implements OnInit {
  currentUser: User | null = null;
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  state: number = 1;

  latitude: number | null = null;
  longitude: number | null = null;

  typesDemandeMap: Map<string, string> = new Map();

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

  needTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  personTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'individual', label: 'Particulier' },
    { value: 'organization', label: 'Organisation' },
    { value: 'rescue', label: 'Secours organisés' },
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private helpRequestService: RequestService,
    private crisisService: CrisisService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesDemande();
    this.loadActiveCrises();
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

  loadTypesDemande(): void {
    this.helpRequestService.getTypes().subscribe({
      next: (types: any[]) => {
        types.forEach(type => {
          this.typesDemandeMap.set(type.type, type.id);
        });

        const byId = new Map(types.map(t => [t.id, t]));
        const topLevel = types.filter(t => !t.parent);

        this.childrenByParentType.clear();
        types.filter(t => t.parent).forEach(child => {
          const parent = byId.get(child.parent);
          if (!parent) return;
          const list = this.childrenByParentType.get(parent.type) ?? [];
          list.push({ value: child.type, label: child.type });
          this.childrenByParentType.set(parent.type, list);
        });

        this.needTypeOptions = [
          { value: '', label: 'Dropdown' },
          ...topLevel.map(t => ({ value: t.type, label: t.type }))
        ];
      },
      error: (err: any) => console.error('Erreur chargement types:', err)
    });
  }

  // Sous-catégorie (précision optionnelle) par index de besoin — ex: "Matériel" >
  // "Groupe électrogène", "Interprétariat / traduction" > "Anglais".
  childrenByParentType: Map<string, { value: string; label: string }[]> = new Map();
  subCategorySelections: string[] = [];

  readonly TYPE_HEBERGEMENT = TYPE_HEBERGEMENT;

  // Critères détaillés du logement recherché, par index de besoin — voir HebergementDetails.
  hebergementDetails: HebergementDetails[] = [];

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

  /** Adresse du logement recherché, propre à ce besoin — indépendante de "Votre adresse" : au
   * submit, on l'utilise pour `location`/`commune_code` si renseignée, sinon on retombe sur
   * l'adresse partagée (voir onSubmit). */
  onHebergementAddressSelected(index: number, addr: AddressResult | null): void {
    this.hebergementDetails[index].latitude = addr?.latitude ?? null;
    this.hebergementDetails[index].longitude = addr?.longitude ?? null;
    this.hebergementDetails[index].communeCode = addr?.citycode ?? null;
  }

  childrenFor(index: number): { value: string; label: string }[] {
    const topLevel = this.needsType.at(index)?.value;
    return topLevel ? (this.childrenByParentType.get(topLevel) ?? []) : [];
  }

  onTopLevelTypeChange(index: number): void {
    // Un changement de besoin principal invalide toute précision déjà choisie pour l'ancien.
    this.subCategorySelections[index] = '';
  }

  onSubCategoryChange(index: number, value: string): void {
    this.subCategorySelections[index] = value;
  }

  /** Type réellement à envoyer pour ce besoin : la précision si choisie, sinon le besoin
   * principal — cf. usage dans onSubmit(). */
  private effectiveNeedType(index: number): string {
    return this.subCategorySelections[index] || this.needsType.at(index).value;
  }

  initForm(): void {
    this.requestForm = this.formBuilder.group({
      crisisId: [''],
      needsType: new FormArray([]),
      descriptions: new FormArray([]),
      addressVisible: [false],
      image: [null],
    });

    this.addNeed(); // Ajouter un besoin initial  

    this.informationForm = this.formBuilder.group({
      lastName: [this.currentUser?.last_name, Validators.required],
      firstName: [this.currentUser?.first_name, Validators.required],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phoneNumber: [this.currentUser?.phone_number, [Validators.required, Validators.pattern(/^\+?[\d\s.-]{10,20}$/)]]
    });
  }

  /** Galerie (jusqu'à 10 photos) — la première du tableau émis est toujours la principale
   * désignée (voir PhotoGalleryPickerComponent), envoyée dans le champ `photo` existant de la
   * demande ; les suivantes sont postées séparément vers la galerie après création. */
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
    if (this.needsType.invalid) errors.push('Précisez chaque besoin (choisissez un type dans la liste).');
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
    if (!this.latitude || !this.longitude) errors.push('Erreur de géolocalisation : vérifiez l\'adresse sélectionnée à l\'étape précédente.');
    if (this.needsType.invalid) errors.push('Précisez chaque besoin (retournez à l\'étape précédente).');
    return errors;
  }

  onSubmit(): void {
    this.informationForm.markAllAsTouched();
    this.needsType.markAllAsTouched();
    this.formErrorsStep2 = this.step2ValidationErrors();
    if (this.formErrorsStep2.length > 0) return;

    const crisisId = this.requestForm.get('crisisId')?.value;
    const crisisLabel = this.crisisOptions.find(c => c.value === crisisId)?.label || 'non liée à une crise';
    const localisation = { type: 'Point', coordinates: [this.longitude, this.latitude] };

    const creations: Observable<Request>[] = this.needsType.controls.map((needControl, i) => {
      const needType = this.effectiveNeedType(i);
      const topLevelType = needControl.value;
      const description = this.descriptions.at(i).value;
      const hd = this.hebergementDetails[i];
      const formData = new FormData();

      formData.append('title', `Demande d'aide - ${crisisLabel} - ${needType}`);
      formData.append('first_name_request', this.informationForm.get('firstName')?.value);
      formData.append('last_name_request', this.informationForm.get('lastName')?.value);
      formData.append('email_request', this.informationForm.get('email')?.value);
      formData.append('phone_request', this.informationForm.get('phoneNumber')?.value);

      // L'adresse propre au logement recherché (si renseignée pour ce besoin Hébergement) prime
      // sur "Votre adresse", partagée par défaut avec tous les besoins de la soumission.
      const hebergementHasOwnLocation = topLevelType === TYPE_HEBERGEMENT && hd?.latitude != null && hd?.longitude != null;
      if (hebergementHasOwnLocation) {
        formData.append('location', JSON.stringify({ type: 'Point', coordinates: [hd.longitude, hd.latitude] }));
        if (hd.communeCode) formData.append('commune_code', hd.communeCode);
      } else {
        formData.append('location', JSON.stringify(localisation));
        if (this.selectedAddress?.citycode) formData.append('commune_code', this.selectedAddress.citycode);
      }

      const typeId = this.typesDemandeMap.get(needType);
      if (typeId) formData.append('request_type', typeId);
      if (crisisId) formData.append('crisis', crisisId);
      if (description) formData.append('description', description);

      if (topLevelType === TYPE_HEBERGEMENT && hd) {
        if (hd.hebergementDuree) formData.append('hebergement_duree', hd.hebergementDuree);
        if (hd.typeLoyer) formData.append('type_loyer', hd.typeLoyer);
        if (hd.typeLoyer && hd.typeLoyer !== 'GRATUIT') {
          if (hd.loyerMontantMin) formData.append('loyer_montant_min', String(hd.loyerMontantMin));
          if (hd.loyerMontantMax) formData.append('loyer_montant_max', String(hd.loyerMontantMax));
        }
        if (hd.typeLogement) formData.append('type_logement', hd.typeLogement);
        if (hd.niveauLogement) formData.append('niveau_logement', hd.niveauLogement);
        if (hd.niveauLogement === 'ETAGE' && hd.accesEtage) formData.append('acces_etage', hd.accesEtage);
        if (hd.nombrePieces) formData.append('nombre_pieces', String(hd.nombrePieces));
        if (hd.nombreChambres) formData.append('nombre_chambres', String(hd.nombreChambres));
        if (hd.capaciteAdultes) formData.append('capacite_adultes', String(hd.capaciteAdultes));
        if (hd.capaciteEnfants) formData.append('capacite_enfants', String(hd.capaciteEnfants));
        formData.append('animaux_acceptes', String(!!hd.animauxAcceptes));
        formData.append('jardin', String(!!hd.jardin));
        formData.append('pmr_compatible', String(!!hd.pmrCompatible));
      }

      formData.append('status', 'NON_TRAITEE');
      if (this.currentUser?.id) formData.append('author', this.currentUser.id);
      if (this.selectedPhotos[0]) formData.append('photo', this.selectedPhotos[0]);

      return this.helpRequestService.create(formData);
    });

    forkJoin(creations).subscribe({
      next: (requests) => {
        // Photos additionnelles de la galerie (au-delà de la principale déjà envoyée avec
        // chaque demande) — postées séparément vers chaque demande créée, une fois qu'elle existe.
        const photosSupplementaires = this.selectedPhotos.slice(1);
        requests.forEach(r => {
          photosSupplementaires.forEach((file, i) => {
            this.helpRequestService.addPhoto(r.id, file, i).subscribe({
              error: (err) => console.error('Erreur ajout photo galerie:', err),
            });
          });
        });
        alert('Votre demande a été enregistrée avec succès !');
        this.router.navigate(['/accueil']);
      },
      error: (err) => {
        console.error('Erreur création demande:', err);
        if (err.status === 400) {
          if (err.error && err.error.photo) {
            alert("ERREUR PHOTO : " + err.error.photo[0]);
          } else {
            alert(this.extractApiErrorMessage(err));
          }
        } else {
          alert("Une erreur technique est survenue. Veuillez réessayer.");
        }
      }
    });
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

  onContinue(): void {
    Object.keys(this.requestForm.controls).forEach(key => {
      this.requestForm.get(key)?.markAsTouched();
    });
    this.needsType.markAllAsTouched();
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

  get needsType(): FormArray {
    return this.requestForm.get('needsType') as FormArray;
  }

  get descriptions(): FormArray {
    return this.requestForm.get('descriptions') as FormArray;
  }

  addNeed(): void {
    this.needsType.push(this.formBuilder.control('', Validators.required));
    this.descriptions.push(this.formBuilder.control('', [Validators.minLength(10)]));
    this.subCategorySelections.push('');
    this.hebergementDetails.push(emptyHebergementDetails());
  }

  removeNeed(index: number): void {
    this.needsType.removeAt(index);
    this.descriptions.removeAt(index);
    this.subCategorySelections.splice(index, 1);
    this.hebergementDetails.splice(index, 1);
  }

  /** Remonte la raison précise d'un refus (ex: "Cette crise est clôturée...") plutôt qu'un
   * message générique — cf. validate_crisis_open_and_monitored côté backend. */
  private extractApiErrorMessage(err: any): string {
    const body = err?.error;
    if (!body) {
      return 'Une erreur technique est survenue. Veuillez réessayer.';
    }
    if (typeof body === 'string') {
      return body;
    }
    if (typeof body.detail === 'string') {
      return body.detail;
    }
    if (typeof body.error === 'string') {
      return body.error;
    }
    const firstKey = Object.keys(body)[0];
    if (firstKey) {
      const value = body[firstKey];
      const message = Array.isArray(value) ? value[0] : value;
      if (typeof message === 'string') {
        return message;
      }
    }
    return 'Une erreur technique est survenue. Veuillez réessayer.';
  }
}
