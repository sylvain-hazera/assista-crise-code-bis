import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { CrisisService } from '../../../services/crisis.service';
import { Router } from '@angular/router';
import { GeolocationService } from '../../../services/geolocation.service';
import { Status } from '../../../shared/models/status.model';
import { LocationService, Department, Commune } from '../../../services/location.service';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-declare-crisis-form',
  standalone: true,
  imports: [ReactiveFormsModule, FormsModule, CommonModule],
  templateUrl: './declare-crisis-form.component.html',
  styleUrl: './declare-crisis-form.component.scss'
})
export class DeclareCrisisFormComponent implements OnInit{
  crisisForm!: FormGroup;
  selectedFile: File | null = null;
  fileName: string = 'Select';
  
  latitude: number | null = null;
  longitude: number | null = null;

  departments: Department[] = [];
  filteredDepartments: Department[] = [];
  communes: Commune[] = [];
  filteredCommunes: Commune[] = [];
  departmentSearch: string = '';
  communeSearch: string = '';
  showDepartmentDropdown: boolean = false;
  showCommuneDropdown: boolean = false;

    eventTypeOptions: { value: string; label: string }[] = [
    { value: '', label: 'Dropdown' },
    { value: 'incendie', label: 'Incendie' },
    { value: 'inondation', label: 'Inondation' },
    { value: 'accident', label: 'Accident' },
    { value: 'catastrophe-naturelle', label: 'Catastrophe naturelle' },
    { value: 'urgence-medicale', label: 'Urgence médicale' },
    { value: 'autre', label: 'Autre' }
  ];

  constructor(
    private formBuilder: FormBuilder,
    private router: Router,
    private crisisService: CrisisService,
    private geolocationService: GeolocationService,
    private locationService: LocationService
  ) {}

  ngOnInit() {
    this.initForm();
    this.loadDepartments();
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

  initForm(): void {
    this.crisisForm = this.formBuilder.group({
      eventType: ['', Validators.required],
      title: ['', Validators.required],
      description: [''],
      streetNumber: ['', Validators.required],
      department: ['', Validators.required],
      commune: ['', Validators.required],
      addressVisible: [false],
      image: [null],
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

      this.crisisForm.patchValue({ image: this.selectedFile });
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
    this.crisisForm.patchValue({ department: department.code });
    this.showDepartmentDropdown = false;
    
    this.locationService.getCommunesByDepartment(department.code).subscribe({
      next: (communes) => {
        this.communes = communes;
        this.filteredCommunes = communes;
        this.communeSearch = '';
        this.crisisForm.patchValue({ commune: '' });
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
    this.crisisForm.patchValue({ commune: commune.code });
    this.showCommuneDropdown = false;
  }

  onSubmit(): void {
    if(this.crisisForm.valid) {
      const street = this.crisisForm.get('streetNumber')?.value;
      const communeCode = this.crisisForm.get('commune')?.value;
      const commune = this.communes.find(c => c.code === communeCode);
      const postalCode = commune?.codesPostaux[0] || '';
      const query = `${street} ${postalCode}`;
      
      // D'abord récupérer les coordonnées, PUIS créer la crise
      this.geolocationService.getCoordinates(query).subscribe({
        next: (response) => {
          if (response.features && response.features.length > 0) {
            const coords = response.features[0].geometry.coordinates;
            this.longitude = coords[0];
            this.latitude = coords[1];
            
            // Maintenant qu'on a les coordonnées, on peut créer la crise
            this.createCrisis();
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
      Object.keys(this.crisisForm.controls).forEach(key => {
        this.crisisForm.get(key)?.markAsTouched();
      });
      
      if (!this.latitude || !this.longitude) {
        alert('Erreur de géolocalisation. Veuillez vérifier l\'adresse.');
      } else {
        alert('Veuillez remplir tous les champs obligatoires');
      }
    }
  }

  private createCrisis(): void {
    const formData = new FormData();

    formData.append('type_evenement', this.crisisForm.get('eventType')?.value);
    formData.append('name', this.crisisForm.get('title')?.value);
    formData.append('description', this.crisisForm.get('description')?.value);

    const localisation = {
      type: 'Point',
      coordinates: [this.longitude, this.latitude]
    };
    formData.append('localisation', JSON.stringify(localisation));
    
    if (this.selectedFile) {
      formData.append('photo', this.selectedFile);
    }
    formData.append('statut', 'NON_TRAITEE');

    this.crisisService.createCrisis(formData).subscribe({
      next: (response) => {
        console.log('Crisis créée:', response);
        alert('Votre crise a été enregistrée avec succès !');
        this.router.navigate(['/accueil']);
      },
      error: (err) => {
        console.error('Erreur création crisis:', err);
        console.error('Détails:', err.error);
        
        let errorMessage = 'Erreur lors de l\'enregistrement. Veuillez réessayer.';
        
        if (err.status === 401) {
          errorMessage = 'Vous devez être connecté en tant qu\'administrateur ou autorité locale pour déclarer une crise.';
        } else if (err.status === 403) {
          errorMessage = 'Vous n\'avez pas les permissions nécessaires pour déclarer une crise.';
        } else if (err.status === 400 && err.error) {
          // Afficher les erreurs de validation spécifiques
          const details = Object.values(err.error).flat().join(' ');
          errorMessage = `Erreur de validation : ${details}`;
        }
        
        alert(errorMessage);
      }
    });
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }
}
