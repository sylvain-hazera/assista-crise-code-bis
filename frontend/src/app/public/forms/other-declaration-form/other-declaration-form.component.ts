import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { InformationService } from '../../../services/information.service';
import { DeclarationSecuriteService } from '../../../services/declaration-securite.service';
import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { Router } from '@angular/router';
import { CrisisService } from '../../../services/crisis.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { InformationType } from '../../../shared/models/information.model';
import { AuthService } from '../../../auth/services/auth.service';
import { GeolocationService } from '../../../services/geolocation.service';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { AddressResult } from '../../../shared/models/address-result.model';
import { CentreAccueilPublic } from '../../../shared/models/point-operationnel.model';

enum StateForm {
  DeclareSafe,
  OtherDeclaration
}

@Component({
  selector: 'app-other-declaration-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule, AddressPickerComponent, TagSearchInputComponent],
  templateUrl: './other-declaration-form.component.html',
  styleUrl: './other-declaration-form.component.scss'
})
export class OtherDeclarationFormComponent implements OnInit {
  declareSafeForm!: FormGroup;
  otherInformationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  StateForm = StateForm; // Expose enum to template
  state: StateForm = StateForm.DeclareSafe;

  latitude: number | null = null;
  longitude: number | null = null;

  selectedAddressOther: AddressResult | null = null;

  onAddressSelectedOther(addr: AddressResult | null): void {
    this.selectedAddressOther = addr;
  }

  crisisOptions: { value: string; label: string }[] = [];
  filteredCrisisOptions: { value: string; label: string }[] = [];
  crisisSearch: string = 'Aucune crise en rapport';
  showCrisisDropdown: boolean = false;

  // Centres d'accueil proposés pour "Je suis en sécurité", une fois une crise choisie — pour
  // le choix explicite d'un centre (situation EN_CENTRE) ou les suggestions du popup
  // "trouver un centre" (situation BESOIN_CENTRE).
  centresAccueil: CentreAccueilPublic[] = [];

  showCentrePopup = false;
  userLatitude: number | null = null;
  userLongitude: number | null = null;
  locatingUser = false;

  selectedInformationType: InformationType | null = null;

