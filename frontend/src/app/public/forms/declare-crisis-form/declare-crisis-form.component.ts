import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { CrisisService } from '../../../services/crisis.service';
import { Router } from '@angular/router';
import { GeolocationService } from '../../../services/geolocation.service';
import { Status } from '../../../shared/models/status.model';
import { LocationService, Department, Commune } from '../../../services/location.service';
import { CommonModule } from '@angular/common';
import { CrisisPayload } from '../../../shared/models/crisis.model';
import { map, Observable } from 'rxjs';
import { AuthService } from '../../../auth/services/auth.service';

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
    private locationService: LocationService,
    private authService: AuthService
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
      description: ['', [Validators.minLength(10)]],
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
    this.departmentSearch = department.name;
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
    this.communeSearch = commune.name;
    this.crisisForm.patchValue({ commune: commune.code });
    this.showCommuneDropdown = false;
  }

  onSubmit(): void {
    if (this.crisisForm.valid) {
      const formValue = this.crisisForm.value;
    
      // 1. D'abord obtenir les coordonnées depuis département/commune
      const street = formValue.streetNumber;
      const communeCode = formValue.commune;
      const commune = this.communes.find(c => c.code === communeCode);
      const postalCode = commune?.codesPostaux[0] || '';
      
      this.getCoordinatesFromAddress(street, postalCode).subscribe({
        next: (coords) => {
          // 2. Construire le payload
          const payload: CrisisPayload = {
            name: formValue.title,
            type: formValue.eventType,
            description: formValue.description,
            latitude: coords.lat,
            longitude: coords.lng,
            author: this.authService.getCurrentUser()?.id,
            status: 'NON_TRAITEE'
          };
          
          // 3. Créer le FormData via le service
          const formData = this.crisisService.buildFormData(
            payload, 
            this.selectedFile!
          );
          
          // 4. Envoyer la requête
          this.crisisService.create(formData).subscribe({
            next: (response) => {
              console.log('Crisis créée:', response);
              alert('Votre crise a été enregistrée avec succès !');
              this.router.navigate(['/accueil']);
            },
            error: (err) => {
              console.error('Erreur création crise:', err);
              
              let errorMessage = 'Erreur lors de l\'enregistrement. Veuillez réessayer.';
              
              if (err.status === 401) {
                errorMessage = 'Vous devez être connecté en tant qu\'administrateur ou autorité locale pour déclarer une crise.';
              } else if (err.status === 403) {
                errorMessage = 'Vous n\'avez pas les permissions nécessaires pour déclarer une crise.';
              } else if (err.status === 400 && err.error) {
                const details = Object.values(err.error).flat().join(' ');
                errorMessage = `Erreur de validation : ${details}`;
              }
              
              alert(errorMessage);
            }
          });
        },
        error: (err) => {
          console.error(err);
          alert("Adresse introuvable. Vérifiez le numéro et le code postal.");
        }
      });
    } else {
      Object.keys(this.crisisForm.controls).forEach(key => {
        this.crisisForm.get(key)?.markAsTouched();
      });
      alert('Veuillez remplir tous les champs obligatoires');
    }
  }

  goBack(): void {
    this.router.navigate(['/accueil']);
  }

  private getCoordinatesFromAddress(street: string, zip: string): Observable<{lat: number, lng: number}> {
    const query = `${street} ${zip}`;
    return this.geolocationService.getCoordinates(query).pipe(
      map(response => {
        if (response.features && response.features.length > 0) {
          const coords = response.features[0].geometry.coordinates;
          return { lng: coords[0], lat: coords[1] };
        }
        throw new Error('Adresse introuvable');
      })
    );
  }
}
