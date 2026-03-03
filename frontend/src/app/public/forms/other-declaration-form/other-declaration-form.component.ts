import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { InformationService } from '../../../services/information.service';
import { Router } from '@angular/router';
import { GeolocationService } from '../../../services/geolocation.service';
import { LocationService, Department, Commune } from '../../../services/location.service';
import { CrisisService } from '../../../services/crisis.service';
import { Crise } from '../../../shared/models/crisis.model';
import { AuthService } from '../../../auth/services/auth.service';

enum StateForm {
  DeclareSafe,
  OtherDeclaration
}

@Component({
  selector: 'app-other-declaration-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule],
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

  typesInformationMap: Map<string, string> = new Map(); // informationType -> UUID

  // Department and commune selection
  departments: Department[] = [];
  filteredDepartments: Department[] = [];
  communes: Commune[] = [];
  filteredCommunes: Commune[] = [];
  departmentSearch: string = '';
  communeSearch: string = '';
  showDepartmentDropdown: boolean = false;
  showCommuneDropdown: boolean = false;

  crisisOptions: { value: string; label: string }[] = [];
  filteredCrisisOptions: { value: string; label: string }[] = [];
  crisisSearch: string = 'Aucune crise en rapport';
  showCrisisDropdown: boolean = false;

  informationTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private informationService: InformationService,
    private geolocationService: GeolocationService,
    private locationService: LocationService,
    private crisisService: CrisisService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.initForm();
    this.loadDepartments();
    this.loadTypesInformation();
    this.loadActiveCrises();
  }

  loadDepartments(): void {
    this.locationService.getDepartments().subscribe({
      next: (deps) => {
        this.departments = deps;
        this.filteredDepartments = deps;
      },
      error: (err) => console.error('Erreur chargement départements:', err)
    });
  }

  loadTypesInformation(): void {
    this.informationService.getTypes().subscribe({
      next: (types: any[]) => {
        types.forEach((t: any) => {
          const normalizedType = t.type.toLowerCase().replace(/\s+/g, '-');
          this.typesInformationMap.set(normalizedType, t.id!);
          this.informationTypeOptions.push({
            value: normalizedType,
            label: t.type
          });
        });
        console.log('Types information chargés:', this.informationTypeOptions);
      },
      error: (err: any) => console.error('Erreur chargement types information:', err)
    });
  }

  loadActiveCrises(): void {
    this.crisisService.getAll().subscribe({
      next: (crises: Crise[]) => {
        this.crisisOptions.push({
          value: '',
          label: 'Aucune crise en rapport'
        });
        
        crises.forEach(crisis => {
          this.crisisOptions.push({
            value: crisis.id!,
            label: crisis.nom
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
      lastName: ['', Validators.required],
      firstName: ['', Validators.required],
      phoneNumber: ['', [Validators.required, Validators.pattern(/^\+?\d{10,15}$/)]],
      email: ['', [Validators.required, Validators.email]],
      streetNumber: ['', Validators.required],
      department: ['', Validators.required],
      commune: ['', Validators.required],
      addressVisible: [false],
      image: [null]
    });

    this.otherInformationForm = this.formBuilder.group({
      crisisId: [''],
      informationType: ['', Validators.required],
      description: ['', [Validators.required, Validators.minLength(10)]],
      streetNumber: ['', Validators.required],
      department: ['', Validators.required],
      commune: ['', Validators.required],
      addressVisible: [false],
      image: [null]
    });
  }

  onDeclareSafe(): void {
    this.state = StateForm.DeclareSafe;
    this.fileName = 'Select'; // Reset file selection
    this.departmentSearch = '';
    this.communeSearch = '';
    this.showDepartmentDropdown = false;
    this.showCommuneDropdown = false;
  }

  onOtherDeclaration(): void {
    this.state = StateForm.OtherDeclaration;
    this.fileName = 'Select'; // Reset file selection
    this.departmentSearch = '';
    this.communeSearch = '';
    this.showDepartmentDropdown = false;
    this.showCommuneDropdown = false;
  }

  onFileSelected(event: Event): void {
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
      }
    }
  }

  // Department and commune selection methods
  onDepartmentSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.departmentSearch = input.value;
    this.filteredDepartments = this.locationService.searchDepartments(
      this.departmentSearch,
      this.departments
    );
    this.showDepartmentDropdown = true;
  }

  selectDepartment(department: Department): void {
    this.departmentSearch = department.nom;
    const form = this.state === StateForm.DeclareSafe ? this.declareSafeForm : this.otherInformationForm;
    form.patchValue({ department: department.code });
    this.showDepartmentDropdown = false;
    
    this.locationService.getCommunesByDepartment(department.code).subscribe({
      next: (communes) => {
        this.communes = communes;
        this.filteredCommunes = communes;
        this.communeSearch = '';
        form.patchValue({ commune: '' });
      },
      error: (err) => console.error('Erreur chargement communes:', err)
    });
  }

  onCommuneSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.communeSearch = input.value;
    this.filteredCommunes = this.locationService.searchCommunes(
      this.communeSearch,
      this.communes
    );
    this.showCommuneDropdown = true;
  }

  selectCommune(commune: Commune): void {
    this.communeSearch = commune.nom;
    const form = this.state === StateForm.DeclareSafe ? this.declareSafeForm : this.otherInformationForm;
    form.patchValue({ commune: commune.code });
    this.showCommuneDropdown = false;
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
  }

  onSubmit(): void {
    if (this.state === StateForm.DeclareSafe && this.declareSafeForm.valid) {
      const street = this.declareSafeForm.get('streetNumber')?.value;
      const communeCode = this.declareSafeForm.get('commune')?.value;
      const commune = this.communes.find(c => c.code === communeCode);
      const postalCode = commune?.codesPostaux[0] || '';
      const query = `${street} ${postalCode}`;

      this.geolocationService.getCoordinates(query).subscribe({
        next: (response) => {
          if (response.features && response.features.length > 0) {
            const coords = response.features[0].geometry.coordinates;
            this.longitude = coords[0];
            this.latitude = coords[1];

            this.submitDeclareSafeForm();
          } else {
            alert("Adresse introuvable. Vérifiez le numéro et la commune.");
          }
        },
        error: (err) => {
          console.error(err);
          alert("Erreur de connexion au service d'adresse.");
        }
      });
    } else if (this.state === StateForm.OtherDeclaration && this.otherInformationForm.valid) {
      const street = this.otherInformationForm.get('streetNumber')?.value;
      const communeCode = this.otherInformationForm.get('commune')?.value;
      const commune = this.communes.find(c => c.code === communeCode);
      const postalCode = commune?.codesPostaux[0] || '';
      const query = `${street} ${postalCode}`;

      this.geolocationService.getCoordinates(query).subscribe({
        next: (response) => {
          if (response.features && response.features.length > 0) {
            const coords = response.features[0].geometry.coordinates;
            this.longitude = coords[0];
            this.latitude = coords[1];

            this.submitOtherInformationForm();
          } else {
            alert("Adresse introuvable. Vérifiez le numéro et la commune.");
          }
        },
        error: (err) => {
          console.error(err);
          alert("Erreur de connexion au service d'adresse.");
        }
      });
    } else {
      // Mark all fields as touched to show validation errors
      const form = this.state === StateForm.DeclareSafe ? this.declareSafeForm : this.otherInformationForm;
      Object.keys(form.controls).forEach(key => {
        form.get(key)?.markAsTouched();
      });
      alert('Veuillez remplir tous les champs obligatoires');
    }
  }

  private submitDeclareSafeForm(): void {
    const formData = new FormData();

    formData.append('titre', 'Je suis en sécurité');
    formData.append('prenom_information', this.declareSafeForm.get('firstName')?.value);
    formData.append('nom_information', this.declareSafeForm.get('lastName')?.value);
    formData.append('email_information', this.declareSafeForm.get('email')?.value);
    formData.append('telephone_information', this.declareSafeForm.get('phoneNumber')?.value);

    const localisation = {
      type: 'Point',
      coordinates: [this.longitude, this.latitude]
    };
    formData.append('localisation', JSON.stringify(localisation));

    if (this.selectedFile) {
      formData.append('photo', this.selectedFile);
    }

    formData.append('statut', 'DISPONIBLE');
    formData.append('auteur', this.authService.getCurrentUser()?.id!);
    
    // Utiliser le premier TypeInformation disponible
    const firstTypeId = Array.from(this.typesInformationMap.values())[0];
    if (!firstTypeId) {
      alert('Type d\'information non trouvé. Veuillez réessayer ou contacter le support.');
      return;
    }
    formData.append('type_information', firstTypeId);

    // Crise (nullable)
    const crisisId = this.declareSafeForm.get('crisisId')?.value;
    if (crisisId) {
      formData.append('crise', crisisId);
    }

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

  private submitOtherInformationForm(): void {
    const formData = new FormData();

    formData.append('titre', this.otherInformationForm.get('description')?.value.substring(0, 100)); // Titre = début de la description
    formData.append('prenom_information', 'Anonyme'); // Information n'a pas de prénom dans ce form
    formData.append('nom_information', 'Anonyme'); // Information n'a pas de nom dans ce form
    formData.append('email_information', 'anonyme@example.com'); // Email requis mais pas dans le form
    formData.append('telephone_information', '0000000000'); // Téléphone requis mais pas dans le form

    const localisation = {
      type: 'Point',
      coordinates: [this.longitude, this.latitude]
    };
    formData.append('localisation', JSON.stringify(localisation));

    if (this.selectedFile) {
      formData.append('photo', this.selectedFile);
    }

    formData.append('statut', 'DISPONIBLE');
    
    // Utiliser le premier TypeInformation disponible
    const firstTypeId = Array.from(this.typesInformationMap.values())[0];
    if (!firstTypeId) {
      alert('Type d\'information non trouvé. Veuillez réessayer ou contacter le support.');
      return;
    }
    formData.append('type_information', firstTypeId);

    // Crise (nullable)
    const crisisId = this.otherInformationForm.get('crisisId')?.value;
    if (crisisId) {
      formData.append('crise', crisisId);
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