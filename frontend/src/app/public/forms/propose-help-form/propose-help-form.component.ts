import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ReactiveFormsModule, FormArray } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { GeolocationService } from '../../../services/geolocation.service';
import { CommonModule } from '@angular/common';
import { OfferService } from '../../../services/offer.service';
import { LocationService, Department, Commune } from '../../../services/location.service';
import { CrisisService } from '../../../services/crisis.service';
import { Crise } from '../../../shared/models/crisis.model';
import { AuthService } from '../../../auth/services/auth.service';
import { RoleUtilisateur, Utilisateur } from '../../../shared/models/user.model';

@Component({
  selector: 'app-request-help-form',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule, FormsModule],
  templateUrl: './propose-help-form.component.html',
  styleUrl: './propose-help-form.component.scss'
})
export class ProposeHelpFormComponent implements OnInit {
  currentUser : Utilisateur | null = null;
  requestForm!: FormGroup;
  informationForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  state: number = 1;

  latitude: number | null = null;
  longitude: number | null = null;

  typesOffreMap: Map<string, string> = new Map(); // offerType -> UUID

  // Départements et communes
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

  offerTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' }
  ];

  personTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: RoleUtilisateur.UTIL_SIMPLE, label: 'Particulier' },
    { value: RoleUtilisateur.AUT_LOCALE , label: 'Organisation' },
    { value: RoleUtilisateur.SECOURS , label: 'Secours organisés' },
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private offerService: OfferService,
    private geolocationService: GeolocationService,
    private locationService: LocationService,
    private crisisService: CrisisService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    this.initForm();
    this.loadTypesOffre();
    this.loadDepartments();
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
      next: (crises: Crise[]) => {
        const activeCrises = crises.filter(c => c.statut !== 'TRAITEE');
        this.crisisOptions = [
          { value: '', label: 'Aucune crise en rapport' },
          ...activeCrises.map(c => ({
            value: c.id,
            label: `${c.nom} - ${c.type}`
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
      offersType: new FormArray([]),
      descriptions: new FormArray([]),
      streetNumber: ['', Validators.required],
      department: ['', Validators.required],
      commune: ['', Validators.required],
      addressVisible: [false],
      image: [null],
    });

    this.addOffer(); // Ajouter un besoin initial  

    this.informationForm = this.formBuilder.group({
      personType: [this.currentUser?.type, Validators.required],
      lastName: [this.currentUser?.last_name, Validators.required],
      firstName: [this.currentUser?.first_name, Validators.required],
      email: [this.currentUser?.email, [Validators.required, Validators.email]],
      phoneNumber: [this.currentUser?.telephone_utilisateur, [Validators.required, Validators.pattern(/^\+?\d{10,15}$/)]]
    });
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

      this.requestForm.patchValue({ image: this.selectedFile });
    }
  }

  onSubmit(): void {    
    if (this.informationForm.valid && this.latitude && this.longitude) {
      console.log('Formulaire valide:', this.informationForm.value);

      // Préparer les données pour Django
      const formData = new FormData();
      
      // Champs du modèle Offre Django
      formData.append('prenom_offre', this.informationForm.get('firstName')?.value);
      formData.append('nom_offre', this.informationForm.get('lastName')?.value);
      formData.append('email_offre', this.informationForm.get('email')?.value);
      formData.append('telephone_offre', this.informationForm.get('phoneNumber')?.value);
      
      // Titre basé sur la crise sélectionnée
      const crisisId = this.requestForm.get('crisisId')?.value;
      const crisisLabel = this.crisisOptions.find(c => c.value === crisisId)?.label || 'non liée à une crise';
      const titre = `Offre d'aide - ${crisisLabel}`;
      formData.append('titre', titre);
      
      // Localisation au format GeoJSON Point
      const localisation = {
        type: 'Point',
        coordinates: [this.longitude, this.latitude]
      };
      formData.append('localisation', JSON.stringify(localisation));
      
      // Type offre - Utiliser le premier type disponible
      const firstTypeId = Array.from(this.typesOffreMap.values())[0];
      if (!firstTypeId) {
        alert('Type d\'offre non trouvé. Veuillez réessayer ou contacter le support.');
        return;
      }
      formData.append('type_offre', firstTypeId);
      
      // Crise (nullable)
      if (crisisId) {
        formData.append('crise', crisisId);
      }
      
      formData.append('statut', 'DISPONIBLE');
      formData.append('auteur', this.currentUser?.id!);

      
      // Photo si présente
      if (this.selectedFile) {
        formData.append('photo', this.selectedFile);
      }

      // Envoyer au backend Django
      this.offerService.create(formData).subscribe({
        next: (response) => {
          console.log('Demande créée:', response);
          alert('Votre demande a été enregistrée avec succès !');
          this.router.navigate(['/accueil']);
        },
        error: (err) => {
          console.error('Erreur création demande:', err);
          console.error('Détails erreur:', err.error);
          if (err.status === 400 && err.error) {
            console.error('Erreurs de validation:', err.error);
            const errors = Object.entries(err.error).map(([key, value]) => `${key}: ${value}`).join('\n');
            alert(`Erreur de validation:\n${errors}`);
          } else {
            alert('Erreur lors de l\'enregistrement. Veuillez réessayer.');
          }
        }
      });

    } else {
      Object.keys(this.informationForm.controls).forEach(key => {
        this.informationForm.get(key)?.markAsTouched();
      });
      
      if (!this.latitude || !this.longitude) {
        alert('Erreur de géolocalisation. Veuillez vérifier l\'adresse.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

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
    this.requestForm.patchValue({ department: department.code });
    this.showDepartmentDropdown = false;
    
    // Charger les communes du département
    this.locationService.getCommunesByDepartment(department.code).subscribe({
      next: (communes) => {
        this.communes = communes;
        this.filteredCommunes = communes;
        // Réinitialiser la commune sélectionnée
        this.communeSearch = '';
        this.requestForm.patchValue({ commune: '' });
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
    this.requestForm.patchValue({ commune: commune.code });
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
    this.requestForm.patchValue({ crisisId: crisis.value });
    this.showCrisisDropdown = false;
  }

  onContinue(): void {
    if (this.requestForm.valid) {

      const street = this.requestForm.get('streetNumber')?.value;
      const communeCode = this.requestForm.get('commune')?.value;
      const commune = this.communes.find(c => c.code === communeCode);
      const postalCode = commune?.codesPostaux[0] || '';
      const query = `${street} ${postalCode}`;

      this.geolocationService.getCoordinates(query).subscribe({
        next: (response) => {
          if (response.features && response.features.length > 0) {
            const coords = response.features[0].geometry.coordinates;
            this.longitude = coords[0];
            this.latitude = coords[1];
            
            this.state = 2;
          } else {
            alert("Adresse introuvable. Vérifiez le numéro et le code postal.");
          }
        },
        error: (err) => {
          console.error(err);
          alert("Erreur de connexion au service d'adresse.");
        }
      });
  } else {
      // Marquer tous les champs comme touchés pour afficher les erreurs
      Object.keys(this.requestForm.controls).forEach(key => {
        this.requestForm.get(key)?.markAsTouched();
      });
      alert('Veuillez remplir tous les champs obligatoires');
  }
}

  goBack(): void {
    if(this.state == 1) {
      this.router.navigate(['/accueil']);
    } else {
      this.state = 1;
    }
  }

  get offersType(): FormArray {
    return this.requestForm.get('offersType') as FormArray;
  }

  get descriptions(): FormArray {
    return this.requestForm.get('descriptions') as FormArray;
  }

  addOffer(): void {
    this.offersType.push(this.formBuilder.control('', Validators.required));
    this.descriptions.push(this.formBuilder.control('', [Validators.minLength(10)]));
  }

  removeOffer(index: number): void {
    this.offersType.removeAt(index);
    this.descriptions.removeAt(index);
  }
}