  // Position + azimut capturés au moment de la photo (prioritaires sur l'adresse saisie
  // manuellement s'ils sont disponibles) — cf. capturePhotoWithLocation().
  capturedLatitude: number | null = null;
  capturedLongitude: number | null = null;
  capturedAzimuth: number | null = null;
  private locationPromise: Promise<{ latitude: number; longitude: number } | null> | null = null;
  private azimuthPromise: Promise<number | null> | null = null;

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private informationService: InformationService,
    private declarationSecuriteService: DeclarationSecuriteService,
    private pointOperationnelService: PointOperationnelService,
    private crisisService: CrisisService,
    private authService: AuthService,
    private geolocationService: GeolocationService
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.loadActiveCrises();
  }

  informationTypeSearchFn = (q: string) => this.informationService.searchTypes(q);
  informationTypeCreateFn = (type: string) => this.informationService.createType(type);

  onInformationTypeSelected(item: InformationType): void {
    this.selectedInformationType = item;
  }

  /** Déclenché par le bouton "Prendre une photo" : lance la capture GPS + boussole (doit
   * démarrer depuis ce geste utilisateur direct pour que iOS autorise l'accès aux capteurs),
   * puis ouvre l'appareil photo natif. Les deux captures tournent en parallèle pendant que
   * l'utilisateur prend la photo — normalement déjà résolues à son retour. */
  capturePhotoWithLocation(fileInput: HTMLInputElement): void {
    this.locationPromise = this.geolocationService.requestLocation().catch(() => null);
    this.azimuthPromise = this.geolocationService.getCurrentAzimuth();
    fileInput.click();
  }

  loadActiveCrises(): void {
    this.crisisService.getAll().subscribe({
      next: (crises: Crisis[]) => {
        this.crisisOptions.push({
          value: '',
          label: 'Aucune crise en rapport'
        });
        
        crises.forEach(crisis => {
          this.crisisOptions.push({
            value: crisis.id!,
            label: crisis.name
          });
        });
        
        this.filteredCrisisOptions = [...this.crisisOptions];
        console.log('Crises chargées:', this.crisisOptions);
      },
      error: (err) => console.error('Erreur chargement crises:', err)
    });
  }

  initForm(): void {
    this.declareSafeForm = this.formBuilder.group({
      crisisId: [''],
      situation: ['RELOGE', Validators.required],
      typeDeclarant: ['PERSONNE_SEULE', Validators.required],
      lastName: ['', Validators.required],
      firstName: ['', Validators.required],
      phoneNumber: ['', [Validators.required, Validators.pattern(/^\+?\d{10,15}$/)]],
      email: ['', [Validators.required, Validators.email]],
      nombreAdultes: [1, [Validators.required, Validators.min(1)]],
      nombreEnfants: [0, [Validators.required, Validators.min(0)]],
      centreAccueil: [''],
      regimeAlimentaire: [false],
    });

    this.otherInformationForm = this.formBuilder.group({
      crisisId: [''],
      description: ['', [Validators.required, Validators.minLength(10)]],
      addressVisible: [false],
      image: [null]
    });
  }

  onDeclareSafe(): void {
    this.state = StateForm.DeclareSafe;
    this.fileName = 'Select'; // Reset file selection
  }

  onOtherDeclaration(): void {
    this.state = StateForm.OtherDeclaration;
    this.fileName = 'Select'; // Reset file selection
  }

  async onFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files[0]) {
      this.selectedFile = input.files[0];
      this.fileName = this.selectedFile.name;

      // Vérifier le type de fichier
      const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif'];
      if (!validTypes.includes(this.selectedFile.type)) {
        alert('Veuillez sélectionner une image valide (JPEG, PNG, GIF)');
        this.selectedFile = null;
        this.fileName = 'Select';
        return;
      }

      // Vérifier la taille (max 5MB)
      if (this.selectedFile.size > 5 * 1024 * 1024) {
        alert('L\'image ne doit pas dépasser 5MB');
        this.selectedFile = null;
        this.fileName = 'Select';
        return;
      }

      if (this.state === StateForm.DeclareSafe) {
        this.declareSafeForm.patchValue({ image: this.selectedFile });
      } else if (this.state === StateForm.OtherDeclaration) {
        this.otherInformationForm.patchValue({ image: this.selectedFile });

        // Récupère la position/l'azimut lancés au clic sur "Prendre une photo" (cf.
        // capturePhotoWithLocation) — déjà résolus la plupart du temps le temps que
        // l'utilisateur revienne de l'appareil photo natif.
        if (this.locationPromise) {
          const [coords, azimuth] = await Promise.all([
            this.locationPromise,
            this.azimuthPromise ?? Promise.resolve(null)
          ]);
          if (coords) {
            this.capturedLatitude = coords.latitude;
            this.capturedLongitude = coords.longitude;
          }
          this.capturedAzimuth = azimuth;
        }
      }
    }
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
    const form = this.state === StateForm.DeclareSafe ? this.declareSafeForm : this.otherInformationForm;
    form.patchValue({ crisisId: crisis.value });
    this.showCrisisDropdown = false;

    if (this.state === StateForm.DeclareSafe) {
      this.loadCentresAccueil(crisis.value);
    }
  }

  /** Centres d'accueil proposés une fois une crise choisie — vide (et champ masqué côté
   * template) si aucune crise n'est sélectionnée, une entrée en centre n'a pas de sens sans
   * savoir à quelle crise elle se rattache. Endpoint public dédié (pas getByCrise, qui exige
   * une session authentifiée — ce formulaire est ouvert à tous). */
  private loadCentresAccueil(crisisId: string): void {
    this.declareSafeForm.patchValue({ centreAccueil: '' });
    this.centresAccueil = [];
    if (!crisisId) return;
    this.pointOperationnelService.getCentresAccueilPublics(crisisId).subscribe({
      next: (centres) => { this.centresAccueil = centres; },
      error: () => { this.centresAccueil = []; },
    });
  }

  get situationChoisie(): string {
    return this.declareSafeForm.get('situation')?.value;
  }

  /** Une position captée automatiquement (photo prise via l'appareil) vaut une adresse
   * saisie à la main — l'une ou l'autre suffit pour situer le signalement. */
  hasLocationForOther(): boolean {
    return !!this.selectedAddressOther || (this.capturedLatitude != null && this.capturedLongitude != null);
  }

  onSubmit(): void {
    if (this.state === StateForm.DeclareSafe) {
      if (!this.declareSafeForm.valid) {
        this.declareSafeForm.markAllAsTouched();
        alert('Veuillez remplir tous les champs obligatoires');
        return;
      }
      if (this.situationChoisie === 'EN_CENTRE' && !this.declareSafeForm.get('centreAccueil')?.value) {
        alert("Veuillez choisir un centre d'accueil dans la liste.");
        return;
      }
      this.submitDeclareSafeForm();
    } else if (
      this.state === StateForm.OtherDeclaration &&
      this.otherInformationForm.valid &&
      this.selectedInformationType &&
      this.hasLocationForOther()
    ) {
      if (this.capturedLatitude != null && this.capturedLongitude != null) {
        this.latitude = this.capturedLatitude;
        this.longitude = this.capturedLongitude;
      } else {
        this.latitude = this.selectedAddressOther!.latitude;
        this.longitude = this.selectedAddressOther!.longitude;
      }
      this.submitOtherInformationForm();
    } else {
      // À ce stade this.state ne peut plus être DeclareSafe : le premier branch gère ce cas
      // en entier (validation + soumission) et retourne toujours avant d'arriver ici.
      Object.keys(this.otherInformationForm.controls).forEach(key => {
        this.otherInformationForm.get(key)?.markAsTouched();
      });
      if (!this.selectedInformationType) {
        alert('Merci de sélectionner ou créer un type de signalement.');
      } else if (!this.hasLocationForOther()) {
        alert('Veuillez sélectionner une adresse dans la liste proposée, ou prendre une photo géolocalisée.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

  private submitDeclareSafeForm(): void {
    const situation = this.situationChoisie;
    const typeDeclarant = this.declareSafeForm.get('typeDeclarant')?.value;
    const payload: any = {
      situation,
      type_declarant: typeDeclarant,
      nom_referent: this.declareSafeForm.get('lastName')?.value,
      prenom_referent: this.declareSafeForm.get('firstName')?.value,
      // Email et téléphone renseignés tous les deux dans le formulaire : le contact retenu
      // pour la déclaration privilégie l'email, le téléphone reste dans le commentaire.
      contact_referent: this.declareSafeForm.get('email')?.value,
      nombre_adultes: typeDeclarant === 'PERSONNE_SEULE' ? 1 : this.declareSafeForm.get('nombreAdultes')?.value,
      nombre_enfants: typeDeclarant === 'PERSONNE_SEULE' ? 0 : this.declareSafeForm.get('nombreEnfants')?.value,
      commentaire: `Téléphone : ${this.declareSafeForm.get('phoneNumber')?.value}`,
    };

    const crisisId = this.declareSafeForm.get('crisisId')?.value;
    if (crisisId) {
      payload.crise = crisisId;
    }

    if (situation === 'EN_CENTRE') {
      payload.centre_accueil = this.declareSafeForm.get('centreAccueil')?.value;
      payload.regime_alimentaire_specifique = this.declareSafeForm.get('regimeAlimentaire')?.value;
    }

    this.declarationSecuriteService.create(payload).subscribe({
      next: (response) => {
        console.log('Déclaration de sécurité créée:', response);
        if (situation === 'BESOIN_CENTRE') {
          // Pas de redirection immédiate : le popup "trouver un centre" propose des
          // suggestions avant de renvoyer la personne à l'accueil.
          this.openCentrePopup();
        } else {
          alert('Votre déclaration a été enregistrée avec succès !');
          this.router.navigate(['/accueil']);
        }
      },
      error: (err) => {
        console.error('Erreur création déclaration:', err);
        console.error('Détails erreur:', err.error);
        alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
      }
    });
  }

  // ── Popup "trouver un centre d'accueil" (situation BESOIN_CENTRE) ────────────

  openCentrePopup(): void {
    this.showCentrePopup = true;
    if (this.userLatitude == null && !this.locatingUser) {
      this.locatingUser = true;
      this.geolocationService.requestLocation()
        .then(coords => {
          this.userLatitude = coords.latitude;
          this.userLongitude = coords.longitude;
        })
        .catch(() => { /* géolocalisation refusée/indisponible : tri par distance simplement désactivé */ })
        .finally(() => { this.locatingUser = false; });
    }
  }

  closeCentrePopup(): void {
    this.showCentrePopup = false;
    this.router.navigate(['/accueil']);
  }

  /** Centres triés par distance croissante si la position de l'utilisateur est connue,
   * ordre du serveur sinon (distance/saturation alors non calculables). */
  get centresTries(): (CentreAccueilPublic & { distanceKm: number | null; sature: boolean })[] {
    return this.centresAccueil
      .map(c => ({
        ...c,
        distanceKm: this.distanceKm(c.latitude, c.longitude),
        sature: c.capacite_accueil != null && c.personnes_presentes >= c.capacite_accueil,
      }))
      .sort((a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity));
  }

  private distanceKm(lat: number | null, lon: number | null): number | null {
    if (lat == null || lon == null || this.userLatitude == null || this.userLongitude == null) return null;
    const R = 6371;
    const dLat = (lat - this.userLatitude) * Math.PI / 180;
    const dLon = (lon - this.userLongitude) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(this.userLatitude * Math.PI / 180) * Math.cos(lat * Math.PI / 180) *
      Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return Math.round(R * c * 10) / 10;
  }

  navigationLink(centre: CentreAccueilPublic): string | null {
    if (centre.latitude == null || centre.longitude == null) return null;
    return `https://www.google.com/maps/dir/?api=1&destination=${centre.latitude},${centre.longitude}`;
  }

  private submitOtherInformationForm(): void {
    const formData = new FormData();

    formData.append('title', this.otherInformationForm.get('description')?.value.substring(0, 100)); // Titre = début de la description
    formData.append('first_name_information', 'Anonyme'); // Information n'a pas de prénom dans ce form
    formData.append('last_name_information', 'Anonyme'); // Information n'a pas de nom dans ce form
    formData.append('email_information', 'anonyme@example.com'); // Email requis mais pas dans le form
    formData.append('phone_information', '0000000000'); // Téléphone requis mais pas dans le form

    const localisation = {
      type: 'Point',
      coordinates: [this.longitude, this.latitude]
    };
    formData.append('location', JSON.stringify(localisation));

    if (this.selectedAddressOther?.citycode) {
      formData.append('commune_code', this.selectedAddressOther.citycode);
    }

    if (this.capturedAzimuth != null) {
      formData.append('azimuth', String(this.capturedAzimuth));
    }

    if (this.selectedFile) {
      formData.append('photo', this.selectedFile);
    }

    formData.append('status', 'DISPONIBLE');

    if (!this.selectedInformationType) {
      alert('Merci de sélectionner ou créer un type de signalement.');
      return;
    }
    formData.append('information_type', this.selectedInformationType.id);

    // Crise (nullable)
    const crisisId = this.otherInformationForm.get('crisisId')?.value;
    if (crisisId) {
      formData.append('crisis', crisisId);
    }

    console.log('FormData envoyé (OtherInformation):', Array.from(formData.entries()));

    this.informationService.create(formData).subscribe({
      next: (response) => {
        console.log('Information créée:', response);
        alert('Votre information a été enregistrée avec succès !');
        this.router.navigate(['/accueil']);
      },
      error: (err) => {
        console.error('Erreur création information:', err);
        console.error('Détails erreur:', err.error);
        alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
      }
    });
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }

  // Helper methods for template
  isFieldInvalid(formName: 'declareSafe' | 'otherInformation', fieldName: string): boolean {
    const form = formName === 'declareSafe' ? this.declareSafeForm : this.otherInformationForm;
    const field = form.get(fieldName);
    return !!(field && field.invalid && (field.dirty || field.touched));
  }

  getErrorMessage(formName: 'declareSafe' | 'otherInformation', fieldName: string): string {
    const form = formName === 'declareSafe' ? this.declareSafeForm : this.otherInformationForm;
    const field = form.get(fieldName);
    
    if (field?.hasError('required')) {
      return 'Ce champ est requis';
    }
    if (field?.hasError('email')) {
      return 'Email invalide';
    }
    if (field?.hasError('pattern')) {
      if (fieldName === 'phoneNumber') {
        return 'Numéro de téléphone invalide';
      }
    }
    if (field?.hasError('minlength')) {
      return `Minimum ${field.errors?.['minlength'].requiredLength} caractères`;
    }
    return '';
  }
}