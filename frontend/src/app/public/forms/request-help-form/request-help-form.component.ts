import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { forkJoin, Observable } from 'rxjs';
import { RequestService } from '../../../services/request.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { Request } from '../../../shared/models/request.model';
import { User } from '../../../shared/models/user.model';
import { AuthService } from '../../../auth/services/auth.service';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { AddressResult } from '../../../shared/models/address-result.model';
import { RgpdNoticeComponent } from '../../../shared/components/public/rgpd-notice/rgpd-notice.component';
import { ValidationSummaryComponent } from '../../../shared/components/public/validation-summary/validation-summary.component';
import { PhotoGalleryPickerComponent } from '../../../shared/components/public/photo-gallery-picker/photo-gallery-picker.component';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { LocationService, Commune } from '../../../services/location.service';
import { CriseLieuThemeComponent } from '../../../shared/components/public/crise-lieu-theme/crise-lieu-theme.component';

const TYPE_HEBERGEMENT = 'Hébergement';

/** Critères du logement recherché, par index de besoin (tableau parallèle à needsType).
 * Pas d'adresse : une recherche de logement porte sur une zone (communes + rayon). */
interface HebergementDetails {
  hebergementDuree: string;
  zoneCommunes: Commune[];
  zoneRayonKm: number | null;
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
    hebergementDuree: '', zoneCommunes: [], zoneRayonKm: null,
    typeLoyer: '', loyerMontantMin: null, loyerMontantMax: null,
    typeLogement: '', niveauLogement: '', accesEtage: '',
    nombrePieces: null, nombreChambres: null, capaciteAdultes: null, capaciteEnfants: null,
    animauxAcceptes: false, jardin: false, pmrCompatible: false,
  };
}

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent, RgpdNoticeComponent, ValidationSummaryComponent, PhotoGalleryPickerComponent, TagSearchInputComponent, CriseLieuThemeComponent],
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

  // Étape « crise + lieu + thèmes à l'écoute » (app-crise-lieu-theme).
  criseSelectionnee: Crisis | null = null;
  typesDemandeAutorises: string[] = [];

  onCriseSelectionnee(crise: Crisis | null): void {
    this.criseSelectionnee = crise;
    this.requestForm.patchValue({ crisisId: crise?.id || '' });
  }

  onTypesAutorises(typeIds: string[]): void {
    this.typesDemandeAutorises = typeIds;
  }

  needTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  /** Types de premier niveau limités aux thèmes à l'écoute ; leurs sous-catégories restent visibles. */
  get needTypeOptionsFiltrees(): { value: string; label: string }[] {
    return this.needTypeOptions.slice(1).filter(opt => {
      const id = this.typesDemandeMap.get(opt.value);
      return id && this.typesDemandeAutorises.includes(id);
    });
  }

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
    private authService: AuthService,
    private locationService: LocationService
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesDemande();
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

  // Sous-catégorie facultative par besoin (ex: Matériel > Groupe électrogène).
  childrenByParentType: Map<string, { value: string; label: string }[]> = new Map();
  subCategorySelections: string[] = [];

  readonly TYPE_HEBERGEMENT = TYPE_HEBERGEMENT;

  // Critères du logement recherché, par besoin (HebergementDetails).
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

  /** Zone de recherche du logement (communes + rayon), propre à ce besoin. */
  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);

  addZoneCommune(index: number, commune: Commune): void {
    const details = this.hebergementDetails[index];
    if (details.zoneCommunes.some(c => c.code === commune.code)) return;
    details.zoneCommunes = [...details.zoneCommunes, commune];
  }

  removeZoneCommune(index: number, code: string): void {
    const details = this.hebergementDetails[index];
    details.zoneCommunes = details.zoneCommunes.filter(c => c.code !== code);
  }

  childrenFor(index: number): { value: string; label: string }[] {
    const topLevel = this.needsType.at(index)?.value;
    return topLevel ? (this.childrenByParentType.get(topLevel) ?? []) : [];
  }

  onTopLevelTypeChange(index: number): void {
    // Changer de besoin principal efface la précision choisie.
    this.subCategorySelections[index] = '';
  }

  onSubCategoryChange(index: number, value: string): void {
    this.subCategorySelections[index] = value;
  }

  /** Type envoyé : la précision si choisie, sinon le besoin principal. */
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

    this.addNeed();

    this.informationForm = this.formBuilder.group({
      lastName: [this.currentUser?.last_name, Validators.required],
      firstName: [this.currentUser?.first_name, Validators.required],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phoneNumber: [this.currentUser?.phone_number, [Validators.required, Validators.pattern(/^\+?[\d\s.-]{10,20}$/)]]
    });
  }

  /** Galerie (10 photos max) : la première part dans `photo` de la demande, les autres après création. */
  selectedPhotos: File[] = [];

  onPhotosSelected(files: File[]): void {
    this.selectedPhotos = files;
  }

  // Résumé des erreurs, un par étape.
  formErrorsStep1: string[] = [];
  formErrorsStep2: string[] = [];

  /** « Votre adresse » est facultative si tous les besoins sont des recherches de logement. */
  addressRequired(): boolean {
    return this.needsType.controls.some(c => c.value !== TYPE_HEBERGEMENT);
  }

  private step1ValidationErrors(): string[] {
    const errors: string[] = [];
    if (this.needsType.invalid) errors.push('Précisez chaque besoin (choisissez un type dans la liste).');
    if (this.addressRequired() && !this.selectedAddress) errors.push('Sélectionnez une adresse dans la liste proposée.');
    return errors;
  }

  private step2ValidationErrors(): string[] {
    const errors: string[] = [];
    const f = this.informationForm;
    if (f.get('lastName')?.invalid) errors.push('Le nom est obligatoire.');
    if (f.get('firstName')?.invalid) errors.push('Le prénom est obligatoire.');
    if (f.get('email')?.invalid) errors.push('L\'email est obligatoire et doit être valide.');
    if (f.get('phoneNumber')?.invalid) errors.push('Le téléphone est obligatoire et doit être valide.');
    if (this.addressRequired() && (!this.latitude || !this.longitude)) {
      errors.push('Erreur de géolocalisation : vérifiez l\'adresse sélectionnée à l\'étape précédente.');
    }
    if (this.needsType.invalid) errors.push('Précisez chaque besoin (retournez à l\'étape précédente).');
    return errors;
  }

  onSubmit(): void {
    this.informationForm.markAllAsTouched();
    this.needsType.markAllAsTouched();
    this.formErrorsStep2 = this.step2ValidationErrors();
    if (this.formErrorsStep2.length > 0) return;

    const crisisId = this.requestForm.get('crisisId')?.value;
    const crisisLabel = this.criseSelectionnee ? `${this.criseSelectionnee.name} - ${this.criseSelectionnee.type_display || this.criseSelectionnee.type}` : 'non liée à une crise';
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

      // Besoin Hébergement : la zone de recherche remplace `location`/`commune_code`.
      if (topLevelType !== TYPE_HEBERGEMENT) {
        formData.append('location', JSON.stringify(localisation));
        if (this.selectedAddress?.citycode) formData.append('commune_code', this.selectedAddress.citycode);
      }

      const typeId = this.typesDemandeMap.get(needType);
      if (typeId) formData.append('request_type', typeId);
      if (crisisId) formData.append('crisis', crisisId);
      if (description) formData.append('description', description);

      if (topLevelType === TYPE_HEBERGEMENT && hd) {
        if (hd.zoneCommunes.length > 0) {
          formData.append('zone_recherche_communes', JSON.stringify(hd.zoneCommunes.map(c => c.code)));
          // commune_code conservé pour un rapprochement géographique de base (team_zone_specificity).
          formData.append('commune_code', hd.zoneCommunes[0].code);
        }
        if (hd.zoneRayonKm) formData.append('zone_recherche_rayon_km', String(hd.zoneRayonKm));
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
        // Photos supplémentaires postées après création de chaque demande.
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

  /** Affiche la raison précise d'un refus (validate_crisis_open_and_monitored). */
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
